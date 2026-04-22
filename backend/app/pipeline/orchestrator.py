import logging
import os
import time
from typing import Optional

from .frame_selector import select_frame
from .plate_localizer import localize
from .plate_cropper import crop_plates
from .plate_quality import score_crops
from .plate_rectifier import rectify
from .plate_classifier import classify
from .plate_ocr import recognize
from .postprocess import postprocess
from .confidence import fuse_confidence
from .tracker import track_plate
from .schemas import PlateInferenceResult

logger = logging.getLogger("anpr.pipeline")


def _env_flag(name: str, default: str = "1") -> bool:
    value = os.getenv(name, default).strip().lower()
    return value not in {"0", "false", "no", "off"}


def pipeline_enabled() -> bool:
    return _env_flag("ANPR_PIPELINE_ENABLED", "1")


def pipeline_store_intermediate() -> bool:
    return _env_flag("ANPR_PIPELINE_STORE_INTERMEDIATE", "0")


class PlateInferencePipeline:
    def __init__(self, enabled: Optional[bool] = None, store_intermediate: Optional[bool] = None):
        self.enabled = pipeline_enabled() if enabled is None else enabled
        self.store_intermediate = pipeline_store_intermediate() if store_intermediate is None else store_intermediate

    def run(self, frame, camera_id: Optional[int] = None, mode_override: Optional[str] = None) -> Optional[PlateInferenceResult]:
        if not self.enabled:
            return None

        pipeline_start = time.perf_counter()

        # ── Stage 1: Frame selection ──────────────────────────────────────────
        try:
            frame_candidate = select_frame(frame, camera_id=camera_id)
        except Exception:
            logger.exception("pipeline[frame_selector] failed for camera_id=%s", camera_id)
            return None

        # ── Stage 2: Plate localisation ───────────────────────────────────────
        try:
            detections = localize(frame_candidate.frame, mode_override=mode_override)
        except Exception:
            logger.exception("pipeline[plate_localizer] failed for camera_id=%s", camera_id)
            return None

        if not detections:
            logger.debug("pipeline[plate_localizer] no detections for camera_id=%s", camera_id)
            return None

        detections = sorted(detections, key=lambda d: float(d.confidence or 0.0), reverse=True)
        primary_det = detections[0]

        # ── Stage 3: Crop ─────────────────────────────────────────────────────
        try:
            crops = crop_plates(frame_candidate.frame, [primary_det])
        except Exception:
            logger.exception("pipeline[plate_cropper] failed for camera_id=%s", camera_id)
            return None

        if not crops:
            logger.debug("pipeline[plate_cropper] no crops produced for camera_id=%s", camera_id)
            return None

        # ── Stage 4: Quality scoring ──────────────────────────────────────────
        try:
            qualities = score_crops(crops)
        except Exception:
            logger.exception("pipeline[plate_quality] failed for camera_id=%s", camera_id)
            return None

        if not qualities:
            logger.debug("pipeline[plate_quality] all crops below quality threshold for camera_id=%s", camera_id)
            return None

        qualities = sorted(qualities, key=lambda q: q.score, reverse=True)
        best_quality = qualities[0]

        # ── Stage 5: Rectification ────────────────────────────────────────────
        try:
            rectified = rectify([best_quality])
        except Exception:
            logger.exception("pipeline[plate_rectifier] failed for camera_id=%s", camera_id)
            rectified = []

        # ── Stage 6: Classification ───────────────────────────────────────────
        try:
            classifier = classify(rectified[0] if rectified else None)
        except Exception:
            logger.exception("pipeline[plate_classifier] failed for camera_id=%s", camera_id)
            # Provide a safe default so pipeline can continue
            from .schemas import PlateClassification
            classifier = PlateClassification(
                stage_name="plate_classifier",
                timing_ms=0.0,
                confidence=None,
                debug={"note": "classifier_error"},
                plate_type="unknown",
            )

        # ── Stage 7: OCR ──────────────────────────────────────────────────────
        try:
            ocr = recognize(rectified, detection=primary_det, plate_type=classifier.plate_type)
        except Exception:
            logger.exception("pipeline[plate_ocr] failed for camera_id=%s", camera_id)
            return None

        # Guard: OCR produced no usable text — don't continue to avoid
        # persisting empty/None detections to the database.
        if not ocr or (not ocr.normalized_text and not ocr.raw_text):
            logger.debug(
                "pipeline[plate_ocr] no text extracted for camera_id=%s (engine=%s)",
                camera_id,
                getattr(ocr, "engine_name", "unknown"),
            )
            return None

        # ── Stage 8: Post-processing ──────────────────────────────────────────
        try:
            post = postprocess(ocr, plate_type=classifier.plate_type)
        except Exception:
            logger.exception("pipeline[postprocess] failed for camera_id=%s", camera_id)
            return None

        # Guard: post-processing must yield a non-empty plate string
        if not post or not post.normalized_text:
            logger.debug("pipeline[postprocess] empty result for camera_id=%s", camera_id)
            return None

        # ── Stage 9: Confidence fusion ────────────────────────────────────────
        try:
            confidence = fuse_confidence(ocr, primary_det, best_quality)
        except Exception:
            logger.exception("pipeline[confidence] failed for camera_id=%s", camera_id)
            from .schemas import ConfidenceResult
            confidence = ConfidenceResult(
                stage_name="confidence",
                timing_ms=0.0,
                confidence=None,
                debug={},
                fused_confidence=None,
            )

        # ── Stage 10: Tracking ────────────────────────────────────────────────
        try:
            tracker = track_plate(post.normalized_text)
        except Exception:
            logger.exception("pipeline[tracker] failed for camera_id=%s", camera_id)
            from .schemas import TrackerResult
            tracker = TrackerResult(
                stage_name="tracker",
                timing_ms=0.0,
                confidence=None,
                debug={},
                status="error",
            )

        total_ms = (time.perf_counter() - pipeline_start) * 1000.0

        stage_outputs = {}
        if self.store_intermediate:
            stage_outputs = {
                "frame": frame_candidate,
                "detections": detections,
                "crops": crops,
                "qualities": qualities,
                "rectified": rectified,
                "classification": classifier,
                "ocr": ocr,
                "postprocess": post,
                "confidence": confidence,
                "tracker": tracker,
            }

        result = PlateInferenceResult(
            stage_name="pipeline",
            timing_ms=total_ms,
            confidence=confidence.fused_confidence,
            debug={
                "pipeline_enabled": self.enabled,
                "tracker_status": tracker.status,
            },
            plate_text=post.normalized_text,
            raw_text=post.raw_text,
            bbox=primary_det.bbox,
            plate_type=classifier.plate_type,
            ocr_result=ocr,
            detection=primary_det,
            crops=rectified,
            stage_outputs=stage_outputs,
        )
        logger.debug(
            "pipeline complete: plate=%r confidence=%.3f time=%.1fms camera_id=%s",
            result.plate_text,
            result.confidence or 0.0,
            total_ms,
            camera_id,
        )
        return result
