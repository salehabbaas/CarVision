"""routers/settings.py — hardware probe and runtime settings API."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Body, Depends
from sqlalchemy.orm import Session

from db import get_db
from models import RuntimeSettings
from routers.deps import get_current_user

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

_VALID_PROFILES = {"cpu", "nvidia", "mac"}
_VALID_DEVICES = {"cpu", "cuda", "mps", "auto"}
_VALID_BACKENDS = {"pytorch", "onnx", "tensorrt", "openvino", "coreml"}
_VALID_OCR_ENGINES = {"easyocr", "paddleocr", "tesseract"}


def _probe_hardware() -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "cpu": True,
        "cuda": False,
        "mps": False,
        "gpu_names": [],
        "pytorch_available": False,
        "usable_backends": ["pytorch"],
    }
    try:
        import torch

        result["pytorch_available"] = True
        if torch.cuda.is_available():
            result["cuda"] = True
            result["gpu_names"] = [
                torch.cuda.get_device_name(i) for i in range(torch.cuda.device_count())
            ]
            result["usable_backends"] = ["pytorch", "onnx", "tensorrt", "openvino"]
        mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
        if mps_backend and mps_backend.is_available():
            result["mps"] = True
            if not result["cuda"]:
                result["usable_backends"] = ["pytorch", "coreml"]
    except ImportError:
        pass

    try:
        import onnxruntime as _ort  # noqa: F401

        if "onnx" not in result["usable_backends"]:
            result["usable_backends"].append("onnx")
    except ImportError:
        pass

    return result


def _get_or_create_runtime(db: Session) -> RuntimeSettings:
    row = db.query(RuntimeSettings).first()
    if not row:
        row = RuntimeSettings()
        db.add(row)
        db.commit()
        db.refresh(row)
    return row


def _runtime_payload(row: RuntimeSettings) -> Dict[str, Any]:
    return {
        "runtime_profile": row.runtime_profile,
        "inference_device": row.inference_device,
        "training_device": row.training_device,
        "model_backend": row.model_backend,
        "target_detection_fps": row.target_detection_fps,
        "batch_inference": bool(row.batch_inference),
        "max_live_cameras": row.max_live_cameras,
        "jpeg_quality": row.jpeg_quality,
        "plate_region": row.plate_region,
        "ocr_engine": row.ocr_engine,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _apply_update(row: RuntimeSettings, body: Dict[str, Any]) -> None:
    if "runtime_profile" in body and body["runtime_profile"] in _VALID_PROFILES:
        row.runtime_profile = body["runtime_profile"]
    if "inference_device" in body and body["inference_device"] in _VALID_DEVICES:
        row.inference_device = body["inference_device"]
    if "training_device" in body and body["training_device"] in _VALID_DEVICES:
        row.training_device = body["training_device"]
    if "model_backend" in body and body["model_backend"] in _VALID_BACKENDS:
        row.model_backend = body["model_backend"]
    if "target_detection_fps" in body:
        row.target_detection_fps = max(0.5, min(30.0, float(body["target_detection_fps"])))
    if "batch_inference" in body:
        row.batch_inference = bool(body["batch_inference"])
    if "max_live_cameras" in body:
        row.max_live_cameras = max(1, min(64, int(body["max_live_cameras"])))
    if "jpeg_quality" in body:
        row.jpeg_quality = max(10, min(100, int(body["jpeg_quality"])))
    if "plate_region" in body:
        row.plate_region = str(body["plate_region"])[:50]
    if "ocr_engine" in body and body["ocr_engine"] in _VALID_OCR_ENGINES:
        row.ocr_engine = body["ocr_engine"]


@router.get("/hardware")
def get_hardware(_user: str = Depends(get_current_user)) -> Dict[str, Any]:
    return _probe_hardware()


@router.get("/runtime")
def get_runtime(
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    return _runtime_payload(_get_or_create_runtime(db))


@router.put("/runtime")
def put_runtime(
    body: Dict[str, Any] = Body(...),
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
) -> Dict[str, Any]:
    row = _get_or_create_runtime(db)
    _apply_update(row, body)
    db.commit()
    db.refresh(row)
    return _runtime_payload(row)
