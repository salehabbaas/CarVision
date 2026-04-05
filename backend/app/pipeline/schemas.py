from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StageResult:
    stage_name: str
    timing_ms: float
    confidence: Optional[float] = None
    debug: Dict[str, Any] = field(default_factory=dict)


@dataclass
class FrameCandidate(StageResult):
    frame: Any = None
    ts: float = 0.0
    camera_id: Optional[int] = None
    frame_id: Optional[str] = None


@dataclass
class PlateDetection(StageResult):
    bbox: Any = None
    detector_name: Optional[str] = None
    class_name: Optional[str] = None
    raw_text: Optional[str] = None
    plate_text: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None


@dataclass
class PlateCrop(StageResult):
    crop: Any = None
    bbox: Any = None
    detection: Optional[PlateDetection] = None


@dataclass
class PlateQuality(StageResult):
    score: float = 0.0
    accepted: bool = True
    crop: Optional[PlateCrop] = None


@dataclass
class PlateRectification(StageResult):
    crop: Any = None
    variant_name: str = "original"
    source_quality: Optional[PlateQuality] = None


@dataclass
class PlateClassification(StageResult):
    plate_type: str = "unknown"


@dataclass
class OCRResult(StageResult):
    raw_text: Optional[str] = None
    normalized_text: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None
    engine_name: Optional[str] = None
    char_scores: Optional[List[float]] = None


@dataclass
class PostprocessResult(StageResult):
    raw_text: Optional[str] = None
    normalized_text: Optional[str] = None
    candidates: Optional[List[Dict[str, Any]]] = None
    engine_name: Optional[str] = None


@dataclass
class ConfidenceResult(StageResult):
    fused_confidence: Optional[float] = None


@dataclass
class TrackerResult(StageResult):
    status: str = "candidate"


@dataclass
class PlateInferenceResult(StageResult):
    plate_text: Optional[str] = None
    raw_text: Optional[str] = None
    bbox: Any = None
    plate_type: Optional[str] = None
    ocr_result: Optional[OCRResult] = None
    detection: Optional[PlateDetection] = None
    crops: Optional[List[PlateRectification]] = None
    stage_outputs: Dict[str, Any] = field(default_factory=dict)

    def to_legacy_detection(self) -> Optional[Dict[str, Any]]:
        if not self.plate_text:
            return None
        return {
            "plate_text": self.plate_text,
            "confidence": self.confidence,
            "bbox": self.bbox,
            "raw_text": self.raw_text,
            "candidates": (self.ocr_result.candidates if self.ocr_result else None),
        }
