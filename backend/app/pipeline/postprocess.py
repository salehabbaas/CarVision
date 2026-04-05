import logging
import time
from typing import Optional

from anpr import normalize_plate

from .schemas import OCRResult, PostprocessResult

logger = logging.getLogger("anpr.pipeline")


def postprocess(ocr: OCRResult, plate_type: Optional[str] = None) -> PostprocessResult:
    start = time.perf_counter()
    text = ocr.normalized_text or ocr.raw_text or ""
    normalized = normalize_plate(text)
    timing_ms = (time.perf_counter() - start) * 1000.0
    result = PostprocessResult(
        stage_name="postprocess",
        timing_ms=timing_ms,
        confidence=ocr.confidence,
        debug={"plate_type": plate_type},
        raw_text=ocr.raw_text,
        normalized_text=normalized or text,
        candidates=ocr.candidates,
        engine_name=ocr.engine_name,
    )
    logger.debug("postprocess", extra={"timing_ms": timing_ms})
    return result
