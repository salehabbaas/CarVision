"""services/model_export.py — post-training model export by runtime profile."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("carvision.model_export")

# Map profile → preferred export format
PROFILE_FORMAT: dict[str, str] = {
    "cpu": "onnx",
    "nvidia": "engine",   # TensorRT
    "mac": "coreml",
}

# Candidate benchmark script for profiling (optional, best-effort)
_BENCHMARK_FORMATS = {"onnx", "engine", "openvino", "coreml"}


def profile_to_format(profile: str) -> str:
    """Return the preferred export format for a runtime profile."""
    return PROFILE_FORMAT.get(profile.lower(), "onnx")


def export_model(
    model_path: str,
    export_format: str,
    imgsz: int = 640,
    device: str = "cpu",
) -> Tuple[Optional[str], Optional[str]]:
    """Export a YOLO .pt model to *export_format*.

    Returns (exported_path, error_message).  On success, error_message is None.
    On failure, exported_path is None and error_message describes the problem.
    """
    try:
        from ultralytics import YOLO
    except ImportError:
        return None, "ultralytics is not installed"

    model_file = Path(model_path)
    if not model_file.exists():
        return None, f"Model file not found: {model_path}"

    fmt = export_format.strip().lower()
    if fmt in ("pt", "pytorch", ""):
        return model_path, None

    logger.info("Exporting %s → format=%s imgsz=%d device=%s", model_path, fmt, imgsz, device)
    try:
        model = YOLO(str(model_file))
        exported = model.export(format=fmt, imgsz=imgsz, device=device)
        if not exported:
            return None, "export() returned no path"
        exported_path = str(exported)
        logger.info("Export complete: %s", exported_path)
        return exported_path, None
    except Exception as exc:
        msg = str(exc)
        logger.warning("Export failed (%s → %s): %s", model_path, fmt, msg)
        return None, msg


def activate_model_version(db, model_version_id: int) -> bool:
    """Mark one ModelVersion as active, deactivating all others.

    Returns True if the activation was committed.
    """
    from models import ModelVersion

    target = db.get(ModelVersion, model_version_id)
    if not target:
        return False
    # Deactivate all others
    db.query(ModelVersion).filter(ModelVersion.id != model_version_id).update(
        {ModelVersion.active: False}, synchronize_session=False
    )
    target.active = True
    db.add(target)
    db.commit()
    logger.info("Activated ModelVersion id=%d path=%s", target.id, target.path)
    return True


def register_model_version(
    db,
    *,
    path: str,
    fmt: str = "pytorch",
    profile: str = "cpu",
    metrics: Optional[dict] = None,
    rollback_source_id: Optional[int] = None,
) -> "ModelVersion":
    """Insert a new ModelVersion row (inactive by default)."""
    from models import ModelVersion

    mv = ModelVersion(
        path=path,
        format=fmt,
        profile=profile,
        metrics=metrics or {},
        active=False,
        rollback_source_id=rollback_source_id,
    )
    db.add(mv)
    db.commit()
    db.refresh(mv)
    logger.info("Registered ModelVersion id=%d path=%s profile=%s", mv.id, mv.path, mv.profile)
    return mv


def should_activate(new_metrics: dict, current_metrics: Optional[dict]) -> bool:
    """Return True if new_metrics represents an improvement over current_metrics.

    Uses mAP50 as the primary key; falls back to precision if absent.
    If there is no current active model, always returns True.
    """
    if not current_metrics:
        return True

    def _map50(m: dict) -> Optional[float]:
        for key in ("metrics/mAP50(B)", "mAP50", "map50", "mAP_0.5"):
            if key in m:
                try:
                    return float(m[key])
                except Exception:
                    pass
        return None

    new_score = _map50(new_metrics)
    cur_score = _map50(current_metrics)

    if new_score is None:
        return False
    if cur_score is None:
        return True
    return new_score > cur_score
