from typing import Optional, List

from pydantic import BaseModel, Field


class ApiLoginBody(BaseModel):
    username: str
    password: str


class ApiBulkIdsBody(BaseModel):
    detection_ids: List[int] = Field(default_factory=list)


class ApiBulkFeedbackBody(BaseModel):
    detection_ids: List[int] = Field(default_factory=list)
    mode: str = "correct"
    expected_plate: Optional[str] = None
    notes: Optional[str] = None


class ApiCameraPatchBody(BaseModel):
    name: Optional[str] = None
    location: Optional[str] = None
    enabled: Optional[bool] = None
    live_view: Optional[bool] = None
    live_order: Optional[int] = None
    detector_mode: Optional[str] = None
    scan_interval: Optional[float] = None
    cooldown_seconds: Optional[float] = None


class ApiLayoutBody(BaseModel):
    max_live_cameras: int = 16


class ApiCameraCreateBody(BaseModel):
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
    live_view: bool = True
    live_order: int = 0
    onvif_xaddr: Optional[str] = None
    onvif_username: Optional[str] = None
    onvif_password: Optional[str] = None
    onvif_profile: Optional[str] = None
    detector_mode: str = "inherit"


class ApiAllowedPlateBody(BaseModel):
    plate_text: str
    label: Optional[str] = None
    active: bool = True


class ApiTrainingAnnotateBody(BaseModel):
    plate_text: Optional[str] = None
    bbox_x: Optional[int] = None
    bbox_y: Optional[int] = None
    bbox_w: Optional[int] = None
    bbox_h: Optional[int] = None
    no_plate: bool = False
    notes: Optional[str] = None


class ApiTrainingIgnoreBody(BaseModel):
    ignored: Optional[bool] = None


class ApiDiscoveryResolveBody(BaseModel):
    xaddr: str
    username: str
    password: str
