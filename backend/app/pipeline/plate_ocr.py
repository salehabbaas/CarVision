import logging
import time
from typing import List, Optional

from anpr import normalize_plate, read_plate_text

from .schemas import OCRResult, PlateDetection, PlateRectification

logger = logging.getLogger("anpr.pipeline")


def recognize(
    variants: List[PlateRectification],
    detection: Optional[PlateDetection] = None,
    plate_type: Optional[str] = None,
) -> OCRResult:
    start = time.perf_counter()

    if detection and detection.plate_text:
        normalized = normalize_plate(detection.plate_text)
        timing_ms = (time.perf_counter() - start) * 1000.0
        result = OCRResult(
            stage_name="plate_ocr",
            timing_ms=timing_ms,
            confidence=detection.confidence,
            debug={"note": "legacy_detection_ocr", "plate_type": plate_type},
            raw_text=detection.raw_text,
            normalized_text=normalized or detection.plate_text,
            candidates=detection.candidates,
            engine_name="legacy",
        )
        logger.debug("plate_ocr", extra={"timing_ms": timing_ms, "engine": result.engine_name})
        return result

    best_variant = variants[0] if variants else None
    ocr = None
    if best_variant and best_variant.crop is not None:
        ocr = read_plate_text(best_variant.crop)

    timing_ms = (time.perf_counter() - start) * 1000.0
    if not ocr:
        result = OCRResult(
            stage_name="plate_ocr",
            timing_ms=timing_ms,
            confidence=None,
            debug={"note": "no_ocr", "plate_type": plate_type},
            engine_name="easyocr",
        )
        logger.debug("plate_ocr: none", extra={"timing_ms": timing_ms})
        return result

    normalized = normalize_plate(ocr.get("plate_text", ""))
    result = OCRResult(
        stage_name="plate_ocr",
        timing_ms=timing_ms,
        confidence=ocr.get("confidence"),
        debug={"note": "direct_ocr", "plate_type": plate_type},
        raw_text=ocr.get("raw_text"),
        normalized_text=normalized or ocr.get("plate_text"),
        candidates=ocr.get("candidates"),
        engine_name="easyocr",
    )
    logger.debug("plate_ocr", extra={"timing_ms": timing_ms, "engine": result.engine_name})
    return result
