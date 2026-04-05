import os
import time
import secrets
import shutil
import zipfile
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Dict
from urllib.parse import quote_plus
from difflib import SequenceMatcher

import cv2
import numpy as np
import jwt
from fastapi import Depends, FastAPI, Form, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware

from api.schemas import (
    ApiAllowedPlateBody,
    ApiBulkFeedbackBody,
    ApiBulkIdsBody,
    ApiCameraCreateBody,
    ApiCameraPatchBody,
    ApiDiscoveryResolveBody,
    ApiLayoutBody,
    ApiLoginBody,
    ApiTrainingAnnotateBody,
    ApiTrainingIgnoreBody,
)
from camera_manager import CameraManager
from core.config import (
    ADMIN_PASS,
    ADMIN_USER,
    API_ADMIN_PASS,
    API_ADMIN_USER,
    API_CORS_ORIGINS,
    API_JWT_ALGORITHM,
    API_JWT_EXPIRE_MINUTES,
    API_JWT_SECRET,
    LEGACY_FRONTEND_DIR,
    MEDIA_DIR,
    PROJECT_ROOT,
    PUBLIC_BASE_URL,
)
from db import Base, engine, get_db, ensure_schema, SessionLocal
from models import AllowedPlate, Camera, Detection, AppSetting, TrainingSample, Notification
from onvif_discovery import discover_onvif, resolve_rtsp_for_xaddr
from onvif_ptz import continuous_move, stop as ptz_stop
from plate_detector import detect_plate, reload_yolo_model
from services.dataset import (
    bbox_to_xywh as _bbox_to_xywh,
    bbox_xywh_to_xyxy as _bbox_xywh_to_xyxy,
    build_yolo_dataset as _build_yolo_dataset,
    copy_training_image as _copy_training_image,
    extract_yolo_bbox as _extract_yolo_bbox,
    is_image_filename as _is_image_filename,
    load_image_size as _load_image_size,
    zip_label_candidates as _zip_label_candidates,
)
from services.debug_assets import (
    build_training_debug as _build_training_debug,
    debug_steps_from_paths as _debug_steps_from_paths,
    detection_debug_map as _detection_debug_map,
    ensure_detection_debug_assets as _ensure_detection_debug_assets,
    save_upload_debug as _save_upload_debug,
)
from services.file_utils import (
    hash_bytes as _hash_bytes,
    hash_file as _hash_file,
    safe_filename as _safe_filename,
)
from services.state import (
    cleanup_upload_jobs as _cleanup_upload_jobs,
    create_upload_job as _create_upload_job,
    get_training_status as _get_training_status,
    get_upload_job as _get_upload_job,
    set_training_status as _set_training_status,
    update_upload_job as _update_upload_job,
)
from anpr import read_plate_text, crop_from_bbox
from stream_manager import StreamManager

app = FastAPI(title="CarVision by SpinelTech")

app.add_middleware(
    CORSMiddleware,
    allow_origins=API_CORS_ORIGINS if API_CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(LEGACY_FRONTEND_DIR / "static")), name="static")
app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

templates = Jinja2Templates(directory=str(LEGACY_FRONTEND_DIR / "templates"))

stream_manager = StreamManager()
camera_manager = CameraManager(media_dir=MEDIA_DIR, stream_manager=stream_manager)
API_TOKEN_SCHEME = HTTPBearer(auto_error=False)


def _api_create_token(username: str) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": username,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=API_JWT_EXPIRE_MINUTES)).timestamp()),
    }
    return jwt.encode(payload, API_JWT_SECRET, algorithm=API_JWT_ALGORITHM)


def _api_get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(API_TOKEN_SCHEME),
) -> str:
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    subject = _jwt_subject_from_token(credentials.credentials)
    if not subject:
        raise HTTPException(status_code=401, detail="Invalid token")
    return str(subject)


def _api_allowed_payload(row: AllowedPlate) -> Dict[str, object]:
    return {
        "id": row.id,
        "plate_text": row.plate_text,
        "label": row.label,
        "active": bool(row.active),
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _api_training_sample_payload(row: TrainingSample) -> Dict[str, object]:
    return {
        "id": row.id,
        "image_path": row.image_path,
        "image_hash": row.image_hash,
        "image_width": row.image_width,
        "image_height": row.image_height,
        "plate_text": row.plate_text,
        "bbox": row.bbox,
        "notes": row.notes,
        "no_plate": bool(row.no_plate),
        "ignored": bool(row.ignored),
        "import_batch": row.import_batch,
        "last_trained_at": row.last_trained_at.isoformat() if row.last_trained_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _create_notification(
    db: Session,
    title: str,
    message: str,
    level: str = "info",
    kind: Optional[str] = None,
    camera_id: Optional[int] = None,
    detection_id: Optional[int] = None,
    extra: Optional[dict] = None,
):
    level = (level or "info").lower()
    if level not in {"info", "warn", "error", "success"}:
        level = "info"
    row = Notification(
        title=(title or "").strip()[:200] or "Notification",
        message=(message or "").strip()[:2000] or "",
        level=level,
        kind=(kind or "").strip()[:50] if kind else None,
        camera_id=camera_id,
        detection_id=detection_id,
        extra=extra or None,
        is_read=False,
    )
    db.add(row)
    db.commit()


def _ensure_capture_token(camera: Camera, db: Session):
    if camera.type != "browser":
        return
    if not camera.capture_token:
        camera.capture_token = secrets.token_urlsafe(16)
        db.commit()


def _public_urls(request: Request):
    base = PUBLIC_BASE_URL or str(request.base_url)
    if not base.endswith("/"):
        base += "/"
    https_base = base
    if base.startswith("http://"):
        https_base = "https://" + base[len("http://") :]
    return base, https_base


def _normalize_camera_source(camera_type: str, source: str) -> str:
    if not source:
        return source
    normalized = source.strip()
    if camera_type == "http_mjpeg":
        if normalized.startswith("tcp://"):
            normalized = "http://" + normalized[len("tcp://") :]
        if not normalized.startswith("http://") and not normalized.startswith("https://"):
            normalized = "http://" + normalized
    return normalized


def _jwt_subject_from_token(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, API_JWT_SECRET, algorithms=[API_JWT_ALGORITHM])
    except Exception:
        return None
    subject = payload.get("sub")
    return str(subject) if subject else None


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/stream"):
        if request.session.get("user"):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        bearer_token = None
        if auth.lower().startswith("bearer "):
            bearer_token = auth.split(" ", 1)[1].strip()
        query_token = request.query_params.get("token") or request.query_params.get("jwt")
        if _jwt_subject_from_token(bearer_token or query_token):
            return await call_next(request)
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    if path.startswith("/admin") or path in {"/capture", "/capture/"}:
        if request.url.path.startswith("/admin/api"):
            if not request.session.get("user"):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        else:
            if not request.session.get("user"):
                return RedirectResponse("/login", status_code=302)
    return await call_next(request)


app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "saleh"))


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    with Session(engine) as db:
        setting = db.get(AppSetting, "detector_mode")
        if not setting:
            db.add(AppSetting(key="detector_mode", value="contour"))
        live_setting = db.get(AppSetting, "max_live_cameras")
        if not live_setting:
            db.add(AppSetting(key="max_live_cameras", value="16"))
        defaults = {
            "yolo_conf": "0.25",
            "yolo_imgsz": "640",
            "yolo_iou": "0.45",
            "yolo_max_det": "5",
            "ocr_max_width": "1280",
            "ocr_langs": "en",
            "contour_canny_low": "30",
            "contour_canny_high": "200",
            "contour_bilateral_d": "11",
            "contour_bilateral_sigma_color": "17",
            "contour_bilateral_sigma_space": "17",
            "contour_approx_eps": "0.018",
            "contour_pad_ratio": "0.15",
            "contour_pad_min": "18",
            "train_model": "yolov8n.pt",
            "train_epochs": "50",
            "train_imgsz": "640",
            "train_batch": "-1",
            "train_device": "auto",
            "train_patience": "15",
            "train_hsv_h": "0.015",
            "train_hsv_s": "0.7",
            "train_hsv_v": "0.4",
            "train_degrees": "5.0",
            "train_translate": "0.1",
            "train_scale": "0.5",
            "train_shear": "2.0",
            "train_perspective": "0.0005",
            "train_fliplr": "0.5",
            "train_mosaic": "0.5",
            "train_mixup": "0.1",
        }
        for key, value in defaults.items():
            if not db.get(AppSetting, key):
                db.add(AppSetting(key=key, value=value))
        db.commit()
    camera_manager.start()


@app.on_event("shutdown")
def on_shutdown():
    camera_manager.stop()


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse("/admin", status_code=302)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid credentials"})


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)


@app.get("/capture/{camera_id}", response_class=HTMLResponse)
def capture_page(camera_id: int, request: Request, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera or camera.type != "browser":
        return RedirectResponse("/admin/cameras", status_code=302)
    _ensure_capture_token(camera, db)
    token = request.query_params.get("token")
    if not token or token != camera.capture_token:
        return JSONResponse({"error": "invalid token"}, status_code=403)
    return templates.TemplateResponse("capture.html", {"request": request, "camera_id": camera_id, "token": token})


@app.get("/capture", response_class=HTMLResponse)
def capture_list(request: Request, db: Session = Depends(get_db)):
    cameras = db.query(Camera).order_by(Camera.id.asc()).all()
    for cam in cameras:
        _ensure_capture_token(cam, db)
    browser_cams = [cam for cam in cameras if cam.type == "browser"]
    offline = [cam for cam in browser_cams if not stream_manager.is_external_online(cam.id)]
    online = [cam for cam in browser_cams if stream_manager.is_external_online(cam.id)]
    other = [cam for cam in cameras if cam.type != "browser"]
    base_url = str(request.base_url).rstrip("/")
    return templates.TemplateResponse(
        "capture_list.html",
        {
            "request": request,
            "offline": offline,
            "online": online,
            "other": other,
            "base_url": base_url,
        },
    )


@app.post("/ingest/{camera_id}")
async def ingest_frame(camera_id: int, request: Request, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera or camera.type != "browser":
        return JSONResponse({"ok": False, "error": "camera not found"}, status_code=404)
    token = request.query_params.get("token")
    if not token or token != camera.capture_token:
        return JSONResponse({"ok": False, "error": "invalid token"}, status_code=403)

    data = await request.body()
    if not data:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"ok": False, "error": "invalid image"}, status_code=400)

    stream_manager.set_external_frame(camera_id, frame, data)
    return {"ok": True}


@app.get("/capture/{camera_id}/overlay")
def capture_overlay(camera_id: int, request: Request, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera or camera.type != "browser":
        return JSONResponse({"ok": False, "error": "camera not found"}, status_code=404)
    token = request.query_params.get("token")
    if not token or token != camera.capture_token:
        return JSONResponse({"ok": False, "error": "invalid token"}, status_code=403)

    det = stream_manager.get_detection(camera_id)
    if not det:
        return {"ok": True, "detection": None}
    if isinstance(det, dict) and not det.get("debug_steps"):
        debug_map = {
            "color": det.get("debug_color_path"),
            "bw": det.get("debug_bw_path"),
            "gray": det.get("debug_gray_path"),
            "edged": det.get("debug_edged_path"),
            "mask": det.get("debug_mask_path"),
        }
        det["debug_steps"] = _debug_steps_from_paths(debug_map)
    return {"ok": True, "detection": det}


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request, db: Session = Depends(get_db)):
    detections = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(Detection.detected_at.desc())
        .limit(200)
        .all()
    )
    dets = [det for det, _ in detections]
    hashes = [det.image_hash for det in dets if det.image_hash]
    missing = [det for det in dets if not det.image_hash and det.image_path]
    for det in missing:
        path = Path(MEDIA_DIR) / det.image_path
        image_hash = _hash_file(path)
        if image_hash:
            det.image_hash = image_hash
            db.add(det)
    if missing:
        db.commit()
        hashes.extend([det.image_hash for det in missing if det.image_hash])

    samples_by_hash = {}
    if hashes:
        samples = db.query(TrainingSample).filter(TrainingSample.image_hash.in_(hashes)).all()
        samples_by_hash = {s.image_hash: s for s in samples if s.image_hash}

    feedback_meta = {}
    for det in dets:
        sample = samples_by_hash.get(det.image_hash) if det.image_hash else None
        feedback_meta[det.id] = {
            "sample_id": sample.id if sample else None,
            "annotated": bool(sample and (sample.bbox or sample.no_plate) and not sample.ignored),
            "ignored": bool(sample and sample.ignored),
            "trained": bool(sample and sample.last_trained_at),
            "notes": sample.notes if sample else None,
            "last_trained_at": sample.last_trained_at.strftime("%Y-%m-%d %H:%M") if sample and sample.last_trained_at else None,
            "feedback_status": det.feedback_status,
            "feedback_at": det.feedback_at.strftime("%Y-%m-%d %H:%M") if det.feedback_at else None,
        }
    return templates.TemplateResponse(
        "dashboard.html",
        {"request": request, "detections": detections, "feedback_meta": feedback_meta},
    )


def _notification_payload(row: Notification) -> Dict[str, object]:
    return {
        "id": row.id,
        "title": row.title,
        "message": row.message,
        "level": row.level,
        "kind": row.kind,
        "is_read": bool(row.is_read),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "read_at": row.read_at.isoformat() if row.read_at else None,
        "camera_id": row.camera_id,
        "detection_id": row.detection_id,
        "extra": row.extra or {},
    }


@app.get("/admin/notifications", response_class=HTMLResponse)
def notifications_page(request: Request, db: Session = Depends(get_db)):
    rows = (
        db.query(Notification)
        .order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(100)
        .all()
    )
    unread_count = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    return templates.TemplateResponse(
        "notifications.html",
        {
            "request": request,
            "items": [_notification_payload(r) for r in rows],
            "unread_count": unread_count,
        },
    )


@app.get("/admin/api/notifications")
def api_notifications(
    limit: int = 100,
    unread_only: bool = False,
    db: Session = Depends(get_db),
):
    limit = max(1, min(500, int(limit)))
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    return {"items": [_notification_payload(r) for r in rows]}


@app.get("/admin/api/notifications/unread_count")
def api_notifications_unread_count(db: Session = Depends(get_db)):
    unread = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    return {"unread": unread}


@app.post("/admin/api/notifications/{notification_id}/read")
def api_notification_mark_read(notification_id: int, db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if not row:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        db.commit()
    return {"ok": True}


@app.post("/admin/api/notifications/read_all")
def api_notification_mark_read_all(db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.is_read.is_(False)).update(
        {Notification.is_read: True, Notification.read_at: datetime.utcnow()},
        synchronize_session=False,
    )
    db.commit()
    return {"ok": True}


@app.delete("/admin/api/notifications/{notification_id}")
def api_notification_delete(notification_id: int, db: Session = Depends(get_db)):
    row = db.get(Notification, notification_id)
    if not row:
        return JSONResponse({"ok": False, "error": "not found"}, status_code=404)
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/admin/live", response_class=HTMLResponse)
def admin_live(request: Request, db: Session = Depends(get_db)):
    mode_setting = db.get(AppSetting, "detector_mode")
    global_mode = (mode_setting.value if mode_setting and mode_setting.value else "auto")
    cameras = (
        db.query(Camera)
        .filter(Camera.enabled.is_(True))
        .order_by(Camera.live_order.asc(), Camera.id.asc())
        .all()
    )
    effective_modes = {
        cam.id: (cam.detector_mode if cam.detector_mode and cam.detector_mode != "inherit" else global_mode)
        for cam in cameras
    }
    status_map = {
        cam.id: stream_manager.is_external_online(cam.id)
        for cam in cameras
        if cam.type == "browser"
    }
    detections = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(Detection.detected_at.desc())
        .limit(50)
        .all()
    )
    return templates.TemplateResponse(
        "live.html",
        {
            "request": request,
            "cameras": cameras,
            "detections": detections,
            "status_map": status_map,
            "effective_modes": effective_modes,
        },
    )


@app.get("/admin/api/detections")
def api_detections(db: Session = Depends(get_db)):
    rows = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(Detection.detected_at.desc())
        .limit(50)
        .all()
    )
    debug_cache: Dict[int, Dict[str, Optional[str]]] = {}
    changed = False
    for det, _ in rows:
        debug_map, row_changed = _ensure_detection_debug_assets(det)
        debug_cache[det.id] = debug_map
        changed = changed or row_changed
    if changed:
        db.commit()

    payload = []
    for det, cam in rows:
        debug_map = debug_cache.get(det.id) or _detection_debug_map(det)
        payload.append(
            {
                "id": det.id,
                "plate_text": det.plate_text,
                "status": det.status,
                "confidence": det.confidence,
                "detector": det.detector,
                "camera_id": cam.id,
                "camera": cam.name,
                "location": cam.location,
                "detected_at": det.detected_at.isoformat(),
                "debug_color_path": debug_map.get("color"),
                "debug_bw_path": debug_map.get("bw"),
                "debug_gray_path": debug_map.get("gray"),
                "debug_edged_path": debug_map.get("edged"),
                "debug_mask_path": debug_map.get("mask"),
            }
        )
    return {"items": payload}


@app.get("/admin/api/live_overlays")
def api_live_overlays(db: Session = Depends(get_db)):
    cameras = (
        db.query(Camera.id)
        .filter(Camera.live_view.is_(True))
        .filter(Camera.enabled.is_(True))
        .all()
    )
    items = {}
    for cam in cameras:
        det = stream_manager.get_detection(cam.id)
        if det:
            if isinstance(det, dict) and not det.get("debug_steps"):
                debug_map = {
                    "color": det.get("debug_color_path"),
                    "bw": det.get("debug_bw_path"),
                    "gray": det.get("debug_gray_path"),
                    "edged": det.get("debug_edged_path"),
                    "mask": det.get("debug_mask_path"),
                }
                det["debug_steps"] = _debug_steps_from_paths(debug_map)
            items[str(cam.id)] = det
    return {"items": items}


@app.get("/admin/api/browser_status")
def api_browser_status(db: Session = Depends(get_db)):
    cameras = db.query(Camera).filter(Camera.type == "browser").all()
    status = {cam.id: stream_manager.is_external_online(cam.id) for cam in cameras}
    return {"items": status}


@app.get("/admin/api/stream_health")
def api_stream_health(db: Session = Depends(get_db)):
    cameras = db.query(Camera).filter(Camera.live_view.is_(True)).all()
    now = time.time()
    items = {}
    for cam in cameras:
        last_ok = stream_manager.get_last_ok(cam.id, cam.type, cam.source)
        items[cam.id] = {
            "last_ok": last_ok,
            "age": (now - last_ok) if last_ok else None,
        }
    return {"items": items}


@app.get("/admin/cameras", response_class=HTMLResponse)
def admin_cameras(request: Request, db: Session = Depends(get_db)):
    cameras = db.query(Camera).order_by(Camera.id.asc()).all()
    for cam in cameras:
        _ensure_capture_token(cam, db)
    status_map = {
        cam.id: stream_manager.is_external_online(cam.id)
        for cam in cameras
        if cam.type == "browser"
    }
    public_base_url, public_https_url = _public_urls(request)
    return templates.TemplateResponse(
        "cameras.html",
        {
            "request": request,
            "cameras": cameras,
            "status_map": status_map,
            "public_base_url": public_base_url,
            "public_https_url": public_https_url,
        },
    )


@app.post("/admin/cameras")
def create_camera(
    name: str = Form(...),
    type: str = Form(...),
    source: str = Form(...),
    location: Optional[str] = Form(None),
    enabled: Optional[bool] = Form(False),
    scan_interval: float = Form(1.0),
    cooldown_seconds: float = Form(10.0),
    save_snapshot: Optional[bool] = Form(False),
    save_clip: Optional[bool] = Form(False),
    clip_seconds: int = Form(5),
    live_view: Optional[bool] = Form(False),
    live_order: int = Form(0),
    onvif_xaddr: Optional[str] = Form(None),
    onvif_username: Optional[str] = Form(None),
    onvif_password: Optional[str] = Form(None),
    onvif_profile: Optional[str] = Form(None),
    detector_mode: str = Form("inherit"),
    db: Session = Depends(get_db),
):
    if detector_mode not in {"inherit", "auto", "contour", "yolo"}:
        detector_mode = "inherit"
    source = _normalize_camera_source(type, source)
    camera = Camera(
        name=name,
        type=type,
        source=source,
        location=location,
        enabled=bool(enabled),
        scan_interval=scan_interval,
        cooldown_seconds=cooldown_seconds,
        save_snapshot=bool(save_snapshot),
        save_clip=bool(save_clip),
        clip_seconds=clip_seconds,
        live_view=bool(live_view),
        live_order=live_order,
        onvif_xaddr=onvif_xaddr,
        onvif_username=onvif_username,
        onvif_password=onvif_password,
        onvif_profile=onvif_profile,
        detector_mode=detector_mode,
    )
    if camera.type == "browser":
        camera.capture_token = secrets.token_urlsafe(16)
    db.add(camera)
    db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@app.post("/admin/cameras/{camera_id}/update")
def update_camera(
    camera_id: int,
    name: str = Form(...),
    type: str = Form(...),
    source: str = Form(...),
    location: Optional[str] = Form(None),
    enabled: Optional[bool] = Form(False),
    scan_interval: float = Form(1.0),
    cooldown_seconds: float = Form(10.0),
    save_snapshot: Optional[bool] = Form(False),
    save_clip: Optional[bool] = Form(False),
    clip_seconds: int = Form(5),
    live_view: Optional[bool] = Form(False),
    live_order: int = Form(0),
    onvif_xaddr: Optional[str] = Form(None),
    onvif_username: Optional[str] = Form(None),
    onvif_password: Optional[str] = Form(None),
    onvif_profile: Optional[str] = Form(None),
    detector_mode: str = Form("inherit"),
    db: Session = Depends(get_db),
):
    if detector_mode not in {"inherit", "auto", "contour", "yolo"}:
        detector_mode = "inherit"
    camera = db.get(Camera, camera_id)
    if camera:
        source = _normalize_camera_source(type, source)
        camera.name = name
        camera.type = type
        camera.source = source
        camera.location = location
        camera.enabled = bool(enabled)
        camera.scan_interval = scan_interval
        camera.cooldown_seconds = cooldown_seconds
        camera.save_snapshot = bool(save_snapshot)
        camera.save_clip = bool(save_clip)
        camera.clip_seconds = clip_seconds
        camera.live_view = bool(live_view)
        camera.live_order = live_order
        camera.onvif_xaddr = onvif_xaddr
        camera.onvif_username = onvif_username
        camera.onvif_password = onvif_password
        camera.onvif_profile = onvif_profile
        camera.detector_mode = detector_mode
        if camera.type == "browser" and not camera.capture_token:
            camera.capture_token = secrets.token_urlsafe(16)
        camera.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@app.post("/admin/cameras/{camera_id}/delete")
def delete_camera(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if camera:
        db.delete(camera)
        db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@app.post("/admin/cameras/{camera_id}/rotate_token")
def rotate_token(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if camera and camera.type == "browser":
        camera.capture_token = secrets.token_urlsafe(16)
        camera.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse("/admin/cameras", status_code=303)


@app.post("/admin/cameras/{camera_id}/use_browser")
def use_browser(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if camera:
        camera.type = "browser"
        camera.source = "browser"
        camera.capture_token = secrets.token_urlsafe(16)
        camera.updated_at = datetime.utcnow()
        db.commit()
    return RedirectResponse("/capture", status_code=303)


@app.get("/admin/allowed", response_class=HTMLResponse)
def admin_allowed(request: Request, db: Session = Depends(get_db)):
    allowed = db.query(AllowedPlate).order_by(AllowedPlate.id.asc()).all()
    return templates.TemplateResponse(
        "allowed.html",
        {"request": request, "allowed": allowed},
    )


@app.post("/admin/allowed")
def create_allowed(
    plate_text: str = Form(...),
    label: Optional[str] = Form(None),
    active: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
):
    plate_text = "".join(ch for ch in plate_text if ch.isalnum()).upper()
    allowed = AllowedPlate(plate_text=plate_text, label=label, active=bool(active))
    db.add(allowed)
    db.commit()
    return RedirectResponse("/admin/allowed", status_code=303)


@app.get("/admin/settings", response_class=HTMLResponse)
def admin_settings(request: Request, db: Session = Depends(get_db)):
    detector = db.get(AppSetting, "detector_mode")
    max_live = db.get(AppSetting, "max_live_cameras")
    def _get(key, default):
        setting = db.get(AppSetting, key)
        return setting.value if setting and setting.value else default
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "detector_mode": detector.value if detector else "contour",
            "max_live": max_live.value if max_live else "16",
            "yolo_conf": _get("yolo_conf", "0.25"),
            "yolo_imgsz": _get("yolo_imgsz", "640"),
            "yolo_iou": _get("yolo_iou", "0.45"),
            "yolo_max_det": _get("yolo_max_det", "5"),
            "ocr_max_width": _get("ocr_max_width", "1280"),
            "ocr_langs": _get("ocr_langs", "en"),
            "contour_canny_low": _get("contour_canny_low", "30"),
            "contour_canny_high": _get("contour_canny_high", "200"),
            "contour_bilateral_d": _get("contour_bilateral_d", "11"),
            "contour_bilateral_sigma_color": _get("contour_bilateral_sigma_color", "17"),
            "contour_bilateral_sigma_space": _get("contour_bilateral_sigma_space", "17"),
            "contour_approx_eps": _get("contour_approx_eps", "0.018"),
            "contour_pad_ratio": _get("contour_pad_ratio", "0.15"),
            "contour_pad_min": _get("contour_pad_min", "18"),
        },
    )


@app.post("/admin/settings")
def update_settings(
    detector_mode: str = Form("contour"),
    max_live_cameras: int = Form(16),
    yolo_conf: float = Form(0.25),
    yolo_imgsz: int = Form(640),
    yolo_iou: float = Form(0.45),
    yolo_max_det: int = Form(5),
    ocr_max_width: int = Form(1280),
    ocr_langs: str = Form("en"),
    contour_canny_low: int = Form(30),
    contour_canny_high: int = Form(200),
    contour_bilateral_d: int = Form(11),
    contour_bilateral_sigma_color: int = Form(17),
    contour_bilateral_sigma_space: int = Form(17),
    contour_approx_eps: float = Form(0.018),
    contour_pad_ratio: float = Form(0.15),
    contour_pad_min: int = Form(18),
    db: Session = Depends(get_db),
):
    detector_mode = detector_mode.lower()
    if detector_mode not in {"auto", "contour", "yolo"}:
        detector_mode = "contour"
    setting = db.get(AppSetting, "detector_mode")
    if not setting:
        setting = AppSetting(key="detector_mode", value=detector_mode)
        db.add(setting)
    else:
        setting.value = detector_mode

    live_setting = db.get(AppSetting, "max_live_cameras")
    if not live_setting:
        live_setting = AppSetting(key="max_live_cameras", value=str(max_live_cameras))
        db.add(live_setting)
    else:
        live_setting.value = str(max_live_cameras)

    def _save_setting(key: str, value: object):
        setting = db.get(AppSetting, key)
        if not setting:
            setting = AppSetting(key=key, value=str(value))
            db.add(setting)
        else:
            setting.value = str(value)

    _save_setting("yolo_conf", max(0.01, min(float(yolo_conf), 0.99)))
    _save_setting("yolo_imgsz", max(320, min(int(yolo_imgsz), 1280)))
    _save_setting("yolo_iou", max(0.05, min(float(yolo_iou), 0.95)))
    _save_setting("yolo_max_det", max(1, min(int(yolo_max_det), 50)))
    _save_setting("ocr_max_width", max(320, min(int(ocr_max_width), 4000)))
    _save_setting("ocr_langs", ",".join([p.strip() for p in ocr_langs.split(",") if p.strip()]) or "en")
    _save_setting("contour_canny_low", max(1, min(int(contour_canny_low), 200)))
    _save_setting("contour_canny_high", max(50, min(int(contour_canny_high), 400)))
    _save_setting("contour_bilateral_d", max(3, min(int(contour_bilateral_d), 31)))
    _save_setting("contour_bilateral_sigma_color", max(1, min(int(contour_bilateral_sigma_color), 150)))
    _save_setting("contour_bilateral_sigma_space", max(1, min(int(contour_bilateral_sigma_space), 150)))
    _save_setting("contour_approx_eps", max(0.005, min(float(contour_approx_eps), 0.1)))
    _save_setting("contour_pad_ratio", max(0.05, min(float(contour_pad_ratio), 0.5)))
    _save_setting("contour_pad_min", max(4, min(int(contour_pad_min), 100)))
    db.commit()
    return RedirectResponse("/admin/settings", status_code=303)


def _get_upload_camera(db: Session) -> Camera:
    camera = db.query(Camera).filter(Camera.type == "upload").first()
    if camera:
        return camera
    camera = Camera(
        name="Uploads",
        type="upload",
        source="upload",
        location="Uploads",
        enabled=False,
        scan_interval=1.0,
        cooldown_seconds=0.0,
        save_snapshot=True,
        save_clip=False,
        clip_seconds=0,
        live_view=False,
        live_order=0,
        detector_mode="inherit",
    )
    db.add(camera)
    db.commit()
    return camera


def _is_allowed(db: Session, plate_text: str) -> bool:
    allowed = (
        db.query(AllowedPlate)
        .filter(AllowedPlate.active.is_(True))
        .filter(AllowedPlate.plate_text == plate_text)
        .first()
    )
    return allowed is not None


def _known_plate_candidates(db: Session) -> List[str]:
    allowed = (
        db.query(AllowedPlate.plate_text)
        .filter(AllowedPlate.active.is_(True))
        .all()
    )
    training = (
        db.query(TrainingSample.plate_text)
        .filter(TrainingSample.ignored.is_(False))
        .filter(TrainingSample.no_plate.is_(False))
        .filter(TrainingSample.plate_text.isnot(None))
        .all()
    )
    pool = {str(v[0]).strip().upper() for v in allowed + training if v and v[0]}
    return [p for p in pool if len(p) >= 5]


def _match_known_plate(db: Session, plate_text: str) -> Tuple[str, Optional[float]]:
    normalized = (plate_text or "").strip().upper()
    if len(normalized) < 5:
        return normalized, None
    candidates = _known_plate_candidates(db)
    if not candidates:
        return normalized, None
    if normalized in candidates:
        return normalized, 1.0
    best = normalized
    best_score = 0.0
    for cand in candidates:
        if abs(len(cand) - len(normalized)) > 1:
            continue
        score = SequenceMatcher(None, normalized, cand).ratio()
        if score > best_score:
            best_score = score
            best = cand
    # Keep fuzzy override conservative to avoid replacing correct OCR with wrong known plates.
    if best_score >= 0.93 and len(best) == len(normalized):
        return best, best_score
    return normalized, None


def _save_upload_snapshot(frame, prefix: str) -> str:
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"uploads/{prefix}_{ts}.jpg"
    path = Path(MEDIA_DIR) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), frame)
    return filename


def _save_training_upload(content: bytes, original_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    safe_name = _safe_filename(original_name)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(4)
    filename = f"training/{ts}_{token}_{safe_name}"
    path = Path(MEDIA_DIR) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        try:
            path.unlink(missing_ok=True)
        except Exception:
            pass
        return None, None, None
    height, width = image.shape[:2]
    return filename, width, height


def _refine_detection_from_crop(frame, detection: Optional[Dict]) -> Optional[Dict]:
    if frame is None or not isinstance(detection, dict):
        return detection
    bbox = detection.get("bbox")
    if not bbox:
        return detection
    try:
        crop = crop_from_bbox(frame, bbox)
    except Exception:
        crop = None
    if crop is None:
        return detection
    ocr = read_plate_text(crop)
    if not ocr or not ocr.get("plate_text"):
        return detection

    detection["plate_text"] = ocr.get("plate_text")
    det_conf = float(detection.get("confidence") or 0.0)
    ocr_conf = float(ocr.get("confidence") or 0.0)
    detection["confidence"] = max(det_conf, ocr_conf)
    detection["raw_text"] = ocr.get("raw_text")
    detection["candidates"] = ocr.get("candidates")
    return detection


@app.get("/admin/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    return templates.TemplateResponse("upload.html", {"request": request, "result": None})


def _process_upload_path(
    file_path: Path,
    content_type: str,
    sample_seconds: float,
    max_frames: int,
    show_debug: bool,
    progress_cb=None,
) -> Dict[str, object]:
    with SessionLocal() as db:
        camera = _get_upload_camera(db)
        setting = db.get(AppSetting, "detector_mode")
        detector_mode = setting.value if setting and setting.value else "contour"

        items = []
        debug_items = []
        message = "No detections."

        is_image = bool(content_type and str(content_type).startswith("image/"))
        if is_image:
            if progress_cb:
                progress_cb(progress=10, step="Reading image")
            content = file_path.read_bytes()
            image_hash = _hash_bytes(content)
            override = (
                db.query(TrainingSample)
                .filter(TrainingSample.image_hash == image_hash)
                .filter(TrainingSample.ignored.is_(False))
                .first()
            )
            if override:
                if override.no_plate:
                    if progress_cb:
                        progress_cb(progress=100, step="Matched feedback override: no plate")
                    return {"message": "No plate (feedback override).", "items": [], "debug": None}
                plate_text = override.plate_text or "UNKNOWN"
                status = "allowed" if _is_allowed(db, plate_text) else "denied"
                image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
                snapshot = _save_upload_snapshot(image, plate_text)
                bbox_xyxy = _bbox_xywh_to_xyxy(override.bbox) if override.bbox else None
                db.add(
                    Detection(
                        camera_id=camera.id,
                        plate_text=plate_text,
                        confidence=1.0,
                        status=status,
                        image_path=snapshot,
                        video_path=None,
                        debug_color_path=None,
                        debug_bw_path=None,
                        debug_gray_path=None,
                        debug_edged_path=None,
                        debug_mask_path=None,
                        bbox=bbox_xyxy,
                        raw_text="feedback_override",
                        detector="feedback",
                        image_hash=image_hash,
                    )
                )
                db.commit()
                items.append(
                    {
                        "plate_text": plate_text,
                        "status": status,
                        "confidence": 1.0,
                        "image_path": snapshot,
                    }
                )
                if progress_cb:
                    progress_cb(progress=100, step="Detection complete via feedback override")
                return {"message": "Detection complete (feedback override).", "items": items, "debug": None}

            image = cv2.imdecode(np.frombuffer(content, np.uint8), cv2.IMREAD_COLOR)
            if progress_cb:
                progress_cb(progress=30, step=f"Running {detector_mode} plate detection")
            detection = detect_plate(image, mode_override=detector_mode)
            used_ocr_fallback = False
            if not detection:
                if progress_cb:
                    progress_cb(progress=55, step="No plate from detector, trying OCR fallback")
                detection = read_plate_text(image)
                used_ocr_fallback = True
            if detection and not detection.get("detector"):
                detection["detector"] = "ocr" if used_ocr_fallback else detector_mode
            if detection:
                detection = _refine_detection_from_crop(image, detection)
                plate_text, matched_score = _match_known_plate(db, detection["plate_text"])
                detection["plate_text"] = plate_text
                if progress_cb and matched_score and matched_score < 1.0:
                    progress_cb(step=f"OCR corrected to known plate {plate_text} (score {matched_score:.2f})")
                status = "allowed" if _is_allowed(db, plate_text) else "denied"
                snapshot = _save_upload_snapshot(image, plate_text)
                (
                    debug_color_path,
                    debug_bw_path,
                    debug_gray_path,
                    debug_edged_path,
                    debug_mask_path,
                ) = _save_upload_debug(image, detection, plate_text, _safe_filename)
                db.add(
                    Detection(
                        camera_id=camera.id,
                        plate_text=plate_text,
                        confidence=detection.get("confidence"),
                        status=status,
                        image_path=snapshot,
                        video_path=None,
                        debug_color_path=debug_color_path,
                        debug_bw_path=debug_bw_path,
                        debug_gray_path=debug_gray_path,
                        debug_edged_path=debug_edged_path,
                        debug_mask_path=debug_mask_path,
                        bbox=detection.get("bbox"),
                        raw_text=str(detection.get("candidates") or detection.get("raw_text")),
                        detector=detection.get("detector"),
                        image_hash=image_hash,
                    )
                )
                db.commit()
                items.append(
                    {
                        "plate_text": plate_text,
                        "status": status,
                        "confidence": detection.get("confidence"),
                        "image_path": snapshot,
                    }
                )
                if show_debug:
                    debug_items.append(
                        {
                            "plate_text": plate_text,
                            "candidates": detection.get("candidates"),
                            "raw_text": detection.get("raw_text"),
                            "debug_color": debug_color_path,
                            "debug_bw": debug_bw_path,
                            "debug_gray": debug_gray_path,
                            "debug_edged": debug_edged_path,
                            "debug_mask": debug_mask_path,
                        }
                    )
                message = "Detection complete (OCR fallback)." if used_ocr_fallback else "Detection complete."
                if progress_cb:
                    progress_cb(progress=100, step=message)
            else:
                if progress_cb:
                    progress_cb(progress=100, step="No plate detected")
        else:
            cap = cv2.VideoCapture(str(file_path))
            fps = cap.get(cv2.CAP_PROP_FPS)
            if not fps or fps != fps or fps <= 0:
                fps = 10.0
            step = max(1, int(sample_seconds * fps))
            frame_idx = 0
            processed = 0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            target_samples = max_frames
            if total_frames > 0:
                target_samples = min(max_frames, max(1, total_frames // step))
            if progress_cb:
                progress_cb(progress=8, step=f"Video opened (sampling every {sample_seconds:.1f}s)")
            while processed < max_frames:
                ret, frame = cap.read()
                if not ret:
                    break
                if frame_idx % step != 0:
                    frame_idx += 1
                    continue
                frame_idx += 1
                processed += 1
                if progress_cb and (processed == 1 or processed % 3 == 0):
                    pct = min(95, int((processed / max(1, target_samples)) * 90) + 5)
                    progress_cb(progress=pct, step=f"Analyzing sampled frame {processed}/{target_samples}")
                detection = detect_plate(frame, mode_override=detector_mode)
                if not detection:
                    detection = read_plate_text(frame)
                    if detection:
                        detection["detector"] = "ocr"
                if not detection:
                    continue
                detection = _refine_detection_from_crop(frame, detection)
                plate_text, matched_score = _match_known_plate(db, detection["plate_text"])
                detection["plate_text"] = plate_text
                status = "allowed" if _is_allowed(db, plate_text) else "denied"
                snapshot = _save_upload_snapshot(frame, plate_text)
                image_hash = _hash_file(Path(MEDIA_DIR) / snapshot)
                (
                    debug_color_path,
                    debug_bw_path,
                    debug_gray_path,
                    debug_edged_path,
                    debug_mask_path,
                ) = _save_upload_debug(frame, detection, plate_text, _safe_filename)
                db.add(
                    Detection(
                        camera_id=camera.id,
                        plate_text=plate_text,
                        confidence=detection.get("confidence"),
                        status=status,
                        image_path=snapshot,
                        video_path=None,
                        debug_color_path=debug_color_path,
                        debug_bw_path=debug_bw_path,
                        debug_gray_path=debug_gray_path,
                        debug_edged_path=debug_edged_path,
                        debug_mask_path=debug_mask_path,
                        bbox=detection.get("bbox"),
                        raw_text=str(detection.get("candidates") or detection.get("raw_text")),
                        detector=detection.get("detector"),
                        image_hash=image_hash,
                    )
                )
                db.commit()
                items.append(
                    {
                        "plate_text": plate_text,
                        "status": status,
                        "confidence": detection.get("confidence"),
                        "image_path": snapshot,
                    }
                )
                if show_debug:
                    debug_items.append(
                        {
                            "plate_text": plate_text,
                            "candidates": detection.get("candidates"),
                            "raw_text": detection.get("raw_text"),
                            "debug_color": debug_color_path,
                            "debug_bw": debug_bw_path,
                            "debug_gray": debug_gray_path,
                            "debug_edged": debug_edged_path,
                            "debug_mask": debug_mask_path,
                        }
                    )
            cap.release()
            if items:
                message = f"Detections: {len(items)}"
            else:
                message = "No detections in sampled frames."
            if progress_cb:
                progress_cb(progress=100, step=message)
        return {"message": message, "items": items, "debug": debug_items if show_debug else None}


def _run_upload_job(
    job_id: str,
    file_path: Path,
    content_type: str,
    sample_seconds: float,
    max_frames: int,
    show_debug: bool,
):
    try:
        _update_upload_job(job_id, status="running", progress=2, message="Running", step="Starting processing")

        def on_progress(progress=None, step=None):
            _update_upload_job(job_id, status="running", progress=progress, message="Running", step=step)

        result = _process_upload_path(
            file_path=file_path,
            content_type=content_type,
            sample_seconds=sample_seconds,
            max_frames=max_frames,
            show_debug=show_debug,
            progress_cb=on_progress,
        )
        _update_upload_job(job_id, status="complete", progress=100, message=result.get("message") or "Complete", step="Upload job finished", result=result)
    except Exception as exc:
        _update_upload_job(job_id, status="failed", progress=100, message=f"Failed: {exc}", step=f"Error: {exc}", error=str(exc))


@app.post("/admin/api/upload/start")
async def upload_start(
    file: UploadFile = File(...),
    sample_seconds: float = Form(1.0),
    max_frames: int = Form(300),
    show_debug: Optional[bool] = Form(False),
):
    _cleanup_upload_jobs()
    upload_dir = Path(MEDIA_DIR) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    filename = f"uploads/{int(time.time())}_{file.filename}"
    file_path = Path(MEDIA_DIR) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)

    job_id = _create_upload_job(file.filename or file_path.name)
    thread = threading.Thread(
        target=_run_upload_job,
        args=(job_id, file_path, file.content_type or "", float(sample_seconds), int(max_frames), bool(show_debug)),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "job_id": job_id}


@app.get("/admin/api/upload/status/{job_id}")
def upload_status(job_id: str):
    _cleanup_upload_jobs()
    job = _get_upload_job(job_id)
    if not job:
        return JSONResponse({"ok": False, "error": "job not found"}, status_code=404)
    return {"ok": True, "job": job}


@app.post("/admin/upload", response_class=HTMLResponse)
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    sample_seconds: float = Form(1.0),
    max_frames: int = Form(300),
    show_debug: Optional[bool] = Form(False),
):
    upload_dir = Path(MEDIA_DIR) / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    filename = f"uploads/{int(time.time())}_{file.filename}"
    file_path = Path(MEDIA_DIR) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_bytes(content)
    result = _process_upload_path(
        file_path=file_path,
        content_type=file.content_type or "",
        sample_seconds=float(sample_seconds),
        max_frames=int(max_frames),
        show_debug=bool(show_debug),
        progress_cb=None,
    )
    return templates.TemplateResponse(
        "upload.html",
        {"request": request, "result": result, "result_items": result.get("items") or []},
    )


@app.get("/admin/training", response_class=HTMLResponse)
def training_page(request: Request, sample_id: Optional[int] = None, db: Session = Depends(get_db)):
    status_filter = (request.query_params.get("status") or "all").lower()
    if status_filter not in {"all", "annotated", "pending", "negative", "ignored"}:
        status_filter = "all"
    query_text = (request.query_params.get("q") or "").strip()

    base_query = db.query(TrainingSample)
    counts = {
        "total": base_query.count(),
        "annotated": base_query.filter(
            TrainingSample.ignored.is_(False),
            or_(TrainingSample.bbox.isnot(None), TrainingSample.no_plate.is_(True)),
        ).count(),
        "negative": base_query.filter(TrainingSample.no_plate.is_(True), TrainingSample.ignored.is_(False)).count(),
        "pending": base_query.filter(
            TrainingSample.bbox.is_(None),
            TrainingSample.no_plate.is_(False),
            TrainingSample.ignored.is_(False),
        ).count(),
        "ignored": base_query.filter(TrainingSample.ignored.is_(True)).count(),
    }

    samples_query = db.query(TrainingSample)
    if status_filter == "annotated":
        samples_query = samples_query.filter(TrainingSample.bbox.isnot(None), TrainingSample.ignored.is_(False))
    elif status_filter == "negative":
        samples_query = samples_query.filter(TrainingSample.no_plate.is_(True), TrainingSample.ignored.is_(False))
    elif status_filter == "pending":
        samples_query = samples_query.filter(
            TrainingSample.bbox.is_(None),
            TrainingSample.no_plate.is_(False),
            TrainingSample.ignored.is_(False),
        )
    elif status_filter == "ignored":
        samples_query = samples_query.filter(TrainingSample.ignored.is_(True))

    if query_text:
        like = f"%{query_text}%"
        samples_query = samples_query.filter(
            or_(
                TrainingSample.plate_text.ilike(like),
                TrainingSample.image_path.ilike(like),
                TrainingSample.notes.ilike(like),
            )
        )

    samples = samples_query.order_by(TrainingSample.created_at.desc()).limit(500).all()

    selected = None
    if sample_id:
        selected = db.get(TrainingSample, sample_id)
    if not selected and samples:
        selected = samples[0]
    selected_debug = _build_training_debug(selected)

    notice = None
    notice_type = "info"
    if request.query_params.get("uploaded") == "1":
        notice = "Upload complete. Select a sample to annotate."
    elif request.query_params.get("saved") == "1":
        notice = "Annotation saved."
        notice_type = "success"
    elif request.query_params.get("deleted") == "1":
        notice = "Sample deleted."
        notice_type = "warn"
    elif request.query_params.get("ignored") == "1":
        notice = "Sample updated."
        notice_type = "success"
    elif request.query_params.get("error") == "1":
        notice = "No valid images were uploaded."
        notice_type = "warn"

    return templates.TemplateResponse(
        "training.html",
        {
            "request": request,
            "samples": samples,
            "selected": selected,
            "counts": counts,
            "status_filter": status_filter,
            "query_text": query_text,
            "notice": notice,
            "notice_type": notice_type,
            "training_status": _get_training_status(),
            "selected_debug": selected_debug,
        },
    )


@app.post("/admin/training/upload")
async def training_upload(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    created_ids: List[int] = []
    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            continue
        content = await file.read()
        if not content:
            continue
        image_hash = _hash_bytes(content)
        rel_path, width, height = _save_training_upload(content, file.filename or "upload.jpg")
        if not rel_path:
            continue
        sample = TrainingSample(
            image_path=rel_path,
            image_hash=image_hash,
            image_width=width,
            image_height=height,
        )
        db.add(sample)
        db.flush()
        created_ids.append(sample.id)
    if created_ids:
        db.commit()
        return RedirectResponse(f"/admin/training?sample_id={created_ids[-1]}&uploaded=1", status_code=303)
    return RedirectResponse("/admin/training?error=1", status_code=303)


@app.post("/admin/training/{sample_id}/annotate")
def training_annotate(
    sample_id: int,
    plate_text: Optional[str] = Form(None),
    bbox_x: Optional[int] = Form(None),
    bbox_y: Optional[int] = Form(None),
    bbox_w: Optional[int] = Form(None),
    bbox_h: Optional[int] = Form(None),
    no_plate: Optional[bool] = Form(False),
    notes: Optional[str] = Form(None),
    save_next: Optional[bool] = Form(False),
    next_sample_id: Optional[str] = Form(None),
    status_filter: Optional[str] = Form("all"),
    query_text: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        return RedirectResponse("/admin/training?error=1", status_code=303)

    if no_plate:
        sample.no_plate = True
        sample.bbox = None
        sample.plate_text = None
    else:
        sample.no_plate = False
        if bbox_x is not None and bbox_y is not None and bbox_w and bbox_h:
            sample.bbox = {
                "x": int(bbox_x),
                "y": int(bbox_y),
                "w": int(bbox_w),
                "h": int(bbox_h),
            }
        else:
            sample.bbox = None
        if plate_text:
            sample.plate_text = plate_text.strip()[:50]
        else:
            sample.plate_text = None

    sample.notes = notes.strip()[:500] if notes else None
    db.commit()
    status_filter = (status_filter or "all").lower()
    if status_filter not in {"all", "annotated", "pending", "negative", "ignored"}:
        status_filter = "all"
    qp = [f"status={status_filter}", "saved=1"]
    if query_text:
        qp.append(f"q={quote_plus(query_text.strip())}")
    parsed_next_id = None
    if next_sample_id is not None and str(next_sample_id).strip() != "":
        try:
            parsed_next_id = int(str(next_sample_id).strip())
        except Exception:
            parsed_next_id = None
    target_id = parsed_next_id if save_next and parsed_next_id else sample_id
    qp.append(f"sample_id={target_id}")
    return RedirectResponse(f"/admin/training?{'&'.join(qp)}", status_code=303)


@app.post("/admin/training/{sample_id}/ignore")
def training_ignore(
    sample_id: int,
    ignored: Optional[bool] = Form(None),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    sample = db.get(TrainingSample, sample_id)
    if sample:
        if ignored is None:
            sample.ignored = not bool(sample.ignored)
        else:
            sample.ignored = bool(ignored)
        db.commit()
    if next_url and next_url.startswith("/admin/training"):
        return RedirectResponse(f"{next_url}&ignored=1" if "?" in next_url else f"{next_url}?ignored=1", status_code=303)
    return RedirectResponse("/admin/training?ignored=1", status_code=303)


def _create_training_from_detection(
    db: Session,
    det: Detection,
    mode: str,
    expected_plate: Optional[str] = None,
    notes: Optional[str] = None,
) -> Optional[int]:
    if not det.image_path:
        return None
    src_path = Path(MEDIA_DIR) / det.image_path
    if not src_path.exists():
        return None

    image_bytes = src_path.read_bytes()
    image_hash = _hash_bytes(image_bytes)

    sample = db.query(TrainingSample).filter(TrainingSample.image_hash == image_hash).first()
    if not sample:
        rel_path = _copy_training_image(src_path, prefix="det")
        if not rel_path:
            return None
        size = _load_image_size(Path(MEDIA_DIR) / rel_path)
        width, height = (size or (None, None))
        sample = TrainingSample(
            image_path=rel_path,
            image_hash=image_hash,
            image_width=width,
            image_height=height,
        )
        db.add(sample)
        db.flush()

    sample.ignored = False
    if mode == "no_plate":
        sample.no_plate = True
        sample.bbox = None
        sample.plate_text = None
    else:
        sample.no_plate = False
        bbox = _bbox_to_xywh(det.bbox)
        sample.bbox = bbox
        if mode == "corrected" and expected_plate:
            sample.plate_text = expected_plate.strip()[:50]
        else:
            sample.plate_text = det.plate_text

    if notes:
        sample.notes = notes.strip()[:500]
    db.commit()
    det.image_hash = image_hash
    det.feedback_sample_id = sample.id
    det.feedback_status = mode
    det.feedback_note = notes.strip()[:500] if notes else None
    det.feedback_at = datetime.utcnow()
    db.add(det)
    db.commit()
    return sample.id


@app.post("/admin/detections/{det_id:int}/feedback")
def detection_feedback(
    det_id: int,
    mode: str = Form("correct"),
    expected_plate: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    det = db.get(Detection, det_id)
    if not det:
        return RedirectResponse("/admin?error=1", status_code=303)
    mode = (mode or "correct").lower()
    if mode not in {"correct", "corrected", "no_plate"}:
        mode = "correct"
    sample_id = _create_training_from_detection(db, det, mode, expected_plate, notes)
    if next_url and next_url.startswith("/admin"):
        return RedirectResponse(
            f"{next_url}&feedback=1&sample_id={sample_id}" if "?" in next_url else f"{next_url}?feedback=1&sample_id={sample_id}",
            status_code=303,
        )
    return RedirectResponse("/admin?feedback=1", status_code=303)


def _append_query(url: str, **params) -> str:
    if not url:
        url = "/admin"
    pairs = []
    for key, val in params.items():
        if val is None:
            continue
        pairs.append(f"{key}={quote_plus(str(val))}")
    if not pairs:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{'&'.join(pairs)}"


def _parse_detection_ids(raw: Optional[str]) -> List[int]:
    if not raw:
        return []
    tokens = re.split(r"[,\s]+", str(raw).strip())
    out = []
    seen = set()
    for token in tokens:
        if not token:
            continue
        try:
            val = int(token)
        except Exception:
            continue
        if val <= 0 or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


def _reprocess_detection_row(db: Session, det: Detection) -> Optional[int]:
    if not det or not det.image_path:
        return None
    image_path = Path(MEDIA_DIR) / det.image_path
    if not image_path.exists():
        return None
    image = cv2.imread(str(image_path))
    if image is None:
        return None

    mode_setting = db.get(AppSetting, "detector_mode")
    detector_mode = mode_setting.value if mode_setting and mode_setting.value else "auto"
    camera = db.get(Camera, det.camera_id) if det.camera_id else None
    if camera and camera.detector_mode and camera.detector_mode != "inherit":
        detector_mode = camera.detector_mode

    detection = detect_plate(image, mode_override=detector_mode)
    used_ocr_fallback = False
    if not detection:
        detection = read_plate_text(image)
        used_ocr_fallback = True
    if not detection:
        return None
    if not detection.get("detector"):
        detection["detector"] = "ocr" if used_ocr_fallback else detector_mode

    plate_text, _ = _match_known_plate(db, detection.get("plate_text") or "")
    detection["plate_text"] = plate_text
    status = "allowed" if _is_allowed(db, plate_text) else "denied"
    (
        debug_color_path,
        debug_bw_path,
        debug_gray_path,
        debug_edged_path,
        debug_mask_path,
    ) = _save_upload_debug(image, detection, plate_text, _safe_filename)

    image_hash = det.image_hash or _hash_file(image_path)
    new_det = Detection(
        camera_id=det.camera_id,
        plate_text=plate_text,
        confidence=detection.get("confidence"),
        status=status,
        image_path=det.image_path,
        video_path=None,
        debug_color_path=debug_color_path,
        debug_bw_path=debug_bw_path,
        debug_gray_path=debug_gray_path,
        debug_edged_path=debug_edged_path,
        debug_mask_path=debug_mask_path,
        bbox=detection.get("bbox"),
        raw_text=str(detection.get("candidates") or detection.get("raw_text") or f"reprocess_of:{det.id}"),
        detector=detection.get("detector"),
        image_hash=image_hash,
    )
    db.add(new_det)
    db.commit()
    return new_det.id


@app.post("/admin/detections/{det_id:int}/reprocess")
def detection_reprocess(
    det_id: int,
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    det = db.get(Detection, det_id)
    if not det:
        return RedirectResponse("/admin?reprocess_error=1", status_code=303)
    new_id = _reprocess_detection_row(db, det)
    if not new_id:
        return RedirectResponse("/admin?reprocess_error=1", status_code=303)

    if next_url and next_url.startswith("/admin"):
        return RedirectResponse(
            _append_query(next_url, reprocessed=1, new_detection_id=new_id, from_detection_id=det.id),
            status_code=303,
        )
    return RedirectResponse(
        _append_query("/admin", reprocessed=1, new_detection_id=new_id, from_detection_id=det.id),
        status_code=303,
    )


@app.post("/admin/detections/bulk/reprocess")
def detections_bulk_reprocess(
    detection_ids: str = Form(""),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    ids = _parse_detection_ids(detection_ids)
    if not ids:
        target = next_url if next_url and next_url.startswith("/admin") else "/admin"
        return RedirectResponse(_append_query(target, bulk_reprocessed=0, bulk_failed=0), status_code=303)

    success = 0
    failed = 0
    for det_id in ids:
        det = db.get(Detection, det_id)
        if not det:
            failed += 1
            continue
        new_id = _reprocess_detection_row(db, det)
        if new_id:
            success += 1
        else:
            failed += 1
    target = next_url if next_url and next_url.startswith("/admin") else "/admin"
    return RedirectResponse(
        _append_query(target, bulk_reprocessed=success, bulk_failed=failed),
        status_code=303,
    )


@app.post("/admin/detections/bulk/feedback")
def detections_bulk_feedback(
    detection_ids: str = Form(""),
    mode: str = Form("correct"),
    expected_plate: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    next_url: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    ids = _parse_detection_ids(detection_ids)
    if not ids:
        target = next_url if next_url and next_url.startswith("/admin") else "/admin"
        return RedirectResponse(_append_query(target, bulk_feedback=0, bulk_feedback_failed=0), status_code=303)

    mode = (mode or "correct").lower()
    if mode not in {"correct", "corrected", "no_plate"}:
        mode = "correct"
    expected = (expected_plate or "").strip()
    if mode == "corrected" and not expected:
        mode = "correct"

    success = 0
    failed = 0
    sample_id_for_redirect = None
    for det_id in ids:
        det = db.get(Detection, det_id)
        if not det:
            failed += 1
            continue
        sample_id = _create_training_from_detection(
            db,
            det,
            mode,
            expected if mode == "corrected" else None,
            notes,
        )
        if sample_id:
            success += 1
            if sample_id_for_redirect is None:
                sample_id_for_redirect = sample_id
        else:
            failed += 1

    target = next_url if next_url and next_url.startswith("/admin") else "/admin"
    return RedirectResponse(
        _append_query(
            target,
            bulk_feedback=success,
            bulk_feedback_failed=failed,
            sample_id=sample_id_for_redirect,
        ),
        status_code=303,
    )


@app.post("/admin/training/{sample_id}/delete")
def training_delete(sample_id: int, db: Session = Depends(get_db)):
    sample = db.get(TrainingSample, sample_id)
    if sample:
        try:
            path = Path(MEDIA_DIR) / sample.image_path
            path.unlink(missing_ok=True)
        except Exception:
            pass
        db.delete(sample)
        db.commit()
    return RedirectResponse("/admin/training?deleted=1", status_code=303)


@app.get("/admin/api/training_status")
def training_status():
    return _get_training_status()


def _get_app_setting(db: Session, key: str, default: str) -> str:
    setting = db.get(AppSetting, key)
    if not setting or setting.value is None:
        return default
    return str(setting.value)


def _resolve_train_device(requested: str) -> str:
    if not requested:
        requested = "auto"
    requested = requested.strip().lower()
    if requested in {"auto", "cuda", "gpu"}:
        try:
            import torch
            if torch.cuda.is_available() and torch.cuda.device_count() > 0:
                return "0"
        except Exception:
            pass
        return "cpu"
    return requested


def _train_yolo_task(data_yaml: str, run_root: Path, sample_ids: List[int]):
    try:
        _set_training_status("running", "Launching YOLO training...")
        try:
            from ultralytics import YOLO
        except Exception:
            _set_training_status("failed", "Ultralytics not available. Install dependencies first.")
            return
        with SessionLocal() as db:
            model_name = _get_app_setting(db, "train_model", "yolov8n.pt")
            epochs = int(_get_app_setting(db, "train_epochs", "50"))
            imgsz = int(_get_app_setting(db, "train_imgsz", "640"))
            batch = int(_get_app_setting(db, "train_batch", "-1"))
            device_setting = _get_app_setting(db, "train_device", "auto")
            patience = int(_get_app_setting(db, "train_patience", "15"))
            aug = {
                "hsv_h": float(_get_app_setting(db, "train_hsv_h", "0.015")),
                "hsv_s": float(_get_app_setting(db, "train_hsv_s", "0.7")),
                "hsv_v": float(_get_app_setting(db, "train_hsv_v", "0.4")),
                "degrees": float(_get_app_setting(db, "train_degrees", "5.0")),
                "translate": float(_get_app_setting(db, "train_translate", "0.1")),
                "scale": float(_get_app_setting(db, "train_scale", "0.5")),
                "shear": float(_get_app_setting(db, "train_shear", "2.0")),
                "perspective": float(_get_app_setting(db, "train_perspective", "0.0005")),
                "fliplr": float(_get_app_setting(db, "train_fliplr", "0.5")),
                "mosaic": float(_get_app_setting(db, "train_mosaic", "0.5")),
                "mixup": float(_get_app_setting(db, "train_mixup", "0.1")),
            }
        device = _resolve_train_device(device_setting)

        _set_training_status(
            "running",
            f"Training config: model={model_name}, epochs={epochs}, imgsz={imgsz}, batch={batch}, device={device}, patience={patience}.",
        )
        model = YOLO(model_name)
        run_name = datetime.utcnow().strftime("run_%Y%m%d_%H%M%S")
        model.train(
            data=data_yaml,
            epochs=epochs,
            imgsz=imgsz,
            batch=batch,
            device=device,
            project=str(run_root),
            name=run_name,
            exist_ok=True,
            verbose=False,
            patience=patience,
            amp=False,
            hsv_h=aug["hsv_h"],
            hsv_s=aug["hsv_s"],
            hsv_v=aug["hsv_v"],
            degrees=aug["degrees"],
            translate=aug["translate"],
            scale=aug["scale"],
            shear=aug["shear"],
            perspective=aug["perspective"],
            fliplr=aug["fliplr"],
            mosaic=aug["mosaic"],
            mixup=aug["mixup"],
        )

        save_dir = None
        if hasattr(model, "trainer") and getattr(model.trainer, "save_dir", None):
            save_dir = Path(model.trainer.save_dir)
        if not save_dir:
            run_dirs = sorted(run_root.glob("*"), key=lambda p: p.stat().st_mtime, reverse=True)
            save_dir = run_dirs[0] if run_dirs else None
        if not save_dir:
            raise RuntimeError("Could not locate training run directory.")

        best = save_dir / "weights" / "best.pt"
        if not best.exists():
            raise RuntimeError("Training completed but best.pt not found.")

        model_dest = PROJECT_ROOT / "models" / "plate.pt"
        model_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, model_dest)
        if sample_ids:
            with SessionLocal() as db:
                now = datetime.utcnow()
                db.query(TrainingSample).filter(TrainingSample.id.in_(sample_ids)).update(
                    {TrainingSample.last_trained_at: now},
                    synchronize_session=False,
                )
                db.commit()
        try:
            reload_yolo_model()
        except Exception:
            pass
        _set_training_status(
            "complete",
            "Training complete. Model saved.",
            run_dir=str(save_dir),
            model_path=str(model_dest),
        )
        try:
            with SessionLocal() as db:
                _create_notification(
                    db,
                    title="Training completed",
                    message=f"New model saved to {model_dest}",
                    level="success",
                    kind="training",
                    extra={"run_dir": str(save_dir), "model_path": str(model_dest)},
                )
        except Exception:
            pass
    except Exception as exc:
        _set_training_status("failed", f"Training failed: {exc}")
        try:
            with SessionLocal() as db:
                _create_notification(
                    db,
                    title="Training failed",
                    message=str(exc),
                    level="error",
                    kind="training",
                )
        except Exception:
            pass


@app.post("/admin/training/train")
def training_train(db: Session = Depends(get_db)):
    status = _get_training_status()
    if status.get("status") == "running":
        return JSONResponse({"ok": False, "error": "Training already running."}, status_code=409)

    positives = (
        db.query(TrainingSample)
        .filter(TrainingSample.ignored.is_(False))
        .filter(TrainingSample.bbox.isnot(None))
        .filter(TrainingSample.no_plate.is_(False))
        .count()
    )
    if positives == 0:
        return JSONResponse({"ok": False, "error": "No annotated samples available."}, status_code=400)

    counts = _build_yolo_dataset(db)
    if counts.get("positives", 0) == 0:
        return JSONResponse({"ok": False, "error": "No positive labels were exported."}, status_code=400)

    run_root = Path(MEDIA_DIR) / "training_runs"
    run_root.mkdir(parents=True, exist_ok=True)
    _set_training_status("running", "Queued training...", run_dir=str(run_root))
    try:
        _create_notification(
            db,
            title="Training queued",
            message=f"YOLO training queued with dataset {counts.get('dataset_root')}",
            level="info",
            kind="training",
            extra={"dataset_root": counts.get("dataset_root")},
        )
    except Exception:
        pass

    data_yaml = str(counts.get("data_yaml"))
    sample_ids = counts.get("sample_ids") or []
    thread = threading.Thread(target=_train_yolo_task, args=(data_yaml, run_root, sample_ids), daemon=True)
    thread.start()
    return JSONResponse({"ok": True, "message": "Training started.", "data_yaml": data_yaml})


@app.get("/admin/training/center", response_class=HTMLResponse)
def training_center(request: Request, db: Session = Depends(get_db)):
    status = _get_training_status()
    settings = {
        "train_model": _get_app_setting(db, "train_model", "yolov8n.pt"),
        "train_epochs": _get_app_setting(db, "train_epochs", "50"),
        "train_imgsz": _get_app_setting(db, "train_imgsz", "640"),
        "train_batch": _get_app_setting(db, "train_batch", "-1"),
        "train_device": _get_app_setting(db, "train_device", "auto"),
        "train_patience": _get_app_setting(db, "train_patience", "15"),
        "train_hsv_h": _get_app_setting(db, "train_hsv_h", "0.015"),
        "train_hsv_s": _get_app_setting(db, "train_hsv_s", "0.7"),
        "train_hsv_v": _get_app_setting(db, "train_hsv_v", "0.4"),
        "train_degrees": _get_app_setting(db, "train_degrees", "5.0"),
        "train_translate": _get_app_setting(db, "train_translate", "0.1"),
        "train_scale": _get_app_setting(db, "train_scale", "0.5"),
        "train_shear": _get_app_setting(db, "train_shear", "2.0"),
        "train_perspective": _get_app_setting(db, "train_perspective", "0.0005"),
        "train_fliplr": _get_app_setting(db, "train_fliplr", "0.5"),
        "train_mosaic": _get_app_setting(db, "train_mosaic", "0.5"),
        "train_mixup": _get_app_setting(db, "train_mixup", "0.1"),
    }
    dataset_root = str(Path(MEDIA_DIR) / "training_yolo")
    run_root = str(Path(MEDIA_DIR) / "training_runs")
    return templates.TemplateResponse(
        "training_center.html",
        {
            "request": request,
            "training_status": status,
            "settings": settings,
            "dataset_root": dataset_root,
            "run_root": run_root,
        },
    )


@app.post("/admin/training/settings")
def training_settings_update(
    train_model: str = Form("yolov8n.pt"),
    train_epochs: int = Form(50),
    train_imgsz: int = Form(640),
    train_batch: int = Form(-1),
    train_device: str = Form("auto"),
    train_patience: int = Form(15),
    train_hsv_h: float = Form(0.015),
    train_hsv_s: float = Form(0.7),
    train_hsv_v: float = Form(0.4),
    train_degrees: float = Form(5.0),
    train_translate: float = Form(0.1),
    train_scale: float = Form(0.5),
    train_shear: float = Form(2.0),
    train_perspective: float = Form(0.0005),
    train_fliplr: float = Form(0.5),
    train_mosaic: float = Form(0.5),
    train_mixup: float = Form(0.1),
    db: Session = Depends(get_db),
):
    values = {
        "train_model": train_model.strip() or "yolov8n.pt",
        "train_epochs": str(max(1, int(train_epochs))),
        "train_imgsz": str(max(160, int(train_imgsz))),
        "train_batch": str(int(train_batch)),
        "train_device": train_device.strip() or "auto",
        "train_patience": str(max(1, int(train_patience))),
        "train_hsv_h": str(max(0.0, min(1.0, float(train_hsv_h)))),
        "train_hsv_s": str(max(0.0, min(1.0, float(train_hsv_s)))),
        "train_hsv_v": str(max(0.0, min(1.0, float(train_hsv_v)))),
        "train_degrees": str(max(0.0, min(30.0, float(train_degrees)))),
        "train_translate": str(max(0.0, min(0.7, float(train_translate)))),
        "train_scale": str(max(0.0, min(1.0, float(train_scale)))),
        "train_shear": str(max(0.0, min(20.0, float(train_shear)))),
        "train_perspective": str(max(0.0, min(0.01, float(train_perspective)))),
        "train_fliplr": str(max(0.0, min(1.0, float(train_fliplr)))),
        "train_mosaic": str(max(0.0, min(1.0, float(train_mosaic)))),
        "train_mixup": str(max(0.0, min(1.0, float(train_mixup)))),
    }
    for key, val in values.items():
        setting = db.get(AppSetting, key)
        if not setting:
            db.add(AppSetting(key=key, value=val))
        else:
            setting.value = val
    db.commit()
    return RedirectResponse("/admin/training/center?saved=1", status_code=303)


@app.get("/admin/discovery", response_class=HTMLResponse)
def admin_discovery(request: Request):
    return templates.TemplateResponse(
        "discovery.html",
        {"request": request, "result": request.session.get("last_discovery")},
    )


@app.post("/admin/discovery", response_class=HTMLResponse)
def run_discovery(
    request: Request,
    timeout: int = Form(3),
):
    result = discover_onvif(timeout=timeout, resolve_rtsp=False)
    request.session["last_discovery"] = result
    return templates.TemplateResponse(
        "discovery.html",
        {"request": request, "result": result},
    )


@app.post("/admin/discovery/resolve", response_class=HTMLResponse)
def resolve_rtsp(
    request: Request,
    xaddr: str = Form(...),
    username: str = Form(...),
    password: str = Form(...),
):
    last = request.session.get("last_discovery") or {"devices": []}
    if not last.get("devices"):
        last = discover_onvif(timeout=3, resolve_rtsp=False)
    rtsp_profiles = resolve_rtsp_for_xaddr(xaddr, username, password)
    for device in last.get("devices", []):
        if xaddr in (device.get("xaddrs") or []):
            device["rtsp_profiles"] = rtsp_profiles
            device["onvif_username"] = username
            device["onvif_password"] = password
            break
    request.session["last_discovery"] = last
    return templates.TemplateResponse(
        "discovery.html",
        {"request": request, "result": last},
    )


@app.post("/admin/allowed/{plate_id}/update")
def update_allowed(
    plate_id: int,
    plate_text: str = Form(...),
    label: Optional[str] = Form(None),
    active: Optional[bool] = Form(False),
    db: Session = Depends(get_db),
):
    plate_text = "".join(ch for ch in plate_text if ch.isalnum()).upper()
    allowed = db.get(AllowedPlate, plate_id)
    if allowed:
        allowed.plate_text = plate_text
        allowed.label = label
        allowed.active = bool(active)
        db.commit()
    return RedirectResponse("/admin/allowed", status_code=303)


@app.post("/admin/allowed/{plate_id}/delete")
def delete_allowed(plate_id: int, db: Session = Depends(get_db)):
    allowed = db.get(AllowedPlate, plate_id)
    if allowed:
        db.delete(allowed)
        db.commit()
    return RedirectResponse("/admin/allowed", status_code=303)


def _open_capture(camera: Camera):
    source = camera.source
    if camera.type == "webcam":
        try:
            source = int(source)
        except ValueError:
            source = 0
    return cv2.VideoCapture(source)


def _draw_overlay(frame, detection):
    if frame is None:
        return frame
    if not detection:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (8, 8), (w - 8, h - 8), (0, 180, 0), 2)
        cv2.rectangle(frame, (12, 12), (180, 36), (0, 0, 0), -1)
        cv2.putText(frame, "Searching...", (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2, cv2.LINE_AA)
        return frame
    ts = detection.get("ts") or 0
    if time.time() - ts > 5:
        h, w = frame.shape[:2]
        cv2.rectangle(frame, (8, 8), (w - 8, h - 8), (0, 180, 0), 2)
        cv2.rectangle(frame, (12, 12), (180, 36), (0, 0, 0), -1)
        cv2.putText(frame, "Searching...", (18, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 220, 0), 2, cv2.LINE_AA)
        return frame

    plate = detection.get("plate_text", "")
    status = detection.get("status", "")
    conf = detection.get("confidence")
    detector = detection.get("detector") or ""
    label = plate
    if status:
        label += f" | {status}"
    if conf is not None:
        label += f" | {conf:.2f}"
    if detector:
        label += f" | {detector}"

    box_color = (0, 255, 0)
    text_x, text_y = 10, 30
    bbox = detection.get("bbox")
    if isinstance(bbox, dict):
        x1 = int(bbox.get("x1", 0))
        y1 = int(bbox.get("y1", 0))
        x2 = int(bbox.get("x2", 0))
        y2 = int(bbox.get("y2", 0))
        cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 2)
        text_x = max(6, x1)
        text_y = y1 - 8 if y1 > 24 else y1 + 22
    elif bbox:
        pts = np.array(bbox, dtype=np.int32)
        if pts.ndim == 3 and pts.shape[1] == 1 and pts.shape[2] == 2:
            pts = pts.reshape(-1, 2)
        if pts.ndim == 2 and pts.shape[1] == 2:
            cv2.polylines(frame, [pts], True, box_color, 2)
            min_xy = pts.min(axis=0)
            text_x = int(max(6, min_xy[0]))
            text_y = int(min_xy[1] - 8 if min_xy[1] > 24 else min_xy[1] + 22)

    (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
    cv2.rectangle(frame, (text_x - 4, text_y - th - 6), (text_x + tw + 4, text_y + 4), (0, 0, 0), -1)
    cv2.putText(frame, label, (text_x, text_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, box_color, 2, cv2.LINE_AA)
    return frame


def _no_signal_jpeg(camera: Camera) -> bytes:
    frame = np.zeros((480, 854, 3), dtype=np.uint8)
    frame[:] = (8, 10, 16)
    cv2.putText(frame, "NO SIGNAL", (30, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (80, 120, 255), 3, cv2.LINE_AA)
    cv2.putText(
        frame,
        f"Camera #{camera.id} - {camera.name}",
        (30, 120),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        (220, 230, 240),
        2,
        cv2.LINE_AA,
    )
    cv2.putText(frame, f"Source: {camera.source}", (30, 165), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (180, 190, 200), 1, cv2.LINE_AA)
    cv2.putText(
        frame,
        "Check camera URL/port/network credentials and try again.",
        (30, 205),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (180, 190, 200),
        1,
        cv2.LINE_AA,
    )
    ok, buffer = cv2.imencode(".jpg", frame)
    if ok:
        return buffer.tobytes()
    return b""


def _mjpeg_stream(camera: Camera, overlay: bool = True):
    while True:
        jpeg = None
        frame = None
        if camera.type == "browser":
            jpeg = stream_manager.get_external_jpeg(camera.id)
            frame = stream_manager.get_external_frame(camera.id)
        else:
            jpeg = stream_manager.get_jpeg(camera.id, camera.type, camera.source)
            frame = stream_manager.get_frame(camera.id, camera.type, camera.source)

        if frame is None and jpeg is None:
            jpeg = _no_signal_jpeg(camera)
            if not jpeg:
                time.sleep(0.2)
                continue

        if frame is not None:
            if overlay:
                detection = stream_manager.get_detection(camera.id)
                frame = _draw_overlay(frame.copy(), detection)
            ret, buffer = cv2.imencode(".jpg", frame)
            if ret:
                jpeg = buffer.tobytes()

        if jpeg is None:
            time.sleep(0.05)
            continue

        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n")
        time.sleep(0.05 if frame is None else 0.001)


@app.get("/stream/{camera_id}")
def stream_camera(camera_id: int, overlay: int = 1, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera or not camera.enabled:
        return JSONResponse({"error": "camera not found"}, status_code=404)
    return StreamingResponse(_mjpeg_stream(camera, overlay=bool(int(overlay))), media_type="multipart/x-mixed-replace; boundary=frame")


@app.post("/admin/ptz/{camera_id}/move")
def ptz_move(
    camera_id: int,
    pan: float = Form(0.0),
    tilt: float = Form(0.0),
    zoom: float = Form(0.0),
    db: Session = Depends(get_db),
):
    camera = db.get(Camera, camera_id)
    if not camera:
        return JSONResponse({"ok": False, "error": "camera not found"}, status_code=404)
    ok, err = continuous_move(camera, pan=pan, tilt=tilt, zoom=zoom)
    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return {"ok": True}


@app.post("/admin/ptz/{camera_id}/stop")
def ptz_stop_route(camera_id: int, db: Session = Depends(get_db)):
    camera = db.get(Camera, camera_id)
    if not camera:
        return JSONResponse({"ok": False, "error": "camera not found"}, status_code=404)
    ok, err = ptz_stop(camera)
    if not ok:
        return JSONResponse({"ok": False, "error": err}, status_code=400)
    return {"ok": True}


# ── Analytics ────────────────────────────────────────────────

@app.get("/admin/analytics", response_class=HTMLResponse)
def admin_analytics(request: Request):
    return templates.TemplateResponse("analytics.html", {"request": request})


@app.get("/admin/api/analytics")
def api_analytics(hours: int = 168, db: Session = Depends(get_db)):
    from datetime import timedelta
    from sqlalchemy import func as sqlfunc
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    rows = db.query(Detection).filter(Detection.detected_at >= cutoff).all()
    total = len(rows)
    allowed_count = sum(1 for r in rows if r.status == "allowed")
    denied_count = sum(1 for r in rows if r.status == "denied")
    unique_plates = len(set(r.plate_text for r in rows))
    camera_ids = set(r.camera_id for r in rows)
    confidences = [r.confidence for r in rows if r.confidence is not None]
    avg_conf = sum(confidences) / len(confidences) if confidences else None

    # Activity over time: bucket by hour or day
    if hours <= 48:
        # Hourly buckets
        buckets = {}
        for r in rows:
            if r.detected_at:
                key = r.detected_at.strftime("%m-%d %H:00")
                buckets[key] = buckets.get(key, 0) + 1
    else:
        # Daily buckets
        buckets = {}
        for r in rows:
            if r.detected_at:
                key = r.detected_at.strftime("%m-%d")
                buckets[key] = buckets.get(key, 0) + 1

    sorted_keys = sorted(buckets.keys())
    activity_labels = sorted_keys
    activity_counts = [buckets[k] for k in sorted_keys]

    # Peak hour
    hour_counts = {}
    for r in rows:
        if r.detected_at:
            h = r.detected_at.hour
            hour_counts[h] = hour_counts.get(h, 0) + 1
    peak_hour = max(hour_counts, key=hour_counts.get) if hour_counts else None

    # Top plates
    plate_counts = {}
    plate_status = {}
    for r in rows:
        plate_counts[r.plate_text] = plate_counts.get(r.plate_text, 0) + 1
        plate_status[r.plate_text] = r.status
    top_plates = sorted(plate_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    top_plates_out = [{"plate": p, "count": c, "status": plate_status.get(p, "denied")} for p, c in top_plates]

    # Camera activity
    cam_counts = {}
    cam_names = {}
    for r in rows:
        cam_counts[r.camera_id] = cam_counts.get(r.camera_id, 0) + 1
    cameras = db.query(Camera).filter(Camera.id.in_(cam_counts.keys())).all()
    for c in cameras:
        cam_names[c.id] = c.name
    cam_activity = sorted(
        [{"camera": cam_names.get(cid, f"Camera {cid}"), "count": cnt} for cid, cnt in cam_counts.items()],
        key=lambda x: x["count"], reverse=True
    )

    last_det = max((r.detected_at for r in rows if r.detected_at), default=None)
    last_detection_str = last_det.strftime("%Y-%m-%d %H:%M") if last_det else None

    return {
        "total": total,
        "allowed": allowed_count,
        "denied": denied_count,
        "unique_plates": unique_plates,
        "active_cameras": len(camera_ids),
        "avg_confidence": avg_conf,
        "peak_hour": peak_hour,
        "activity_labels": activity_labels,
        "activity_counts": activity_counts,
        "top_plates": top_plates_out,
        "camera_activity": cam_activity,
        "last_detection": last_detection_str,
    }


# ── Export CSV ───────────────────────────────────────────────

@app.get("/admin/export/csv")
def export_detections_csv(db: Session = Depends(get_db)):
    import csv
    import io
    rows = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(Detection.detected_at.desc())
        .limit(5000)
        .all()
    )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Detected At", "Plate", "Status", "Confidence", "Camera", "Location", "Image", "Video"])
    for det, cam in rows:
        writer.writerow([
            det.id,
            det.detected_at.isoformat() if det.detected_at else "",
            det.plate_text,
            det.status,
            f"{(det.confidence or 0):.4f}",
            cam.name,
            cam.location or "",
            det.image_path or "",
            det.video_path or "",
        ])
    content = output.getvalue()
    from fastapi.responses import Response
    return Response(
        content=content,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=carvision_detections.csv"},
    )


@app.get("/admin/export/allowed")
def export_allowed_csv(db: Session = Depends(get_db)):
    import csv
    import io
    rows = db.query(AllowedPlate).order_by(AllowedPlate.id.asc()).all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Plate", "Label", "Active", "Created At"])
    for p in rows:
        writer.writerow([p.id, p.plate_text, p.label or "", "Yes" if p.active else "No", p.created_at.isoformat() if p.created_at else ""])
    from fastapi.responses import Response
    return Response(
        content=output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=carvision_allowed_plates.csv"},
    )


@app.get("/admin/export/training")
def export_training_json(db: Session = Depends(get_db)):
    rows = (
        db.query(TrainingSample)
        .order_by(TrainingSample.created_at.desc())
        .all()
    )
    items = []
    for sample in rows:
        items.append(
            {
                "id": sample.id,
                "image_path": sample.image_path,
                "image_hash": sample.image_hash,
                "image_width": sample.image_width,
                "image_height": sample.image_height,
                "plate_text": sample.plate_text,
                "bbox": sample.bbox,
                "notes": sample.notes,
                "no_plate": sample.no_plate,
                "ignored": sample.ignored,
                "last_trained_at": sample.last_trained_at.isoformat() if sample.last_trained_at else None,
                "created_at": sample.created_at.isoformat() if sample.created_at else None,
                "updated_at": sample.updated_at.isoformat() if sample.updated_at else None,
            }
        )
    return JSONResponse({"count": len(items), "items": items})


@app.get("/admin/export/yolo")
def export_training_yolo(db: Session = Depends(get_db)):
    counts = _build_yolo_dataset(db)
    return JSONResponse({"ok": True, "counts": counts})


# ── CarVision API (JWT) ─────────────────────────────────────

@app.post("/api/v1/auth/login")
def api_v1_login(body: ApiLoginBody):
    if body.username != API_ADMIN_USER or body.password != API_ADMIN_PASS:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = _api_create_token(body.username)
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": API_JWT_EXPIRE_MINUTES * 60,
        "user": {"username": body.username, "role": "admin"},
    }


@app.get("/api/v1/auth/me")
def api_v1_me(user: str = Depends(_api_get_current_user)):
    return {"username": user, "role": "admin"}


@app.get("/api/v1/dashboard/summary")
def api_v1_dashboard_summary(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    total_detections = db.query(Detection).count()
    total_cameras = db.query(Camera).count()
    active_cameras = db.query(Camera).filter(Camera.enabled.is_(True)).count()
    allowed_count = db.query(Detection).filter(Detection.status == "allowed").count()
    denied_count = db.query(Detection).filter(Detection.status == "denied").count()
    unread_notifications = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    training_status = _get_training_status()
    return {
        "totals": {
            "detections": total_detections,
            "cameras": total_cameras,
            "active_cameras": active_cameras,
            "allowed": allowed_count,
            "denied": denied_count,
            "unread_notifications": unread_notifications,
        },
        "training": training_status,
    }


@app.get("/api/v1/cameras")
def api_v1_cameras(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    mode_setting = db.get(AppSetting, "detector_mode")
    global_mode = mode_setting.value if mode_setting and mode_setting.value else "auto"
    rows = db.query(Camera).order_by(Camera.live_order.asc(), Camera.id.asc()).all()
    out = []
    for cam in rows:
        if cam.type == "browser":
            _ensure_capture_token(cam, db)
        out.append(
            {
                "id": cam.id,
                "name": cam.name,
                "type": cam.type,
                "source": cam.source,
                "location": cam.location,
                "enabled": bool(cam.enabled),
                "live_view": bool(cam.live_view),
                "live_order": cam.live_order,
                "scan_interval": cam.scan_interval,
                "cooldown_seconds": cam.cooldown_seconds,
                "detector_mode": cam.detector_mode,
                "effective_detector_mode": cam.detector_mode if cam.detector_mode != "inherit" else global_mode,
                "browser_online": stream_manager.is_external_online(cam.id) if cam.type == "browser" else None,
                "stream_url": f"/stream/{cam.id}?overlay=1",
                "capture_token": cam.capture_token if cam.type == "browser" else None,
                "capture_url": f"/capture/{cam.id}?token={cam.capture_token}" if cam.type == "browser" and cam.capture_token else None,
            }
        )
    return {"items": out}


@app.post("/api/v1/cameras")
def api_v1_camera_create(
    body: ApiCameraCreateBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    cam_type = (body.type or "").strip().lower()
    if cam_type not in {"webcam", "rtsp", "http_mjpeg", "browser", "upload"}:
        raise HTTPException(status_code=400, detail="Invalid camera type")
    detector_mode = (body.detector_mode or "inherit").strip().lower()
    if detector_mode not in {"inherit", "auto", "contour", "yolo"}:
        detector_mode = "inherit"

    source = _normalize_camera_source(cam_type, body.source or "")
    if not source:
        raise HTTPException(status_code=400, detail="Source is required")

    camera = Camera(
        name=(body.name or "").strip()[:100],
        type=cam_type,
        source=source,
        location=(body.location or "").strip()[:200] if body.location else None,
        enabled=bool(body.enabled),
        scan_interval=max(0.1, float(body.scan_interval)),
        cooldown_seconds=max(0.0, float(body.cooldown_seconds)),
        save_snapshot=bool(body.save_snapshot),
        save_clip=bool(body.save_clip),
        clip_seconds=max(0, int(body.clip_seconds)),
        live_view=bool(body.live_view),
        live_order=int(body.live_order),
        onvif_xaddr=(body.onvif_xaddr or "").strip()[:500] if body.onvif_xaddr else None,
        onvif_username=(body.onvif_username or "").strip()[:200] if body.onvif_username else None,
        onvif_password=(body.onvif_password or "").strip()[:200] if body.onvif_password else None,
        onvif_profile=(body.onvif_profile or "").strip()[:200] if body.onvif_profile else None,
        detector_mode=detector_mode,
    )
    if camera.type == "browser":
        camera.capture_token = secrets.token_urlsafe(16)
    db.add(camera)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Camera name already exists")
    return {"ok": True, "id": camera.id}


@app.patch("/api/v1/cameras/{camera_id:int}")
def api_v1_camera_update(
    camera_id: int,
    body: ApiCameraPatchBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")

    if body.name is not None:
        cam.name = body.name.strip()[:100] or cam.name
    if body.location is not None:
        cam.location = body.location.strip()[:200] if body.location else None
    if body.enabled is not None:
        cam.enabled = body.enabled
    if body.live_view is not None:
        cam.live_view = body.live_view
    if body.live_order is not None:
        cam.live_order = int(body.live_order)
    if body.detector_mode is not None:
        val = (body.detector_mode or "inherit").strip().lower()
        if val not in {"inherit", "contour", "yolo", "ocr", "auto"}:
            raise HTTPException(status_code=400, detail="Invalid detector mode")
        cam.detector_mode = val
    if body.scan_interval is not None:
        cam.scan_interval = max(0.1, float(body.scan_interval))
    if body.cooldown_seconds is not None:
        cam.cooldown_seconds = max(0.0, float(body.cooldown_seconds))
    db.add(cam)
    db.commit()
    return {"ok": True}


@app.delete("/api/v1/cameras/{camera_id:int}")
def api_v1_camera_delete(
    camera_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam)
    db.commit()
    return {"ok": True}


@app.get("/api/v1/cameras/layout")
def api_v1_camera_layout(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    max_live = _get_app_setting(db, "max_live_cameras", "16")
    return {"max_live_cameras": int(max_live)}


@app.get("/api/v1/live/overlays")
def api_v1_live_overlays(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    return api_live_overlays(db)


@app.get("/api/v1/live/stream_health")
def api_v1_live_stream_health(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    return api_stream_health(db)


@app.post("/api/v1/cameras/layout")
def api_v1_camera_layout_save(
    body: ApiLayoutBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    value = max(1, min(64, int(body.max_live_cameras)))
    setting = db.get(AppSetting, "max_live_cameras")
    if not setting:
        setting = AppSetting(key="max_live_cameras", value=str(value))
    else:
        setting.value = str(value)
    db.add(setting)
    db.commit()
    return {"ok": True, "max_live_cameras": value}


@app.get("/api/v1/detections")
def api_v1_detections(
    q: str = "",
    status: str = "",
    feedback: str = "",
    trained: str = "",
    camera_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    limit = max(1, min(1000, int(limit)))
    offset = max(0, int(offset))
    rows = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id)
        .order_by(Detection.detected_at.desc(), Detection.id.desc())
        .limit(limit + offset)
        .all()
    )
    if offset:
        rows = rows[offset:]

    sample_ids = [det.feedback_sample_id for det, _ in rows if det.feedback_sample_id]
    sample_map: Dict[int, TrainingSample] = {}
    if sample_ids:
        samples = db.query(TrainingSample).filter(TrainingSample.id.in_(sample_ids)).all()
        sample_map = {s.id: s for s in samples}

    q_norm = (q or "").strip().lower()
    status_norm = (status or "").strip().lower()
    feedback_norm = (feedback or "").strip().lower()
    trained_norm = (trained or "").strip().lower()
    out = []
    changed = False
    for det, cam in rows:
        debug_map, row_changed = _ensure_detection_debug_assets(det)
        changed = changed or row_changed

        sample = sample_map.get(det.feedback_sample_id) if det.feedback_sample_id else None
        annotated = bool(sample and sample.bbox and not sample.no_plate and not sample.ignored)
        ignored = bool(sample.ignored) if sample else False
        trained_flag = bool(sample and sample.last_trained_at)
        feedback_state = "ignored" if ignored else ("annotated" if annotated else "pending")

        if camera_id and cam.id != camera_id:
            continue
        if q_norm:
            hay = f"{det.plate_text or ''} {cam.name or ''} {cam.location or ''} {det.feedback_note or ''}".lower()
            if q_norm not in hay:
                continue
        if status_norm and det.status != status_norm:
            continue
        if feedback_norm and feedback_state != feedback_norm:
            continue
        if trained_norm == "trained" and not trained_flag:
            continue
        if trained_norm == "not_trained" and trained_flag:
            continue

        out.append(
            {
                "id": det.id,
                "camera_id": cam.id,
                "camera_name": cam.name,
                "camera_location": cam.location,
                "plate_text": det.plate_text,
                "status": det.status,
                "confidence": det.confidence,
                "detector": det.detector,
                "image_path": det.image_path,
                "video_path": det.video_path,
                "bbox": det.bbox,
                "raw_text": det.raw_text,
                "detected_at": det.detected_at.isoformat() if det.detected_at else None,
                "feedback_status": det.feedback_status,
                "feedback_note": det.feedback_note,
                "feedback_at": det.feedback_at.isoformat() if det.feedback_at else None,
                "feedback_sample_id": det.feedback_sample_id,
                "sample": {
                    "annotated": annotated,
                    "ignored": ignored,
                    "trained": trained_flag,
                    "last_trained_at": sample.last_trained_at.isoformat() if sample and sample.last_trained_at else None,
                }
                if sample
                else None,
                "debug": {
                    "color": debug_map.get("color"),
                    "bw": debug_map.get("bw"),
                    "gray": debug_map.get("gray"),
                    "edged": debug_map.get("edged"),
                    "mask": debug_map.get("mask"),
                },
                "debug_steps": _debug_steps_from_paths(debug_map),
            }
        )
    if changed:
        db.commit()
    return {"items": out, "count": len(out)}


@app.post("/api/v1/detections/{det_id:int}/reprocess")
def api_v1_reprocess_detection(
    det_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")
    new_id = _reprocess_detection_row(db, det)
    if not new_id:
        raise HTTPException(status_code=400, detail="Reprocess failed")
    return {"ok": True, "new_detection_id": new_id}


@app.post("/api/v1/detections/bulk/reprocess")
def api_v1_bulk_reprocess(
    body: ApiBulkIdsBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    ids = [int(x) for x in body.detection_ids if int(x) > 0]
    if not ids:
        return {"ok": True, "processed": 0, "failed": 0}
    success = 0
    failed = 0
    for det_id in ids:
        det = db.get(Detection, det_id)
        if not det:
            failed += 1
            continue
        if _reprocess_detection_row(db, det):
            success += 1
        else:
            failed += 1
    return {"ok": True, "processed": success, "failed": failed}


def _delete_detection_row(db: Session, det: Detection) -> None:
    for rel_path in [
        det.image_path,
        det.video_path,
        det.debug_color_path,
        det.debug_bw_path,
        det.debug_gray_path,
        det.debug_edged_path,
        det.debug_mask_path,
    ]:
        if not rel_path:
            continue
        try:
            (Path(MEDIA_DIR) / rel_path).unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(det)


@app.delete("/api/v1/detections/{det_id:int}")
def api_v1_delete_detection(
    det_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")
    _delete_detection_row(db, det)
    db.commit()
    return {"ok": True}


@app.post("/api/v1/detections/bulk/delete")
def api_v1_bulk_delete_detections(
    body: ApiBulkIdsBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    ids = [int(x) for x in body.detection_ids if int(x) > 0]
    if not ids:
        return {"ok": True, "deleted": 0, "failed": 0}

    deleted = 0
    failed = 0
    for det_id in ids:
        det = db.get(Detection, det_id)
        if not det:
            failed += 1
            continue
        _delete_detection_row(db, det)
        deleted += 1
    db.commit()
    return {"ok": True, "deleted": deleted, "failed": failed}


@app.post("/api/v1/detections/{det_id:int}/debug/regenerate")
def api_v1_regenerate_detection_debug(
    det_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")

    debug_map, changed = _ensure_detection_debug_assets(det, force=True)
    if not any(debug_map.values()):
        raise HTTPException(status_code=400, detail="Could not build debug steps for this detection")
    if changed:
        db.add(det)
        db.commit()

    return {"ok": True, "debug_steps": _debug_steps_from_paths(debug_map)}


@app.post("/api/v1/detections/{det_id:int}/feedback")
def api_v1_feedback_detection(
    det_id: int,
    body: ApiBulkFeedbackBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")
    mode = (body.mode or "correct").strip().lower()
    if mode not in {"correct", "corrected", "no_plate"}:
        raise HTTPException(status_code=400, detail="Invalid mode")
    sample_id = _create_training_from_detection(db, det, mode, body.expected_plate, body.notes)
    return {"ok": True, "sample_id": sample_id}


@app.post("/api/v1/detections/bulk/feedback")
def api_v1_bulk_feedback(
    body: ApiBulkFeedbackBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    ids = [int(x) for x in body.detection_ids if int(x) > 0]
    mode = (body.mode or "correct").strip().lower()
    if mode not in {"correct", "corrected", "no_plate"}:
        raise HTTPException(status_code=400, detail="Invalid mode")
    success = 0
    failed = 0
    sample_ids: List[int] = []
    for det_id in ids:
        det = db.get(Detection, det_id)
        if not det:
            failed += 1
            continue
        sample_id = _create_training_from_detection(db, det, mode, body.expected_plate, body.notes)
        if sample_id:
            sample_ids.append(sample_id)
            success += 1
        else:
            failed += 1
    return {"ok": True, "processed": success, "failed": failed, "sample_ids": sample_ids}


@app.get("/api/v1/training/status")
def api_v1_training_status(user: str = Depends(_api_get_current_user)):
    del user
    return _get_training_status()


@app.post("/api/v1/training/start")
def api_v1_training_start(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    return training_train(db)


@app.get("/api/v1/training/settings")
def api_v1_training_settings(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    return {
        "train_model": _get_app_setting(db, "train_model", "yolov8n.pt"),
        "train_epochs": _get_app_setting(db, "train_epochs", "50"),
        "train_imgsz": _get_app_setting(db, "train_imgsz", "640"),
        "train_batch": _get_app_setting(db, "train_batch", "-1"),
        "train_device": _get_app_setting(db, "train_device", "auto"),
        "train_patience": _get_app_setting(db, "train_patience", "15"),
    }


@app.get("/api/v1/training/samples")
def api_v1_training_samples(
    status: str = "all",
    q: str = "",
    batch: str = "",
    limit: int = 500,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    status = (status or "all").strip().lower()
    if status not in {"all", "annotated", "pending", "negative", "ignored"}:
        status = "all"
    limit = max(1, min(2000, int(limit)))

    batch_filter = (batch or "").strip()[:80]
    base_query = db.query(TrainingSample)
    if batch_filter:
        base_query = base_query.filter(TrainingSample.import_batch == batch_filter)
    counts = {
        "total": base_query.count(),
        "annotated": base_query.filter(
            TrainingSample.ignored.is_(False),
            or_(TrainingSample.bbox.isnot(None), TrainingSample.no_plate.is_(True)),
        ).count(),
        "negative": base_query.filter(TrainingSample.no_plate.is_(True), TrainingSample.ignored.is_(False)).count(),
        "pending": base_query.filter(
            TrainingSample.bbox.is_(None),
            TrainingSample.no_plate.is_(False),
            TrainingSample.ignored.is_(False),
        ).count(),
        "ignored": base_query.filter(TrainingSample.ignored.is_(True)).count(),
    }

    qy = db.query(TrainingSample)
    if batch_filter:
        qy = qy.filter(TrainingSample.import_batch == batch_filter)
    if status == "annotated":
        qy = qy.filter(TrainingSample.bbox.isnot(None), TrainingSample.ignored.is_(False))
    elif status == "negative":
        qy = qy.filter(TrainingSample.no_plate.is_(True), TrainingSample.ignored.is_(False))
    elif status == "pending":
        qy = qy.filter(
            TrainingSample.bbox.is_(None),
            TrainingSample.no_plate.is_(False),
            TrainingSample.ignored.is_(False),
        )
    elif status == "ignored":
        qy = qy.filter(TrainingSample.ignored.is_(True))

    if q:
        q_like = f"%{q.strip()}%"
        qy = qy.filter(
            or_(
                TrainingSample.plate_text.ilike(q_like),
                TrainingSample.image_path.ilike(q_like),
                TrainingSample.notes.ilike(q_like),
            )
        )

    rows = qy.order_by(TrainingSample.created_at.desc()).limit(limit).all()
    return {"counts": counts, "items": [_api_training_sample_payload(r) for r in rows], "batch": batch_filter or None}


@app.get("/api/v1/training/samples/{sample_id:int}")
def api_v1_training_sample(
    sample_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    row = db.get(TrainingSample, sample_id)
    if not row:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"item": _api_training_sample_payload(row), "debug_steps": _build_training_debug(row)}


@app.post("/api/v1/training/upload")
async def api_v1_training_upload(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    created_ids: List[int] = []
    batch_id = f"img_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            continue
        content = await file.read()
        if not content:
            continue
        image_hash = _hash_bytes(content)
        rel_path, width, height = _save_training_upload(content, file.filename or "upload.jpg")
        if not rel_path:
            continue
        sample = TrainingSample(
            image_path=rel_path,
            image_hash=image_hash,
            image_width=width,
            image_height=height,
            import_batch=batch_id,
        )
        db.add(sample)
        db.flush()
        created_ids.append(sample.id)
    if created_ids:
        db.commit()
    return {"ok": True, "created": len(created_ids), "ids": created_ids, "batch_id": batch_id if created_ids else None}


@app.post("/api/v1/training/import")
async def api_v1_training_import(
    files: Optional[List[UploadFile]] = File(None),
    dataset_zip: Optional[UploadFile] = File(None),
    has_annotations: bool = Form(False),
    annotations_format: str = Form("yolo"),
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    image_files = files or []
    if not image_files and dataset_zip is None:
        raise HTTPException(status_code=400, detail="Provide images and/or a ZIP dataset")

    fmt = (annotations_format or "yolo").strip().lower()
    if bool(has_annotations) and fmt != "yolo":
        raise HTTPException(status_code=400, detail="Only YOLO annotations are currently supported")

    batch_id = f"import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    created_ids: List[int] = []
    annotated = 0
    negatives = 0
    pending = 0

    def add_sample(image_bytes: bytes, filename: str, label_text: Optional[str] = None):
        nonlocal annotated, negatives, pending
        if not image_bytes:
            return
        image_hash = _hash_bytes(image_bytes)
        rel_path, width, height = _save_training_upload(image_bytes, filename or "import.jpg")
        if not rel_path:
            return

        sample = TrainingSample(
            image_path=rel_path,
            image_hash=image_hash,
            image_width=width,
            image_height=height,
            import_batch=batch_id,
        )

        if bool(has_annotations) and label_text is not None:
            text = (label_text or "").strip()
            if not text:
                sample.no_plate = True
                sample.bbox = None
                sample.plate_text = None
                sample.notes = "Imported as negative sample from empty YOLO label."
                negatives += 1
            else:
                bbox = _extract_yolo_bbox(text, width or 0, height or 0)
                if bbox:
                    sample.no_plate = False
                    sample.bbox = bbox
                    sample.notes = "Imported YOLO bbox. Add/correct plate text before training."
                    annotated += 1
                else:
                    sample.notes = "Label file found but YOLO bbox could not be parsed."
                    pending += 1
        else:
            pending += 1

        db.add(sample)
        db.flush()
        created_ids.append(sample.id)

    if image_files:
        text_map: Dict[str, str] = {}
        image_payloads: List[Tuple[str, bytes]] = []
        for file in image_files:
            name = (file.filename or "upload").strip()
            content = await file.read()
            if not content:
                continue
            if _is_image_filename(name) or (file.content_type and file.content_type.startswith("image/")):
                image_payloads.append((name, content))
                continue
            if bool(has_annotations) and Path(name).suffix.lower() == ".txt":
                text_map[Path(name).stem.lower()] = content.decode("utf-8", errors="ignore")

        for name, content in image_payloads:
            label = text_map.get(Path(name).stem.lower()) if bool(has_annotations) else None
            add_sample(content, name, label)

    if dataset_zip is not None:
        zip_bytes = await dataset_zip.read()
        if zip_bytes:
            try:
                with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
                    text_map: Dict[str, str] = {}
                    image_entries = []
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        name = info.filename.replace("\\", "/")
                        low = name.lower()
                        if _is_image_filename(low):
                            image_entries.append(info)
                        elif bool(has_annotations) and low.endswith(".txt"):
                            try:
                                text_map[low] = zf.read(info).decode("utf-8", errors="ignore")
                            except Exception:
                                text_map[low] = ""

                    for info in image_entries:
                        name = info.filename.replace("\\", "/")
                        try:
                            content = zf.read(info)
                        except Exception:
                            continue
                        label = None
                        if bool(has_annotations):
                            for cand in _zip_label_candidates(name):
                                label = text_map.get(cand.lower())
                                if label is not None:
                                    break
                        add_sample(content, Path(name).name, label)
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="Invalid ZIP file")

    if created_ids:
        db.commit()

    return {
        "ok": True,
        "created": len(created_ids),
        "ids": created_ids,
        "batch_id": batch_id if created_ids else None,
        "has_annotations": bool(has_annotations),
        "annotated": annotated,
        "negatives": negatives,
        "pending": pending,
    }


@app.patch("/api/v1/training/samples/{sample_id:int}/annotate")
def api_v1_training_annotate(
    sample_id: int,
    body: ApiTrainingAnnotateBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    if body.no_plate:
        sample.no_plate = True
        sample.bbox = None
        sample.plate_text = None
    else:
        sample.no_plate = False
        if (
            body.bbox_x is not None
            and body.bbox_y is not None
            and body.bbox_w is not None
            and body.bbox_h is not None
            and body.bbox_w > 0
            and body.bbox_h > 0
        ):
            sample.bbox = {
                "x": int(body.bbox_x),
                "y": int(body.bbox_y),
                "w": int(body.bbox_w),
                "h": int(body.bbox_h),
            }
        else:
            sample.bbox = None
        sample.plate_text = body.plate_text.strip()[:50] if body.plate_text else None

    sample.notes = body.notes.strip()[:500] if body.notes else None
    sample.ignored = False
    db.add(sample)
    db.commit()
    return {"ok": True, "item": _api_training_sample_payload(sample)}


@app.post("/api/v1/training/samples/{sample_id:int}/ignore")
def api_v1_training_ignore(
    sample_id: int,
    body: ApiTrainingIgnoreBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if body.ignored is None:
        sample.ignored = not bool(sample.ignored)
    else:
        sample.ignored = bool(body.ignored)
    db.add(sample)
    db.commit()
    return {"ok": True, "item": _api_training_sample_payload(sample)}


@app.delete("/api/v1/training/samples/{sample_id:int}")
def api_v1_training_delete(
    sample_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    try:
        path = Path(MEDIA_DIR) / sample.image_path
        path.unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(sample)
    db.commit()
    return {"ok": True}


@app.get("/api/v1/training/export_yolo")
def api_v1_training_export_yolo(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    counts = _build_yolo_dataset(db)
    return {"ok": True, "counts": counts}


@app.post("/api/v1/upload/start")
async def api_v1_upload_start(
    file: UploadFile = File(...),
    sample_seconds: float = Form(1.0),
    max_frames: int = Form(300),
    show_debug: Optional[bool] = Form(False),
    user: str = Depends(_api_get_current_user),
):
    del user
    _cleanup_upload_jobs()
    filename = f"uploads/{int(time.time())}_{file.filename}"
    file_path = Path(MEDIA_DIR) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    file_path.write_bytes(content)

    job_id = _create_upload_job(file.filename or file_path.name)
    thread = threading.Thread(
        target=_run_upload_job,
        args=(job_id, file_path, file.content_type or "", float(sample_seconds), int(max_frames), bool(show_debug)),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "job_id": job_id}


@app.get("/api/v1/upload/status/{job_id}")
def api_v1_upload_status(
    job_id: str,
    user: str = Depends(_api_get_current_user),
):
    del user
    _cleanup_upload_jobs()
    job = _get_upload_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}


@app.get("/api/v1/allowed")
def api_v1_allowed_list(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    rows = db.query(AllowedPlate).order_by(AllowedPlate.id.asc()).all()
    return {"items": [_api_allowed_payload(r) for r in rows]}


@app.post("/api/v1/allowed")
def api_v1_allowed_create(
    body: ApiAllowedPlateBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
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
    return {"ok": True, "item": _api_allowed_payload(row)}


@app.patch("/api/v1/allowed/{plate_id:int}")
def api_v1_allowed_update(
    plate_id: int,
    body: ApiAllowedPlateBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
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
    return {"ok": True, "item": _api_allowed_payload(row)}


@app.delete("/api/v1/allowed/{plate_id:int}")
def api_v1_allowed_delete(
    plate_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    row = db.get(AllowedPlate, plate_id)
    if not row:
        raise HTTPException(status_code=404, detail="Allowed plate not found")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/v1/discovery/run")
def api_v1_discovery_run(
    timeout: int = 3,
    user: str = Depends(_api_get_current_user),
):
    del user
    timeout = max(1, min(int(timeout), 15))
    result = discover_onvif(timeout=timeout, resolve_rtsp=False)
    return result


@app.post("/api/v1/discovery/resolve")
def api_v1_discovery_resolve(
    body: ApiDiscoveryResolveBody,
    user: str = Depends(_api_get_current_user),
):
    del user
    profiles = resolve_rtsp_for_xaddr(body.xaddr, body.username, body.password)
    return {"xaddr": body.xaddr, "rtsp_profiles": profiles}


@app.get("/api/v1/notifications")
def api_v1_notifications(
    limit: int = 100,
    unread_only: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    limit = max(1, min(500, int(limit)))
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.is_read.is_(False))
    rows = q.order_by(Notification.created_at.desc(), Notification.id.desc()).limit(limit).all()
    unread = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    return {"items": [_notification_payload(r) for r in rows], "unread": unread}


@app.post("/api/v1/notifications/{notification_id:int}/read")
def api_v1_notification_read(
    notification_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    row = db.get(Notification, notification_id)
    if not row:
        raise HTTPException(status_code=404, detail="Notification not found")
    if not row.is_read:
        row.is_read = True
        row.read_at = datetime.utcnow()
        db.commit()
    return {"ok": True}


@app.post("/api/v1/notifications/read_all")
def api_v1_notifications_read_all(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    db.query(Notification).filter(Notification.is_read.is_(False)).update(
        {Notification.is_read: True, Notification.read_at: datetime.utcnow()},
        synchronize_session=False,
    )
    db.commit()
    return {"ok": True}
