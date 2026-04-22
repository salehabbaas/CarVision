import os
import re
import json
import subprocess
import threading
import time
import secrets
import shutil
import zipfile
import ipaddress
import socket
import signal
import sys
import tempfile
from io import BytesIO
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Tuple, Dict, Callable
from urllib.parse import quote_plus, urlparse
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

import cv2
import numpy as np
import jwt
from fastapi import Depends, FastAPI, Form, Request, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse, StreamingResponse, JSONResponse, FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_, func, case
from sqlalchemy.exc import IntegrityError
from starlette.middleware.sessions import SessionMiddleware

from api.schemas import (
    ApiAllowedPlateBody,
    ApiBulkFeedbackBody,
    ApiBulkIdsBody,
    ApiCameraCreateBody,
    ApiCameraPatchBody,
    ApiCameraTestBody,
    ApiDiscoveryResolveBody,
    ApiLayoutBody,
    ApiClipControlBody,
    ApiLoginBody,
    ApiModelTestBody,
    ApiTrainingSettingsBody,
    ApiTrainingAnnotateBody,
    ApiTrainingIgnoreBody,
    ApiTrainingSampleIdsBody,
    ApiTrainingStartBody,
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
    FRONTEND_PUBLIC_BASE_URL,
    FRONTEND_PUBLIC_PORT,
    FRONTEND_PUBLIC_SCHEME,
    MEDIA_DIR,
    PROJECT_ROOT,
    PUBLIC_BASE_URL,
)
from db import Base, engine, get_db, ensure_schema, SessionLocal
from models import AllowedPlate, Camera, Detection, AppSetting, TrainingSample, Notification, ClipRecord, TrainingJob
from onvif_discovery import discover_onvif, resolve_rtsp_for_xaddr
from onvif_ptz import continuous_move, stop as ptz_stop
from plate_detector import detect_plate, reload_yolo_model
from services.dataset import (
    bbox_to_xywh as _bbox_to_xywh,
    bbox_xywh_to_xyxy as _bbox_xywh_to_xyxy,
    build_yolo_dataset as _build_yolo_dataset,
    copy_training_image as _copy_training_image,
    extract_yolo_bbox as _extract_yolo_bbox,
    extract_yolo_bboxes as _extract_yolo_bboxes,
    is_image_filename as _is_image_filename,
    load_image_size as _load_image_size,
    zip_label_candidates as _zip_label_candidates,
    build_yolo_dataset_for_sample_ids as _build_yolo_dataset_for_sample_ids,
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
from services.camera_edit import (
    apply_camera_patch as _apply_camera_patch,
    normalize_camera_source as _normalize_camera_source_service,
    validate_camera_type as _validate_camera_type,
    validate_detector_mode as _validate_detector_mode,
)
from services.state import (
    cleanup_upload_jobs as _cleanup_upload_jobs,
    create_upload_job as _create_upload_job,
    get_training_status as _get_training_status,
    get_upload_job as _get_upload_job,
    get_latest_ocr_job_id as _get_latest_ocr_job_id,
    set_latest_ocr_job as _set_latest_ocr_job,
    set_training_status as _set_training_status,
    update_upload_job as _update_upload_job,
)
from anpr import read_plate_text, crop_from_bbox, set_anpr_config
from stream_manager import StreamManager


class ManualClipManager:
    def __init__(self, media_dir: str, stream_manager: StreamManager):
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.stream_manager = stream_manager
        self._lock = threading.Lock()
        self._sessions: Dict[int, Dict] = {}

    def start(self, camera: Camera) -> Dict[str, object]:
        with self._lock:
            current = self._sessions.get(camera.id)
            if current and current.get("running"):
                return {"ok": True, "already_running": True, "camera_id": camera.id}

            started_at = datetime.utcnow()
            ts = started_at.strftime("%Y%m%d_%H%M%S")
            token = secrets.token_hex(4)
            rel_path = f"clips/{camera.id}_{ts}_{token}.mp4"
            abs_path = self.media_dir / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)

            stop_event = threading.Event()
            session = {
                "camera_id": camera.id,
                "camera_type": camera.type,
                "source": camera.source,
                "started_at": started_at,
                "file_path": rel_path,
                "abs_path": abs_path,
                "stop_event": stop_event,
                "running": True,
                "frames": 0,
                "fps": 10.0,
                "writer_started": False,
                "stopped_at": None,
            }

            def run():
                writer = None
                fps = float(session["fps"])
                frame_interval = 1.0 / max(1.0, fps)
                try:
                    while not stop_event.is_set():
                        frame = self.stream_manager.get_frame(camera.id, camera.type, camera.source)
                        if frame is None:
                            time.sleep(0.03)
                            continue
                        if writer is None:
                            height, width = frame.shape[:2]
                            writer = cv2.VideoWriter(
                                str(abs_path),
                                cv2.VideoWriter_fourcc(*"mp4v"),
                                fps,
                                (width, height),
                            )
                            session["writer_started"] = True
                        writer.write(frame)
                        session["frames"] += 1
                        time.sleep(frame_interval)
                finally:
                    if writer is not None:
                        writer.release()
                    session["running"] = False
                    session["stopped_at"] = datetime.utcnow()

            thread = threading.Thread(target=run, daemon=True)
            session["thread"] = thread
            self._sessions[camera.id] = session
            thread.start()
            return {"ok": True, "already_running": False, "camera_id": camera.id, "file_path": rel_path}

    def stop(self, camera_id: int) -> Optional[Dict[str, object]]:
        with self._lock:
            session = self._sessions.get(camera_id)
            if not session:
                return None
            session["stop_event"].set()
            thread = session.get("thread")
        if thread:
            thread.join(timeout=8)
        with self._lock:
            self._sessions.pop(camera_id, None)

        abs_path = Path(session["abs_path"])
        frames = int(session.get("frames") or 0)
        if not session.get("writer_started") or frames <= 0:
            try:
                abs_path.unlink(missing_ok=True)
            except Exception:
                pass
            return {
                "ok": False,
                "camera_id": camera_id,
                "error": "No frames captured",
                "started_at": session.get("started_at"),
                "ended_at": session.get("stopped_at") or datetime.utcnow(),
            }

        ended_at = session.get("stopped_at") or datetime.utcnow()
        started_at = session.get("started_at") or ended_at
        duration = max(0.0, (ended_at - started_at).total_seconds())
        size_bytes = abs_path.stat().st_size if abs_path.exists() else 0
        return {
            "ok": True,
            "camera_id": camera_id,
            "file_path": session.get("file_path"),
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration,
            "size_bytes": int(size_bytes),
        }

    def active(self) -> List[Dict[str, object]]:
        with self._lock:
            rows = []
            for camera_id, session in self._sessions.items():
                if not session.get("running"):
                    continue
                rows.append(
                    {
                        "camera_id": camera_id,
                        "file_path": session.get("file_path"),
                        "started_at": session.get("started_at"),
                        "frames": int(session.get("frames") or 0),
                    }
                )
            return rows

    def stop_all(self):
        for active in list(self.active()):
            self.stop(int(active["camera_id"]))


app = FastAPI(title="CarVision by SpinelTech")

app.add_middleware(
    CORSMiddleware,
    allow_origins=API_CORS_ORIGINS if API_CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=MEDIA_DIR), name="media")


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


def _legacy_ui_target_path(path: str) -> str:
    if path == "/admin":
        return "/"
    if path.startswith("/admin/"):
        return "/" + path[len("/admin/") :]
    return path


def _legacy_ui_redirect(request: Request) -> RedirectResponse:
    target = f"{_frontend_origin_from_request(request)}{_legacy_ui_target_path(request.url.path)}"
    if request.url.query:
        target = f"{target}?{request.url.query}"
    return RedirectResponse(target, status_code=307)


class _LegacyUiRemovedTemplates:
    @staticmethod
    def TemplateResponse(_template_name: str, context: Dict[str, object]):
        request = context.get("request")
        if isinstance(request, Request):
            return _legacy_ui_redirect(request)
        return JSONResponse({"error": "legacy frontend removed"}, status_code=410)


templates = _LegacyUiRemovedTemplates()

stream_manager = StreamManager()
manual_clip_manager = ManualClipManager(media_dir=MEDIA_DIR, stream_manager=stream_manager)
camera_manager = CameraManager(media_dir=MEDIA_DIR, stream_manager=stream_manager)
API_TOKEN_SCHEME = HTTPBearer(auto_error=False)
LIVE_STREAM_JPEG_PARAMS = [int(cv2.IMWRITE_JPEG_QUALITY), 82]
TRAIN_PIPELINE_LOCK = threading.Lock()
TRAIN_PIPELINE_THREAD: Optional[threading.Thread] = None
TRAIN_PIPELINE_STOP = threading.Event()
TRAIN_PIPELINE_PROC_LOCK = threading.Lock()
TRAIN_PIPELINE_PROC: Optional[subprocess.Popen] = None
TRAIN_PIPELINE_STALL_TIMEOUT_SECONDS = int(os.getenv("TRAIN_PIPELINE_STALL_TIMEOUT_SECONDS", "1800") or "1800")
TRAIN_SCHEDULER_LOCK = threading.Lock()
TRAIN_SCHEDULER_THREAD: Optional[threading.Thread] = None
TRAIN_SCHEDULER_STOP = threading.Event()


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _job_payload(job: Optional[TrainingJob]) -> Dict[str, object]:
    if not job:
        return {
            "id": None,
            "status": "idle",
            "mode": None,
            "stage": "idle",
            "progress": 0,
            "message": "Idle",
            "total_samples": 0,
            "trained_samples": 0,
            "ocr_scanned": 0,
            "ocr_updated": 0,
            "chunk_size": 0,
            "chunk_index": 0,
            "chunk_total": 0,
            "run_dir": None,
            "model_path": None,
            "details": {},
            "error": None,
            "started_at": None,
            "updated_at": None,
            "finished_at": None,
            "run_started_at": None,
        }
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "mode": job.mode,
        "stage": job.stage,
        "progress": int(max(0.0, min(100.0, float(job.progress or 0.0)))),
        "message": job.message or "",
        "total_samples": int(job.total_samples or 0),
        "trained_samples": int(job.trained_samples or 0),
        "ocr_scanned": int(job.ocr_scanned or 0),
        "ocr_updated": int(job.ocr_updated or 0),
        "chunk_size": int(job.chunk_size or 0),
        "chunk_index": int(job.chunk_index or 0),
        "chunk_total": int(job.chunk_total or 0),
        "run_dir": job.run_dir,
        "model_path": job.model_path,
        "details": job.details or {},
        "error": job.error,
        "run_started_at": job.run_started_at.isoformat() if job.run_started_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


def _job_duration_seconds(job: TrainingJob) -> Optional[float]:
    start = job.run_started_at or job.started_at
    if not start:
        return None
    end = job.finished_at or datetime.utcnow()
    try:
        return max(0.0, float((end - start).total_seconds()))
    except Exception:
        return None


def _job_history_payload(job: TrainingJob) -> Dict[str, object]:
    payload = _job_payload(job)
    payload["duration_seconds"] = _job_duration_seconds(job)
    return payload


def _append_training_job_log(job: TrainingJob, message: str) -> None:
    details = dict(job.details or {})
    logs = details.get("logs")
    if not isinstance(logs, list):
        logs = []
    ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    logs.append(f"[{ts}] {message}")
    details["logs"] = logs[-120:]
    job.details = details


def _latest_training_job(db: Session) -> Optional[TrainingJob]:
    return (
        db.query(TrainingJob)
        .filter(TrainingJob.kind == "pipeline")
        .order_by(TrainingJob.started_at.desc(), TrainingJob.id.desc())
        .first()
    )


def _active_training_job(db: Session) -> Optional[TrainingJob]:
    return (
        db.query(TrainingJob)
        .filter(TrainingJob.kind == "pipeline", TrainingJob.status.in_(("queued", "running")))
        .order_by(TrainingJob.started_at.desc(), TrainingJob.id.desc())
        .first()
    )


def _touch_training_job(
    db: Session,
    job: TrainingJob,
    *,
    status: Optional[str] = None,
    stage: Optional[str] = None,
    progress: Optional[float] = None,
    message: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    if status is not None:
        job.status = status
    if stage is not None:
        job.stage = stage
    if progress is not None:
        try:
            job.progress = max(0.0, min(100.0, float(progress)))
        except Exception:
            pass
    if message is not None:
        job.message = str(message)[:600]
        _append_training_job_log(job, job.message)
        _set_training_status(job.status or "running", job.message, run_dir=job.run_dir, model_path=job.model_path)
    if error is not None:
        job.error = str(error)[:2000]
    if (job.status or "") in {"complete", "failed", "stopped"}:
        # Clear ephemeral runtime-only activity details when a run is no longer active.
        details = dict(job.details or {})
        if "backend" in details:
            details.pop("backend", None)
            job.details = details
    job.updated_at = datetime.utcnow()
    if (job.status or "") in {"complete", "failed", "stopped"} and not job.finished_at:
        job.finished_at = datetime.utcnow()
    db.add(job)
    db.commit()


def _set_training_proc(proc: Optional[subprocess.Popen]) -> None:
    global TRAIN_PIPELINE_PROC
    with TRAIN_PIPELINE_PROC_LOCK:
        TRAIN_PIPELINE_PROC = proc


def _stop_training_proc(force: bool = False) -> bool:
    with TRAIN_PIPELINE_PROC_LOCK:
        proc = TRAIN_PIPELINE_PROC
    if not proc or proc.poll() is not None:
        return False
    try:
        if force:
            os.killpg(proc.pid, signal.SIGKILL)
        else:
            os.killpg(proc.pid, signal.SIGTERM)
        return True
    except Exception:
        try:
            if force:
                proc.kill()
            else:
                proc.terminate()
            return True
        except Exception:
            return False


def _resume_pipeline_if_needed() -> None:
    try:
        with SessionLocal() as db:
            active = _active_training_job(db)
            if active:
                _start_training_pipeline_thread(active.id)
    except Exception:
        pass


def _training_scheduler_loop() -> None:
    while not TRAIN_SCHEDULER_STOP.is_set():
        try:
            with SessionLocal() as db:
                enabled = _as_bool(_get_app_setting(db, "train_nightly_enabled", "1"), True)
                if enabled:
                    try:
                        hh = max(0, min(23, int(_get_app_setting(db, "train_nightly_hour", "0") or "0")))
                    except Exception:
                        hh = 0
                    try:
                        mm = max(0, min(59, int(_get_app_setting(db, "train_nightly_minute", "0") or "0")))
                    except Exception:
                        mm = 0
                    tz_name = (_get_app_setting(db, "train_schedule_tz", "America/Toronto") or "America/Toronto").strip()
                    try:
                        now_local = datetime.now(ZoneInfo(tz_name))
                    except Exception:
                        now_local = datetime.utcnow()
                        tz_name = "UTC"
                    today = now_local.strftime("%Y-%m-%d")
                    last_day = _get_app_setting(db, "train_nightly_last_date", "")
                    if now_local.hour == hh and now_local.minute == mm and last_day != today:
                        result = _start_training_pipeline_from_request(db, mode="new_only", trigger="nightly")
                        _set_app_setting(db, "train_nightly_last_date", today)
                        db.commit()
                        if result.get("ok"):
                            try:
                                _create_notification(
                                    db,
                                    title="Nightly training started",
                                    message=f"Nightly job started ({tz_name} {hh:02d}:{mm:02d})",
                                    level="info",
                                    kind="training",
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
        "unclear_plate": bool(getattr(row, "unclear_plate", False)),
        "ignored": bool(row.ignored),
        "import_batch": row.import_batch,
        "processed_at": row.processed_at.isoformat() if getattr(row, "processed_at", None) else None,
        "processed": bool(getattr(row, "processed_at", None)),
        "last_trained_at": row.last_trained_at.isoformat() if row.last_trained_at else None,
        "trained": bool(row.last_trained_at),
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


def _get_browser_camera_by_token(camera_id: int, token: Optional[str], db: Session) -> Camera:
    camera = db.get(Camera, camera_id)
    if not camera or camera.type != "browser":
        raise HTTPException(status_code=404, detail="Camera not found")
    _ensure_capture_token(camera, db)
    if not token or token != camera.capture_token:
        raise HTTPException(status_code=403, detail="Invalid token")
    return camera


def _public_urls(request: Request):
    base = PUBLIC_BASE_URL or str(request.base_url)
    if not base.endswith("/"):
        base += "/"
    https_base = base
    if base.startswith("http://"):
        https_base = "https://" + base[len("http://") :]
    return base, https_base


def _frontend_capture_url(request: Request, camera_id: int, token: str) -> str:
    token_q = quote_plus(token or "")
    if FRONTEND_PUBLIC_BASE_URL:
        return f"{FRONTEND_PUBLIC_BASE_URL.rstrip('/')}/capture/{camera_id}?token={token_q}"
    if PUBLIC_BASE_URL:
        return f"{PUBLIC_BASE_URL.rstrip('/')}/capture/{camera_id}?token={token_q}"
    try:
        parsed = urlparse(str(request.base_url).rstrip("/"))
        host = parsed.hostname or request.url.hostname or "localhost"
        scheme = FRONTEND_PUBLIC_SCHEME if FRONTEND_PUBLIC_SCHEME in {"http", "https"} else "http"
        port = FRONTEND_PUBLIC_PORT or ("443" if scheme == "https" else "80")
        if (scheme == "http" and port == "80") or (scheme == "https" and port == "443"):
            netloc = host
        else:
            netloc = f"{host}:{port}"
        return f"{scheme}://{netloc}/capture/{camera_id}?token={token_q}"
    except Exception:
        return f"/capture/{camera_id}?token={token_q}"


def _normalize_camera_source(camera_type: str, source: str) -> str:
    return _normalize_camera_source_service(camera_type, source)


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
    if path.startswith("/admin/api"):
        if not request.session.get("user"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
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
            "inference_device": "cpu",
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
            "train_model": "yolo26n.pt",
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
            "plate_region": "generic",
            "plate_min_length": "5",
            "plate_max_length": "8",
            "plate_charset": "alnum",
            "plate_pattern_regex": "",
            "plate_shape_hint": "standard",
            "plate_reference_date": "",
            "ocr_char_map": "{}",
            "allowed_stationary_enabled": "1",
            "allowed_stationary_motion_threshold": "7.0",
            "allowed_stationary_hold_seconds": "0",
            "train_chunk_size": "1000",
            "train_chunk_epochs": "8",
            "train_new_only_default": "1",
            "train_nightly_enabled": "1",
            "train_nightly_hour": "0",
            "train_nightly_minute": "0",
            "train_schedule_tz": "America/Toronto",
            "train_nightly_last_date": "",
        }
        for key, value in defaults.items():
            if not db.get(AppSetting, key):
                db.add(AppSetting(key=key, value=value))
        train_model_setting = db.get(AppSetting, "train_model")
        if train_model_setting and str(train_model_setting.value or "").strip() == "yolov8n.pt":
            train_model_setting.value = "yolo26n.pt"
        # Migrate cameras that still have the old 1.0s scan_interval default
        # to the faster 0.15s value so detection works at real-time speed.
        db.query(Camera).filter(Camera.scan_interval >= 1.0).update(
            {Camera.scan_interval: 0.15}, synchronize_session=False
        )
        db.commit()
        _refresh_anpr_config(db)
    camera_manager.start()
    _resume_pipeline_if_needed()
    _start_training_scheduler()


@app.on_event("shutdown")
def on_shutdown():
    camera_manager.stop()
    manual_clip_manager.stop_all()
    TRAIN_PIPELINE_STOP.set()
    _stop_training_proc(force=False)
    TRAIN_SCHEDULER_STOP.set()


@app.get("/", response_class=HTMLResponse)
def root(request: Request):
    return _legacy_ui_redirect(request)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "error": None})


@app.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if username == ADMIN_USER and password == ADMIN_PASS:
        request.session["user"] = username
        return _legacy_ui_redirect(request)
    return JSONResponse({"error": "invalid credentials"}, status_code=401)


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
    return RedirectResponse(_frontend_capture_url(request, camera_id, token), status_code=302)


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
    try:
        _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
    except HTTPException as exc:
        return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)

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
    try:
        _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
    except HTTPException as exc:
        return JSONResponse({"ok": False, "error": exc.detail}, status_code=exc.status_code)

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


@app.get("/capture/{camera_id}/session")
def capture_session(camera_id: int, request: Request, db: Session = Depends(get_db)):
    camera = _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
    return {
        "ok": True,
        "camera": {
            "id": camera.id,
            "name": camera.name,
            "location": camera.location,
            "online": stream_manager.is_external_online(camera.id),
        },
    }


@app.get("/api/v1/capture/{camera_id:int}")
def api_v1_capture_session(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    camera = _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
    return {
        "ok": True,
        "camera": {
            "id": camera.id,
            "name": camera.name,
            "location": camera.location,
            "online": stream_manager.is_external_online(camera.id),
        },
    }


@app.post("/api/v1/capture/{camera_id:int}/ingest")
async def api_v1_capture_ingest(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    camera = _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
    del camera

    data = await request.body()
    if not data:
        return JSONResponse({"ok": False, "error": "empty"}, status_code=400)

    frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return JSONResponse({"ok": False, "error": "invalid image"}, status_code=400)

    stream_manager.set_external_frame(camera_id, frame, data)
    return {"ok": True}


@app.get("/api/v1/capture/{camera_id:int}/overlay")
def api_v1_capture_overlay(
    camera_id: int,
    request: Request,
    db: Session = Depends(get_db),
):
    camera = _get_browser_camera_by_token(camera_id, request.query_params.get("token"), db)
    del camera

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


def _clip_record_payload(row: ClipRecord, camera_name: Optional[str] = None) -> Dict[str, object]:
    return {
        "id": row.id,
        "camera_id": row.camera_id,
        "camera_name": camera_name,
        "kind": row.kind,
        "file_path": row.file_path,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_seconds": row.duration_seconds,
        "size_bytes": row.size_bytes,
        "detection_count": row.detection_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _clip_abs_path(rel_path: Optional[str]) -> Optional[Path]:
    if not rel_path:
        return None
    clean = str(rel_path).replace("\\", "/").lstrip("/")
    if clean.startswith("media/"):
        clean = clean[len("media/") :]
    return Path(MEDIA_DIR) / clean


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
        age = (now - last_ok) if last_ok else None
        reason = None
        online = bool(last_ok and age is not None and age <= 5.0)
        if cam.type == "webcam":
            try:
                webcam_idx = int(cam.source)
            except Exception:
                webcam_idx = 0
            if not Path(f"/dev/video{webcam_idx}").exists():
                online = False
                reason = f"webcam /dev/video{webcam_idx} not found"
        elif cam.type == "browser" and not stream_manager.is_external_online(cam.id):
            online = False
            reason = "waiting for phone stream"
        items[cam.id] = {
            "last_ok": last_ok,
            "age": age,
            "online": online,
            "reason": reason,
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
    scan_interval: float = Form(0.15),
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
    detector_mode = _validate_detector_mode(detector_mode or "inherit")
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
    scan_interval: float = Form(0.15),
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
    detector_mode = _validate_detector_mode(detector_mode or "inherit")
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
            "saved": request.query_params.get("saved") == "1",
            "detector_mode": detector.value if detector else "contour",
            "max_live": max_live.value if max_live else "16",
            "inference_device": _get("inference_device", "cpu"),
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
    detector_mode = detector_mode.lower()
    if detector_mode not in {"auto", "contour", "yolo"}:
        detector_mode = "contour"
    inference_device = str(inference_device or "cpu").strip().lower()
    if inference_device not in {"cpu", "gpu"}:
        inference_device = "cpu"
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

    _save_setting("inference_device", inference_device)
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
    _refresh_anpr_config(db)
    return RedirectResponse("/admin/settings?saved=1", status_code=303)


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
        scan_interval=0.15,
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


def _apply_plate_policy(
    plate_text: str,
    min_len: int,
    max_len: int,
    charset: str,
    pattern_regex: str,
) -> str:
    out = "".join(ch for ch in str(plate_text or "").upper() if ch.isalnum())
    if charset == "digits":
        out = "".join(ch for ch in out if ch.isdigit())
    elif charset == "letters":
        out = "".join(ch for ch in out if ch.isalpha())
    if len(out) < min_len:
        return out
    if len(out) > max_len:
        out = out[:max_len]
    if pattern_regex:
        try:
            if not re.fullmatch(pattern_regex, out):
                return out
        except re.error:
            pass
    return out


def _match_known_plate(db: Session, plate_text: str) -> Tuple[str, Optional[float]]:
    try:
        min_len = int(_get_app_setting(db, "plate_min_length", "5"))
    except Exception:
        min_len = 5
    try:
        max_len = int(_get_app_setting(db, "plate_max_length", "8"))
    except Exception:
        max_len = 8
    if min_len > max_len:
        min_len, max_len = max_len, min_len
    charset = _get_app_setting(db, "plate_charset", "alnum").strip().lower()
    if charset not in {"alnum", "digits", "letters"}:
        charset = "alnum"
    pattern_regex = _get_app_setting(db, "plate_pattern_regex", "").strip()

    normalized = _apply_plate_policy(plate_text, min_len=min_len, max_len=max_len, charset=charset, pattern_regex=pattern_regex)
    if len(normalized) < min_len:
        return normalized, None
    candidates = _known_plate_candidates(db)
    if not candidates:
        return normalized, None
    candidates = [_apply_plate_policy(c, min_len=min_len, max_len=max_len, charset=charset, pattern_regex=pattern_regex) for c in candidates]
    candidates = [c for c in candidates if c and len(c) >= min_len]
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


def _parse_discovery_subnets(raw_value: Optional[str]) -> Tuple[List[object], List[str]]:
    if not raw_value:
        return [], []
    networks: List[object] = []
    invalid: List[str] = []
    for token in str(raw_value).split(","):
        item = token.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except Exception:
            invalid.append(item)
    return networks, invalid


def _xaddr_host_port(xaddr: str) -> Tuple[Optional[str], Optional[int]]:
    try:
        parsed = urlparse(str(xaddr))
    except Exception:
        return None, None
    host = parsed.hostname
    if not host:
        return None, None
    if parsed.port:
        return host, int(parsed.port)
    return host, 443 if parsed.scheme == "https" else 80


def _host_in_subnets(host: str, subnets: List[object]) -> bool:
    if not subnets:
        return True
    try:
        ip_value = ipaddress.ip_address(host)
    except Exception:
        return False
    return any(ip_value in net for net in subnets)


def _probe_tcp_port(host: str, port: int, timeout: float = 0.35) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            return sock.connect_ex((host, int(port))) == 0
    except Exception:
        return False


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


def _set_app_setting(db: Session, key: str, value: str) -> None:
    setting = db.get(AppSetting, key)
    if not setting:
        setting = AppSetting(key=key, value=value)
        db.add(setting)
    else:
        setting.value = value


def _batch_ocr_job_key(batch_id: str) -> str:
    return f"batch_ocr_job:{(batch_id or '').strip()[:80]}"


def _batch_ocr_stop_key(batch_id: str) -> str:
    return f"batch_ocr_stop:{(batch_id or '').strip()[:80]}"


def _utc_iso_now() -> str:
    return datetime.utcnow().isoformat()


def _parse_iso_datetime(value: object) -> Optional[datetime]:
    if not value:
        return None
    txt = str(value).strip()
    if not txt:
        return None
    try:
        return datetime.fromisoformat(txt.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        return None


def _batch_ocr_stop_requested(db: Session, batch_id: str) -> bool:
    return _as_bool(_get_app_setting(db, _batch_ocr_stop_key(batch_id), "0"), False)


def _set_batch_ocr_stop(db: Session, batch_id: str, value: bool) -> None:
    _set_app_setting(db, _batch_ocr_stop_key(batch_id), "1" if value else "0")


def _finalize_batch_ocr_job_view(
    db: Session,
    batch_id: str,
    data: Dict[str, object],
    *,
    persist_if_stale: bool = True,
) -> Dict[str, object]:
    status = str(data.get("status") or "").strip().lower()
    started_at = _parse_iso_datetime(data.get("started_at"))
    updated_at = _parse_iso_datetime(data.get("updated_at"))
    finished_at = _parse_iso_datetime(data.get("finished_at"))
    processed = int(data.get("processed") or 0)
    total = max(0, int(data.get("total") or 0))
    stale_seconds = None
    now = datetime.utcnow()
    if updated_at:
        stale_seconds = max(0, int((now - updated_at).total_seconds()))
    if status in {"running", "stopping"} and stale_seconds is not None and stale_seconds >= 180:
        data["status"] = "stale"
        data["message"] = (str(data.get("message") or "").strip() or "No heartbeat from worker")
        data["error"] = str(data.get("error") or "").strip() or "Worker heartbeat stale"
        if persist_if_stale:
            _write_batch_ocr_job(db, batch_id, data)
            db.commit()
    if started_at and (status in {"running", "stopping", "stale"} or not finished_at):
        elapsed = max(1.0, (now - started_at).total_seconds())
    elif started_at and finished_at:
        elapsed = max(1.0, (finished_at - started_at).total_seconds())
    else:
        elapsed = None
    speed_sps = None
    eta_seconds = None
    if elapsed and processed > 0:
        speed_sps = round(float(processed) / float(elapsed), 3)
        if total > processed and speed_sps > 0:
            eta_seconds = int((total - processed) / speed_sps)
    data["stale_seconds"] = stale_seconds
    data["speed_sps"] = speed_sps
    data["eta_seconds"] = eta_seconds
    return data


def _get_batch_ocr_job(db: Session, batch_id: str) -> Optional[Dict[str, object]]:
    key = _batch_ocr_job_key(batch_id)
    raw = _get_app_setting(db, key, "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _finalize_batch_ocr_job_view(db, batch_id, data, persist_if_stale=True)


def _write_batch_ocr_job(db: Session, batch_id: str, payload: Dict[str, object]) -> None:
    compact = {
        "id": str(payload.get("id") or ""),
        "batch": str(payload.get("batch") or batch_id),
        "status": str(payload.get("status") or "unknown"),
        "progress": int(max(0, min(100, int(payload.get("progress") or 0)))),
        "processed": int(payload.get("processed") or 0),
        "updated": int(payload.get("updated") or 0),
        "skipped": int(payload.get("skipped") or 0),
        "total": int(payload.get("total") or 0),
        "chunk_size": int(payload.get("chunk_size") or 1000),
        "message": str(payload.get("message") or "")[:160],
        "started_at": str(payload.get("started_at") or ""),
        "updated_at": str(payload.get("updated_at") or ""),
        "heartbeat_at": str(payload.get("heartbeat_at") or payload.get("updated_at") or ""),
        "finished_at": str(payload.get("finished_at") or ""),
        "error": str(payload.get("error") or "")[:180],
        "last_id": int(payload.get("last_id") or 0),
        "chunk_index": int(payload.get("chunk_index") or 0),
        "chunk_total": int(payload.get("chunk_total") or 0),
        "speed_sps": float(payload.get("speed_sps") or 0),
        "eta_seconds": int(payload.get("eta_seconds") or 0),
        "current_sample_id": int(payload.get("current_sample_id") or 0),
        "resumed_from": int(payload.get("resumed_from") or 0),
    }
    # app_settings.value is VARCHAR(500), so keep serialized payload safely under that size.
    compact["message"] = str(compact.get("message") or "")[:80]
    compact["error"] = str(compact.get("error") or "")[:80]
    raw = json.dumps(compact, separators=(",", ":"))
    if len(raw) > 480:
        for key in ("current_sample_id", "eta_seconds", "speed_sps", "resumed_from", "chunk_total", "chunk_index"):
            compact.pop(key, None)
        compact["message"] = str(compact.get("message") or "")[:56]
        compact["error"] = str(compact.get("error") or "")[:56]
        raw = json.dumps(compact, separators=(",", ":"))
    if len(raw) > 480:
        compact["message"] = ""
        compact["error"] = ""
        raw = json.dumps(compact, separators=(",", ":"))
    _set_app_setting(db, _batch_ocr_job_key(batch_id), raw)


def _refresh_anpr_config(db: Session) -> None:
    set_anpr_config(
        {
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
        }
    )


def _training_settings_payload(db: Session) -> Dict[str, str]:
    return {
        "train_model": _get_app_setting(db, "train_model", "yolo26n.pt"),
        "train_epochs": _get_app_setting(db, "train_epochs", "50"),
        "train_imgsz": _get_app_setting(db, "train_imgsz", "640"),
        "train_batch": _get_app_setting(db, "train_batch", "-1"),
        "train_device": _get_app_setting(db, "train_device", "auto"),
        "train_patience": _get_app_setting(db, "train_patience", "15"),
        "plate_region": _get_app_setting(db, "plate_region", "generic"),
        "plate_min_length": _get_app_setting(db, "plate_min_length", "5"),
        "plate_max_length": _get_app_setting(db, "plate_max_length", "8"),
        "plate_charset": _get_app_setting(db, "plate_charset", "alnum"),
        "plate_pattern_regex": _get_app_setting(db, "plate_pattern_regex", ""),
        "plate_shape_hint": _get_app_setting(db, "plate_shape_hint", "standard"),
        "plate_reference_date": _get_app_setting(db, "plate_reference_date", ""),
        "allowed_stationary_enabled": _get_app_setting(db, "allowed_stationary_enabled", "1"),
        "allowed_stationary_motion_threshold": _get_app_setting(db, "allowed_stationary_motion_threshold", "7.0"),
        "allowed_stationary_hold_seconds": _get_app_setting(db, "allowed_stationary_hold_seconds", "0"),
        "train_chunk_size": _get_app_setting(db, "train_chunk_size", "1000"),
        "train_chunk_epochs": _get_app_setting(db, "train_chunk_epochs", "8"),
        "train_new_only_default": _get_app_setting(db, "train_new_only_default", "1"),
        "train_nightly_enabled": _get_app_setting(db, "train_nightly_enabled", "1"),
        "train_nightly_hour": _get_app_setting(db, "train_nightly_hour", "0"),
        "train_nightly_minute": _get_app_setting(db, "train_nightly_minute", "0"),
        "train_schedule_tz": _get_app_setting(db, "train_schedule_tz", "America/Toronto"),
    }


def _sanitize_training_settings(payload: Dict[str, object]) -> Dict[str, str]:
    train_model = str(payload.get("train_model") or "yolo26n.pt").strip() or "yolo26n.pt"
    train_device = str(payload.get("train_device") or "auto").strip() or "auto"
    plate_region = str(payload.get("plate_region") or "generic").strip()[:80] or "generic"
    plate_charset = str(payload.get("plate_charset") or "alnum").strip().lower()
    if plate_charset not in {"alnum", "digits", "letters"}:
        plate_charset = "alnum"
    plate_shape_hint = str(payload.get("plate_shape_hint") or "standard").strip().lower()
    if plate_shape_hint not in {"standard", "long", "square", "motorcycle"}:
        plate_shape_hint = "standard"
    plate_pattern_regex = str(payload.get("plate_pattern_regex") or "").strip()[:200]
    plate_reference_date = str(payload.get("plate_reference_date") or "").strip()[:40]
    raw_stationary_enabled = payload.get("allowed_stationary_enabled", True)
    if isinstance(raw_stationary_enabled, str):
        allowed_stationary_enabled = raw_stationary_enabled.strip().lower() in {"1", "true", "yes", "on"}
    else:
        allowed_stationary_enabled = bool(raw_stationary_enabled)
    try:
        allowed_stationary_motion_threshold = max(
            0.5,
            min(
                50.0,
                float(
                    payload.get("allowed_stationary_motion_threshold")
                    if payload.get("allowed_stationary_motion_threshold") is not None
                    else 7.0
                ),
            ),
        )
    except Exception:
        allowed_stationary_motion_threshold = 7.0
    try:
        allowed_stationary_hold_seconds = max(
            0.0,
            min(
                3600.0,
                float(
                    payload.get("allowed_stationary_hold_seconds")
                    if payload.get("allowed_stationary_hold_seconds") is not None
                    else 0.0
                ),
            ),
        )
    except Exception:
        allowed_stationary_hold_seconds = 0.0

    try:
        plate_min_length = max(1, min(12, int(payload.get("plate_min_length") if payload.get("plate_min_length") is not None else 5)))
    except Exception:
        plate_min_length = 5
    try:
        plate_max_length = max(1, min(16, int(payload.get("plate_max_length") if payload.get("plate_max_length") is not None else 8)))
    except Exception:
        plate_max_length = 8
    if plate_min_length > plate_max_length:
        plate_min_length, plate_max_length = plate_max_length, plate_min_length

    try:
        train_epochs = max(1, int(payload.get("train_epochs") if payload.get("train_epochs") is not None else 50))
    except Exception:
        train_epochs = 50
    try:
        train_imgsz = max(160, int(payload.get("train_imgsz") if payload.get("train_imgsz") is not None else 640))
    except Exception:
        train_imgsz = 640
    try:
        train_batch = int(payload.get("train_batch") if payload.get("train_batch") is not None else -1)
    except Exception:
        train_batch = -1
    try:
        train_patience = max(1, int(payload.get("train_patience") if payload.get("train_patience") is not None else 15))
    except Exception:
        train_patience = 15
    try:
        train_chunk_size = max(100, min(5000, int(payload.get("train_chunk_size") if payload.get("train_chunk_size") is not None else 1000)))
    except Exception:
        train_chunk_size = 1000
    try:
        train_chunk_epochs = max(1, min(50, int(payload.get("train_chunk_epochs") if payload.get("train_chunk_epochs") is not None else 8)))
    except Exception:
        train_chunk_epochs = 8
    raw_new_only = payload.get("train_new_only_default", True)
    if isinstance(raw_new_only, str):
        train_new_only_default = raw_new_only.strip().lower() in {"1", "true", "yes", "on"}
    else:
        train_new_only_default = bool(raw_new_only)
    raw_nightly_enabled = payload.get("train_nightly_enabled", True)
    if isinstance(raw_nightly_enabled, str):
        train_nightly_enabled = raw_nightly_enabled.strip().lower() in {"1", "true", "yes", "on"}
    else:
        train_nightly_enabled = bool(raw_nightly_enabled)
    try:
        train_nightly_hour = max(0, min(23, int(payload.get("train_nightly_hour") if payload.get("train_nightly_hour") is not None else 0)))
    except Exception:
        train_nightly_hour = 0
    try:
        train_nightly_minute = max(0, min(59, int(payload.get("train_nightly_minute") if payload.get("train_nightly_minute") is not None else 0)))
    except Exception:
        train_nightly_minute = 0
    train_schedule_tz = str(payload.get("train_schedule_tz") or "America/Toronto").strip()[:80] or "America/Toronto"
    try:
        ZoneInfo(train_schedule_tz)
    except Exception:
        train_schedule_tz = "America/Toronto"

    return {
        "train_model": train_model,
        "train_epochs": str(train_epochs),
        "train_imgsz": str(train_imgsz),
        "train_batch": str(train_batch),
        "train_device": train_device,
        "train_patience": str(train_patience),
        "plate_region": plate_region,
        "plate_min_length": str(plate_min_length),
        "plate_max_length": str(plate_max_length),
        "plate_charset": plate_charset,
        "plate_pattern_regex": plate_pattern_regex,
        "plate_shape_hint": plate_shape_hint,
        "plate_reference_date": plate_reference_date,
        "allowed_stationary_enabled": "1" if allowed_stationary_enabled else "0",
        "allowed_stationary_motion_threshold": str(allowed_stationary_motion_threshold),
        "allowed_stationary_hold_seconds": str(allowed_stationary_hold_seconds),
        "train_chunk_size": str(train_chunk_size),
        "train_chunk_epochs": str(train_chunk_epochs),
        "train_new_only_default": "1" if train_new_only_default else "0",
        "train_nightly_enabled": "1" if train_nightly_enabled else "0",
        "train_nightly_hour": str(train_nightly_hour),
        "train_nightly_minute": str(train_nightly_minute),
        "train_schedule_tz": train_schedule_tz,
    }


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


def _resolve_train_model_source(model_spec: str) -> str:
    spec = str(model_spec or "").strip()
    if not spec:
        return "yolo26n.pt"
    if spec.startswith(("http://", "https://")):
        return spec
    if Path(spec).exists() or spec.endswith(".pt"):
        return spec

    repo_id = None
    filename = ""
    if spec.startswith("hf://"):
        rest = spec[5:].strip("/")
        parts = rest.split("/")
        if len(parts) >= 2:
            repo_id = f"{parts[0]}/{parts[1]}"
            filename = "/".join(parts[2:]).strip()
    elif re.fullmatch(r"[\w.-]+/[\w.-]+(?::[^:]+)?", spec):
        repo_id, _, filename = spec.partition(":")
        filename = filename.strip()

    if not repo_id:
        return spec

    try:
        from huggingface_hub import HfApi, hf_hub_download
    except Exception as exc:
        raise RuntimeError("Hugging Face model source requires huggingface_hub package.") from exc

    api = HfApi()
    if not filename:
        files = api.list_repo_files(repo_id=repo_id, repo_type="model")
        preferred = [
            "best.pt",
            "weights/best.pt",
            "model.pt",
            "last.pt",
            "weights/last.pt",
        ]
        for candidate in preferred:
            if candidate in files:
                filename = candidate
                break
        if not filename:
            pt_files = [f for f in files if str(f).lower().endswith(".pt")]
            if not pt_files:
                raise RuntimeError(
                    f"No .pt weight file found in Hugging Face repo '{repo_id}'. "
                    "Use repo:filename.pt format."
                )
            filename = pt_files[0]

    local_dir = PROJECT_ROOT / "models" / "hf_cache"
    local_dir.mkdir(parents=True, exist_ok=True)
    return hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        repo_type="model",
        local_dir=str(local_dir),
        local_dir_use_symlinks=False,
    )


def _training_pending_filter(mode: str, run_started_at: datetime):
    if mode == "all":
        return or_(TrainingSample.last_trained_at.is_(None), TrainingSample.last_trained_at < run_started_at)
    return or_(
        TrainingSample.last_trained_at.is_(None),
        and_(
            TrainingSample.processed_at.isnot(None),
            or_(TrainingSample.last_trained_at.is_(None), TrainingSample.last_trained_at < TrainingSample.processed_at),
        ),
    )


def _learn_ocr_corrections_from_db(db: Session) -> Dict[str, object]:
    rows = (
        db.query(TrainingSample)
        .filter(
            TrainingSample.ignored.is_(False),
            TrainingSample.no_plate.is_(False),
            TrainingSample.plate_text.isnot(None),
            TrainingSample.notes.isnot(None),
        )
        .all()
    )

    stats: Dict[str, Dict[str, int]] = {}
    pairs = 0
    for row in rows:
        notes = str(row.notes or "")
        raw = ""
        if "OCR_PREFILL_RAW:" in notes:
            raw = notes.split("OCR_PREFILL_RAW:", 1)[1].splitlines()[0].strip().upper()
        elif "OCR_BATCH_RAW:" in notes:
            raw = notes.split("OCR_BATCH_RAW:", 1)[1].splitlines()[0].strip().upper()
        corrected = str(row.plate_text or "").strip().upper()
        if not raw or not corrected or len(raw) != len(corrected):
            continue
        pairs += 1
        for a, b in zip(raw, corrected):
            if not a.isalnum() or not b.isalnum():
                continue
            bucket = stats.setdefault(a, {})
            bucket[b] = bucket.get(b, 0) + 1

    learned: Dict[str, str] = {}
    for src, targets in stats.items():
        best_char = src
        best_count = 0
        for dst, count in targets.items():
            if count > best_count:
                best_count = count
                best_char = dst
        if best_char != src and best_count >= 2:
            learned[src] = best_char

    setting = db.get(AppSetting, "ocr_char_map")
    if not setting:
        setting = AppSetting(key="ocr_char_map", value="{}")
        db.add(setting)
    setting.value = json.dumps(learned, separators=(",", ":"))
    db.commit()
    _refresh_anpr_config(db)
    return {"pairs": pairs, "learned_map": learned, "replacements": len(learned)}


def _compact_training_error_text(raw: object, fallback: str = "Training process failed") -> str:
    text = str(raw or "").replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines() if line and line.strip()]
    if not lines:
        return fallback

    cleaned: List[str] = []
    for line in lines:
        lowered = line.lower()
        # Drop tqdm/progress-bar noise and repetitive transfer meter lines.
        if (
            "complete" in lowered and "|" in line and "%" in line
        ) or (
            "<?, ?b/s]" in lowered
        ) or (
            "/s]" in lowered and "%" in lowered and "|" in line
        ):
            continue
        # Drop generic deprecation/future warnings from the user-facing status.
        if "futurewarning:" in lowered or "deprecationwarning:" in lowered:
            continue
        cleaned.append(line)

    if not cleaned:
        return fallback

    preferred = None
    for line in reversed(cleaned):
        lowered = line.lower()
        if any(token in lowered for token in ("error", "exception", "failed", "not found", "no module named", "out of memory")):
            preferred = line
            break
    message = preferred or cleaned[-1]
    message = re.sub(r"\s+", " ", message).strip(" :-")
    if len(message) > 220:
        message = f"{message[:217]}..."
    return message or fallback


def _train_chunk_with_yolo(
    *,
    data_yaml: str,
    run_root: Path,
    model_source: str,
    run_name: str,
    epochs: int,
    imgsz: int,
    batch: int,
    device: str,
    patience: int,
    aug: Dict[str, float],
    stop_event: Optional[threading.Event] = None,
    heartbeat: Optional[Callable[[int, int], None]] = None,
) -> Tuple[Path, Path]:
    worker = Path(__file__).resolve().parent / "services" / "yolo_train_worker.py"
    with tempfile.NamedTemporaryFile(prefix="carvision_train_", suffix=".json", delete=False) as fh:
        result_path = Path(fh.name)
    cmd = [
        sys.executable,
        str(worker),
        "--data-yaml", str(data_yaml),
        "--run-root", str(run_root),
        "--model-source", str(model_source),
        "--run-name", str(run_name),
        "--epochs", str(int(epochs)),
        "--imgsz", str(int(imgsz)),
        "--batch", str(int(batch)),
        "--device", str(device),
        "--patience", str(int(patience)),
        "--aug-json", json.dumps(aug, separators=(",", ":")),
        "--result-json", str(result_path),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    _set_training_proc(proc)
    started_at = time.time()
    stall_timeout = max(300, int(TRAIN_PIPELINE_STALL_TIMEOUT_SECONDS or 1800))
    result_csv = Path(run_root) / str(run_name) / "results.csv"
    last_progress_at = started_at
    last_results_mtime = None
    last_beat = 0.0
    try:
        while proc.poll() is None:
            if stop_event and stop_event.is_set():
                _stop_training_proc(force=False)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _stop_training_proc(force=True)
                raise InterruptedError("Training stop requested by admin")
            now = time.time()
            if result_csv.exists():
                try:
                    mtime = result_csv.stat().st_mtime
                    if last_results_mtime is None or mtime > float(last_results_mtime):
                        last_results_mtime = mtime
                        last_progress_at = now
                except Exception:
                    pass
            if now - last_progress_at >= stall_timeout:
                _stop_training_proc(force=False)
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    _stop_training_proc(force=True)
                raise RuntimeError(
                    f"Training stalled for {int(now - last_progress_at)}s with no progress updates (chunk watchdog timeout)."
                )
            if heartbeat and (now - last_beat >= 2.0):
                heartbeat(proc.pid, int(now - started_at))
                last_beat = now
            time.sleep(0.25)
        if proc.returncode != 0:
            summary = f"Training process failed with exit code {proc.returncode}"
            try:
                if result_path.exists():
                    payload = json.loads(result_path.read_text(encoding="utf-8"))
                    err = str(payload.get("error") or "").strip()
                    if err:
                        summary = _compact_training_error_text(err, fallback=summary)
            except Exception:
                pass
            raise RuntimeError(summary)
        payload = json.loads(result_path.read_text(encoding="utf-8"))
        save_dir = Path(str(payload.get("save_dir") or ""))
        best = Path(str(payload.get("best") or ""))
        if not save_dir.exists():
            raise RuntimeError("Could not locate training run directory.")
        if not best.exists():
            raise RuntimeError("Training completed but best.pt not found.")
        return save_dir, best
    finally:
        _set_training_proc(None)
        try:
            result_path.unlink(missing_ok=True)
        except Exception:
            pass


def _run_training_pipeline_job(job_id: str) -> None:
    local_db = SessionLocal()
    try:
        job = local_db.get(TrainingJob, job_id)
        if not job:
            return
        if (job.status or "") not in {"queued", "running"}:
            return

        run_started_at = job.run_started_at or datetime.utcnow()
        job.run_started_at = run_started_at
        _touch_training_job(local_db, job, status="running", stage="prepare", progress=1, message="Preparing training pipeline")

        settings = _training_settings_payload(local_db)
        mode = (job.mode or "new_only").strip().lower()
        if mode not in {"new_only", "all"}:
            mode = "new_only"
        chunk_size = int(job.chunk_size or int(settings.get("train_chunk_size") or 1000))
        chunk_size = max(100, min(5000, chunk_size))
        chunk_epochs = int((job.details or {}).get("chunk_epochs") or int(settings.get("train_chunk_epochs") or 8))
        chunk_epochs = max(1, min(50, chunk_epochs))
        run_ocr_prefill = _as_bool((job.details or {}).get("run_ocr_prefill"), True)
        run_ocr_learn = _as_bool((job.details or {}).get("run_ocr_learn"), True)

        base_q = local_db.query(TrainingSample).filter(
            TrainingSample.ignored.is_(False),
            or_(TrainingSample.bbox.isnot(None), TrainingSample.no_plate.is_(True)),
        )
        pending_filter = _training_pending_filter(mode, run_started_at)
        total_samples = base_q.filter(pending_filter).count()
        positive_count = (
            local_db.query(TrainingSample.id)
            .filter(
                TrainingSample.ignored.is_(False),
                TrainingSample.no_plate.is_(False),
                TrainingSample.bbox.isnot(None),
                pending_filter,
            )
            .count()
        )
        if positive_count <= 0:
            _touch_training_job(
                local_db,
                job,
                status="failed",
                stage="prepare",
                progress=100,
                message="No positive annotated samples available for training",
                error="no_positive_samples",
            )
            return
        if total_samples <= 0:
            _touch_training_job(local_db, job, status="complete", stage="complete", progress=100, message="No pending samples to train")
            return

        job.total_samples = int(total_samples)
        job.chunk_size = int(chunk_size)
        job.chunk_total = int((total_samples + chunk_size - 1) // chunk_size)
        job.details = {**(job.details or {}), "chunk_epochs": chunk_epochs, "run_ocr_prefill": run_ocr_prefill, "run_ocr_learn": run_ocr_learn}
        local_db.add(job)
        local_db.commit()

        run_root = Path(MEDIA_DIR) / "training_runs"
        run_root.mkdir(parents=True, exist_ok=True)
        job.run_dir = str(run_root)
        model_name = settings.get("train_model") or "yolo26n.pt"
        try:
            from ultralytics import YOLO  # noqa: F401
        except Exception:
            _touch_training_job(local_db, job, status="failed", stage="prepare", progress=100, message="Ultralytics not available", error="ultralytics_missing")
            return
        try:
            current_model_source = str(PROJECT_ROOT / "models" / "plate.pt") if (PROJECT_ROOT / "models" / "plate.pt").exists() else _resolve_train_model_source(model_name)
        except Exception as exc:
            _touch_training_job(local_db, job, status="failed", stage="prepare", progress=100, message=f"Model source error: {exc}", error=str(exc))
            return

        epochs = int(settings.get("train_epochs") or 50)
        imgsz = int(settings.get("train_imgsz") or 640)
        batch = int(settings.get("train_batch") or -1)
        device = _resolve_train_device(settings.get("train_device") or "auto")
        patience = int(settings.get("train_patience") or 15)
        aug = {
            "hsv_h": float(_get_app_setting(local_db, "train_hsv_h", "0.015")),
            "hsv_s": float(_get_app_setting(local_db, "train_hsv_s", "0.7")),
            "hsv_v": float(_get_app_setting(local_db, "train_hsv_v", "0.4")),
            "degrees": float(_get_app_setting(local_db, "train_degrees", "5.0")),
            "translate": float(_get_app_setting(local_db, "train_translate", "0.1")),
            "scale": float(_get_app_setting(local_db, "train_scale", "0.5")),
            "shear": float(_get_app_setting(local_db, "train_shear", "2.0")),
            "perspective": float(_get_app_setting(local_db, "train_perspective", "0.0005")),
            "fliplr": float(_get_app_setting(local_db, "train_fliplr", "0.5")),
            "mosaic": float(_get_app_setting(local_db, "train_mosaic", "0.5")),
            "mixup": float(_get_app_setting(local_db, "train_mixup", "0.1")),
        }
        _touch_training_job(
            local_db,
            job,
            status="running",
            stage="detect_train",
            progress=5,
            message=f"Detection training started ({total_samples} samples, chunk {chunk_size}, mode={mode})",
        )

        trained_samples = int(job.trained_samples or 0)
        chunk_index = int(job.chunk_index or 0)
        while True:
            if TRAIN_PIPELINE_STOP.is_set():
                _touch_training_job(local_db, job, status="stopped", stage="stopped", progress=job.progress or 0, message="Training stop requested by admin")
                return
            pending_rows = (
                local_db.query(TrainingSample)
                .filter(
                    TrainingSample.ignored.is_(False),
                    or_(TrainingSample.bbox.isnot(None), TrainingSample.no_plate.is_(True)),
                    _training_pending_filter(mode, run_started_at),
                )
                .order_by(TrainingSample.id.asc())
                .limit(chunk_size)
                .all()
            )
            if not pending_rows:
                break

            chunk_index += 1
            chunk_ids = [int(s.id) for s in pending_rows]
            chunk_positive = sum(1 for s in pending_rows if bool(s.bbox) and not bool(s.no_plate))
            job.chunk_index = chunk_index
            local_db.add(job)
            local_db.commit()
            _touch_training_job(
                local_db,
                job,
                status="running",
                stage="detect_train",
                progress=10 + ((chunk_index - 1) / max(1, job.chunk_total)) * 65,
                message=f"Chunk {chunk_index}/{job.chunk_total}: preparing dataset ({len(chunk_ids)} samples)",
            )

            dataset_subdir = f"training_yolo_jobs/{job.id}/chunk_{chunk_index:04d}"
            counts = _build_yolo_dataset_for_sample_ids(local_db, chunk_ids, dataset_subdir=dataset_subdir)
            if chunk_positive > 0 and int(counts.get("positives") or 0) > 0:
                run_name = f"{job.id}_c{chunk_index:04d}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                _touch_training_job(
                    local_db,
                    job,
                    status="running",
                    stage="detect_train",
                    progress=12 + ((chunk_index - 1) / max(1, job.chunk_total)) * 65,
                    message=f"Chunk {chunk_index}/{job.chunk_total}: training detector for {chunk_epochs} epochs",
                )
                def _chunk_heartbeat(pid: int, elapsed_seconds: int) -> None:
                    details = dict(job.details or {})
                    details["backend"] = {
                        "activity": "detector_training",
                        "pid": int(pid),
                        "elapsed_seconds": int(elapsed_seconds),
                        "chunk_index": int(chunk_index),
                        "chunk_total": int(job.chunk_total or 0),
                    }
                    job.details = details
                    local_db.add(job)
                    local_db.commit()
                    _touch_training_job(
                        local_db,
                        job,
                        status="running",
                        stage="detect_train",
                        progress=12 + ((chunk_index - 1) / max(1, job.chunk_total)) * 65,
                        message=f"Chunk {chunk_index}/{job.chunk_total}: detector training running ({elapsed_seconds}s, pid {pid})",
                    )
                save_dir, best = _train_chunk_with_yolo(
                    data_yaml=str(counts.get("data_yaml")),
                    run_root=run_root,
                    model_source=current_model_source,
                    run_name=run_name,
                    epochs=chunk_epochs,
                    imgsz=imgsz,
                    batch=batch,
                    device=device,
                    patience=max(1, min(patience, max(2, chunk_epochs))),
                    aug=aug,
                    stop_event=TRAIN_PIPELINE_STOP,
                    heartbeat=_chunk_heartbeat,
                )
                model_dest = PROJECT_ROOT / "models" / "plate.pt"
                model_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(best, model_dest)
                current_model_source = str(model_dest)
                job.run_dir = str(save_dir)
                job.model_path = str(model_dest)
                details = dict(job.details or {})
                details["backend"] = {
                    "activity": "detector_training_complete",
                    "chunk_index": int(chunk_index),
                    "chunk_total": int(job.chunk_total or 0),
                }
                job.details = details
                local_db.add(job)
                local_db.commit()

            now = datetime.utcnow()
            local_db.query(TrainingSample).filter(TrainingSample.id.in_(chunk_ids)).update(
                {TrainingSample.last_trained_at: now},
                synchronize_session=False,
            )
            local_db.commit()
            trained_samples += len(chunk_ids)
            job.trained_samples = int(trained_samples)
            local_db.add(job)
            local_db.commit()
            _touch_training_job(
                local_db,
                job,
                status="running",
                stage="detect_train",
                progress=10 + (trained_samples / max(1, total_samples)) * 70,
                message=f"Chunk {chunk_index}/{job.chunk_total} complete ({trained_samples}/{total_samples} samples)",
            )

        if run_ocr_prefill:
            _touch_training_job(local_db, job, status="running", stage="ocr_prefill", progress=82, message="OCR pass: extracting plate text from annotated boxes")
            ocr_scanned = 0
            ocr_updated = 0
            last_ocr_id = 0
            while True:
                if TRAIN_PIPELINE_STOP.is_set():
                    _touch_training_job(local_db, job, status="stopped", stage="stopped", progress=job.progress or 0, message="Training stop requested by admin")
                    return
                rows = (
                    local_db.query(TrainingSample)
                    .filter(
                        TrainingSample.ignored.is_(False),
                        TrainingSample.no_plate.is_(False),
                        TrainingSample.bbox.isnot(None),
                        TrainingSample.last_trained_at.isnot(None),
                        TrainingSample.last_trained_at >= run_started_at,
                        TrainingSample.id > last_ocr_id,
                    )
                    .order_by(TrainingSample.id.asc())
                    .limit(chunk_size)
                    .all()
                )
                if not rows:
                    break
                changed_ids: List[int] = []
                for sample in rows:
                    ocr_scanned += 1
                    if (sample.plate_text or "").strip():
                        continue
                    frame = cv2.imread(str(Path(MEDIA_DIR) / str(sample.image_path or "")))
                    if frame is None:
                        continue
                    crop = crop_from_bbox(frame, _bbox_xywh_to_xyxy(sample.bbox or {}))
                    if crop is None:
                        continue
                    ocr = read_plate_text(crop) or {}
                    text = str(ocr.get("plate_text") or "").strip().upper()
                    if not text:
                        continue
                    raw = str(ocr.get("raw_text") or text).strip()
                    sample.plate_text = text
                    sample.unclear_plate = False
                    sample.processed_at = datetime.utcnow()
                    sample.notes = f"OCR_BATCH_RAW:{raw}\n{(sample.notes or '').strip()}".strip()
                    local_db.add(sample)
                    changed_ids.append(sample.id)
                    ocr_updated += 1
                if changed_ids:
                    local_db.commit()
                else:
                    local_db.rollback()
                last_ocr_id = max(int(r.id) for r in rows)
                job.ocr_scanned = int(ocr_scanned)
                job.ocr_updated = int(ocr_updated)
                local_db.add(job)
                local_db.commit()
                _touch_training_job(local_db, job, status="running", stage="ocr_prefill", progress=82 + min(10, (ocr_scanned / max(1, total_samples)) * 10), message=f"OCR prefill: scanned {ocr_scanned}, updated {ocr_updated}")

        if run_ocr_learn:
            _touch_training_job(local_db, job, status="running", stage="ocr_learn", progress=95, message="Learning OCR corrections from manual fixes")
            learn = _learn_ocr_corrections_from_db(local_db)
            details = dict(job.details or {})
            details["ocr_learn"] = {
                "pairs": int(learn.get("pairs") or 0),
                "replacements": int(learn.get("replacements") or 0),
            }
            job.details = details
            local_db.add(job)
            local_db.commit()

        try:
            reload_yolo_model()
        except Exception:
            pass
        _touch_training_job(
            local_db,
            job,
            status="complete",
            stage="complete",
            progress=100,
            message="Training pipeline completed successfully",
        )
        try:
            _create_notification(
                local_db,
                title="Training completed",
                message=f"New model saved to {job.model_path or (PROJECT_ROOT / 'models' / 'plate.pt')}",
                level="success",
                kind="training",
                extra={"job_id": job.id, "run_dir": job.run_dir, "model_path": job.model_path},
            )
            local_db.commit()
        except Exception:
            pass
    except InterruptedError:
        try:
            job = local_db.get(TrainingJob, job_id)
            if job:
                _touch_training_job(local_db, job, status="stopped", stage="stopped", progress=job.progress or 0, message="Training stopped")
        except Exception:
            pass
    except Exception as exc:
        try:
            job = local_db.get(TrainingJob, job_id)
            if job:
                summary = _compact_training_error_text(exc, fallback="Training failed")
                _touch_training_job(local_db, job, status="failed", stage="failed", progress=100, message=f"Training failed: {summary}", error=summary)
        except Exception:
            pass
    finally:
        _set_training_proc(None)
        local_db.close()
        global TRAIN_PIPELINE_THREAD
        with TRAIN_PIPELINE_LOCK:
            TRAIN_PIPELINE_THREAD = None


def _start_training_pipeline_thread(job_id: str) -> bool:
    global TRAIN_PIPELINE_THREAD
    with TRAIN_PIPELINE_LOCK:
        if TRAIN_PIPELINE_THREAD and TRAIN_PIPELINE_THREAD.is_alive():
            return False
        TRAIN_PIPELINE_STOP.clear()
        TRAIN_PIPELINE_THREAD = threading.Thread(target=_run_training_pipeline_job, args=(job_id,), daemon=True)
        TRAIN_PIPELINE_THREAD.start()
        return True


def _create_training_job(
    db: Session,
    *,
    mode: str,
    chunk_size: int,
    chunk_epochs: int,
    run_ocr_prefill: bool,
    run_ocr_learn: bool,
    trigger: str,
) -> TrainingJob:
    job = TrainingJob(
        id=secrets.token_urlsafe(14),
        kind="pipeline",
        status="queued",
        mode=mode,
        stage="queued",
        progress=0,
        message=f"Queued ({trigger})",
        chunk_size=chunk_size,
        chunk_index=0,
        chunk_total=0,
        total_samples=0,
        trained_samples=0,
        ocr_scanned=0,
        ocr_updated=0,
        run_started_at=datetime.utcnow(),
        details={
            "trigger": trigger,
            "chunk_epochs": chunk_epochs,
            "run_ocr_prefill": bool(run_ocr_prefill),
            "run_ocr_learn": bool(run_ocr_learn),
        },
        error=None,
    )
    _append_training_job_log(job, f"Queued by {trigger}")
    db.add(job)
    db.commit()
    db.refresh(job)
    _set_training_status("running", f"Queued training job {job.id}")
    return job


def _start_training_pipeline_from_request(
    db: Session,
    *,
    mode: Optional[str] = None,
    chunk_size: Optional[int] = None,
    chunk_epochs: Optional[int] = None,
    run_ocr_prefill: Optional[bool] = None,
    run_ocr_learn: Optional[bool] = None,
    trigger: str = "manual",
) -> Dict[str, object]:
    running = _active_training_job(db)
    if running:
        _start_training_pipeline_thread(running.id)
        return {"ok": True, "job": _job_payload(running), "already_running": True}

    settings = _training_settings_payload(db)
    mode_resolved = (mode or ("new_only" if _as_bool(settings.get("train_new_only_default"), True) else "all")).strip().lower()
    if mode_resolved not in {"new_only", "all"}:
        mode_resolved = "new_only"
    chunk_size_resolved = int(chunk_size or int(settings.get("train_chunk_size") or 1000))
    chunk_size_resolved = max(100, min(5000, chunk_size_resolved))
    chunk_epochs_resolved = int(chunk_epochs or int(settings.get("train_chunk_epochs") or 8))
    chunk_epochs_resolved = max(1, min(50, chunk_epochs_resolved))
    ocr_prefill_resolved = _as_bool(run_ocr_prefill, True)
    ocr_learn_resolved = _as_bool(run_ocr_learn, True)

    job = _create_training_job(
        db,
        mode=mode_resolved,
        chunk_size=chunk_size_resolved,
        chunk_epochs=chunk_epochs_resolved,
        run_ocr_prefill=ocr_prefill_resolved,
        run_ocr_learn=ocr_learn_resolved,
        trigger=trigger,
    )
    _start_training_pipeline_thread(job.id)
    try:
        _create_notification(
            db,
            title="Training queued",
            message=f"Training job {job.id} queued ({mode_resolved}, chunk={chunk_size_resolved})",
            level="info",
            kind="training",
            extra={"job_id": job.id, "mode": mode_resolved, "chunk_size": chunk_size_resolved},
        )
        db.commit()
    except Exception:
        pass
    return {"ok": True, "job": _job_payload(job), "already_running": False}


def _resume_training_pipeline_job(db: Session, job: TrainingJob) -> Dict[str, object]:
    if (job.status or "") not in {"stopped", "queued"}:
        raise HTTPException(status_code=400, detail="Only stopped or queued training jobs can be resumed")
    job.status = "queued"
    job.stage = "queued"
    job.message = "Queued (resume requested)"
    job.error = None
    job.finished_at = None
    details = dict(job.details or {})
    details["resumed_at"] = datetime.utcnow().isoformat()
    job.details = details
    db.add(job)
    db.commit()
    _append_training_job_log(job, "Resume requested")
    db.add(job)
    db.commit()
    started = _start_training_pipeline_thread(job.id)
    if not started:
        return {"ok": True, "job": _job_payload(job), "already_running": True}
    return {"ok": True, "job": _job_payload(job), "already_running": False}


@app.post("/admin/training/train")
def training_train(db: Session = Depends(get_db)):
    result = _start_training_pipeline_from_request(db, trigger="admin")
    if result.get("already_running"):
        return JSONResponse({"ok": False, "error": "Training already running.", "job": result.get("job")}, status_code=409)
    return JSONResponse(result)


@app.get("/admin/training/center", response_class=HTMLResponse)
def training_center(request: Request, db: Session = Depends(get_db)):
    status = _get_training_status()
    settings = _training_settings_payload(db)
    settings.update(
        {
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
    )
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
    train_model: str = Form("yolo26n.pt"),
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
    plate_region: str = Form("generic"),
    plate_min_length: int = Form(5),
    plate_max_length: int = Form(8),
    plate_charset: str = Form("alnum"),
    plate_pattern_regex: str = Form(""),
    plate_shape_hint: str = Form("standard"),
    plate_reference_date: str = Form(""),
    allowed_stationary_enabled: bool = Form(True),
    allowed_stationary_motion_threshold: float = Form(7.0),
    allowed_stationary_hold_seconds: float = Form(0.0),
    db: Session = Depends(get_db),
):
    values = _sanitize_training_settings(
        {
            "train_model": train_model,
            "train_epochs": train_epochs,
            "train_imgsz": train_imgsz,
            "train_batch": train_batch,
            "train_device": train_device,
            "train_patience": train_patience,
            "plate_region": plate_region,
            "plate_min_length": plate_min_length,
            "plate_max_length": plate_max_length,
            "plate_charset": plate_charset,
            "plate_pattern_regex": plate_pattern_regex,
            "plate_shape_hint": plate_shape_hint,
            "plate_reference_date": plate_reference_date,
            "allowed_stationary_enabled": allowed_stationary_enabled,
            "allowed_stationary_motion_threshold": allowed_stationary_motion_threshold,
            "allowed_stationary_hold_seconds": allowed_stationary_hold_seconds,
        }
    )
    values.update(
        {
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
    )
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

        if overlay and frame is not None:
            if overlay:
                detection = stream_manager.get_detection(camera.id)
                frame = _draw_overlay(frame.copy(), detection)
            ret, buffer = cv2.imencode(".jpg", frame, LIVE_STREAM_JPEG_PARAMS)
            if ret:
                jpeg = buffer.tobytes()
        elif jpeg is None and frame is not None:
            ret, buffer = cv2.imencode(".jpg", frame, LIVE_STREAM_JPEG_PARAMS)
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
    return StreamingResponse(
        _mjpeg_stream(camera, overlay=bool(int(overlay))),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


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
    now = datetime.utcnow()
    since_24h = now - timedelta(hours=24)

    total_detections = db.query(Detection).count()
    total_cameras = db.query(Camera).count()
    active_cameras = db.query(Camera).filter(Camera.enabled.is_(True)).count()
    allowed_count = db.query(Detection).filter(Detection.status == "allowed").count()
    denied_count = db.query(Detection).filter(Detection.status == "denied").count()
    unread_notifications = db.query(Notification).filter(Notification.is_read.is_(False)).count()
    other_count = max(0, total_detections - allowed_count - denied_count)
    training_status = _get_training_status()

    recent = (
        db.query(Detection, Camera)
        .join(Camera, Detection.camera_id == Camera.id, isouter=True)
        .filter(Detection.detected_at >= since_24h)
        .all()
    )

    hour_starts = [since_24h + timedelta(hours=i + 1) for i in range(24)]
    hour_labels = [h.strftime("%H:00") for h in hour_starts]
    hourly_total = [0 for _ in hour_starts]
    hourly_allowed = [0 for _ in hour_starts]
    hourly_denied = [0 for _ in hour_starts]
    camera_counts: Dict[str, int] = {}
    plate_counts: Dict[str, int] = {}

    for det, cam in recent:
        if not det.detected_at:
            continue
        hour_idx = int((det.detected_at.replace(tzinfo=None) - since_24h).total_seconds() // 3600)
        hour_idx = max(0, min(23, hour_idx))
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

    top_cameras = sorted(camera_counts.items(), key=lambda item: item[1], reverse=True)[:6]
    top_plates = sorted(plate_counts.items(), key=lambda item: item[1], reverse=True)[:6]

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
                "labels": [name for name, _ in top_cameras],
                "values": [count for _, count in top_cameras],
            },
            "top_plates": {
                "labels": [plate for plate, _ in top_plates],
                "values": [count for _, count in top_plates],
            },
            "future_users_actions": {
                "labels": future_labels,
                "users": [0 for _ in future_labels],
                "actions": [0 for _ in future_labels],
            },
        },
        "recent_events": recent_events,
        "future_metrics": {
            "users": {"total": 0, "active": 0, "new_today": 0},
            "actions": {"queued": 0, "completed": 0, "pending": 0},
            "notes": "These metrics are placeholders for upcoming user/action tracking features.",
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
    active_manual = {int(item["camera_id"]) for item in manual_clip_manager.active()}
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
                "model": cam.model,
                "enabled": bool(cam.enabled),
                "live_view": bool(cam.live_view),
                "live_order": cam.live_order,
                "scan_interval": cam.scan_interval,
                "cooldown_seconds": cam.cooldown_seconds,
                "save_clip": bool(cam.save_clip),
                "clip_seconds": int(cam.clip_seconds or 0),
                "onvif_xaddr": cam.onvif_xaddr,
                "onvif_username": cam.onvif_username,
                "onvif_profile": cam.onvif_profile,
                "detector_mode": cam.detector_mode,
                "effective_detector_mode": cam.detector_mode if cam.detector_mode != "inherit" else global_mode,
                "browser_online": stream_manager.is_external_online(cam.id) if cam.type == "browser" else None,
                "manual_recording": cam.id in active_manual,
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
    cam_type = _validate_camera_type(body.type or "")
    detector_mode = _validate_detector_mode(body.detector_mode or "inherit")

    raw_source = body.source or ""
    if cam_type == "browser" and not raw_source.strip():
        raw_source = "browser"
    source = _normalize_camera_source(cam_type, raw_source)
    if not source:
        raise HTTPException(status_code=400, detail="Source is required")

    camera = Camera(
        name=(body.name or "").strip()[:100],
        type=cam_type,
        source=source,
        location=(body.location or "").strip()[:200] if body.location else None,
        model=(body.model or "").strip()[:200] if body.model else None,
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
    _apply_camera_patch(cam, body.dict(exclude_unset=True))
    db.add(cam)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Camera name already exists")
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


@app.post("/api/v1/cameras/test_connection")
def api_v1_camera_test_connection(
    body: ApiCameraTestBody,
    user: str = Depends(_api_get_current_user),
):
    """Step-by-step network diagnostic: ping → TCP port → RTSP probe → full stream."""
    del user
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    # Resolve host/port — prefer explicit fields, fall back to URL parsing
    parsed = urlparse(url)
    host = (body.host or "").strip() or parsed.hostname or ""
    port = body.port or parsed.port or 554

    if not host:
        raise HTTPException(status_code=400, detail="Cannot determine host from URL")

    steps: list = []

    # ── Step 1: Ping ─────────────────────────────────────────────────────────
    ping_ok = False
    try:
        ping_cmd = ["ping", "-c", "1", "-W", "2", "-w", "4", host]
        pr = subprocess.run(ping_cmd, capture_output=True, text=True, timeout=6)
        ping_ok = pr.returncode == 0
        if ping_ok:
            rtt_m = re.search(r"time[=<]([\d.]+)\s*ms", pr.stdout)
            rtt_s = f" ({rtt_m.group(1)} ms)" if rtt_m else ""
            steps.append({"step": "ping", "ok": True,
                          "msg": f"Host {host} is reachable{rtt_s}"})
        else:
            steps.append({"step": "ping", "ok": False,
                          "msg": f"No ping response from {host} — host may be down, wrong IP, or ICMP is blocked by firewall"})
    except subprocess.TimeoutExpired:
        steps.append({"step": "ping", "ok": False,
                      "msg": f"Ping to {host} timed out — host unreachable or ICMP blocked"})
    except FileNotFoundError:
        steps.append({"step": "ping", "ok": None,
                      "msg": "ping command not available in container — skipping"})
    except Exception as exc:
        steps.append({"step": "ping", "ok": False, "msg": f"Ping error: {exc}"})

    # ── Step 2: TCP port reachability ────────────────────────────────────────
    port_ok = False
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
        port_ok = True
        steps.append({"step": "port", "ok": True,
                      "msg": f"Port {port}/tcp is open on {host}"})
    except socket.timeout:
        steps.append({"step": "port", "ok": False,
                      "msg": f"Port {port}/tcp timed out — firewall is blocking it or wrong port number"})
    except ConnectionRefusedError:
        steps.append({"step": "port", "ok": False,
                      "msg": f"Port {port}/tcp refused — no RTSP service listening on that port. "
                             f"Try 554, 8554, or check your NVR settings"})
    except OSError as exc:
        steps.append({"step": "port", "ok": False,
                      "msg": f"Port {port}/tcp unreachable: {exc}"})

    # ── Step 3: RTSP OPTIONS handshake (no auth needed) ──────────────────────
    rtsp_ok = False
    if port_ok:
        try:
            raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw.settimeout(5)
            raw.connect((host, port))
            probe = (
                f"OPTIONS rtsp://{host}:{port}/ RTSP/1.0\r\n"
                f"CSeq: 1\r\n"
                f"User-Agent: CarVision/1.0\r\n\r\n"
            )
            raw.sendall(probe.encode())
            resp = raw.recv(512).decode("utf-8", errors="replace")
            raw.close()
            first_line = resp.split("\r\n")[0] if resp else ""
            if "RTSP/1.0" in resp:
                rtsp_ok = True
                if "401" in resp or "403" in resp:
                    steps.append({"step": "rtsp", "ok": True,
                                  "msg": f"RTSP server responded — auth required ({first_line}). "
                                         f"Credentials will be verified in the next step"})
                else:
                    steps.append({"step": "rtsp", "ok": True,
                                  "msg": f"RTSP server is running and responded: {first_line}"})
            elif resp:
                steps.append({"step": "rtsp", "ok": False,
                              "msg": f"Port {port} responded but not with RTSP — "
                                     f"this may be an HTTP or other service. First bytes: {resp[:80]!r}"})
            else:
                steps.append({"step": "rtsp", "ok": False,
                              "msg": f"Port {port} is open but returned no data to RTSP OPTIONS"})
        except socket.timeout:
            steps.append({"step": "rtsp", "ok": False,
                          "msg": "RTSP handshake timed out — service is not responding"})
        except Exception as exc:
            steps.append({"step": "rtsp", "ok": False, "msg": f"RTSP probe error: {exc}"})
    else:
        steps.append({"step": "rtsp", "ok": False,
                      "msg": "Skipped — port is not reachable"})

    # ── Step 4: ffprobe stream probe (handles Digest auth, gives real errors) ──
    stream: dict = {"ok": False, "msg": "", "info": {}}
    ffprobe_ok = False
    try:
        import shutil as _shutil
        ffprobe_bin = _shutil.which("ffprobe")
        if not ffprobe_bin:
            raise FileNotFoundError("ffprobe not found")
        ffprobe_cmd = [
            ffprobe_bin,
            "-v", "error",
            "-rtsp_transport", "tcp",
            "-timeout", "10000000",   # 10 s in µs
            "-show_entries", "stream=codec_name,codec_type,width,height,r_frame_rate",
            "-of", "json",
            url,
        ]
        pr = subprocess.run(ffprobe_cmd, capture_output=True, text=True, timeout=14)
        stderr = (pr.stderr or "").strip()
        if pr.returncode == 0:
            try:
                data = json.loads(pr.stdout or "{}")
            except Exception:
                data = {}
            streams = data.get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
            if video or streams:
                stream["ok"] = True
                ffprobe_ok = True
                parts = []
                if video:
                    w, h = video.get("width"), video.get("height")
                    if w and h:
                        parts.append(f"{w}×{h}")
                    codec = video.get("codec_name", "")
                    if codec:
                        parts.append(codec.upper())
                    fps_raw = video.get("r_frame_rate", "")
                    if fps_raw and "/" in fps_raw:
                        n, d = fps_raw.split("/")
                        try:
                            fps = round(int(n) / int(d), 1)
                            parts.append(f"{fps} fps")
                        except Exception:
                            pass
                if audio:
                    parts.append(f"+ audio ({audio.get('codec_name','?')})")
                stream["msg"] = "Stream is live — " + (", ".join(parts) if parts else "connected")
                stream["info"] = {"video": video, "audio": audio}
            else:
                stream["msg"] = "ffprobe connected but found no streams — camera may be offline"
        else:
            # Parse stderr for specific Dahua / RTSP error patterns
            sl = stderr.lower()
            if "401" in stderr or "unauthorized" in sl:
                stream["msg"] = ("Authentication failed — wrong username or password. "
                                 "For Dahua NVRs use the NVR admin credentials, not the camera's own credentials")
            elif "403" in stderr or "forbidden" in sl:
                stream["msg"] = "Access forbidden — account may not have RTSP stream permission"
            elif "404" in stderr or "not found" in sl:
                stream["msg"] = ("Stream path not found (404) — wrong channel number or path. "
                                 "Try channel 1, or use the Dahua path with &unicast=true")
            elif "connection refused" in sl:
                stream["msg"] = f"Connection refused on port {port} — wrong port"
            elif "no route" in sl or "unreachable" in sl or "network" in sl:
                stream["msg"] = f"Network unreachable — VPN may be disconnected or route to {host} is missing"
            elif "timeout" in sl or "timed out" in sl:
                stream["msg"] = ("Connection timed out — camera is reachable but not streaming. "
                                 "Check channel number and that the camera is powered and assigned in the NVR")
            elif stderr:
                # Return raw ffprobe error — it's always more useful than a generic message
                stream["msg"] = f"Stream error: {stderr[:300]}"
            else:
                stream["msg"] = "Stream could not be opened (no error detail from ffprobe)"
    except subprocess.TimeoutExpired:
        stream["msg"] = ("ffprobe timed out after 14 s — RTSP server is reachable but not delivering video. "
                         "Check channel number, stream path, and that the camera is assigned in the NVR")
    except FileNotFoundError:
        # ffprobe not available — fall back to OpenCV
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            ret, _ = cap.read()
            if ret:
                stream["ok"] = True
                stream["msg"] = "Stream is live (OpenCV)"
            else:
                stream["msg"] = "Stream opened but no frame — check stream path and channel"
        else:
            stream["msg"] = "Could not open stream — check credentials and stream path"
        cap.release()
    except Exception as exc:
        stream["msg"] = f"Stream probe error: {exc}"

    steps.append({"step": "stream", "ok": stream["ok"], "msg": stream["msg"]})

    # ── Overall summary ───────────────────────────────────────────────────────
    ping_step_ok = steps[0].get("ok")
    if stream["ok"]:
        summary = stream["msg"]
    elif ping_step_ok is False:
        summary = (f"Cannot reach {host} — verify the IP address, "
                   f"that your VPN is connected, and that the device is powered on")
    elif not port_ok:
        summary = (f"Host {host} is up but port {port}/tcp is closed — "
                   f"check the port number (try 554 or 8554) and NVR firewall settings")
    elif not rtsp_ok:
        summary = (f"Port {port} is open but not serving RTSP — "
                   f"make sure this is the RTSP port, not the web UI port (80/443)")
    else:
        summary = stream["msg"]

    return {
        "ok": stream["ok"],
        "message": summary,
        "steps": steps,
        "host": host,
        "port": port,
    }


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
    db.query(Notification).filter(Notification.detection_id == det.id).delete(synchronize_session=False)
    if det.video_path:
        db.query(ClipRecord).filter(
            ClipRecord.camera_id == det.camera_id,
            ClipRecord.file_path == det.video_path,
        ).delete(synchronize_session=False)
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


@app.get("/api/v1/training/dataset_stats")
def api_v1_training_dataset_stats(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    """Return detailed counts about the training dataset."""
    del user
    total = db.query(TrainingSample).count()
    annotated = db.query(TrainingSample).filter(
        TrainingSample.ignored.is_(False),
        or_(TrainingSample.bbox.isnot(None), TrainingSample.no_plate.is_(True)),
    ).count()
    with_bbox = db.query(TrainingSample).filter(
        TrainingSample.bbox.isnot(None),
        TrainingSample.ignored.is_(False),
    ).count()
    with_text = db.query(TrainingSample).filter(
        TrainingSample.plate_text.isnot(None),
        TrainingSample.plate_text != "",
        TrainingSample.ignored.is_(False),
    ).count()
    negative = db.query(TrainingSample).filter(
        TrainingSample.no_plate.is_(True),
        TrainingSample.ignored.is_(False),
    ).count()
    unclear = db.query(TrainingSample).filter(
        TrainingSample.unclear_plate.is_(True),
        TrainingSample.ignored.is_(False),
    ).count()
    pending = db.query(TrainingSample).filter(
        TrainingSample.bbox.is_(None),
        TrainingSample.no_plate.is_(False),
        TrainingSample.ignored.is_(False),
    ).count()
    ignored = db.query(TrainingSample).filter(
        TrainingSample.ignored.is_(True),
    ).count()
    trained = db.query(TrainingSample).filter(
        TrainingSample.last_trained_at.isnot(None),
    ).count()
    from_system = db.query(TrainingSample).filter(
        TrainingSample.import_batch.is_(None),
    ).count()
    from_dataset = db.query(TrainingSample).filter(
        TrainingSample.import_batch.isnot(None),
    ).count()
    testable = db.query(TrainingSample).filter(
        TrainingSample.bbox.isnot(None),
        TrainingSample.plate_text.isnot(None),
        TrainingSample.plate_text != "",
        TrainingSample.ignored.is_(False),
    ).count()
    return {
        "total": total,
        "annotated": annotated,
        "with_bbox": with_bbox,
        "with_text": with_text,
        "negative": negative,
        "unclear": unclear,
        "pending": pending,
        "ignored": ignored,
        "trained": trained,
        "untrained": total - trained,
        "from_system": from_system,
        "from_dataset": from_dataset,
        "testable": testable,
        "annotation_rate": round(annotated / total * 100, 1) if total else 0,
        "trained_rate": round(trained / total * 100, 1) if total else 0,
    }


@app.post("/api/v1/training/test_model")
def api_v1_training_test_model(
    body: ApiModelTestBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    """Run the active model against manually annotated samples and report accuracy."""
    del user
    limit = max(1, min(500, int(body.limit or 100)))

    qy = db.query(TrainingSample).filter(
        TrainingSample.bbox.isnot(None),
        TrainingSample.plate_text.isnot(None),
        TrainingSample.plate_text != "",
        TrainingSample.ignored.is_(False),
    )
    if body.sample_ids:
        qy = qy.filter(TrainingSample.id.in_(body.sample_ids))
    rows = qy.order_by(TrainingSample.id.desc()).limit(limit).all()

    if not rows:
        return {"ok": False, "error": "No annotated samples with plate text found to test.", "results": [], "summary": {}}

    from difflib import SequenceMatcher

    results = []
    exact_matches = 0
    fuzzy_total = 0.0
    conf_total = 0.0
    conf_count = 0
    no_detection = 0

    for row in rows:
        image_abs = Path(row.image_path)
        if not image_abs.is_absolute():
            image_abs = Path(MEDIA_DIR) / row.image_path
        expected = (row.plate_text or "").strip().upper()
        entry: Dict = {
            "sample_id": row.id,
            "image_path": row.image_path,
            "expected": expected,
            "predicted": None,
            "exact_match": False,
            "similarity": 0.0,
            "confidence": None,
            "detector": None,
            "error": None,
        }
        if not image_abs.exists():
            entry["error"] = "image file not found"
            results.append(entry)
            no_detection += 1
            continue
        try:
            frame = cv2.imread(str(image_abs))
            if frame is None:
                entry["error"] = "could not decode image"
                results.append(entry)
                no_detection += 1
                continue
            det = detect_plate(frame)
            if not det:
                entry["error"] = "no plate detected"
                no_detection += 1
                results.append(entry)
                continue
            predicted = (det.get("plate_text") or "").strip().upper()
            conf = det.get("confidence")
            sim = SequenceMatcher(None, expected, predicted).ratio()
            exact = (predicted == expected)
            entry["predicted"] = predicted
            entry["exact_match"] = exact
            entry["similarity"] = round(sim, 3)
            entry["confidence"] = round(float(conf), 3) if conf is not None else None
            entry["detector"] = det.get("detector")
            if exact:
                exact_matches += 1
            fuzzy_total += sim
            if conf is not None:
                conf_total += float(conf)
                conf_count += 1
        except Exception as exc:
            entry["error"] = str(exc)
            no_detection += 1
        results.append(entry)

    tested = len(rows)
    detected = tested - no_detection
    return {
        "ok": True,
        "results": results,
        "summary": {
            "total_tested": tested,
            "detected": detected,
            "no_detection": no_detection,
            "exact_matches": exact_matches,
            "exact_accuracy": round(exact_matches / tested * 100, 1) if tested else 0,
            "fuzzy_accuracy": round(fuzzy_total / tested * 100, 1) if tested else 0,
            "avg_similarity": round(fuzzy_total / tested, 3) if tested else 0,
            "avg_confidence": round(conf_total / conf_count, 3) if conf_count else None,
            "detection_rate": round(detected / tested * 100, 1) if tested else 0,
        },
    }


@app.get("/api/v1/training/status")
def api_v1_training_status(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    active = _active_training_job(db)
    job = active or _latest_training_job(db)
    payload = _job_payload(job)
    return {
        **payload,
        "status": payload.get("status"),
        "message": payload.get("message"),
        "last_run_dir": payload.get("run_dir"),
        "last_model_path": payload.get("model_path"),
    }


@app.get("/api/v1/training/jobs")
def api_v1_training_jobs(
    page: int = 1,
    limit: int = 20,
    status: str = "all",
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    page = max(1, int(page or 1))
    limit = max(1, min(100, int(limit or 20)))
    status = (status or "all").strip().lower()
    allowed = {"all", "queued", "running", "stopping", "stopped", "failed", "complete"}
    if status not in allowed:
        status = "all"

    qy = db.query(TrainingJob).filter(TrainingJob.kind == "pipeline")
    if status != "all":
        qy = qy.filter(TrainingJob.status == status)

    total = qy.count()
    pages = max(1, (total + limit - 1) // limit)
    if page > pages:
        page = pages
    offset = (page - 1) * limit

    rows = (
        qy.order_by(TrainingJob.started_at.desc(), TrainingJob.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "items": [_job_history_payload(row) for row in rows],
        "total": int(total),
        "page": int(page),
        "pages": int(pages),
        "limit": int(limit),
        "status": status,
    }


@app.post("/api/v1/training/start")
def api_v1_training_start(
    body: Optional[ApiTrainingStartBody] = None,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    result = _start_training_pipeline_from_request(
        db,
        mode=(body.mode if body else None),
        chunk_size=(body.chunk_size if body else None),
        chunk_epochs=(body.chunk_epochs if body else None),
        run_ocr_prefill=(body.run_ocr_prefill if body else None),
        run_ocr_learn=(body.run_ocr_learn if body else None),
        trigger="api",
    )
    return result


@app.post("/api/v1/training/stop")
def api_v1_training_stop(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    job = _active_training_job(db)
    if not job:
        return {"ok": True, "stopped": False, "message": "No active job"}
    TRAIN_PIPELINE_STOP.set()
    _stop_training_proc(force=False)
    _touch_training_job(db, job, status="running", stage="stopping", message="Stop requested")
    return {"ok": True, "stopped": True, "job": _job_payload(job)}


@app.post("/api/v1/training/resume")
def api_v1_training_resume(
    job_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    active = _active_training_job(db)
    if active:
        _start_training_pipeline_thread(active.id)
        return {"ok": True, "job": _job_payload(active), "already_running": True}
    job: Optional[TrainingJob] = None
    if job_id:
        job = db.get(TrainingJob, str(job_id).strip())
    if not job:
        job = (
            db.query(TrainingJob)
            .filter(TrainingJob.kind == "pipeline", TrainingJob.status.in_(("stopped", "queued")))
            .order_by(TrainingJob.updated_at.desc(), TrainingJob.id.desc())
            .first()
        )
    if not job:
        raise HTTPException(status_code=404, detail="No stopped training job available to resume")
    return _resume_training_pipeline_job(db, job)


@app.get("/api/v1/training/model/download")
def api_v1_training_model_download(
    job_id: Optional[str] = None,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    model_path: Optional[Path] = None
    if job_id:
        job = db.get(TrainingJob, str(job_id).strip())
        if not job or job.kind != "pipeline":
            raise HTTPException(status_code=404, detail="Training job not found")
        candidates: List[Path] = []
        if job.model_path:
            candidates.append(Path(job.model_path))
        if job.run_dir:
            run_dir = Path(job.run_dir)
            candidates.extend(
                [
                    run_dir / "weights" / "best.pt",
                    run_dir / "best.pt",
                ]
            )
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                model_path = candidate
                break
        if not model_path:
            raise HTTPException(status_code=404, detail="No model artifact found for this job")
    else:
        model_path = PROJECT_ROOT / "models" / "plate.pt"

    if not model_path.exists():
        raise HTTPException(status_code=404, detail="Trained model not found")
    filename_suffix = (str(job_id).strip() if job_id else datetime.utcnow().strftime("%Y%m%d_%H%M%S")).replace("/", "_")
    return FileResponse(
        str(model_path),
        media_type="application/octet-stream",
        filename=f"carvision_plate_{filename_suffix}.pt",
    )


@app.post("/api/v1/training/model/reset")
def api_v1_training_model_reset(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    active = _active_training_job(db)
    if active:
        raise HTTPException(status_code=409, detail="Cannot reset model while training is active")

    model_path = PROJECT_ROOT / "models" / "plate.pt"
    existed = model_path.exists()
    if existed:
        try:
            model_path.unlink()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to remove existing model: {exc}") from exc

    try:
        camera_manager.sync()
    except Exception:
        logger.warning("camera_manager sync failed after model reset", exc_info=True)

    return {
        "ok": True,
        "removed": bool(existed),
        "path": str(model_path),
        "message": "Existing trained model removed. Future training will use the configured base model.",
    }


@app.get("/api/v1/training/settings")
def api_v1_training_settings(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    return _training_settings_payload(db)


@app.post("/api/v1/training/settings")
def api_v1_training_settings_update(
    body: ApiTrainingSettingsBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    current = _training_settings_payload(db)
    incoming = body.dict(exclude_none=True)
    merged = {**current, **incoming}
    values = _sanitize_training_settings(merged)
    for key, val in values.items():
        setting = db.get(AppSetting, key)
        if not setting:
            db.add(AppSetting(key=key, value=val))
        else:
            setting.value = val
    db.commit()
    _refresh_anpr_config(db)
    return {"ok": True, "settings": _training_settings_payload(db)}


@app.get("/api/v1/training/samples")
def api_v1_training_samples(
    status: str = "all",
    q: str = "",
    batch: str = "",
    source: str = "system",
    has_text: str = "all",
    processed: str = "all",
    trained: str = "all",
    sort_by: str = "created_at",
    sort_dir: str = "desc",
    page: int = 1,
    page_size: int = 50,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    status = (status or "all").strip().lower()
    if status not in {"all", "annotated", "pending", "negative", "ignored", "unclear"}:
        status = "all"
    page = max(1, int(page or 1))
    page_size = max(10, min(200, int(page_size or 50)))
    source = (source or "system").strip().lower()
    if source not in {"all", "system", "dataset"}:
        source = "system"
    has_text = (has_text or "all").strip().lower()
    if has_text not in {"all", "yes", "no"}:
        has_text = "all"
    processed = (processed or "all").strip().lower()
    if processed not in {"all", "yes", "no"}:
        processed = "all"
    trained = (trained or "all").strip().lower()
    if trained not in {"all", "yes", "no"}:
        trained = "all"
    sort_by = (sort_by or "created_at").strip().lower()
    if sort_by not in {"id", "created_at", "updated_at", "plate_text", "processed_at", "last_trained_at"}:
        sort_by = "created_at"
    sort_dir = (sort_dir or "desc").strip().lower()
    if sort_dir not in {"asc", "desc"}:
        sort_dir = "desc"

    batch_filter = (batch or "").strip()[:80]
    base_query = db.query(TrainingSample)
    if batch_filter:
        base_query = base_query.filter(TrainingSample.import_batch == batch_filter)
    elif source == "system":
        base_query = base_query.filter(TrainingSample.import_batch.is_(None))
    elif source == "dataset":
        base_query = base_query.filter(TrainingSample.import_batch.isnot(None))
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
        "unclear": base_query.filter(TrainingSample.unclear_plate.is_(True), TrainingSample.ignored.is_(False)).count(),
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
    elif status == "unclear":
        qy = qy.filter(TrainingSample.unclear_plate.is_(True), TrainingSample.ignored.is_(False))

    if q:
        q_like = f"%{q.strip()}%"
        qy = qy.filter(
            or_(
                TrainingSample.plate_text.ilike(q_like),
                TrainingSample.image_path.ilike(q_like),
                TrainingSample.notes.ilike(q_like),
            )
        )
    if not batch_filter:
        if source == "system":
            qy = qy.filter(TrainingSample.import_batch.is_(None))
        elif source == "dataset":
            qy = qy.filter(TrainingSample.import_batch.isnot(None))
    if has_text == "yes":
        qy = qy.filter(TrainingSample.plate_text.isnot(None), TrainingSample.plate_text != "")
    elif has_text == "no":
        qy = qy.filter(or_(TrainingSample.plate_text.is_(None), TrainingSample.plate_text == ""))
    if processed == "yes":
        qy = qy.filter(TrainingSample.processed_at.isnot(None))
    elif processed == "no":
        qy = qy.filter(TrainingSample.processed_at.is_(None))
    if trained == "yes":
        qy = qy.filter(TrainingSample.last_trained_at.isnot(None))
    elif trained == "no":
        qy = qy.filter(TrainingSample.last_trained_at.is_(None))

    total_filtered = qy.count()
    pages = max(1, (total_filtered + page_size - 1) // page_size)
    if page > pages:
        page = pages
    offset = (page - 1) * page_size
    sort_map = {
        "id": TrainingSample.id,
        "created_at": TrainingSample.created_at,
        "updated_at": TrainingSample.updated_at,
        "plate_text": TrainingSample.plate_text,
        "processed_at": TrainingSample.processed_at,
        "last_trained_at": TrainingSample.last_trained_at,
    }
    sort_col = sort_map.get(sort_by, TrainingSample.created_at)
    sort_expr = sort_col.asc() if sort_dir == "asc" else sort_col.desc()
    rows = qy.order_by(sort_expr).offset(offset).limit(page_size).all()
    return {
        "counts": counts,
        "items": [_api_training_sample_payload(r) for r in rows],
        "batch": batch_filter or None,
        "source": source,
        "has_text": has_text,
        "processed": processed,
        "trained": trained,
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total_filtered,
            "total_pages": pages,
        },
    }


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
    updated_existing = 0
    annotated = 0
    negatives = 0
    pending = 0
    annotations_detected = False
    existing_by_hash: Dict[str, Optional[TrainingSample]] = {}

    def _resolve_size_for_sample(sample: TrainingSample, width: int, height: int) -> Tuple[int, int]:
        if (width <= 0 or height <= 0) and sample.image_path:
            try:
                src = Path(MEDIA_DIR) / str(sample.image_path)
                size = _load_image_size(src)
                if size:
                    width, height = int(size[0]), int(size[1])
                    sample.image_width = width
                    sample.image_height = height
            except Exception:
                pass
        return int(width or 0), int(height or 0)

    def _label_to_entries(label_text: Optional[str], width: int, height: int) -> List[Dict[str, object]]:
        text = (label_text or "").strip()
        if not text:
            return [{"kind": "negative"}]
        boxes = _extract_yolo_bboxes(text, width, height)
        if boxes:
            return [{"kind": "bbox", "bbox": b} for b in boxes]
        return [{"kind": "pending"}]

    def apply_entry_to_sample(sample: TrainingSample, entry: Dict[str, object], width: int, height: int) -> str:
        width, height = _resolve_size_for_sample(sample, width, height)
        kind = str(entry.get("kind") or "pending")
        if kind == "negative":
            sample.no_plate = True
            sample.unclear_plate = False
            sample.bbox = None
            sample.plate_text = None
            sample.notes = "Imported as negative sample from empty YOLO label."
            return "negative"
        if kind == "bbox":
            bbox = entry.get("bbox")
            if isinstance(bbox, dict):
                sample.no_plate = False
                sample.unclear_plate = False
                sample.bbox = bbox
                sample.notes = "Imported YOLO bbox. Add/correct plate text before training."
                return "annotated"
            sample.notes = "Label file found but YOLO bbox could not be parsed."
            return "pending"
        sample.notes = "Imported sample pending annotation."
        return "pending"

    def add_sample(image_bytes: bytes, filename: str, label_text: Optional[str] = None):
        nonlocal annotated, negatives, pending, updated_existing
        if not image_bytes:
            return
        image_hash = _hash_bytes(image_bytes)
        existing = existing_by_hash.get(image_hash)
        if image_hash not in existing_by_hash:
            existing = (
                db.query(TrainingSample)
                .filter(TrainingSample.image_hash == image_hash)
                .order_by(TrainingSample.updated_at.desc(), TrainingSample.id.desc())
                .first()
            )
            existing_by_hash[image_hash] = existing

        # If this image already exists, merge annotations into existing sample instead of duplicating.
        if existing is not None:
            if label_text is not None:
                entries = _label_to_entries(label_text, int(existing.image_width or 0), int(existing.image_height or 0))
                primary = entries[0] if entries else {"kind": "pending"}
                state = apply_entry_to_sample(existing, primary, int(existing.image_width or 0), int(existing.image_height or 0))
                if state == "annotated":
                    annotated += 1
                elif state == "negative":
                    negatives += 1
                else:
                    pending += 1
                updated_existing += 1
                db.add(existing)

                for extra in entries[1:]:
                    extra_sample = TrainingSample(
                        image_path=existing.image_path,
                        image_hash=existing.image_hash,
                        image_width=existing.image_width,
                        image_height=existing.image_height,
                        import_batch=batch_id,
                    )
                    extra_state = apply_entry_to_sample(
                        extra_sample,
                        extra,
                        int(existing.image_width or 0),
                        int(existing.image_height or 0),
                    )
                    if extra_state == "annotated":
                        annotated += 1
                    elif extra_state == "negative":
                        negatives += 1
                    else:
                        pending += 1
                    db.add(extra_sample)
                    db.flush()
                    created_ids.append(extra_sample.id)
            return

        rel_path, width, height = _save_training_upload(image_bytes, filename or "import.jpg")
        if not rel_path:
            return
        entries: List[Dict[str, object]]
        if label_text is not None:
            entries = _label_to_entries(label_text, int(width or 0), int(height or 0))
        else:
            entries = [{"kind": "pending"}]

        first_sample: Optional[TrainingSample] = None
        for idx, entry in enumerate(entries):
            sample = TrainingSample(
                image_path=rel_path,
                image_hash=image_hash,
                image_width=width,
                image_height=height,
                import_batch=batch_id,
            )
            state = apply_entry_to_sample(sample, entry, int(width or 0), int(height or 0))
            if state == "annotated":
                annotated += 1
            elif state == "negative":
                negatives += 1
            else:
                pending += 1
            db.add(sample)
            db.flush()
            created_ids.append(sample.id)
            if idx == 0:
                first_sample = sample
        if first_sample is not None:
            existing_by_hash[image_hash] = first_sample

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
            if Path(name).suffix.lower() == ".txt":
                text_map[Path(name).stem.lower()] = content.decode("utf-8", errors="ignore")
        if text_map:
            annotations_detected = True
        use_annotations = bool(has_annotations) or bool(text_map)

        for name, content in image_payloads:
            label = text_map.get(Path(name).stem.lower()) if use_annotations else None
            add_sample(content, name, label)

    if dataset_zip is not None:
        temp_dir = Path(MEDIA_DIR) / "temp_imports"
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_zip = temp_dir / f"dataset_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(4)}.zip"
        try:
            with temp_zip.open("wb") as f:
                while True:
                    chunk = await dataset_zip.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
            if not temp_zip.exists() or temp_zip.stat().st_size == 0:
                raise HTTPException(status_code=400, detail="Empty ZIP file")
            try:
                with zipfile.ZipFile(temp_zip) as zf:
                    text_map: Dict[str, str] = {}
                    text_by_stem: Dict[str, str] = {}
                    image_entries = []
                    for info in zf.infolist():
                        if info.is_dir():
                            continue
                        name = info.filename.replace("\\", "/")
                        low = name.lower()
                        if _is_image_filename(low):
                            image_entries.append(info)
                        elif low.endswith(".txt"):
                            try:
                                txt = zf.read(info).decode("utf-8", errors="ignore")
                                text_map[low] = txt
                                stem = Path(low).stem.lower()
                                if stem and stem not in text_by_stem:
                                    text_by_stem[stem] = txt
                            except Exception:
                                text_map[low] = ""
                    if text_map:
                        annotations_detected = True
                    use_annotations = bool(has_annotations) or bool(text_map)

                    for info in image_entries:
                        name = info.filename.replace("\\", "/")
                        try:
                            content = zf.read(info)
                        except Exception:
                            continue
                        label = None
                        if use_annotations:
                            for cand in _zip_label_candidates(name):
                                label = text_map.get(cand.lower())
                                if label is not None:
                                    break
                            if label is None:
                                label = text_by_stem.get(Path(name).stem.lower())
                        add_sample(content, Path(name).name, label)
            except zipfile.BadZipFile:
                raise HTTPException(status_code=400, detail="Invalid ZIP file")
        finally:
            try:
                temp_zip.unlink(missing_ok=True)
            except Exception:
                pass

    if created_ids:
        db.commit()

    return {
        "ok": True,
        "created": len(created_ids),
        "ids": created_ids,
        "batch_id": batch_id if (created_ids or updated_existing) else None,
        "has_annotations": bool(has_annotations) or bool(annotations_detected),
        "annotations_detected": bool(annotations_detected),
        "updated_existing": updated_existing,
        "annotated": annotated,
        "negatives": negatives,
        "pending": pending,
    }


@app.get("/api/v1/training/import_batches")
def api_v1_training_import_batches(
    limit: int = 200,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    safe_limit = max(1, min(int(limit or 200), 1000))
    rows = (
        db.query(
            TrainingSample.import_batch.label("batch"),
            func.count(TrainingSample.id).label("total"),
            func.sum(case((TrainingSample.no_plate.is_(True), 1), else_=0)).label("negatives"),
            func.sum(case((TrainingSample.bbox.isnot(None), 1), else_=0)).label("annotated"),
            func.max(TrainingSample.updated_at).label("updated_at"),
            func.min(TrainingSample.created_at).label("created_at"),
        )
        .filter(TrainingSample.import_batch.isnot(None))
        .group_by(TrainingSample.import_batch)
        .order_by(func.max(TrainingSample.updated_at).desc())
        .limit(safe_limit)
        .all()
    )
    items = []
    for row in rows:
        total = int(row.total or 0)
        negatives = int(row.negatives or 0)
        annotated = int(row.annotated or 0)
        pending = max(0, total - negatives - annotated)
        items.append(
            {
                "batch": row.batch,
                "total": total,
                "annotated": annotated,
                "negatives": negatives,
                "pending": pending,
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                "ocr_job": _get_batch_ocr_job(db, row.batch),
            }
        )
    return {"items": items}


@app.delete("/api/v1/training/import_batches/{batch_id}")
def api_v1_training_delete_import_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    batch = (batch_id or "").strip()
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")

    rows = (
        db.query(TrainingSample)
        .filter(TrainingSample.import_batch == batch)
        .order_by(TrainingSample.id.asc())
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="Import batch not found")

    image_paths = {str(r.image_path or "").strip() for r in rows if r.image_path}
    deleted = len(rows)
    for row in rows:
        db.delete(row)
    db.flush()

    removed_files = 0
    for rel in image_paths:
        still_used = db.query(TrainingSample.id).filter(TrainingSample.image_path == rel).first() is not None
        if still_used:
            continue
        abs_path = Path(MEDIA_DIR) / rel
        try:
            if abs_path.exists():
                abs_path.unlink()
                removed_files += 1
        except Exception:
            # Keep DB delete successful even if filesystem cleanup fails.
            pass

    db.commit()
    return {"ok": True, "batch_id": batch, "deleted": deleted, "removed_files": removed_files}


@app.post("/api/v1/training/import_batches/{batch_id}/ocr/reprocess")
def api_v1_training_reprocess_import_batch_ocr(
    batch_id: str,
    chunk_size: int = 1000,
    resume: bool = True,
    force_restart: bool = False,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    batch = (batch_id or "").strip()[:80]
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    safe_chunk = max(100, min(int(chunk_size or 1000), 2000))

    total = (
        db.query(TrainingSample.id)
        .filter(
            TrainingSample.import_batch == batch,
            TrainingSample.ignored.is_(False),
            TrainingSample.no_plate.is_(False),
            TrainingSample.bbox.isnot(None),
        )
        .count()
    )
    if total <= 0:
        raise HTTPException(status_code=404, detail="No annotated import samples found for this batch")

    existing = _get_batch_ocr_job(db, batch)
    if existing:
        existing_status = str(existing.get("status") or "").strip().lower()
        stale_seconds = int(existing.get("stale_seconds") or 0)
        if existing_status in {"running", "stopping"} and stale_seconds < 180:
            return {"ok": True, "job": existing, "already_running": True}

    resumed_from = 0
    initial_processed = 0
    initial_updated = 0
    initial_skipped = 0
    if existing and resume and not force_restart:
        resumed_from = max(0, int(existing.get("last_id") or 0))
        initial_processed = max(0, int(existing.get("processed") or 0))
        initial_updated = max(0, int(existing.get("updated") or 0))
        initial_skipped = max(0, int(existing.get("skipped") or 0))
        if resumed_from <= 0 and initial_processed > 0:
            cursor_row = (
                db.query(TrainingSample.id)
                .filter(
                    TrainingSample.import_batch == batch,
                    TrainingSample.ignored.is_(False),
                    TrainingSample.no_plate.is_(False),
                    TrainingSample.bbox.isnot(None),
                )
                .order_by(TrainingSample.id.asc())
                .offset(max(0, initial_processed - 1))
                .first()
            )
            if cursor_row and cursor_row[0]:
                resumed_from = int(cursor_row[0])

    _set_batch_ocr_stop(db, batch, False)
    now_iso = _utc_iso_now()
    job_id = secrets.token_urlsafe(10)
    chunk_total = max(1, (int(total) + safe_chunk - 1) // safe_chunk)
    job = {
        "id": job_id,
        "batch": batch,
        "status": "running",
        "progress": int((initial_processed / max(1, int(total))) * 100),
        "processed": initial_processed,
        "updated": initial_updated,
        "skipped": initial_skipped,
        "total": int(total),
        "chunk_size": safe_chunk,
        "message": "Queued (resuming)" if resumed_from > 0 else "Queued",
        "started_at": now_iso,
        "updated_at": now_iso,
        "heartbeat_at": now_iso,
        "finished_at": "",
        "error": "",
        "last_id": resumed_from,
        "chunk_index": int(initial_processed // safe_chunk),
        "chunk_total": chunk_total,
        "speed_sps": 0.0,
        "eta_seconds": 0,
        "current_sample_id": 0,
        "resumed_from": resumed_from,
    }
    _write_batch_ocr_job(db, batch, job)
    db.commit()

    def _run_batch_ocr():
        local_db = SessionLocal()
        try:
            processed = int(initial_processed)
            updated = int(initial_updated)
            skipped = int(initial_skipped)
            last_id = int(resumed_from)
            chunk_index = int(processed // safe_chunk)
            started_dt = _parse_iso_datetime(now_iso) or datetime.utcnow()
            while True:
                if _batch_ocr_stop_requested(local_db, batch):
                    stopped_state = {
                        "id": job_id,
                        "batch": batch,
                        "status": "stopped",
                        "progress": int((processed / max(1, total)) * 100),
                        "processed": processed,
                        "updated": updated,
                        "skipped": skipped,
                        "total": int(total),
                        "chunk_size": safe_chunk,
                        "message": "Stopped by admin",
                        "started_at": now_iso,
                        "updated_at": _utc_iso_now(),
                        "heartbeat_at": _utc_iso_now(),
                        "finished_at": _utc_iso_now(),
                        "error": "",
                        "last_id": last_id,
                        "chunk_index": chunk_index,
                        "chunk_total": chunk_total,
                        "current_sample_id": 0,
                        "resumed_from": resumed_from,
                    }
                    _write_batch_ocr_job(local_db, batch, stopped_state)
                    local_db.commit()
                    return
                rows = (
                    local_db.query(TrainingSample)
                    .filter(
                        TrainingSample.import_batch == batch,
                        TrainingSample.ignored.is_(False),
                        TrainingSample.no_plate.is_(False),
                        TrainingSample.bbox.isnot(None),
                        TrainingSample.id > last_id,
                    )
                    .order_by(TrainingSample.id.asc())
                    .limit(safe_chunk)
                    .all()
                )
                if not rows:
                    break

                chunk_index += 1
                current_sample_id = 0
                for sample in rows:
                    if _batch_ocr_stop_requested(local_db, batch):
                        break
                    last_id = sample.id
                    current_sample_id = sample.id
                    processed += 1
                    existing_text = (sample.plate_text or "").strip()
                    if existing_text:
                        skipped += 1
                        continue
                    try:
                        frame = cv2.imread(str(Path(MEDIA_DIR) / str(sample.image_path or "")))
                        if frame is None:
                            skipped += 1
                            continue
                        crop = crop_from_bbox(frame, _bbox_xywh_to_xyxy(sample.bbox or {}))
                        if crop is None:
                            skipped += 1
                            continue
                        ocr = read_plate_text(crop) or {}
                        text = str(ocr.get("plate_text") or "").strip().upper()
                        if not text:
                            skipped += 1
                            continue
                        raw = str(ocr.get("raw_text") or text).strip()
                        sample.plate_text = text
                        sample.unclear_plate = False
                        sample.processed_at = datetime.utcnow()
                        sample.notes = f"OCR_BATCH_RAW:{raw}\n{(sample.notes or '').strip()}".strip()
                        local_db.add(sample)
                        updated += 1
                    except Exception:
                        skipped += 1

                local_db.commit()
                elapsed = max(1.0, (datetime.utcnow() - started_dt).total_seconds())
                speed_sps = round(float(processed) / float(elapsed), 3) if processed > 0 else 0.0
                eta_seconds = int((max(0, total - processed)) / speed_sps) if speed_sps > 0 else 0
                pct = int((processed / max(1, total)) * 100)
                job_state = {
                    "id": job_id,
                    "batch": batch,
                    "status": "running",
                    "progress": pct,
                    "processed": processed,
                    "updated": updated,
                    "skipped": skipped,
                    "total": int(total),
                    "chunk_size": safe_chunk,
                    "message": f"Processed {processed}/{total}",
                    "started_at": now_iso,
                    "updated_at": _utc_iso_now(),
                    "heartbeat_at": _utc_iso_now(),
                    "finished_at": "",
                    "error": "",
                    "last_id": last_id,
                    "chunk_index": chunk_index,
                    "chunk_total": chunk_total,
                    "speed_sps": speed_sps,
                    "eta_seconds": eta_seconds,
                    "current_sample_id": current_sample_id,
                    "resumed_from": resumed_from,
                }
                _write_batch_ocr_job(local_db, batch, job_state)
                local_db.commit()

            done_state = {
                "id": job_id,
                "batch": batch,
                "status": "complete",
                "progress": 100,
                "processed": processed,
                "updated": updated,
                "skipped": skipped,
                "total": int(total),
                "chunk_size": safe_chunk,
                "message": f"Completed: {updated} updated, {skipped} skipped",
                "started_at": now_iso,
                "updated_at": _utc_iso_now(),
                "heartbeat_at": _utc_iso_now(),
                "finished_at": _utc_iso_now(),
                "error": "",
                "last_id": last_id,
                "chunk_index": chunk_index,
                "chunk_total": chunk_total,
                "current_sample_id": 0,
                "resumed_from": resumed_from,
            }
            _write_batch_ocr_job(local_db, batch, done_state)
            local_db.commit()
        except Exception as exc:
            try:
                local_db.rollback()
            except Exception:
                pass
            failed_state = {
                "id": job_id,
                "batch": batch,
                "status": "failed",
                "progress": 100,
                "processed": 0,
                "updated": 0,
                "skipped": 0,
                "total": int(total),
                "chunk_size": safe_chunk,
                "message": "Batch OCR failed",
                "started_at": now_iso,
                "updated_at": _utc_iso_now(),
                "heartbeat_at": _utc_iso_now(),
                "finished_at": _utc_iso_now(),
                "error": str(exc),
                "last_id": last_id,
                "chunk_index": chunk_index,
                "chunk_total": chunk_total,
                "current_sample_id": 0,
                "resumed_from": resumed_from,
            }
            _write_batch_ocr_job(local_db, batch, failed_state)
            local_db.commit()
        finally:
            local_db.close()

    threading.Thread(target=_run_batch_ocr, daemon=True).start()
    return {"ok": True, "job": job, "already_running": False}


@app.get("/api/v1/training/import_batches/{batch_id}/ocr/reprocess")
def api_v1_training_reprocess_import_batch_ocr_status(
    batch_id: str,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    batch = (batch_id or "").strip()[:80]
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    job = _get_batch_ocr_job(db, batch)
    if not job:
        raise HTTPException(status_code=404, detail="No OCR job found for this batch")
    return {"ok": True, "job": job}


@app.post("/api/v1/training/import_batches/{batch_id}/ocr/control")
def api_v1_training_import_batch_ocr_control(
    batch_id: str,
    action: str = "stop",
    chunk_size: int = 1000,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    batch = (batch_id or "").strip()[:80]
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    action_norm = (action or "stop").strip().lower()
    if action_norm not in {"stop", "resume", "restart", "clear"}:
        raise HTTPException(status_code=400, detail="Invalid action")

    if action_norm == "stop":
        _set_batch_ocr_stop(db, batch, True)
        job = _get_batch_ocr_job(db, batch)
        if job and str(job.get("status") or "").lower() == "running":
            job["status"] = "stopping"
            job["message"] = "Stop requested by admin"
            job["updated_at"] = _utc_iso_now()
            _write_batch_ocr_job(db, batch, job)
        db.commit()
        return {"ok": True, "action": action_norm, "job": _get_batch_ocr_job(db, batch)}

    if action_norm == "clear":
        _set_app_setting(db, _batch_ocr_job_key(batch), "")
        _set_batch_ocr_stop(db, batch, False)
        db.commit()
        return {"ok": True, "action": action_norm}

    if action_norm == "resume":
        return api_v1_training_reprocess_import_batch_ocr(
            batch_id=batch,
            chunk_size=chunk_size,
            resume=True,
            force_restart=False,
            db=db,
            user="admin",
        )

    return api_v1_training_reprocess_import_batch_ocr(
        batch_id=batch,
        chunk_size=chunk_size,
        resume=False,
        force_restart=True,
        db=db,
        user="admin",
    )


@app.post("/api/v1/training/ocr/prefill")
def api_v1_training_ocr_prefill(
    batch: str = "",
    source: str = "all",
    limit: int = 0,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    batch_norm = batch.strip()[:80]
    source_norm = (source or "all").strip().lower()
    # limit=0 means process ALL unfilled samples (no cap)
    safe_limit = max(0, int(limit or 0))

    _cleanup_upload_jobs()
    job_id = _create_upload_job("ocr_prefill")
    _set_latest_ocr_job(job_id)  # so the frontend can recover after page refresh

    def _run():
        local_db = SessionLocal()
        try:
            _update_upload_job(
                job_id,
                status="running",
                progress=1,
                message="Starting OCR prefill",
                step="Preparing samples",
            )
            q = local_db.query(TrainingSample).filter(
                TrainingSample.ignored.is_(False),
                TrainingSample.no_plate.is_(False),
                TrainingSample.bbox.isnot(None),
                or_(TrainingSample.plate_text.is_(None), TrainingSample.plate_text == ""),
            )
            if batch_norm:
                q = q.filter(TrainingSample.import_batch == batch_norm)
            else:
                if source_norm == "system":
                    q = q.filter(TrainingSample.import_batch.is_(None))
                elif source_norm == "dataset":
                    q = q.filter(TrainingSample.import_batch.isnot(None))
            q = q.order_by(TrainingSample.id.asc())
            if safe_limit > 0:
                samples = q.limit(safe_limit).all()
            else:
                samples = q.all()
            total = len(samples)
            scanned = 0
            updated = 0
            skipped = 0
            if total == 0:
                _update_upload_job(
                    job_id,
                    status="complete",
                    progress=100,
                    message="No annotated samples found",
                    result={"scanned": 0, "updated": 0, "skipped": 0, "total": 0},
                )
                return

            for sample in samples:
                scanned += 1
                try:
                    path = Path(MEDIA_DIR) / str(sample.image_path)
                    frame = cv2.imread(str(path))
                    if frame is None:
                        skipped += 1
                    else:
                        crop = crop_from_bbox(frame, _bbox_xywh_to_xyxy(sample.bbox or {}))
                        if crop is None:
                            skipped += 1
                        else:
                            ocr = read_plate_text(crop) or {}
                            text = str(ocr.get("plate_text") or "").strip().upper()
                            if not text:
                                skipped += 1
                            else:
                                raw = str(ocr.get("raw_text") or text).strip()
                                sample.plate_text = text
                                sample.unclear_plate = False
                                sample.processed_at = datetime.utcnow()
                                sample.notes = f"OCR_PREFILL_RAW:{raw}\n{(sample.notes or '').strip()}".strip()
                                local_db.add(sample)
                                updated += 1
                except Exception:
                    skipped += 1

                if scanned % 100 == 0:
                    local_db.commit()
                if scanned % 20 == 0 or scanned == total:
                    progress = int((scanned / total) * 100)
                    _update_upload_job(
                        job_id,
                        status="running",
                        progress=progress,
                        message=f"Processed {scanned}/{total} — updated {updated}",
                        step=f"Updated {updated}, skipped {skipped}",
                        result={"scanned": scanned, "updated": updated, "skipped": skipped, "total": total},
                    )
            local_db.commit()
            _update_upload_job(
                job_id,
                status="complete",
                progress=100,
                message=f"OCR prefill completed ({updated} updated)",
                step="OCR prefill finished",
                result={"scanned": scanned, "updated": updated, "skipped": skipped, "total": total},
            )
        except Exception as exc:
            try:
                local_db.rollback()
            except Exception:
                pass
            _update_upload_job(
                job_id,
                status="failed",
                progress=100,
                message=f"OCR prefill failed: {exc}",
                step=f"Error: {exc}",
                error=str(exc),
            )
        finally:
            local_db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@app.get("/api/v1/training/ocr/prefill/latest")
def api_v1_training_ocr_prefill_latest(
    user: str = Depends(_api_get_current_user),
):
    """Return the most recent OCR prefill job (survives frontend page refresh, not server restart)."""
    del user
    job_id = _get_latest_ocr_job_id()
    if not job_id:
        return {"ok": True, "job": None}
    job = _get_upload_job(job_id)
    return {"ok": True, "job": job}


@app.get("/api/v1/training/ocr/prefill/{job_id}")
def api_v1_training_ocr_prefill_status(
    job_id: str,
    user: str = Depends(_api_get_current_user),
):
    del user
    _cleanup_upload_jobs()
    job = _get_upload_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}


@app.post("/api/v1/training/ocr/learn")
def api_v1_training_ocr_learn(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    result = _learn_ocr_corrections_from_db(db)
    return {
        "ok": True,
        "pairs": int(result.get("pairs") or 0),
        "learned_map": result.get("learned_map") or {},
        "replacements": int(result.get("replacements") or 0),
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
        sample.unclear_plate = False
        sample.bbox = None
        sample.plate_text = None
    else:
        sample.no_plate = False
        sample.unclear_plate = bool(body.unclear_plate)
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
        if sample.unclear_plate:
            sample.plate_text = None
        else:
            sample.plate_text = body.plate_text.strip()[:50] if body.plate_text else None

    sample.notes = body.notes.strip()[:500] if body.notes else None
    sample.processed_at = datetime.utcnow()
    sample.ignored = False
    db.add(sample)
    db.commit()
    return {
        "ok": True,
        "item": _api_training_sample_payload(sample),
        "debug_steps": _build_training_debug(sample),
    }


@app.post("/api/v1/training/samples/{sample_id:int}/reprocess")
def api_v1_training_reprocess_sample(
    sample_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if sample.no_plate:
        raise HTTPException(status_code=400, detail="Sample is marked as no-plate")
    if not sample.bbox:
        raise HTTPException(status_code=400, detail="Sample has no bbox")

    path = Path(MEDIA_DIR) / str(sample.image_path or "")
    frame = cv2.imread(str(path))
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not read sample image")

    crop = crop_from_bbox(frame, _bbox_xywh_to_xyxy(sample.bbox or {}))
    if crop is None:
        raise HTTPException(status_code=400, detail="Could not crop sample bbox")

    ocr = read_plate_text(crop) or {}
    plate_text = str(ocr.get("plate_text") or "").strip().upper()
    raw_text = str(ocr.get("raw_text") or plate_text).strip()
    if plate_text:
        sample.plate_text = plate_text[:50]
        sample.unclear_plate = False
    notes = (sample.notes or "").strip()
    sample.notes = f"OCR_REPROCESS_RAW:{raw_text}\n{notes}".strip()
    sample.processed_at = datetime.utcnow()
    sample.ignored = False
    db.add(sample)
    db.commit()
    return {
        "ok": True,
        "plate_text": sample.plate_text,
        "raw_text": raw_text,
        "item": _api_training_sample_payload(sample),
        "debug_steps": _build_training_debug(sample),
    }


@app.post("/api/v1/training/samples/reprocess")
def api_v1_training_reprocess_bulk(
    body: ApiTrainingSampleIdsBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    ids = [int(x) for x in (body.sample_ids or []) if int(x) > 0]
    if not ids:
        return {"ok": True, "processed": 0, "updated": 0, "failed": 0}

    updated = 0
    failed = 0
    processed = 0
    for sid in ids:
        sample = db.get(TrainingSample, sid)
        if not sample or sample.no_plate or not sample.bbox:
            failed += 1
            continue
        path = Path(MEDIA_DIR) / str(sample.image_path or "")
        frame = cv2.imread(str(path))
        if frame is None:
            failed += 1
            continue
        crop = crop_from_bbox(frame, _bbox_xywh_to_xyxy(sample.bbox or {}))
        if crop is None:
            failed += 1
            continue
        ocr = read_plate_text(crop) or {}
        plate_text = str(ocr.get("plate_text") or "").strip().upper()
        raw_text = str(ocr.get("raw_text") or plate_text).strip()
        if plate_text:
            sample.plate_text = plate_text[:50]
            sample.unclear_plate = False
            updated += 1
        notes = (sample.notes or "").strip()
        sample.notes = f"OCR_REPROCESS_RAW:{raw_text}\n{notes}".strip()
        sample.processed_at = datetime.utcnow()
        db.add(sample)
        processed += 1

    db.commit()
    return {"ok": True, "processed": processed, "updated": updated, "failed": failed}


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
    subnets: Optional[str] = None,
    probe_ports: bool = False,
    user: str = Depends(_api_get_current_user),
):
    del user
    timeout = max(1, min(int(timeout), 15))
    result = discover_onvif(timeout=timeout, resolve_rtsp=False) or {"error": None, "devices": []}
    raw_devices = result.get("devices") or []
    subnet_filters, invalid_subnets = _parse_discovery_subnets(subnets)

    devices = []
    for device in raw_devices:
        xaddrs = device.get("xaddrs") or []
        host = None
        xaddr_ports = set()
        for xaddr in xaddrs:
            parsed_host, parsed_port = _xaddr_host_port(xaddr)
            if not host and parsed_host:
                host = parsed_host
            if parsed_port:
                xaddr_ports.add(int(parsed_port))

        if subnet_filters and (not host or not _host_in_subnets(host, subnet_filters)):
            continue

        enriched = dict(device)
        enriched["host"] = host
        enriched["xaddr_ports"] = sorted(xaddr_ports)

        if probe_ports and host:
            probe_targets = {80, 443, 554}
            probe_targets.update(xaddr_ports)
            enriched["port_probe"] = {
                str(port): _probe_tcp_port(host, port)
                for port in sorted(probe_targets)
            }
        else:
            enriched["port_probe"] = {}
        devices.append(enriched)

    return {
        "error": result.get("error"),
        "devices": devices,
        "total_found": len(raw_devices),
        "total_after_filter": len(devices),
        "filters": {
            "subnets": [str(item) for item in subnet_filters],
            "invalid_subnets": invalid_subnets,
            "probe_ports": bool(probe_ports),
        },
    }


@app.post("/api/v1/discovery/resolve")
def api_v1_discovery_resolve(
    body: ApiDiscoveryResolveBody,
    user: str = Depends(_api_get_current_user),
):
    del user
    profiles = resolve_rtsp_for_xaddr(body.xaddr, body.username, body.password)
    return {"xaddr": body.xaddr, "rtsp_profiles": profiles}


@app.get("/api/v1/clips")
def api_v1_clips_list(
    camera_id: Optional[int] = None,
    kind: str = "",
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    limit = max(1, min(500, int(limit)))
    offset = max(0, int(offset))
    kind_norm = (kind or "").strip().lower()
    q = (
        db.query(ClipRecord, Camera)
        .join(Camera, Camera.id == ClipRecord.camera_id)
        .order_by(ClipRecord.created_at.desc(), ClipRecord.id.desc())
    )
    if camera_id:
        q = q.filter(ClipRecord.camera_id == int(camera_id))
    if kind_norm in {"manual", "detection"}:
        q = q.filter(ClipRecord.kind == kind_norm)
    rows = q.offset(offset).limit(limit).all()
    items = [_clip_record_payload(row, camera_name=cam.name) for row, cam in rows]
    return {"items": items, "count": len(items)}


@app.get("/api/v1/clips/active")
def api_v1_clips_active(
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    active_rows = manual_clip_manager.active()
    if not active_rows:
        return {"items": []}
    camera_ids = [int(item["camera_id"]) for item in active_rows]
    camera_rows = db.query(Camera.id, Camera.name).filter(Camera.id.in_(camera_ids)).all()
    camera_name = {int(cid): name for cid, name in camera_rows}
    items = []
    for row in active_rows:
        started_at = row.get("started_at")
        duration_seconds = None
        if isinstance(started_at, datetime):
            duration_seconds = max(0.0, (datetime.utcnow() - started_at).total_seconds())
        size_bytes = None
        clip_path = _clip_abs_path(row.get("file_path"))
        if clip_path and clip_path.exists():
            try:
                size_bytes = int(clip_path.stat().st_size)
            except Exception:
                size_bytes = None
        items.append(
            {
                "camera_id": int(row["camera_id"]),
                "camera_name": camera_name.get(int(row["camera_id"])),
                "file_path": row.get("file_path"),
                "frames": int(row.get("frames") or 0),
                "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
                "duration_seconds": duration_seconds,
                "size_bytes": size_bytes,
            }
        )
    return {"items": items}


@app.post("/api/v1/clips/start")
def api_v1_clips_start(
    body: ApiClipControlBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    camera = db.get(Camera, int(body.camera_id))
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")
    if not camera.save_clip:
        raise HTTPException(status_code=400, detail="Clip saving is disabled for this camera")
    if not camera.enabled:
        raise HTTPException(status_code=400, detail="Camera is disabled")

    started = manual_clip_manager.start(camera)
    if not started.get("ok"):
        raise HTTPException(status_code=500, detail="Could not start clip recording")

    if not started.get("already_running"):
        _create_notification(
            db,
            title=f"Manual clip recording started on {camera.name}",
            message=f"Recording has started for camera {camera.name}.",
            level="info",
            kind="clip",
            camera_id=camera.id,
            extra={"event": "manual_clip_start"},
        )
    return {
        "ok": True,
        "camera_id": camera.id,
        "camera_name": camera.name,
        "already_running": bool(started.get("already_running")),
        "file_path": started.get("file_path"),
    }


@app.post("/api/v1/clips/stop")
def api_v1_clips_stop(
    body: ApiClipControlBody,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    camera = db.get(Camera, int(body.camera_id))
    if not camera:
        raise HTTPException(status_code=404, detail="Camera not found")

    stopped = manual_clip_manager.stop(camera.id)
    if not stopped:
        raise HTTPException(status_code=400, detail="No active clip recording for this camera")
    if not stopped.get("ok"):
        raise HTTPException(status_code=400, detail=str(stopped.get("error") or "Clip recording did not capture frames"))
    file_path = str(stopped.get("file_path") or "").strip()
    if not file_path:
        raise HTTPException(status_code=500, detail="Clip path is missing")

    started_at = stopped.get("started_at")
    ended_at = stopped.get("ended_at")
    if not isinstance(started_at, datetime) or not isinstance(ended_at, datetime):
        started_at = datetime.utcnow()
        ended_at = datetime.utcnow()

    detection_count = (
        db.query(Detection)
        .filter(Detection.camera_id == camera.id)
        .filter(Detection.detected_at >= started_at)
        .filter(Detection.detected_at <= ended_at)
        .count()
    )

    row = ClipRecord(
        camera_id=camera.id,
        kind="manual",
        file_path=file_path,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=float(stopped.get("duration_seconds") or 0),
        size_bytes=int(stopped.get("size_bytes") or 0),
        detection_count=int(detection_count),
    )
    db.add(row)
    db.commit()

    _create_notification(
        db,
        title=f"Manual clip saved for {camera.name}",
        message=f"Clip saved with {detection_count} detections during recording.",
        level="success",
        kind="clip",
        camera_id=camera.id,
        extra={"event": "manual_clip_stop", "clip_id": row.id, "detections": detection_count},
    )

    return {"ok": True, "item": _clip_record_payload(row, camera_name=camera.name)}


@app.delete("/api/v1/clips/{clip_id:int}")
def api_v1_clip_delete(
    clip_id: int,
    db: Session = Depends(get_db),
    user: str = Depends(_api_get_current_user),
):
    del user
    row = db.get(ClipRecord, clip_id)
    if not row:
        raise HTTPException(status_code=404, detail="Clip not found")
    _delete_clip_row(db, row)
    db.commit()
    return {"ok": True}


def _delete_clip_row(db: Session, row: ClipRecord) -> None:
    clip_path = _clip_abs_path(row.file_path)
    if clip_path:
        try:
            clip_path.unlink(missing_ok=True)
        except Exception:
            pass
    db.delete(row)


@app.post("/api/v1/clips/bulk/delete")
def api_v1_clips_bulk_delete(
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
    rows = db.query(ClipRecord).filter(ClipRecord.id.in_(ids)).all()
    found_ids = {int(row.id) for row in rows}
    for row in rows:
        _delete_clip_row(db, row)
        deleted += 1
    failed += max(0, len(ids) - len(found_ids))
    db.commit()
    return {"ok": True, "deleted": deleted, "failed": failed}


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
