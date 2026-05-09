"""routers/live.py — authenticated WebSocket for real-time live updates.

Sends a single JSON frame every second containing:
  - overlays: per-camera latest plate detection
  - events:   40 most-recent detections
  - health:   per-camera stream health (age, online flag)

REST endpoints (/live/overlays, /live/stream_health) remain available as
fallback for clients that cannot use WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from db import SessionLocal
from models import Camera, Detection
from routers.deps import is_token_valid_for_current_admin

logger = logging.getLogger("carvision.live")

router = APIRouter(prefix="/api/v1/live", tags=["live"])

# Injected by main.py via _init()
_stream_manager = None


def _init(stream_manager) -> None:
    global _stream_manager
    _stream_manager = stream_manager


# ── Data collectors (run in threadpool — synchronous SQLAlchemy) ──────────────

def _collect(db: Session) -> Dict[str, Any]:
    """Build one live_update frame synchronously."""
    cameras: List[Camera] = (
        db.query(Camera)
        .filter(Camera.enabled.is_(True), Camera.live_view.is_(True))
        .all()
    )

    now = time.time()
    overlays: Dict[str, Any] = {}
    health: Dict[int, Any] = {}

    for cam in cameras:
        # Detection overlay
        det: Optional[Dict] = None
        if _stream_manager:
            det = _stream_manager.get_detection(cam.id)
        if det:
            overlays[str(cam.id)] = det

        # Stream health
        last_ok: Optional[float] = None
        if _stream_manager:
            try:
                last_ok = _stream_manager.get_last_ok(cam.id, cam.type, cam.source)
            except Exception:
                pass
        age = (now - last_ok) if last_ok else None
        online = bool(last_ok and age is not None and age <= 5.0)
        health[cam.id] = {"age": age, "online": online}

    # Recent detections
    rows = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id, isouter=True)
        .order_by(Detection.detected_at.desc())
        .limit(40)
        .all()
    )
    events = [
        {
            "id": det.id,
            "camera_id": det.camera_id,
            "camera_name": cam.name if cam else None,
            "plate_text": det.plate_text,
            "status": det.status,
            "confidence": det.confidence,
            "image_path": det.image_path,
            "detected_at": det.detected_at.isoformat() if det.detected_at else None,
        }
        for det, cam in rows
    ]

    return {"type": "live_update", "overlays": overlays, "events": events, "health": health}


def _build_frame() -> str:
    """Thread-safe: opens its own DB session, collects data, returns JSON string."""
    with SessionLocal() as db:
        payload = _collect(db)
    return json.dumps(payload)


# ── WebSocket endpoint ────────────────────────────────────────────────────────

@router.websocket("/ws")
async def live_ws(websocket: WebSocket, token: Optional[str] = None) -> None:
    with SessionLocal() as db:
        if not is_token_valid_for_current_admin(token, db):
            await websocket.close(code=1008)  # Policy Violation
            return

    await websocket.accept()
    logger.debug("live_ws: client connected")

    try:
        while True:
            frame = await asyncio.to_thread(_build_frame)
            await websocket.send_text(frame)
            await asyncio.sleep(1.0)
    except WebSocketDisconnect:
        logger.debug("live_ws: client disconnected")
    except Exception as exc:
        logger.warning("live_ws: error — %s", exc)
