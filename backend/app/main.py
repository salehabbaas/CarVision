"""
main.py — CarVision application factory.

Responsible for:
  - Creating the FastAPI app with middleware
  - Instantiating shared services (StreamManager, ManualClipManager, CameraManager)
  - Registering all APIRouter modules
  - Startup / shutdown lifecycle events
  - Thin non-API routes: MJPEG stream, browser-capture ingest, legacy redirects
"""
from __future__ import annotations

import logging
import os
import secrets
import signal
import subprocess
import threading
import time
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import cv2
import numpy as np
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from anpr import crop_from_bbox, read_plate_text, set_anpr_config
from camera_manager import CameraManager
from core.config import (
    API_CORS_ORIGINS,
    FRONTEND_PUBLIC_BASE_URL,
    FRONTEND_PUBLIC_PORT,
    FRONTEND_PUBLIC_SCHEME,
    MEDIA_DIR,
    PROJECT_ROOT,
)
from db import Base, SessionLocal, engine, ensure_schema, get_db
from models import AppSetting, Camera, Detection
from onvif_ptz import continuous_move, stop as ptz_stop
from plate_detector import detect_plate, reload_yolo_model
from services.dataset import (
    bbox_xywh_to_xyxy as _bbox_xywh_to_xyxy,
    build_yolo_dataset as _build_yolo_dataset,
    copy_training_image as _copy_training_image,
    extract_yolo_bbox as _extract_yolo_bbox,
    load_image_size as _load_image_size,
    zip_label_candidates as _zip_label_candidates,
)
from services.debug_assets import (
    debug_steps_from_paths as _debug_steps_from_paths,
    save_upload_debug as _save_upload_debug,
)
from services.file_utils import hash_bytes as _hash_bytes, hash_file as _hash_file, safe_filename as _safe_filename
from services.manual_clip_manager import ManualClipManager
from services.state import (
    cleanup_upload_jobs as _cleanup_upload_jobs,
    create_upload_job as _create_upload_job,
    get_training_status as _get_training_status,
    set_training_status as _set_training_status,
    update_upload_job as _update_upload_job,
)
from stream_manager import StreamManager

# ── Router imports ────────────────────────────────────────────────────────────
from routers import (
    allowed,
    auth,
    cameras,
    clips,
    dashboard,
    detections,
    discovery,
    notifications,
    training,
    training_samples,
    upload,
)

logger = logging.getLogger("carvision")

# ── JPEG quality for live MJPEG streams ──────────────────────────────────────
LIVE_STREAM_JPEG_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), 82]

# ── Training scheduler stop event ────────────────────────────────────────────
TRAIN_SCHEDULER_LOCK = threading.Lock()
TRAIN_SCHEDULER_THREAD: Optional[threading.Thread] = None
TRAIN_SCHEDULER_STOP = threading.Event()


# ═══════════════════════════════════════════════════════════════════════════════
# Shared service instances
# ═══════════════════════════════════════════════════════════════════════════════

stream_manager = StreamManager()
manual_clip_manager = ManualClipManager(media_dir=MEDIA_DIR, stream_manager=stream_manager)
camera_manager = CameraManager(media_dir=MEDIA_DIR, stream_manager=stream_manager)


# ═══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _get_app_setting(db: Session, key: str, default: str = "") -> str:
    setting = db.get(AppSetting, key)
    if not setting or setting.value is None:
        return default
    return str(setting.value)


def _set_app_setting(db: Session, key: str, value: str) -> None:
    setting = db.get(AppSetting, key)
    if not setting:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value


def update_settings(
    detector_mode: str = Form("auto"),
    max_live_cameras: int = Form(16),
    inference_device: str = Form("cpu"),
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
    """
    Backward-compatible settings updater kept for test and legacy call sites.
    The v1 API should use dedicated routers/services, but this shim preserves behavior.
    """
    values = {
        "detector_mode": str(detector_mode or "auto"),
        "max_live_cameras": str(max(1, min(64, int(max_live_cameras)))),
        "inference_device": str(inference_device or "cpu"),
        "yolo_conf": str(max(0.01, min(1.0, float(yolo_conf)))),
        "yolo_imgsz": str(max(128, min(2048, int(yolo_imgsz)))),
        "yolo_iou": str(max(0.01, min(1.0, float(yolo_iou)))),
        "yolo_max_det": str(max(1, min(50, int(yolo_max_det)))),
        "ocr_max_width": str(max(320, min(8192, int(ocr_max_width)))),
        "ocr_langs": str(ocr_langs or "en"),
        "contour_canny_low": str(max(0, min(255, int(contour_canny_low)))),
        "contour_canny_high": str(max(0, min(255, int(contour_canny_high)))),
        "contour_bilateral_d": str(max(1, min(31, int(contour_bilateral_d)))),
        "contour_bilateral_sigma_color": str(max(1, min(255, int(contour_bilateral_sigma_color)))),
        "contour_bilateral_sigma_space": str(max(1, min(255, int(contour_bilateral_sigma_space)))),
        "contour_approx_eps": str(max(0.001, min(0.2, float(contour_approx_eps)))),
        "contour_pad_ratio": str(max(0.0, min(1.0, float(contour_pad_ratio)))),
        "contour_pad_min": str(max(0, min(500, int(contour_pad_min)))),
    }
    for key, val in values.items():
        _set_app_setting(db, key, val)
    db.commit()
    _refresh_anpr_config(db)
    reload_yolo_model()
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _refresh_anpr_config(db: Session) -> None:
    set_anpr_config({
        "inference_device": _get_app_setting(db, "inference_device", "cpu"),
        "ocr_max_width": _get_app_setting(db, "ocr_max_width", "1280"),
        "ocr_langs": _get_app_setting(db, "ocr_langs", "en"),
        "contour_canny_low": _get_app_setting(db, "contour_canny_low", "30"),
        "contour_canny_high": _get_app_setting(db, "contour_canny_high", "200"),
        "contour_bilateral_d": _get_app_setting(db, "contour_bilateral_d", "11"),
        "contour_bilateral_sigma_color": _get_app_setting(db, "contour_bilateral_sigma_color", "17"),
        "contour_bilateral_sigma_space": _get_app_setting(db, "contour_bilateral_sigma_space", "17"),
        "contour_approx_eps": _get_app_setting(db, "contour_approx_eps", "0.018"),
        "contour_pad_ratio": _get_app_setting(db, "contour_pad_ratio", "0.15"),
        "contour_pad_min": _get_app_setting(db, "contour_pad_min", "18"),
        "plate_min_length": _get_app_setting(db, "plate_min_length", "5"),
        "plate_max_length": _get_app_setting(db, "plate_max_length", "8"),
        "plate_charset": _get_app_setting(db, "plate_charset", "alnum"),
        "plate_pattern_regex": _get_app_setting(db, "plate_pattern_regex", ""),
        "plate_shape_hint": _get_app_setting(db, "plate_shape_hint", "standard"),
        "plate_reference_date": _get_app_setting(db, "plate_reference_date", ""),
        "ocr_char_map": _get_app_setting(db, "ocr_char_map", "{}"),
    })


def _get_browser_camera_by_token(camera_id: int, token: Optional[str], db: Session) -> Camera:
    camera = db.get(Camera, camera_id)
    if not camera or camera.type != "browser":
        raise HTTPException(status_code=404, detail="Camera not found")
    if not token or token != camera.capture_token:
        raise HTTPException(status_code=403, detail="Invalid capture token")
    return camera


def _frontend_origin_from_request(request: Request) -> str:
    if FRONTEND_PUBLIC_BASE_URL:
        return FRONTEND_PUBLIC_BASE_URL.rstrip("/")
    parsed = urlparse(str(request.base_url))
    host = parsed.hostname or request.url.hostname or "localhost"
    scheme = FRONTEND_PUBLIC_SCHEME or parsed.scheme or "http"
    port = (FRONTEND_PUBLIC_PORT or "").strip()
    if not port:
        port = "443" if scheme == "https" else "80"
    if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
        return f"{scheme}://{host}"
    return f"{scheme}://{host}:{port}"


def _legacy_redirect(request: Request) -> RedirectResponse:
    path = request.url.path
    if path == "/admin":
        target_path = "/"
    elif path.startswith("/admin/"):
        target_path = "/" + path[len("/admin/"):]
    else:
        target_path = path
    target = f"{_frontend_origin_from_request(request)}{target_path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(target, status_code=307)


def _run_upload_job(
    job_id: str,
    file_path: Path,
    content_type: str,
    sample_seconds: float,
    max_frames: int,
    show_debug: bool,
) -> None:
    """Background worker: extract frames from a video/image and run the plate detector."""
    local_db = SessionLocal()
    try:
        _update_upload_job(job_id, status="running", progress=5, message="Starting analysis", step="Reading file")
        is_video = content_type.startswith("video/") or file_path.suffix.lower() in {
            ".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv",
        }
        results = []

        if is_video:
            cap = cv2.VideoCapture(str(file_path))
            fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            step_frames = max(1, int(fps * float(sample_seconds)))
            frames_to_process = min(max_frames, max(1, total_frames // step_frames))
            processed = 0
            frame_idx = 0

            while cap.isOpened() and processed < max_frames:
                cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
                ret, frame = cap.read()
                if not ret:
                    break
                detection = detect_plate(frame)
                if detection and detection.get("plate_text"):
                    plate_text = detection["plate_text"]
                    from models import AllowedPlate
                    norm = "".join(ch for ch in plate_text if ch.isalnum()).upper()
                    allowed_row = local_db.query(AllowedPlate).filter(
                        AllowedPlate.plate_text == norm, AllowedPlate.active.is_(True)
                    ).first()
                    status = "allowed" if allowed_row else "denied"
                    results.append({
                        "frame": frame_idx,
                        "plate_text": plate_text,
                        "confidence": detection.get("confidence"),
                        "status": status,
                        "detector": detection.get("detector"),
                    })
                processed += 1
                frame_idx += step_frames
                pct = int((processed / max(1, frames_to_process)) * 90)
                if processed % 5 == 0:
                    _update_upload_job(job_id, status="running", progress=pct,
                                       message=f"Analysed {processed} frames, found {len(results)} plates",
                                       step=f"Frame {frame_idx}/{total_frames}")
            cap.release()
        else:
            frame = cv2.imread(str(file_path))
            if frame is not None:
                detection = detect_plate(frame)
                if detection and detection.get("plate_text"):
                    plate_text = detection["plate_text"]
                    from models import AllowedPlate
                    norm = "".join(ch for ch in plate_text if ch.isalnum()).upper()
                    allowed_row = local_db.query(AllowedPlate).filter(
                        AllowedPlate.plate_text == norm, AllowedPlate.active.is_(True)
                    ).first()
                    status = "allowed" if allowed_row else "denied"
                    results.append({"frame": 0, "plate_text": plate_text,
                                    "confidence": detection.get("confidence"), "status": status,
                                    "detector": detection.get("detector")})

        _update_upload_job(job_id, status="complete", progress=100,
                           message=f"Analysis complete — {len(results)} plate(s) found",
                           result={"plates": results, "total": len(results)})
    except Exception as exc:
        logger.exception("Upload job %s failed", job_id)
        try:
            local_db.rollback()
        except Exception:
            pass
        _update_upload_job(job_id, status="failed", progress=100,
                           message=f"Analysis failed: {exc}", error=str(exc))
    finally:
        local_db.close()
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass


# ── MJPEG stream generator ────────────────────────────────────────────────────

def _mjpeg_stream(camera: Camera, overlay: bool = True):
    """Yield MJPEG frames from the stream manager."""
    while True:
        frame = stream_manager.get_frame(camera.id, camera.type, camera.source)
        if frame is None:
            time.sleep(0.05)
            continue
        if overlay:
            det = stream_manager.get_detection(camera.id)
            if det and isinstance(det, dict):
                bbox = det.get("bbox")
                plate_text = det.get("plate_text", "")
                status = det.get("status", "")
                if bbox and isinstance(bbox, dict):
                    x, y, w, h = (int(bbox.get(k, 0)) for k in ("x", "y", "w", "h"))
                    color = (0, 200, 0) if status == "allowed" else (0, 0, 220)
                    cv2.rectangle(frame, (x, y), (x + w, y + h), color, 2)
                    if plate_text:
                        cv2.putText(frame, plate_text, (x, max(0, y - 8)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
        _, jpeg = cv2.imencode(".jpg", frame, LIVE_STREAM_JPEG_PARAMS)
        yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg.tobytes() + b"\r\n")
        time.sleep(0.04)


# ── Nightly training scheduler ────────────────────────────────────────────────

def _training_scheduler_loop() -> None:
    while not TRAIN_SCHEDULER_STOP.is_set():
        try:
            with SessionLocal() as db:
                enabled = _as_bool(_get_app_setting(db, "train_nightly_enabled", "1"), True)
                if enabled:
                    hh = max(0, min(23, int(_get_app_setting(db, "train_nightly_hour", "0") or "0")))
                    mm = max(0, min(59, int(_get_app_setting(db, "train_nightly_minute", "0") or "0")))
                    tz_name = (_get_app_setting(db, "train_schedule_tz", "America/Toronto") or "America/Toronto").strip()
                    try:
                        now_local = datetime.now(ZoneInfo(tz_name))
                    except Exception:
                        now_local = datetime.utcnow()
                        tz_name = "UTC"
                    today = now_local.strftime("%Y-%m-%d")
                    last_day = _get_app_setting(db, "train_nightly_last_date", "")
                    if now_local.hour == hh and now_local.minute == mm and last_day != today:
                        result = training._start_training_pipeline_from_request(db, mode="new_only", trigger="nightly")
                        _set_app_setting(db, "train_nightly_last_date", today)
                        db.commit()
                        if result.get("ok"):
                            from routers.deps import create_notification
                            try:
                                create_notification(
                                    db, title="Nightly training started",
                                    message=f"Nightly job started ({tz_name} {hh:02d}:{mm:02d})",
                                    level="info", kind="training",
                                )
                                db.commit()
                            except Exception:
                                pass
        except Exception:
            pass
        TRAIN_SCHEDULER_STOP.wait(20)


def _start_training_scheduler() -> None:
    global TRAIN_SCHEDULER_THREAD
    with TRAIN_SCHEDULER_LOCK:
        if TRAIN_SCHEDULER_THREAD and TRAIN_SCHEDULER_THREAD.is_alive():
            return
        TRAIN_SCHEDULER_STOP.clear()
        TRAIN_SCHEDULER_THREAD = threading.Thread(target=_training_scheduler_loop, daemon=True)
        TRAIN_SCHEDULER_THREAD.start()


def _resume_pipeline_if_needed() -> None:
    try:
        with SessionLocal() as db:
            active = training._active_training_job(db)
            if active:
                training._start_training_pipeline_thread(active.id)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# FastAPI application factory
# ═══════════════════════════════════════════════════════════════════════════════

def create_app() -> FastAPI:
    application = FastAPI(title="CarVision by Saleh Abbaas")

    application.add_middleware(
        CORSMiddleware,
        allow_origins=API_CORS_ORIGINS if API_CORS_ORIGINS else ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Serve uploaded media files
    application.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")

    # ── Inject shared state into each router ──────────────────────────────────
    cameras._init(stream_manager, manual_clip_manager)
    clips._init(manual_clip_manager)
    detections._init(detect_plate, read_plate_text, _copy_training_image, _load_image_size)
    training._init(camera_manager, read_plate_text, crop_from_bbox, set_anpr_config)
    upload._init(_run_upload_job)

    # ── Register routers ──────────────────────────────────────────────────────
    for r in [
        auth.router,
        dashboard.router,
        cameras.router,
        detections.router,
        allowed.router,
        notifications.router,
        training.router,
        training_samples.router,
        upload.router,
        clips.router,
        discovery.router,
    ]:
        application.include_router(r)

    # ── Startup ───────────────────────────────────────────────────────────────
    @application.on_event("startup")
    def on_startup():
        Base.metadata.create_all(bind=engine)
        ensure_schema()
        _seed_default_settings()
        camera_manager.start()
        _resume_pipeline_if_needed()
        _start_training_scheduler()

    # ── Shutdown ──────────────────────────────────────────────────────────────
    @application.on_event("shutdown")
    def on_shutdown():
        camera_manager.stop()
        manual_clip_manager.stop_all()
        training.TRAIN_PIPELINE_STOP.set()
        training._stop_training_proc(force=False)
        TRAIN_SCHEDULER_STOP.set()

    # ── MJPEG camera stream ───────────────────────────────────────────────────
    @application.get("/stream/{camera_id}")
    def stream_camera(camera_id: int, overlay: int = 1, db: Session = Depends(get_db)):
        camera = db.get(Camera, camera_id)
        if not camera or not camera.enabled:
            return JSONResponse({"error": "camera not found"}, status_code=404)
        return StreamingResponse(
            _mjpeg_stream(camera, overlay=bool(int(overlay))),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    # ── Browser camera capture endpoints ─────────────────────────────────────
    @application.get("/api/v1/capture/{camera_id}")
    def capture_session(camera_id: int, request: Request, db: Session = Depends(get_db)):
        camera = _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
        return {"ok": True, "camera": {"id": camera.id, "name": camera.name, "location": camera.location,
                                        "online": stream_manager.is_external_online(camera.id)}}

    @application.post("/api/v1/capture/{camera_id}/ingest")
    async def capture_ingest(camera_id: int, request: Request, db: Session = Depends(get_db)):
        _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
        data = await request.body()
        if not data:
            return JSONResponse({"ok": False, "error": "empty"}, status_code=400)
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return JSONResponse({"ok": False, "error": "invalid image"}, status_code=400)
        stream_manager.set_external_frame(camera_id, frame, data)
        return {"ok": True}

    @application.get("/api/v1/capture/{camera_id}/overlay")
    def capture_overlay(camera_id: int, request: Request, db: Session = Depends(get_db)):
        _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
        det = stream_manager.get_detection(camera_id)
        if not det:
            return {"ok": True, "detection": None}
        if isinstance(det, dict) and not det.get("debug_steps"):
            det["debug_steps"] = _debug_steps_from_paths({
                "color": det.get("debug_color_path"), "bw": det.get("debug_bw_path"),
                "gray": det.get("debug_gray_path"), "edged": det.get("debug_edged_path"),
                "mask": det.get("debug_mask_path"),
            })
        return {"ok": True, "detection": det}

    # ── PTZ control ───────────────────────────────────────────────────────────
    @application.post("/api/v1/ptz/{camera_id}/move")
    def ptz_move(camera_id: int, pan: float = Form(0.0), tilt: float = Form(0.0),
                 zoom: float = Form(0.0), db: Session = Depends(get_db)):
        camera = db.get(Camera, camera_id)
        if not camera:
            return JSONResponse({"ok": False, "error": "camera not found"}, status_code=404)
        ok, err = continuous_move(camera, pan=pan, tilt=tilt, zoom=zoom)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
        return {"ok": True}

    @application.post("/api/v1/ptz/{camera_id}/stop")
    def ptz_stop_route(camera_id: int, db: Session = Depends(get_db)):
        camera = db.get(Camera, camera_id)
        if not camera:
            return JSONResponse({"ok": False, "error": "camera not found"}, status_code=404)
        ok, err = ptz_stop(camera)
        if not ok:
            return JSONResponse({"ok": False, "error": err}, status_code=400)
        return {"ok": True}

    # ── Legacy /admin/* redirect to React frontend ───────────────────────────
    @application.get("/admin", response_class=HTMLResponse)
    @application.get("/admin/{path:path}", response_class=HTMLResponse)
    def admin_redirect(request: Request):
        return _legacy_redirect(request)

    @application.get("/", response_class=HTMLResponse)
    def root_redirect(request: Request):
        return RedirectResponse(f"{_frontend_origin_from_request(request)}/", status_code=307)

    return application


def _seed_default_settings() -> None:
    """Write factory-default AppSettings rows (idempotent — skips existing keys)."""
    defaults = {
        "detector_mode": "contour",
        "max_live_cameras": "16",
        "yolo_conf": "0.25", "yolo_imgsz": "640", "yolo_iou": "0.45", "yolo_max_det": "5",
        "inference_device": "cpu", "ocr_max_width": "1280", "ocr_langs": "en",
        "contour_canny_low": "30", "contour_canny_high": "200",
        "contour_bilateral_d": "11", "contour_bilateral_sigma_color": "17",
        "contour_bilateral_sigma_space": "17", "contour_approx_eps": "0.018",
        "contour_pad_ratio": "0.15", "contour_pad_min": "18",
        "train_model": "yolo26n.pt", "train_epochs": "50", "train_imgsz": "640",
        "train_batch": "-1", "train_device": "auto", "train_patience": "15",
        "train_hsv_h": "0.015", "train_hsv_s": "0.7", "train_hsv_v": "0.4",
        "train_degrees": "5.0", "train_translate": "0.1", "train_scale": "0.5",
        "train_shear": "2.0", "train_perspective": "0.0005",
        "train_fliplr": "0.5", "train_mosaic": "0.5", "train_mixup": "0.1",
        "plate_region": "generic", "plate_min_length": "5", "plate_max_length": "8",
        "plate_charset": "alnum", "plate_pattern_regex": "", "plate_shape_hint": "standard",
        "plate_reference_date": "", "ocr_char_map": "{}",
        "allowed_stationary_enabled": "1", "allowed_stationary_motion_threshold": "7.0",
        "allowed_stationary_hold_seconds": "0",
        "train_chunk_size": "1000", "train_chunk_epochs": "8",
        "train_new_only_default": "1", "train_nightly_enabled": "1",
        "train_nightly_hour": "0", "train_nightly_minute": "0",
        "train_schedule_tz": "America/Toronto", "train_nightly_last_date": "",
    }
    with SessionLocal() as db:
        for key, value in defaults.items():
            if not db.get(AppSetting, key):
                db.add(AppSetting(key=key, value=value))
        # Migrate legacy train model name
        setting = db.get(AppSetting, "train_model")
        if setting and str(setting.value or "").strip() == "yolov8n.pt":
            setting.value = "yolo26n.pt"
        # Speed-up legacy cameras with slow scan_interval
        from models import Camera as CameraModel
        db.query(CameraModel).filter(CameraModel.scan_interval >= 1.0).update(
            {CameraModel.scan_interval: 0.15}, synchronize_session=False
        )
        db.commit()
        _refresh_anpr_config(db)


# ═══════════════════════════════════════════════════════════════════════════════
# App instance (consumed by uvicorn)
# ═══════════════════════════════════════════════════════════════════════════════

app = create_app()
