import logging
import time
from typing import List

from anpr import crop_from_bbox

from .schemas import PlateCrop, PlateDetection

logger = logging.getLogger("anpr.pipeline")


def crop_plates(frame, detections: List[PlateDetection]) -> List[PlateCrop]:
    crops: List[PlateCrop] = []
    for det in detections:
        start = time.perf_counter()
        crop = crop_from_bbox(frame, det.bbox)
        timing_ms = (time.perf_counter() - start) * 1000.0
        if crop is None:
            logger.debug("plate_cropper: empty", extra={"timing_ms": timing_ms})
            continue
        crops.append(
            PlateCrop(
                stage_name="plate_cropper",
                timing_ms=timing_ms,
                confidence=det.confidence,
                debug={"bbox": det.bbox},
                crop=crop,
                bbox=det.bbox,
                detection=det,
            )
        )
    logger.debug("plate_cropper", extra={"count": len(crops)})
    return crops
