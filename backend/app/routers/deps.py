"""
routers/deps.py — shared FastAPI dependencies, JWT helpers, and payload builders.

Every router imports from here instead of duplicating auth logic.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from core.config import (
    API_ADMIN_PASS,
    API_ADMIN_USER,
    API_JWT_ALGORITHM,
    API_JWT_EXPIRE_MINUTES,
    API_JWT_SECRET,
)
from db import get_db
from models import AllowedPlate, AppSetting, ClipRecord, Detection, Notification, TrainingSample

logger = logging.getLogger("carvision.deps")

_BEARER = HTTPBearer(auto_error=False)


# ── JWT ───────────────────────────────────────────────────────────────────────

def create_access_token(username: str) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=API_JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, API_JWT_SECRET, algorithm=API_JWT_ALGORITHM)


def decode_token_subject(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        data = jwt.decode(token, API_JWT_SECRET, algorithms=[API_JWT_ALGORITHM])
    except Exception:
        return None
    subject = data.get("sub")
    return str(subject) if subject else None


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_BEARER),
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    subject = decode_token_subject(credentials.credentials)
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    return subject


def verify_credentials(username: str, password: str) -> bool:
    return username == API_ADMIN_USER and password == API_ADMIN_PASS


# ── App settings helpers ──────────────────────────────────────────────────────

def get_setting(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    if not row or row.value is None:
        return default
    return str(row.value)


def set_setting(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if not row:
        row = AppSetting(key=key, value=value)
        db.add(row)
    else:
        row.value = value


def as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    txt = str(value).strip().lower()
    if txt in {"1", "true", "yes", "on"}:
        return True
    if txt in {"0", "false", "no", "off"}:
        return False
    return default


# ── Serialisation helpers ─────────────────────────────────────────────────────

def allowed_plate_payload(row: AllowedPlate) -> Dict[str, Any]:
    return {
        "id": row.id,
        "plate_text": row.plate_text,
        "label": row.label,
        "active": bool(row.active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def training_sample_payload(row: TrainingSample) -> Dict[str, Any]:
    return {
        "id": row.id,
        "image_path": row.image_path,
        "image_hash": row.image_hash,
        "image_width": row.image_width,
        "image_height": row.image_height,
        "plate_text": row.plate_text,
        "bbox": row.bbox,
        "notes": row.notes,
        "no_plate": bool(row.no_plate),
        "unclear_plate": bool(getattr(row, "unclear_plate", False)),
        "ignored": bool(row.ignored),
        "import_batch": row.import_batch,
        "processed_at": row.processed_at.isoformat() if getattr(row, "processed_at", None) else None,
        "processed": bool(getattr(row, "processed_at", None)),
        "last_trained_at": row.last_trained_at.isoformat() if row.last_trained_at else None,
        "trained": bool(row.last_trained_at),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def notification_payload(row: Notification) -> Dict[str, Any]:
    return {
        "id": row.id,
        "title": row.title,
        "message": row.message,
        "level": row.level,
        "kind": row.kind,
        "is_read": bool(row.is_read),
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "camera_id": row.camera_id,
        "detection_id": row.detection_id,
        "extra": row.extra,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def clip_record_payload(row: ClipRecord, camera_name: Optional[str] = None) -> Dict[str, Any]:
    return {
        "id": row.id,
        "camera_id": row.camera_id,
        "camera_name": camera_name,
        "kind": row.kind,
        "file_path": row.file_path,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_seconds": row.duration_seconds,
        "size_bytes": row.size_bytes,
        "detection_count": row.detection_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def create_notification(
    db: Session,
    title: str,
    message: str,
    level: str = "info",
    kind: Optional[str] = None,
    camera_id: Optional[int] = None,
    detection_id: Optional[int] = None,
    extra: Optional[dict] = None,
) -> None:
    level = (level or "info").lower()
    if level not in {"info", "warn", "error", "success"}:
        level = "info"
    row = Notification(
        title=(title or "").strip()[:200] or "Notification",
        message=(message or "").strip()[:2000] or "",
        level=level,
        kind=(kind or "").strip()[:50] if kind else None,
        camera_id=camera_id,
        detection_id=detection_id,
        extra=extra or None,
        is_read=False,
    )
    db.add(row)
    db.commit()
