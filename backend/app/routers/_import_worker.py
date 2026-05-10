"""Background worker that validates and atomically restores a backup ZIP."""
from __future__ import annotations

import json
import logging
import shutil
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
    _coerce_row,
    _set_import_state,
    _sha256_file,
    EXPORT_FORMAT,
)

logger = logging.getLogger("carvision.routers.exports")


def _run_import(extracted_dir: Path, job_id: str) -> None:
    """Atomic import: validate → DB replace → file copy. Rollback on any error."""
    copied_files: list[Path] = []
    db = SessionLocal()

    try:
        # ── Phase 1: Validate manifest ────────────────────────────────────────
        _set_import_state(phase="validating", percent=5, message="Validating manifest…", error=None)

        manifest_path = extracted_dir / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("manifest.json not found in backup")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("export_format") != EXPORT_FORMAT:
            raise ValueError(
                f"Unsupported export format: {manifest.get('export_format')!r}. "
                f"Expected {EXPORT_FORMAT!r}"
            )

        # ── Phase 2: Verify file checksums ────────────────────────────────────
        _set_import_state(phase="validating", percent=15, message="Verifying file checksums…")

        checksums: dict[str, str] = manifest.get("media_checksums", {})
        for arc_path, expected_hex in checksums.items():
            local = extracted_dir / arc_path
            if not local.is_file():
                raise ValueError(f"Expected file missing from backup: {arc_path}")
            actual = _sha256_file(local)
            if actual != expected_hex:
                raise ValueError(
                    f"Checksum mismatch for {arc_path}: "
                    f"expected {expected_hex}, got {actual}"
                )

        # ── Phase 3: Load backup data ─────────────────────────────────────────
        _set_import_state(phase="importing", percent=25, message="Loading backup data…")

        def _load(table: str) -> list[dict]:
            p = extracted_dir / "data" / f"{table}.json"
            if not p.is_file():
                return []
            return json.loads(p.read_text(encoding="utf-8"))

        data_cameras = _load("cameras")
        data_detections = _load("detections")
        data_allowed_plates = _load("allowed_plates")
        data_training_samples = _load("training_samples")
        data_training_jobs = _load("training_jobs")
        data_clip_records = _load("clip_records")
        data_notifications = _load("notifications")
        data_app_settings = _load("app_settings")
        data_runtime_settings = _load("runtime_settings")
        data_model_versions = _load("model_versions")

        # ── Phase 4: Database replace (single transaction) ────────────────────
        _set_import_state(percent=35, message="Replacing database records…")

        # Save protected auth keys before wiping app_settings
        auth_rows = {
            r.key: r.value
            for r in db.query(AppSetting).all()
            if any(r.key.startswith(p) for p in _AUTH_PREFIXES)
        }

        # Delete in FK-safe order
        db.query(Notification).delete()
        db.query(ClipRecord).delete()
        db.query(Detection).delete()
        db.query(TrainingJob).delete()
        db.query(TrainingSample).delete()
        # Nullify self-FK before deleting model_versions
        db.query(ModelVersion).update({"rollback_source_id": None})
        db.query(ModelVersion).delete()
        db.query(Camera).delete()
        db.query(RuntimeSettings).delete()
        db.query(AppSetting).delete()
        db.query(AllowedPlate).delete()
        db.flush()

        _set_import_state(percent=45, message="Inserting backup data…")

        # Insert in dependency order
        for row in data_allowed_plates:
            db.add(AllowedPlate(**_coerce_row(row, AllowedPlate)))

        # app_settings from backup (no auth keys)
        for row in data_app_settings:
            key = row.get("key", "")
            if any(key.startswith(p) for p in _AUTH_PREFIXES):
                continue
            db.add(AppSetting(**_coerce_row(row, AppSetting)))

        # Restore auth keys (they were saved above)
        for key, value in auth_rows.items():
            db.add(AppSetting(key=key, value=value))

        # runtime_settings: keep hardware fields from current system
        for row in data_runtime_settings:
            for field in _HW_FIELDS:
                row.pop(field, None)
            db.add(RuntimeSettings(**_coerce_row(row, RuntimeSettings)))

        for row in data_cameras:
            db.add(Camera(**_coerce_row(row, Camera)))
        db.flush()  # assign camera PKs for FK children

        # model_versions: drop self-referential rollback FK (lineage not preserved)
        for row in data_model_versions:
            row.pop("rollback_source_id", None)
            db.add(ModelVersion(**_coerce_row(row, ModelVersion)))
        db.flush()

        for row in data_training_samples:
            db.add(TrainingSample(**_coerce_row(row, TrainingSample)))

        for row in data_training_jobs:
            db.add(TrainingJob(**_coerce_row(row, TrainingJob)))

        for row in data_detections:
            db.add(Detection(**_coerce_row(row, Detection)))
        db.flush()  # assign detection PKs for notifications

        for row in data_clip_records:
            db.add(ClipRecord(**_coerce_row(row, ClipRecord)))

        for row in data_notifications:
            db.add(Notification(**_coerce_row(row, Notification)))

        db.commit()

        # ── Phase 5: Copy media files ─────────────────────────────────────────
        _set_import_state(percent=75, message="Copying media files…")

        media_root = Path(MEDIA_DIR)
        model_root = Path(PROJECT_ROOT) / "models"

        media_src = extracted_dir / "media"
        if media_src.is_dir():
            for src in media_src.rglob("*"):
                if not src.is_file():
                    continue
                rel = src.relative_to(media_src)
                dest = media_root / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied_files.append(dest)

        # Active model
        model_src = extracted_dir / "models" / "plate.pt"
        if model_src.is_file():
            model_root.mkdir(parents=True, exist_ok=True)
            dest = model_root / "plate.pt"
            shutil.copy2(model_src, dest)
            copied_files.append(dest)

        _set_import_state(phase="done", percent=100, message="Import complete.", error=None)
        logger.info("Backup import %s completed successfully.", job_id)

    except Exception as exc:
        logger.exception("Backup import %s failed: %s", job_id, exc)
        try:
            db.rollback()
        except Exception:
            pass
        for f in copied_files:
            f.unlink(missing_ok=True)
        _set_import_state(phase="error", percent=0, message="Import failed.", error=str(exc))

    finally:
        db.close()
        shutil.rmtree(extracted_dir.parent, ignore_errors=True)
