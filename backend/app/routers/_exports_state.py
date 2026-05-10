"""Shared state, locks, constants, and serialization helpers for the exports router."""
from __future__ import annotations

import hashlib
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import DateTime

EXPORT_FORMAT = "carvision-backup-v1"
_CHUNK = 65536  # 64 KB

# Auth setting keys that must never leave or be overwritten by a backup
_AUTH_PREFIXES = ("auth_admin_", "auth_master_")

# RuntimeSettings columns that are hardware-specific and must not be imported
_HW_FIELDS = frozenset(
    {"runtime_profile", "inference_device", "training_device", "model_backend"}
)

# ── Export background state ───────────────────────────────────────────────────

_EXPORT_LOCK = threading.Lock()
_EXPORT_STATE: dict[str, Any] = {
    "phase": "idle",   # idle | building | ready | error
    "percent": 0,
    "message": "",
    "error": None,
    "job_id": None,
    "file_path": None,
    "filename": None,
}


def _set_export_state(**kwargs: Any) -> None:
    with _EXPORT_LOCK:
        _EXPORT_STATE.update(kwargs)


def _get_export_state() -> dict[str, Any]:
    with _EXPORT_LOCK:
        return dict(_EXPORT_STATE)


# ── Import background state ───────────────────────────────────────────────────

_IMPORT_LOCK = threading.Lock()
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


def _coerce_row(row: dict[str, Any], model_cls: Any) -> dict[str, Any]:
    """Return only keys that exist as columns in model_cls, converting ISO datetime
    strings back to datetime objects where needed."""
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
