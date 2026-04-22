"""routers/auth.py — authentication endpoints."""
from fastapi import APIRouter, HTTPException

from api.schemas import ApiLoginBody
from core.config import API_JWT_EXPIRE_MINUTES
from routers.deps import create_access_token, get_current_user, verify_credentials
from fastapi import Depends

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login")
def login(body: ApiLoginBody):
    if not verify_credentials(body.username, body.password):
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
