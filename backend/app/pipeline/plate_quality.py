import logging
import os
import time
from typing import List

import cv2
import numpy as np

from .schemas import PlateCrop, PlateQuality

logger = logging.getLogger("anpr.pipeline")


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _quality_metrics(crop) -> dict:
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    lap_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    brightness = float(np.mean(gray)) / 255.0
    contrast = float(np.std(gray)) / 128.0

    edges = cv2.Canny(gray, 50, 150)
    edge_density = float(np.mean(edges > 0))

    blur_score = _clamp(lap_var / 800.0)
    brightness_score = 1.0 - abs(brightness - 0.5) * 2.0
    contrast_score = _clamp(contrast)
    edge_score = _clamp(edge_density * 4.0)

    score = _clamp(
        0.4 * blur_score
        + 0.2 * contrast_score
        + 0.2 * edge_score
        + 0.2 * brightness_score
    )

    return {
        "lap_var": lap_var,
        "brightness": brightness,
        "contrast": contrast,
        "edge_density": edge_density,
        "blur_score": blur_score,
        "brightness_score": brightness_score,
        "contrast_score": contrast_score,
        "edge_score": edge_score,
        "score": score,
    }


def score_crops(crops: List[PlateCrop]) -> List[PlateQuality]:
    min_score = float(os.getenv("ANPR_PLATE_QUALITY_MIN", "0.25"))
    results: List[PlateQuality] = []
    for crop in crops:
        start = time.perf_counter()
        metrics = _quality_metrics(crop.crop)
        timing_ms = (time.perf_counter() - start) * 1000.0
        score = metrics["score"]
        accepted = score >= min_score
        results.append(
            PlateQuality(
                stage_name="plate_quality",
                timing_ms=timing_ms,
                confidence=crop.confidence,
                debug=metrics,
                score=score,
                accepted=accepted,
                crop=crop,
            )
        )
    logger.debug("plate_quality", extra={"count": len(results)})
    return results
