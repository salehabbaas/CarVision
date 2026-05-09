"""routers/auth.py — authentication endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import ApiAdminResetBody, ApiBootstrapBody, ApiLoginBody
from core.auth_store import bootstrap_admin, bootstrap_status, reset_admin_with_master
from core.config import API_JWT_EXPIRE_MINUTES
from db import get_db
from routers.deps import create_access_token, get_current_user, verify_credentials

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/bootstrap_status")
def get_bootstrap_status(db: Session = Depends(get_db)):
    return bootstrap_status(db)


@router.post("/bootstrap")
def bootstrap(body: ApiBootstrapBody, db: Session = Depends(get_db)):
    try:
        master_password = bootstrap_admin(db, body.username, body.password)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "ok": True,
        "user": {"username": body.username, "role": "admin"},
        "master_password": master_password,
        "message": "Save this master password now. It will not be shown again.",
    }


@router.post("/admin/reset")
def reset_admin(body: ApiAdminResetBody, db: Session = Depends(get_db)):
    try:
        reset_admin_with_master(
            db,
            body.master_password,
            new_username=body.username,
            new_password=body.password,
            remove_admin=bool(body.remove_admin),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"ok": True, "removed": bool(body.remove_admin)}


@router.post("/login")
def login(body: ApiLoginBody, db: Session = Depends(get_db)):
    state = bootstrap_status(db)
    if state["setup_required"]:
        raise HTTPException(status_code=403, detail="Admin setup required")
    if not verify_credentials(db, body.username, body.password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token(body.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": API_JWT_EXPIRE_MINUTES * 60,
        "user": {"username": body.username, "role": "admin"},
    }


@router.get("/me")
def me(user: str = Depends(get_current_user)):
    return {"username": user, "role": "admin"}
