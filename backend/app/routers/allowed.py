"""routers/allowed.py — allowed plates CRUD."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.schemas import ApiAllowedPlateBody
from db import get_db
from models import AllowedPlate
from routers.deps import allowed_plate_payload, get_current_user

router = APIRouter(prefix="/api/v1/allowed", tags=["allowed"])


@router.get("")
def list_allowed(
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    rows = db.query(AllowedPlate).order_by(AllowedPlate.id.asc()).all()
    return {"items": [allowed_plate_payload(r) for r in rows]}


@router.post("", status_code=201)
def create_allowed(
    body: ApiAllowedPlateBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    plate = "".join(ch for ch in (body.plate_text or "") if ch.isalnum()).upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Plate text required")
    row = AllowedPlate(plate_text=plate, label=body.label, active=bool(body.active))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plate already exists")
    return {"ok": True, "item": allowed_plate_payload(row)}


@router.patch("/{plate_id}")
def update_allowed(
    plate_id: int,
    body: ApiAllowedPlateBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    row = db.get(AllowedPlate, plate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Allowed plate not found")
    plate = "".join(ch for ch in (body.plate_text or "") if ch.isalnum()).upper()
    if not plate:
        raise HTTPException(status_code=400, detail="Plate text required")
    row.plate_text = plate
    row.label = body.label
    row.active = bool(body.active)
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plate already exists")
    return {"ok": True, "item": allowed_plate_payload(row)}


@router.delete("/{plate_id}")
def delete_allowed(
    plate_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    row = db.get(AllowedPlate, plate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Allowed plate not found")
    db.delete(row)
    db.commit()
    return {"ok": True}
