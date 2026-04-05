import logging
import time
from typing import Optional

from .schemas import PlateClassification, PlateRectification

logger = logging.getLogger("anpr.pipeline")


def classify(crop: Optional[PlateRectification]) -> PlateClassification:
    start = time.perf_counter()
    timing_ms = (time.perf_counter() - start) * 1000.0
    result = PlateClassification(
        stage_name="plate_classifier",
        timing_ms=timing_ms,
        confidence=None,
        debug={"note": "heuristic_stub"},
        plate_type="unknown",
    )
    logger.debug("plate_classifier", extra={"timing_ms": timing_ms, "plate_type": result.plate_type})
    return result
