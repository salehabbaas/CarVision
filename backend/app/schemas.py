from datetime import datetime
from typing import Optional
from pydantic import BaseModel


class CameraCreate(BaseModel):
    name: str
    type: str
    source: str
    location: Optional[str] = None
    enabled: bool = True
    scan_interval: float = 1.0
    cooldown_seconds: float = 10.0
    save_snapshot: bool = True
    save_clip: bool = False
    clip_seconds: int = 5


class CameraOut(CameraCreate):
    id: int
    created_at: Optional[datetime]
    updated_at: Optional[datetime]

    class Config:
        from_attributes = True


class AllowedPlateCreate(BaseModel):
    plate_text: str
    label: Optional[str] = None
    active: bool = True


class AllowedPlateOut(AllowedPlateCreate):
    id: int
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


class DetectionOut(BaseModel):
    id: int
    camera_id: int
    plate_text: str
    confidence: Optional[float]
    status: str
    image_path: Optional[str]
    video_path: Optional[str]
    detected_at: datetime

    class Config:
        from_attributes = True
