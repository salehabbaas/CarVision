"""
plate_detector.py – YOLO and contour-based plate detection.

Real-time optimisations applied here:
  1. YOLO model is pre-warmed in a background thread at import time so the
     first inference isn't blocked by PyTorch/CUDA initialisation.
  2. In "auto" mode, YOLO and contour detectors run concurrently in two
     worker threads (concurrent.futures.ThreadPoolExecutor).  Whichever
     finishes first wins; the winner is returned without waiting for the
     slower one (unless both finish within the same time window).
  3. YOLO imgsz is reduced to 320 for real-time operation (was 640).
     320 is fast enough to localise a plate at live-stream resolutions and
     leaves the accurate OCR step to read_plate_text on the tight crop.
     Override with YOLO_IMGSZ env var if you want higher accuracy.
"""

import os
import threading
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed, Future
from pathlib import Path
from typing import Optional, Dict

import numpy as np

from anpr import detect_plate as contour_detect, read_plate_text

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

logger = logging.getLogger("anpr.detector")

def _default_model_path() -> str:
    """Return path to plate.pt: env var override first, then project models/ dir."""
    env = os.getenv("YOLO_PLATE_MODEL", "").strip()
    if env:
        return env
    candidate = Path(__file__).resolve().parents[3] / "models" / "plate.pt"
    return str(candidate) if candidate.exists() else ""


# ── YOLO runtime config (updated from DB by camera_manager.sync) ──────────────
_YOLO_CONFIG = {
    "conf":       0.25,
    "imgsz":      int(os.getenv("YOLO_IMGSZ", "320")),  # 320 for real-time
    "iou":        0.45,
    "max_det":    5,
    "device":     os.getenv("ANPR_INFERENCE_DEVICE", "cpu"),
    "model_path": _default_model_path(),
}

# Thread pool used for parallel YOLO+contour detection in "auto" mode.
# Keep max_workers=2 – each detector runs in its own thread.
_detector_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="detector")


def set_yolo_config(config: Dict):
    if not isinstance(config, dict):
        return
    previous_device = str(_YOLO_CONFIG.get("device", "cpu") or "cpu").strip().lower()
    previous_path = str(_YOLO_CONFIG.get("model_path", "") or "")
    for key in _YOLO_CONFIG.keys():
        if key in config and config[key] is not None:
            _YOLO_CONFIG[key] = config[key]
    current_device = str(_YOLO_CONFIG.get("device", "cpu") or "cpu").strip().lower()
    current_path = str(_YOLO_CONFIG.get("model_path", "") or "")
    if current_device != previous_device or current_path != previous_path:
        try:
            reload_yolo_model()
        except Exception:
            logger.debug("yolo reload skipped after config change", exc_info=True)


def _torch_device() -> str:
    requested = str(_YOLO_CONFIG.get("device", "cpu") or "cpu").strip().lower()
    if requested != "gpu":
        return "cpu"
    try:
        import torch
    except Exception:
        return "cpu"
    try:
        if torch.cuda.is_available() and torch.cuda.device_count() > 0:
            return "cuda"
    except Exception:
        pass
    try:
        mps = getattr(getattr(torch, "backends", None), "mps", None)
        if mps and mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


class PlateDetector:
    def __init__(self):
        self._model      = None
        self._model_lock = threading.Lock()
        self._mode       = os.getenv("ANPR_DETECTOR", "auto").lower()

    # ── model management ──────────────────────────────────────────────────────
    def _load_model(self):
        if self._model is not None:
            return self._model
        with self._model_lock:
            if self._model is not None:       # double-checked locking
                return self._model
            if YOLO is None:
                return None
            model_path = str(_YOLO_CONFIG.get("model_path", "") or "")
            if not model_path or not os.path.exists(model_path):
                return None
            self._model = YOLO(model_path)
        return self._model

    def reload_model(self):
        with self._model_lock:
            self._model = None
        return self._load_model()

    def _prewarm(self):
        """
        Run a silent 1×1 dummy inference so PyTorch allocates all layers and
        CUDA memory before the first real frame arrives.
        Runs once in a daemon thread at import time.
        """
        def _do():
            try:
                model = self._load_model()
                if model is None:
                    return
                dummy = np.zeros((64, 64, 3), dtype=np.uint8)
                model.predict(
                    dummy,
                    imgsz=int(_YOLO_CONFIG.get("imgsz", 320)),
                    conf=0.9,   # high threshold so nothing spurious fires
                    device=_torch_device(),
                    verbose=False,
                )
            except Exception:
                pass  # pre-warm is best-effort

        t = threading.Thread(target=_do, daemon=True, name="yolo-prewarm")
        t.start()

    # ── YOLO inference ────────────────────────────────────────────────────────
    def _detect_with_yolo(self, frame) -> Optional[Dict]:
        model = self._load_model()
        if model is None:
            return None

        results = model.predict(
            frame,
            imgsz=int(_YOLO_CONFIG.get("imgsz", 320)),
            conf=float(_YOLO_CONFIG.get("conf", 0.25)),
            iou=float(_YOLO_CONFIG.get("iou", 0.45)),
            max_det=int(_YOLO_CONFIG.get("max_det", 5)),
            device=_torch_device(),
            verbose=False,
        )
        if not results:
            return None

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        confs    = boxes.conf.cpu().numpy()
        best_idx = int(np.argmax(confs))
        xyxy     = boxes.xyxy[best_idx].cpu().numpy().tolist()
        conf     = float(confs[best_idx])

        x1, y1, x2, y2 = [int(max(0, v)) for v in xyxy]
        h, w = frame.shape[:2]
        x1 = min(x1, w - 1); x2 = min(max(x2, x1 + 1), w)
        y1 = min(y1, h - 1); y2 = min(max(y2, y1 + 1), h)

        box_w = max(1, x2 - x1); box_h = max(1, y2 - y1)
        pad   = max(6, int(0.08 * max(box_w, box_h)))
        x1 = max(0, x1 - pad); y1 = max(0, y1 - pad)
        x2 = min(w, x2 + pad);  y2 = min(h, y2 + pad)

        crop = frame[y1:y2, x1:x2]
        ocr  = read_plate_text(crop)
        if not ocr:
            return None

        return {
            "plate_text": ocr["plate_text"],
            "confidence": ocr.get("confidence"),
            "bbox": {"x1": x1, "y1": y1, "x2": x2, "y2": y2, "detector_conf": conf},
            "raw_text":   ocr.get("raw_text"),
            "candidates": ocr.get("candidates"),
            "detector":   "yolo",
        }

    # ── contour wrapper (adds detector tag) ───────────────────────────────────
    @staticmethod
    def _detect_with_contour(frame) -> Optional[Dict]:
        result = contour_detect(frame)
        if result:
            result["detector"] = "contour"
        return result

    # ── scoring helper ────────────────────────────────────────────────────────
    @staticmethod
    def _score(det: Dict) -> float:
        cand = det.get("candidates")
        if isinstance(cand, list) and cand:
            scores = [c.get("score", -1.0) for c in cand if isinstance(c, dict)]
            if scores:
                return max(scores)
        conf = det.get("confidence")
        return float(conf or 0) * 100.0

    # ── main detect entry point ───────────────────────────────────────────────
    def detect(self, frame, mode_override: Optional[str] = None) -> Optional[Dict]:
        mode = (mode_override or self._mode or "auto").lower()

        # ── contour-only ──
        if mode in {"contour", "opencv", "classic"}:
            return self._detect_with_contour(frame)

        # ── yolo-only ──
        if mode == "yolo":
            return self._detect_with_yolo(frame)

        # ── auto: run YOLO and contour concurrently ───────────────────────────
        # Submit both detectors to the shared thread pool.
        # We collect both results and pick the best one by score so accuracy
        # is not sacrificed; but we don't block longer than the slower detector
        # would anyway – both run simultaneously.
        futures: Dict[str, Future] = {
            "yolo":    _detector_pool.submit(self._detect_with_yolo, frame),
            "contour": _detector_pool.submit(self._detect_with_contour, frame),
        }

        yolo_result    = None
        contour_result = None
        for future in as_completed(futures.values()):
            for name, f in futures.items():
                if f is future:
                    try:
                        result = future.result()
                        if name == "yolo":
                            yolo_result = result
                        else:
                            contour_result = result
                    except Exception:
                        pass

        # Pick the winner
        if yolo_result and not contour_result:
            return yolo_result
        if contour_result and not yolo_result:
            return contour_result
        if not yolo_result and not contour_result:
            return None

        y_score = self._score(yolo_result)
        c_score = self._score(contour_result)
        if y_score > c_score:
            return yolo_result
        if c_score > y_score:
            return contour_result
        # Tie-break: prefer longer plate text
        y_text = yolo_result.get("plate_text") or ""
        c_text = contour_result.get("plate_text") or ""
        return yolo_result if len(y_text) >= len(c_text) else contour_result


# ── Module-level singleton ────────────────────────────────────────────────────
_detector = PlateDetector()
# Kick off pre-warm immediately at import time
_detector._prewarm()


def detect_plate(frame, mode_override: Optional[str] = None) -> Optional[Dict]:
    return _detector.detect(frame, mode_override=mode_override)


def reload_yolo_model():
    return _detector.reload_model()
