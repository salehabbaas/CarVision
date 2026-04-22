"""routers/clips.py — manual clip recording and clip record management."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import ApiClipControlBody, ApiBulkIdsBody
from core.config import MEDIA_DIR
from db import get_db
from models import Camera, ClipRecord, Detection
from routers.deps import clip_record_payload, create_notification, get_current_user

logger = logging.getLogger("carvision.routers.clips")

router = APIRouter(prefix="/api/v1/clips", tags=["clips"])

# Populated by main.py app factory
_manual_clip_manager = None


def _init(manual_clip_manager) -> None:
    global _manual_clip_manager
    _manual_clip_manager = manual_clip_manager


# ── Internal helpers ──────────────────────────────────────────────────────────

def _clip_abs_path(rel_path: Optional[str]) -> Optional[Path]:
    if not rel_path:
        return None
    p = Path(MEDIA_DIR) / rel_path
    return p if p.exists() else None


def _delete_clip_row(db: Session, row: ClipRecord) -> None:
    clip_path = _clip_abs_path(row.file_path)
    if clip_path:
        try:
            clip_path.unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(row)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("")
def list_clips(
    camera_id: Optional[int] = None,
    kind: str = "",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    kind_norm = (kind or "").strip().lower()
    q = (
        db.query(ClipRecord, Camera)
        .join(Camera, Camera.id == ClipRecord.camera_id)
        .order_by(ClipRecord.created_at.desc(), ClipRecord.id.desc())
    )
    if camera_id:
        q = q.filter(ClipRecord.camera_id == int(camera_id))
    if kind_norm in {"manual", "detection"}:
        q = q.filter(ClipRecord.kind == kind_norm)
    rows = q.offset(offset).limit(limit).all()
    items = [clip_record_payload(row, camera_name=cam.name) for row, cam in rows]
    return {"items": items, "count": len(items)}


@router.get("/active")
def list_active_clips(
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    if not _manual_clip_manager:
        return {"items": []}
    active_rows = _manual_clip_manager.active()
    if not active_rows:
        return {"items": []}
    camera_ids = [int(item["camera_id"]) for item in active_rows]
    camera_rows = db.query(Camera.id, Camera.name).filter(Camera.id.in_(camera_ids)).all()
    camera_name_map = {int(cid): name for cid, name in camera_rows}
    items = []
    for row in active_rows:
        started_at = row.get("started_at")
        duration_seconds = None
        if isinstance(started_at, datetime):
            duration_seconds = max(0.0, (datetime.utcnow() - started_at).total_seconds())
        size_bytes = None
        clip_path = _clip_abs_path(row.get("file_path"))
        if clip_path and clip_path.exists():
            try:
                size_bytes = int(clip_path.stat().st_size)
            except Exception:
                pass
        items.append({
            "camera_id": int(row["camera_id"]),
            "camera_name": camera_name_map.get(int(row["camera_id"])),
            "file_path": row.get("file_path"),
            "frames": int(row.get("frames") or 0),
            "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
            "duration_seconds": duration_seconds,
            "size_bytes": size_bytes,
        })
    return {"items": items}


@router.post("/start")
def start_clip(
    body: ApiClipControlBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    if not _manual_clip_manager:
        raise HTTPException(status_code=503, detail="Clip manager not initialised")
    camera = db.get(Camera, int(body.camera_id))
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.save_clip:
        raise HTTPException(status_code=400, detail="Clip saving is disabled for this camera")
    if not camera.enabled:
        raise HTTPException(status_code=400, detail="Camera is disabled")

    started = _manual_clip_manager.start(camera)
    if not started.get("ok"):
        raise HTTPException(status_code=500, detail="Could not start clip recording")

    if not started.get("already_running"):
        create_notification(
            db,
            title=f"Manual clip recording started on {camera.name}",
            message=f"Recording has started for camera {camera.name}.",
            level="info",
            kind="clip",
            camera_id=camera.id,
            extra={"event": "manual_clip_start"},
        )

    return {
        "ok": True,
        "camera_id": camera.id,
        "camera_name": camera.name,
        "already_running": bool(started.get("already_running")),
        "file_path": started.get("file_path"),
    }


@router.post("/stop")
def stop_clip(
    body: ApiClipControlBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    if not _manual_clip_manager:
        raise HTTPException(status_code=503, detail="Clip manager not initialised")
    camera = db.get(Camera, int(body.camera_id))
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    stopped = _manual_clip_manager.stop(camera.id)
    if not stopped:
        raise HTTPException(status_code=400, detail="No active clip recording for this camera")
    if not stopped.get("ok"):
        raise HTTPException(status_code=400, detail=str(stopped.get("error") or "Clip recording did not capture frames"))

    file_path = str(stopped.get("file_path") or "").strip()
    if not file_path:
        raise HTTPException(status_code=500, detail="Clip path is missing")

    started_at = stopped.get("started_at")
    ended_at = stopped.get("ended_at")
    if not isinstance(started_at, datetime) or not isinstance(ended_at, datetime):
        started_at = datetime.utcnow()
        ended_at = datetime.utcnow()

    detection_count = (
        db.query(Detection)
        .filter(Detection.camera_id == camera.id)
        .filter(Detection.detected_at >= started_at)
        .filter(Detection.detected_at <= ended_at)
        .count()
    )

    row = ClipRecord(
        camera_id=camera.id,
        kind="manual",
        file_path=file_path,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=float(stopped.get("duration_seconds") or 0),
        size_bytes=int(stopped.get("size_bytes") or 0),
        detection_count=int(detection_count),
    )
    db.add(row)
    db.commit()

    create_notification(
        db,
        title=f"Manual clip saved for {camera.name}",
        message=f"Clip saved with {detection_count} detections during recording.",
        level="success",
        kind="clip",
        camera_id=camera.id,
        extra={"event": "manual_clip_stop", "clip_id": row.id, "detections": detection_count},
    )

    return {"ok": True, "item": clip_record_payload(row, camera_name=camera.name)}


@router.delete("/{clip_id}")
def delete_clip(
    clip_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    row = db.get(ClipRecord, clip_id)
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    _delete_clip_row(db, row)
    db.commit()
    return {"ok": True}


@router.post("/bulk/delete")
def bulk_delete_clips(
    body: ApiBulkIdsBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    ids = [int(x) for x in body.detection_ids if int(x) > 0]
    if not ids:
        return {"ok": True, "deleted": 0, "failed": 0}
    rows = db.query(ClipRecord).filter(ClipRecord.id.in_(ids)).all()
    found_ids = {int(row.id) for row in rows}
    for row in rows:
        _delete_clip_row(db, row)
    failed = max(0, len(ids) - len(found_ids))
    db.commit()
    return {"ok": True, "deleted": len(found_ids), "failed": failed}
