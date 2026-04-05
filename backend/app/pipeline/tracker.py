import logging
import time
from typing import Optional

from .schemas import TrackerResult

logger = logging.getLogger("anpr.pipeline")


def track_plate(plate_text: Optional[str]) -> TrackerResult:
    start = time.perf_counter()
    timing_ms = (time.perf_counter() - start) * 1000.0
    result = TrackerResult(
        stage_name="tracker",
        timing_ms=timing_ms,
        confidence=None,
        debug={"note": "temporal_stub"},
        status="candidate",
    )
    logger.debug("tracker", extra={"timing_ms": timing_ms, "status": result.status})
    return result
