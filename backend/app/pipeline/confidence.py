import logging
import time
from typing import Optional

from .schemas import ConfidenceResult, OCRResult, PlateDetection, PlateQuality

logger = logging.getLogger("anpr.pipeline")


def fuse_confidence(
    ocr: Optional[OCRResult],
    detection: Optional[PlateDetection],
    quality: Optional[PlateQuality],
) -> ConfidenceResult:
    start = time.perf_counter()
    conf = None
    if ocr and ocr.confidence is not None:
        conf = float(ocr.confidence)
    elif detection and detection.confidence is not None:
        conf = float(detection.confidence)

    quality_score = quality.score if quality is not None else None
    if conf is not None and quality_score is not None:
        conf = max(0.0, min(1.0, conf)) * (0.6 + 0.4 * quality_score)

    timing_ms = (time.perf_counter() - start) * 1000.0
    result = ConfidenceResult(
        stage_name="confidence",
        timing_ms=timing_ms,
        confidence=conf,
        debug={"quality_score": quality_score},
        fused_confidence=conf,
    )
    logger.debug("confidence", extra={"timing_ms": timing_ms, "confidence": conf})
    return result
