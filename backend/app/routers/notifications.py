"""routers/notifications.py — notification listing and read-state management."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db import get_db
from models import Notification
from routers.deps import get_current_user, notification_payload

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("")
def list_notifications(
    limit: int = 100,
    unread_only: bool = False,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    limit = max(1, min(500, int(limit)))
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    unread = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    return {"items": [notification_payload(r) for r in rows], "unread": unread}


@router.post("/{notification_id}/read")
def mark_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        db.commit()
    return {"ok": True}


@router.post("/read_all")
def mark_all_notifications_read(
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    db.query(Notification).filter(Notification.is_read.is_(False)).update(
        {Notification.is_read: True, Notification.read_at: datetime.utcnow()},
        synchronize_session=False,
    )
    db.commit()
    return {"ok": True}
