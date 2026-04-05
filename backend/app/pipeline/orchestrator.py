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

        frame_candidate = select_frame(frame, camera_id=camera_id)
        detections = localize(frame_candidate.frame, mode_override=mode_override)
        if not detections:
            return None

        detections = sorted(detections, key=lambda d: float(d.confidence or 0.0), reverse=True)
        primary_det = detections[0]

        crops = crop_plates(frame_candidate.frame, [primary_det])
        if not crops:
            return None

        qualities = score_crops(crops)
        if not qualities:
            return None

        qualities = sorted(qualities, key=lambda q: q.score, reverse=True)
        best_quality = qualities[0]

        rectified = rectify([best_quality])
        classifier = classify(rectified[0] if rectified else None)
        ocr = recognize(rectified, detection=primary_det, plate_type=classifier.plate_type)
        post = postprocess(ocr, plate_type=classifier.plate_type)
        confidence = fuse_confidence(ocr, primary_det, best_quality)
        tracker = track_plate(post.normalized_text)

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
        logger.debug("pipeline", extra={"timing_ms": total_ms, "plate_text": result.plate_text})
        return result
