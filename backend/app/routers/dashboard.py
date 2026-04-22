"""routers/dashboard.py — dashboard summary endpoint."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from models import Camera, Detection, Notification
from routers.deps import get_current_user
from services.state import get_training_status

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/summary")
def summary(
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)

    total_detections = db.query(Detection).count()
    total_cameras = db.query(Camera).count()
    active_cameras = db.query(Camera).filter(Camera.enabled.is_(True)).count()
    allowed_count = db.query(Detection).filter(Detection.status == "allowed").count()
    denied_count = db.query(Detection).filter(Detection.status == "denied").count()
    unread_notifications = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    other_count = max(0, total_detections - allowed_count - denied_count)
    training_status = get_training_status()

    recent = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id, isouter=True)
        .filter(Detection.detected_at >= since_24h)
        .all()
    )

    hour_starts = [since_24h + timedelta(hours=i + 1) for i in range(24)]
    hour_labels = [h.strftime("%H:00") for h in hour_starts]
    hourly_total = [0] * 24
    hourly_allowed = [0] * 24
    hourly_denied = [0] * 24
    camera_counts: Dict[str, int] = {}
    plate_counts: Dict[str, int] = {}

    for det, cam in recent:
        if not det.detected_at:
            continue
        hour_idx = max(0, min(23, int((det.detected_at.replace(tzinfo=None) - since_24h).total_seconds() // 3600)))
        hourly_total[hour_idx] += 1
        if det.status == "allowed":
            hourly_allowed[hour_idx] += 1
        elif det.status == "denied":
            hourly_denied[hour_idx] += 1
        camera_name = (cam.name if cam and cam.name else f"Camera {det.camera_id or '-'}").strip()
        camera_counts[camera_name] = camera_counts.get(camera_name, 0) + 1
        plate_key = (det.plate_text or "").strip().upper()
        if plate_key:
            plate_counts[plate_key] = plate_counts.get(plate_key, 0) + 1

    top_cameras = sorted(camera_counts.items(), key=lambda x: x[1], reverse=True)[:6]
    top_plates = sorted(plate_counts.items(), key=lambda x: x[1], reverse=True)[:6]

    latest_detections = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id, isouter=True)
        .order_by(Detection.detected_at.desc())
        .limit(8)
        .all()
    )
    recent_events = [
        {
            "id": det.id,
            "plate_text": det.plate_text,
            "status": det.status,
            "camera_name": cam.name if cam else None,
            "detected_at": det.detected_at.isoformat() if det.detected_at else None,
        }
        for det, cam in latest_detections
    ]

    recent_total = len(recent)
    recent_allowed = sum(1 for det, _ in recent if det.status == "allowed")
    recent_denied = sum(1 for det, _ in recent if det.status == "denied")
    allowed_rate_24h = round((recent_allowed / recent_total) * 100, 2) if recent_total else 0.0
    denied_rate_24h = round((recent_denied / recent_total) * 100, 2) if recent_total else 0.0
    future_labels = [(now - timedelta(days=i)).strftime("%a") for i in range(6, -1, -1)]

    return {
        "totals": {
            "detections": total_detections,
            "cameras": total_cameras,
            "active_cameras": active_cameras,
            "allowed": allowed_count,
            "denied": denied_count,
            "other": other_count,
            "unread_notifications": unread_notifications,
        },
        "details": {
            "recent_24h_total": recent_total,
            "allowed_rate_24h": allowed_rate_24h,
            "denied_rate_24h": denied_rate_24h,
            "last_detection_at": recent_events[0]["detected_at"] if recent_events else None,
        },
        "charts": {
            "hourly_activity": {
                "labels": hour_labels,
                "detections": hourly_total,
                "allowed": hourly_allowed,
                "denied": hourly_denied,
            },
            "status_breakdown": {
                "labels": ["Allowed", "Denied", "Other"],
                "values": [allowed_count, denied_count, other_count],
            },
            "top_cameras": {
                "labels": [n for n, _ in top_cameras],
                "values": [c for _, c in top_cameras],
            },
            "top_plates": {
                "labels": [p for p, _ in top_plates],
                "values": [c for _, c in top_plates],
            },
            "future_users_actions": {
                "labels": future_labels,
                "users": [0] * len(future_labels),
                "actions": [0] * len(future_labels),
            },
        },
        "recent_events": recent_events,
        "training": training_status,
    }
