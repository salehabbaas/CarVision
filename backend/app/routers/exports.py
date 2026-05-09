"""routers/exports.py — full-system backup export and atomic import."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import shutil
import tempfile
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from starlette.background import BackgroundTask
from sqlalchemy.orm import Session

from core.config import MEDIA_DIR, PROJECT_ROOT
from db import SessionLocal, get_db
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
from routers.deps import get_current_user

logger = logging.getLogger("carvision.routers.exports")
router = APIRouter(prefix="/api/v1/exports", tags=["exports"])

EXPORT_FORMAT = "carvision-backup-v1"
_CHUNK = 65536  # 64 KB

# Auth setting keys that must never leave or be overwritten by a backup
_AUTH_PREFIXES = ("auth_admin_", "auth_master_")

# RuntimeSettings columns that are hardware-specific and must not be imported
_HW_FIELDS = frozenset(
    {"runtime_profile", "inference_device", "training_device", "model_backend"}
)

# ── Import background state ───────────────────────────────────────────────────

_IMPORT_LOCK = threading.Lock()
_IMPORT_THREAD: threading.Thread | None = None
_IMPORT_STATE: dict[str, Any] = {
    "phase": "idle",
    "percent": 0,
    "message": "",
    "error": None,
    "job_id": None,
}


def _set_import_state(**kwargs: Any) -> None:
    with _IMPORT_LOCK:
        _IMPORT_STATE.update(kwargs)


def _get_import_state() -> dict[str, Any]:
    with _IMPORT_LOCK:
        return dict(_IMPORT_STATE)


# ── Serialisation helpers ─────────────────────────────────────────────────────

def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy model row to a plain dict, normalising datetimes."""
    result: dict[str, Any] = {}
    for col in row.__table__.columns:
        val = getattr(row, col.name)
        if isinstance(val, datetime):
            val = val.isoformat()
        result[col.name] = val
    return result


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_zip_member(zf: zipfile.ZipFile, name: str) -> str:
    h = hashlib.sha256()
    with zf.open(name) as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Export endpoint ───────────────────────────────────────────────────────────

@router.get("/download")
def export_download(
    include_detection_images: bool = False,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
) -> FileResponse:
    """Stream a complete backup ZIP of the CarVision installation."""
    media_root = Path(MEDIA_DIR)
    model_root = Path(PROJECT_ROOT) / "models"

    # ── Serialise all tables ──────────────────────────────────────────────────
    cameras = [_row_to_dict(r) for r in db.query(Camera).all()]
    detections = [_row_to_dict(r) for r in db.query(Detection).all()]
    allowed_plates = [_row_to_dict(r) for r in db.query(AllowedPlate).all()]
    training_samples = [_row_to_dict(r) for r in db.query(TrainingSample).all()]
    training_jobs = [_row_to_dict(r) for r in db.query(TrainingJob).all()]
    clip_records = [_row_to_dict(r) for r in db.query(ClipRecord).all()]
    notifications = [_row_to_dict(r) for r in db.query(Notification).all()]
    model_versions = [_row_to_dict(r) for r in db.query(ModelVersion).all()]

    # app_settings: strip auth credential keys
    app_settings = [
        _row_to_dict(r)
        for r in db.query(AppSetting).all()
        if not any(r.key.startswith(p) for p in _AUTH_PREFIXES)
    ]

    # runtime_settings: strip hardware-specific columns
    rt_rows = db.query(RuntimeSettings).all()
    runtime_settings = []
    for r in rt_rows:
        d = _row_to_dict(r)
        for field in _HW_FIELDS:
            d.pop(field, None)
        runtime_settings.append(d)

    # ── Write ZIP to a temp file ──────────────────────────────────────────────
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".zip", prefix="carvision_export_")
    os.close(tmp_fd)

    media_checksums: dict[str, str] = {}

    try:
        with zipfile.ZipFile(tmp_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            # JSON table dumps
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
            for name, rows in tables.items():
                zf.writestr(
                    f"data/{name}.json",
                    json.dumps(rows, ensure_ascii=False, indent=2),
                )

            # Training sample images
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
                for det in detections:
                    rel = det.get("image_path")
                    if not rel:
                        continue
                    src = media_root / rel
                    if not src.is_file():
                        continue
                    arc_name = f"media/detections/{src.name}"
                    if arc_name not in media_checksums:  # dedup
                        zf.write(src, arc_name)
                        media_checksums[arc_name] = _sha256_zip_member(zf, arc_name)

            # Active model file
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

    except Exception:
        Path(tmp_path).unlink(missing_ok=True)
        raise

    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"carvision-backup-{ts}.zip"

    return FileResponse(
        tmp_path,
        media_type="application/zip",
        filename=filename,
        background=BackgroundTask(os.unlink, tmp_path),
    )


# ── Import background worker ──────────────────────────────────────────────────

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

        def _load(table: str) -> list[dict[str, Any]]:
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


def _coerce_row(row: dict[str, Any], model_cls: Any) -> dict[str, Any]:
    """Return only the keys that exist as columns in model_cls, converting
    ISO-format datetime strings back to datetime objects where needed."""
    from sqlalchemy import DateTime
    valid_cols = {col.name: col for col in model_cls.__table__.columns}
    result: dict[str, Any] = {}
    for key, val in row.items():
        if key not in valid_cols:
            continue
        col = valid_cols[key]
        if val is not None and isinstance(col.type, DateTime) and isinstance(val, str):
            try:
                val = datetime.fromisoformat(val.rstrip("Z"))
            except ValueError:
                val = None
        result[key] = val
    return result


# ── Import endpoint ───────────────────────────────────────────────────────────

@router.post("/import")
async def import_upload(
    file: UploadFile = File(...),
    _user: str = Depends(get_current_user),
) -> JSONResponse:
    """Upload a backup ZIP and import it atomically."""
    state = _get_import_state()
    if state["phase"] in {"validating", "importing", "uploading"}:
        raise HTTPException(status_code=409, detail="An import is already in progress")

    tmp_dir = Path(tempfile.mkdtemp(prefix="carvision_import_"))
    zip_path = tmp_dir / "upload.zip"

    try:
        # Stream upload to disk (avoids buffering large ZIPs in RAM)
        with zip_path.open("wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)

        # Basic ZIP integrity check + path-traversal guard before handing off
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    name = info.filename.replace("\\", "/")
                    if name.startswith("..") or name.startswith("/"):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unsafe path in ZIP: {info.filename!r}",
                        )
                zf.extractall(tmp_dir / "extracted")
        except zipfile.BadZipFile:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP")

        zip_path.unlink(missing_ok=True)

    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    job_id = secrets.token_hex(8)
    _set_import_state(phase="uploading", percent=20, message="Starting import…", error=None, job_id=job_id)

    global _IMPORT_THREAD
    _IMPORT_THREAD = threading.Thread(
        target=_run_import,
        args=(tmp_dir / "extracted", job_id),
        daemon=True,
        name=f"carvision-import-{job_id}",
    )
    _IMPORT_THREAD.start()

    return JSONResponse({"ok": True, "job_id": job_id, "message": "Import started"})


# ── Status endpoint ───────────────────────────────────────────────────────────

@router.get("/import/status")
def import_status(_user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current import job state."""
    return _get_import_state()
