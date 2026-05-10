"""Background worker that builds the export ZIP."""
from __future__ import annotations

import json
import logging
import os
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from core.config import MEDIA_DIR, PROJECT_ROOT
from db import SessionLocal
from models import (
    AllowedPlate,
    AppSetting,
    Camera,
    ClipRecord,
    Detection,
    ModelVersion,
    Notification,
    RuntimeSettings,
    TrainingJob,
    TrainingSample,
)
from routers._exports_state import (
    _AUTH_PREFIXES,
    _HW_FIELDS,
    _row_to_dict,
    _set_export_state,
    _sha256_zip_member,
)

logger = logging.getLogger("carvision.routers.exports")

EXPORT_FORMAT = "carvision-backup-v1"


def _run_export(include_detection_images: bool, job_id: str) -> None:
    """Build export ZIP in a daemon thread so the uvicorn pool stays free."""
    db = SessionLocal()
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="carvision_export_")
    os.close(tmp_fd)

    try:
        # ── Phase 1: Query database ───────────────────────────────────────────
        _set_export_state(phase="building", percent=5, message="Querying database…", error=None)

        media_root = Path(MEDIA_DIR)
        model_root = Path(PROJECT_ROOT) / "models"

        cameras = [_row_to_dict(r) for r in db.query(Camera).all()]
        detections = [_row_to_dict(r) for r in db.query(Detection).all()]
        allowed_plates = [_row_to_dict(r) for r in db.query(AllowedPlate).all()]
        training_samples = [_row_to_dict(r) for r in db.query(TrainingSample).all()]
        training_jobs = [_row_to_dict(r) for r in db.query(TrainingJob).all()]
        clip_records = [_row_to_dict(r) for r in db.query(ClipRecord).all()]
        notifications = [_row_to_dict(r) for r in db.query(Notification).all()]
        model_versions = [_row_to_dict(r) for r in db.query(ModelVersion).all()]

        app_settings = [
            _row_to_dict(r)
            for r in db.query(AppSetting).all()
            if not any(r.key.startswith(p) for p in _AUTH_PREFIXES)
        ]

        rt_rows = db.query(RuntimeSettings).all()
        runtime_settings = []
        for r in rt_rows:
            d = _row_to_dict(r)
            for field in _HW_FIELDS:
                d.pop(field, None)
            runtime_settings.append(d)

        db.close()
        db = None

        tables = {
            "cameras": cameras,
            "detections": detections,
            "allowed_plates": allowed_plates,
            "training_samples": training_samples,
            "training_jobs": training_jobs,
            "clip_records": clip_records,
            "notifications": notifications,
            "app_settings": app_settings,
            "runtime_settings": runtime_settings,
            "model_versions": model_versions,
        }

        # ── Phase 2: Build ZIP ────────────────────────────────────────────────
        _set_export_state(percent=20, message="Building backup archive…")

        media_checksums: dict[str, str] = {}

        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # JSON table dumps
            _set_export_state(percent=25, message="Serialising database tables…")
            for name, rows in tables.items():
                zf.writestr(
                    f"data/{name}.json",
                    json.dumps(rows, ensure_ascii=False, indent=2),
                )

            # Training sample images
            _set_export_state(percent=40, message="Packing training samples…")
            for sample in training_samples:
                rel = sample.get("image_path")
                if not rel:
                    continue
                src = media_root / rel
                if not src.is_file():
                    continue
                arc_name = f"media/training_samples/{src.name}"
                zf.write(src, arc_name)
                media_checksums[arc_name] = _sha256_zip_member(zf, arc_name)

            # Detection snapshot images (optional)
            if include_detection_images:
                _set_export_state(percent=60, message="Packing detection images…")
                for det in detections:
                    rel = det.get("image_path")
                    if not rel:
                        continue
                    src = media_root / rel
                    if not src.is_file():
                        continue
                    arc_name = f"media/detections/{src.name}"
                    if arc_name not in media_checksums:
                        zf.write(src, arc_name)
                        media_checksums[arc_name] = _sha256_zip_member(zf, arc_name)

            # Active model file
            _set_export_state(percent=80, message="Packing model weights…")
            active_mv = next((mv for mv in model_versions if mv.get("active")), None)
            if active_mv:
                model_src = Path(active_mv["path"])
                if not model_src.is_absolute():
                    model_src = model_root / model_src
                if model_src.is_file():
                    arc_name = "models/plate.pt"
                    zf.write(model_src, arc_name)
                    media_checksums[arc_name] = _sha256_zip_member(zf, arc_name)

            # Manifest (written last so checksums are complete)
            _set_export_state(percent=90, message="Writing manifest…")
            manifest = {
                "export_format": EXPORT_FORMAT,
                "exported_at": datetime.utcnow().isoformat() + "Z",
                "options": {"include_detection_images": include_detection_images},
                "record_counts": {k: len(v) for k, v in tables.items()},
                "media_checksums": media_checksums,
                "notes": {
                    "onvif_credentials": (
                        "Fernet-encrypted; require matching FERNET_KEY on destination"
                    ),
                    "users": "User credentials are never included in exports.",
                    "hardware": (
                        "Hardware-specific settings (profile, devices, backend) are "
                        "excluded so the backup restores cleanly on different hardware."
                    ),
                },
            }
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"carvision-backup-{ts}.zip"
        _set_export_state(
            phase="ready",
            percent=100,
            message="Backup ready for download.",
            error=None,
            file_path=tmp_path,
            filename=filename,
        )
        logger.info("Backup export %s ready: %s", job_id, filename)

    except Exception as exc:
        logger.exception("Backup export %s failed: %s", job_id, exc)
        Path(tmp_path).unlink(missing_ok=True)
        _set_export_state(
            phase="error",
            percent=0,
            message="Export failed.",
            error=str(exc),
            file_path=None,
            filename=None,
        )
    finally:
        if db is not None:
            db.close()
