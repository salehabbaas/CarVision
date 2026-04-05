import os
from typing import Optional, Dict

import numpy as np

from anpr import detect_plate as contour_detect, read_plate_text

try:
    from ultralytics import YOLO
except Exception:
    YOLO = None

_YOLO_CONFIG = {
    "conf": 0.25,
    "imgsz": 640,
    "iou": 0.45,
    "max_det": 5,
}


def set_yolo_config(config: Dict):
    if not isinstance(config, dict):
        return
    for key in _YOLO_CONFIG.keys():
        if key in config and config[key] is not None:
            _YOLO_CONFIG[key] = config[key]


class PlateDetector:
    def __init__(self):
        self._model = None
        self._model_path = os.getenv("YOLO_PLATE_MODEL", "")
        self._mode = os.getenv("ANPR_DETECTOR", "auto").lower()

    def _load_model(self):
        if self._model is not None:
            return self._model
        if YOLO is None:
            return None
        if not self._model_path:
            return None
        if not os.path.exists(self._model_path):
            return None
        self._model = YOLO(self._model_path)
        return self._model

    def reload_model(self):
        self._model = None
        return self._load_model()

    def _detect_with_yolo(self, frame) -> Optional[Dict]:
        model = self._load_model()
        if model is None:
            return None

        results = model.predict(
            frame,
            imgsz=int(_YOLO_CONFIG.get("imgsz", 640)),
            conf=float(_YOLO_CONFIG.get("conf", 0.25)),
            iou=float(_YOLO_CONFIG.get("iou", 0.45)),
            max_det=int(_YOLO_CONFIG.get("max_det", 5)),
            verbose=False,
        )
        if not results:
            return None

        boxes = results[0].boxes
        if boxes is None or len(boxes) == 0:
            return None

        # Pick highest confidence detection
        confs = boxes.conf.cpu().numpy()
        best_idx = int(np.argmax(confs))
        xyxy = boxes.xyxy[best_idx].cpu().numpy().tolist()
        conf = float(confs[best_idx])

        x1, y1, x2, y2 = [int(max(0, v)) for v in xyxy]
        h, w = frame.shape[:2]
        x1 = min(x1, w - 1)
        x2 = min(max(x2, x1 + 1), w)
        y1 = min(y1, h - 1)
        y2 = min(max(y2, y1 + 1), h)

        box_w = max(1, x2 - x1)
        box_h = max(1, y2 - y1)
        pad = max(6, int(0.08 * max(box_w, box_h)))
        x1 = max(0, x1 - pad)
        y1 = max(0, y1 - pad)
        x2 = min(w, x2 + pad)
        y2 = min(h, y2 + pad)

        crop = frame[y1:y2, x1:x2]
        ocr = read_plate_text(crop)
        if not ocr:
            return None

        return {
            "plate_text": ocr["plate_text"],
            "confidence": ocr.get("confidence"),
            "bbox": {
                "x1": x1,
                "y1": y1,
                "x2": x2,
                "y2": y2,
                "detector_conf": conf,
            },
            "raw_text": ocr.get("raw_text"),
            "candidates": ocr.get("candidates"),
            "detector": "yolo",
        }

    def detect(self, frame, mode_override: Optional[str] = None) -> Optional[Dict]:
        mode = (mode_override or self._mode or "auto").lower()
        if mode in {"contour", "opencv", "classic"}:
            result = contour_detect(frame)
            if result:
                result["detector"] = "contour"
            return result
        if mode in {"yolo", "auto"}:
            yolo_result = self._detect_with_yolo(frame)
            contour_result = contour_detect(frame)
            if contour_result:
                contour_result["detector"] = "contour"
            if mode == "yolo":
                return yolo_result
            if yolo_result and not contour_result:
                return yolo_result
            if contour_result and not yolo_result:
                return contour_result
            if not yolo_result and not contour_result:
                return None

            def _score(det: Dict) -> float:
                cand = det.get("candidates")
                if isinstance(cand, list) and cand:
                    scores = [c.get("score", -1.0) for c in cand if isinstance(c, dict)]
                    if scores:
                        return max(scores)
                conf = det.get("confidence")
                return float(conf or 0) * 100.0

            y_score = _score(yolo_result)
            c_score = _score(contour_result)
            if y_score > c_score:
                return yolo_result
            if c_score > y_score:
                return contour_result

            # Tie-break: prefer longer plate_text
            y_text = yolo_result.get("plate_text") or ""
            c_text = contour_result.get("plate_text") or ""
            return yolo_result if len(y_text) >= len(c_text) else contour_result
        result = contour_detect(frame)
        if result:
            result["detector"] = "contour"
        return result


_detector = PlateDetector()


def detect_plate(frame, mode_override: Optional[str] = None) -> Optional[Dict]:
    return _detector.detect(frame, mode_override=mode_override)


def reload_yolo_model():
    return _detector.reload_model()
