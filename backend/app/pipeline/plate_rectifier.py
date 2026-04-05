import logging
import time
from typing import List

from .schemas import PlateQuality, PlateRectification

logger = logging.getLogger("anpr.pipeline")


def rectify(qualities: List[PlateQuality]) -> List[PlateRectification]:
    results: List[PlateRectification] = []
    for quality in qualities:
        start = time.perf_counter()
        timing_ms = (time.perf_counter() - start) * 1000.0
        results.append(
            PlateRectification(
                stage_name="plate_rectifier",
                timing_ms=timing_ms,
                confidence=quality.confidence,
                debug={"note": "pass_through"},
                crop=quality.crop.crop if quality.crop else None,
                variant_name="original",
                source_quality=quality,
            )
        )
    logger.debug("plate_rectifier", extra={"count": len(results)})
    return results
