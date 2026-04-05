import logging
import time
from typing import Optional

from .schemas import FrameCandidate

logger = logging.getLogger("anpr.pipeline")


def select_frame(frame, camera_id: Optional[int] = None, frame_id: Optional[str] = None) -> FrameCandidate:
    start = time.perf_counter()
    ts = time.time()
    timing_ms = (time.perf_counter() - start) * 1000.0
    result = FrameCandidate(
        stage_name="frame_selector",
        timing_ms=timing_ms,
        confidence=1.0,
        debug={},
        frame=frame,
        ts=ts,
        camera_id=camera_id,
        frame_id=frame_id,
    )
    logger.debug("frame_selector", extra={"camera_id": camera_id, "timing_ms": timing_ms})
    return result
