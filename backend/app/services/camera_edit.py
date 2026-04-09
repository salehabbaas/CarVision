from typing import Any, Dict

from fastapi import HTTPException

from models import Camera

VALID_CAMERA_TYPES = {"webcam", "rtsp", "http_mjpeg", "browser", "upload"}
VALID_DETECTOR_MODES = {"inherit", "auto", "contour", "yolo", "ocr"}


def normalize_camera_source(camera_type: str, source: str) -> str:
    if source is None:
        return ""
    normalized = str(source).strip()
    if camera_type == "http_mjpeg":
        if normalized.startswith("tcp://"):
            normalized = "http://" + normalized[len("tcp://") :]
        if normalized and not normalized.startswith("http://") and not normalized.startswith("https://"):
            normalized = "http://" + normalized
    return normalized


def validate_camera_type(value: str) -> str:
    camera_type = (value or "").strip().lower()
    if camera_type not in VALID_CAMERA_TYPES:
        raise HTTPException(status_code=400, detail="Invalid camera type")
    return camera_type


def validate_detector_mode(value: str) -> str:
    mode = (value or "inherit").strip().lower()
    if mode not in VALID_DETECTOR_MODES:
        raise HTTPException(status_code=400, detail="Invalid detector mode")
    return mode


def apply_camera_patch(cam: Camera, patch: Dict[str, Any]) -> None:
    patch = patch or {}

    if "name" in patch and patch.get("name") is not None:
        name = str(patch.get("name") or "").strip()[:100]
        if name:
            cam.name = name

    type_changed = False
    if "type" in patch and patch.get("type") is not None:
        cam.type = validate_camera_type(str(patch.get("type")))
        type_changed = True
        if cam.type == "browser" and not cam.capture_token:
            # Keep browser capture links valid after type switch.
            import secrets

            cam.capture_token = secrets.token_urlsafe(16)

    if "source" in patch:
        raw_source = patch.get("source") or ""
        if cam.type == "browser" and not str(raw_source).strip():
            raw_source = "browser"
        source = normalize_camera_source(cam.type, str(raw_source))
        if not source:
            raise HTTPException(status_code=400, detail="Source is required")
        cam.source = source
    elif type_changed and cam.type == "browser":
        # If caller only changed type -> browser, force valid browser source.
        cam.source = "browser"
    elif type_changed and cam.type != "browser" and str(cam.source or "").strip().lower() == "browser":
        # Prevent invalid non-browser type with browser placeholder source.
        raise HTTPException(status_code=400, detail="Source is required for selected camera type")

    if "location" in patch and patch.get("location") is not None:
        loc = str(patch.get("location") or "").strip()[:200]
        cam.location = loc if loc else None
    if "enabled" in patch and patch.get("enabled") is not None:
        cam.enabled = bool(patch.get("enabled"))
    if "live_view" in patch and patch.get("live_view") is not None:
        cam.live_view = bool(patch.get("live_view"))
    if "live_order" in patch and patch.get("live_order") is not None:
        cam.live_order = int(patch.get("live_order"))
    if "detector_mode" in patch and patch.get("detector_mode") is not None:
        cam.detector_mode = validate_detector_mode(str(patch.get("detector_mode")))
    if "scan_interval" in patch and patch.get("scan_interval") is not None:
        cam.scan_interval = max(0.1, float(patch.get("scan_interval")))
    if "cooldown_seconds" in patch and patch.get("cooldown_seconds") is not None:
        cam.cooldown_seconds = max(0.0, float(patch.get("cooldown_seconds")))
    if "save_clip" in patch and patch.get("save_clip") is not None:
        cam.save_clip = bool(patch.get("save_clip"))
    if "clip_seconds" in patch and patch.get("clip_seconds") is not None:
        cam.clip_seconds = max(0, int(patch.get("clip_seconds")))

    if "onvif_xaddr" in patch and patch.get("onvif_xaddr") is not None:
        val = str(patch.get("onvif_xaddr") or "").strip()[:500]
        cam.onvif_xaddr = val if val else None
    if "onvif_username" in patch and patch.get("onvif_username") is not None:
        val = str(patch.get("onvif_username") or "").strip()[:200]
        cam.onvif_username = val if val else None
    if "onvif_password" in patch and patch.get("onvif_password") is not None:
        val = str(patch.get("onvif_password") or "").strip()[:200]
        cam.onvif_password = val if val else None
    if "onvif_profile" in patch and patch.get("onvif_profile") is not None:
        val = str(patch.get("onvif_profile") or "").strip()[:200]
        cam.onvif_profile = val if val else None
