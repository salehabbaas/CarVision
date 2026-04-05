import logging
import time
from typing import List, Optional

from plate_detector import detect_plate

from .schemas import PlateDetection

logger = logging.getLogger("anpr.pipeline")


def localize(frame, mode_override: Optional[str] = None) -> List[PlateDetection]:
    start = time.perf_counter()
    detection = detect_plate(frame, mode_override=mode_override)
    timing_ms = (time.perf_counter() - start) * 1000.0
    if not detection:
        logger.debug("plate_localizer: none", extra={"timing_ms": timing_ms})
        return []

    bbox = detection.get("bbox")
    detector_name = detection.get("detector_name")
    if not detector_name:
        detector_name = "yolo" if isinstance(bbox, dict) and bbox.get("detector_conf") is not None else "contour"

    result = PlateDetection(
        stage_name="plate_localizer",
        timing_ms=timing_ms,
        confidence=detection.get("confidence"),
        debug={"raw_detection": detection},
        bbox=bbox,
        detector_name=detector_name,
        class_name=detection.get("class_name"),
        raw_text=detection.get("raw_text"),
        plate_text=detection.get("plate_text"),
        candidates=detection.get("candidates"),
    )
    logger.debug("plate_localizer", extra={"timing_ms": timing_ms, "detector": detector_name})
    return [result]
