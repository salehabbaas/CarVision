"""routers/training.py — training pipeline, samples, OCR, import/batch management."""
from __future__ import annotations

import json
import logging
import secrets
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from api.schemas import (
    ApiModelTestBody,
    ApiTrainingAnnotateBody,
    ApiTrainingIgnoreBody,
    ApiTrainingSampleIdsBody,
    ApiTrainingSettingsBody,
    ApiTrainingStartBody,
)
from core.config import MEDIA_DIR, PROJECT_ROOT
from db import SessionLocal, get_db
from models import AppSetting, TrainingJob, TrainingSample
from routers.deps import get_current_user, training_sample_payload
from services.dataset import (
    bbox_xywh_to_xyxy as _bbox_xywh_to_xyxy,
    build_yolo_dataset as _build_yolo_dataset,
    is_image_filename as _is_image_filename,
    load_image_size as _load_image_size,
    zip_label_candidates as _zip_label_candidates,
    extract_yolo_bboxes as _extract_yolo_bboxes,
    build_yolo_dataset_for_sample_ids as _build_yolo_dataset_for_sample_ids,
)
from services.debug_assets import build_training_debug as _build_training_debug
from services.file_utils import hash_bytes as _hash_bytes
from services.state import (
    cleanup_upload_jobs as _cleanup_upload_jobs,
    create_upload_job as _create_upload_job,
    get_latest_ocr_job_id as _get_latest_ocr_job_id,
    get_training_status as _get_training_status,
    get_upload_job as _get_upload_job,
    set_latest_ocr_job as _set_latest_ocr_job,
    set_training_status as _set_training_status,
    update_upload_job as _update_upload_job,
)

logger = logging.getLogger("carvision.routers.training")
router = APIRouter(prefix="/api/v1/training", tags=["training"])

# ── Global pipeline state (injected by main.py) ───────────────────────────────
_camera_manager = None
_read_plate_text_fn = None
_crop_from_bbox_fn = None
_set_anpr_config_fn = None

# Thread primitives — shared so stop/resume work across requests
TRAIN_PIPELINE_LOCK = threading.Lock()
TRAIN_PIPELINE_THREAD: Optional[threading.Thread] = None
TRAIN_PIPELINE_STOP = threading.Event()

import subprocess, signal, os as _os
TRAIN_PIPELINE_PROC_LOCK = threading.Lock()
TRAIN_PIPELINE_PROC: Optional[subprocess.Popen] = None


def _init(camera_manager, read_plate_text, crop_from_bbox, set_anpr_config) -> None:
    global _camera_manager, _read_plate_text_fn, _crop_from_bbox_fn, _set_anpr_config_fn
    _camera_manager = camera_manager
    _read_plate_text_fn = read_plate_text
    _crop_from_bbox_fn = crop_from_bbox
    _set_anpr_config_fn = set_anpr_config


# ── Settings helpers (DB-backed) ──────────────────────────────────────────────

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


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _training_settings_payload(db: Session) -> Dict[str, str]:
    keys_defaults = {
        "train_model": "yolo26n.pt",
        "train_epochs": "50",
        "train_imgsz": "640",
        "train_batch": "-1",
        "train_device": "auto",
        "train_patience": "15",
        "plate_region": "generic",
        "plate_min_length": "5",
        "plate_max_length": "8",
        "plate_charset": "alnum",
        "plate_pattern_regex": "",
        "plate_shape_hint": "standard",
        "plate_reference_date": "",
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
    }
    return {k: _get_app_setting(db, k, v) for k, v in keys_defaults.items()}


def _sanitize_training_settings(payload: Dict[str, object]) -> Dict[str, str]:
    def _si(k, default, lo=None, hi=None):
        try:
            v = int(payload.get(k) or default)
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return str(v)
        except Exception:
            return str(default)

    def _sf(k, default, lo=None, hi=None):
        try:
            v = float(payload.get(k) or default)
            if lo is not None:
                v = max(lo, v)
            if hi is not None:
                v = min(hi, v)
            return str(round(v, 4))
        except Exception:
            return str(default)

    train_model = str(payload.get("train_model") or "yolo26n.pt").strip() or "yolo26n.pt"
    train_device = str(payload.get("train_device") or "auto").strip() or "auto"
    plate_region = str(payload.get("plate_region") or "generic").strip()[:80] or "generic"
    plate_charset = str(payload.get("plate_charset") or "alnum").strip().lower()
    if plate_charset not in {"alnum", "digits", "letters"}:
        plate_charset = "alnum"
    plate_shape_hint = str(payload.get("plate_shape_hint") or "standard").strip().lower()
    if plate_shape_hint not in {"standard", "long", "square", "motorcycle"}:
        plate_shape_hint = "standard"
    raw_stationary_enabled = payload.get("allowed_stationary_enabled", True)
    stationary_enabled = "1" if _as_bool(raw_stationary_enabled, True) else "0"
    return {
        "train_model": train_model,
        "train_epochs": _si("train_epochs", 50, 1, 500),
        "train_imgsz": _si("train_imgsz", 640, 320, 1280),
        "train_batch": _si("train_batch", -1, -1, 128),
        "train_device": train_device,
        "train_patience": _si("train_patience", 15, 0, 200),
        "plate_region": plate_region,
        "plate_min_length": _si("plate_min_length", 5, 2, 20),
        "plate_max_length": _si("plate_max_length", 8, 4, 30),
        "plate_charset": plate_charset,
        "plate_pattern_regex": str(payload.get("plate_pattern_regex") or "").strip()[:200],
        "plate_shape_hint": plate_shape_hint,
        "plate_reference_date": str(payload.get("plate_reference_date") or "").strip()[:40],
        "allowed_stationary_enabled": stationary_enabled,
        "allowed_stationary_motion_threshold": _sf("allowed_stationary_motion_threshold", 7.0, 0.1, 100.0),
        "allowed_stationary_hold_seconds": _si("allowed_stationary_hold_seconds", 0, 0, 86400),
        "train_chunk_size": _si("train_chunk_size", 1000, 100, 5000),
        "train_chunk_epochs": _si("train_chunk_epochs", 8, 1, 50),
        "train_new_only_default": "1" if _as_bool(payload.get("train_new_only_default"), True) else "0",
        "train_nightly_enabled": "1" if _as_bool(payload.get("train_nightly_enabled"), True) else "0",
        "train_nightly_hour": _si("train_nightly_hour", 0, 0, 23),
        "train_nightly_minute": _si("train_nightly_minute", 0, 0, 59),
        "train_schedule_tz": str(payload.get("train_schedule_tz") or "America/Toronto").strip()[:60] or "America/Toronto",
    }


def _refresh_anpr_config(db: Session) -> None:
    if not _set_anpr_config_fn:
        return
    _set_anpr_config_fn({
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


# ── Job helpers ───────────────────────────────────────────────────────────────

def _job_payload(job: Optional[TrainingJob]) -> Dict:
    if not job:
        return {
            "id": None, "status": "idle", "mode": None, "stage": "idle",
            "progress": 0, "message": "Idle", "total_samples": 0, "trained_samples": 0,
            "ocr_scanned": 0, "ocr_updated": 0, "chunk_size": 0, "chunk_index": 0,
            "chunk_total": 0, "run_dir": None, "model_path": None, "details": {},
            "error": None, "started_at": None, "updated_at": None, "finished_at": None,
            "run_started_at": None,
        }
    return {
        "id": job.id, "kind": job.kind, "status": job.status, "mode": job.mode,
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
        "run_dir": job.run_dir, "model_path": job.model_path,
        "details": job.details or {}, "error": job.error,
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


def _job_history_payload(job: TrainingJob) -> Dict:
    payload = _job_payload(job)
    payload["duration_seconds"] = _job_duration_seconds(job)
    return payload


def _append_training_job_log(job: TrainingJob, message: str) -> None:
    details = dict(job.details or {})
    logs: list = list(details.get("logs") or [])
    logs.append(f"{datetime.utcnow().isoformat()} {message}")
    if len(logs) > 200:
        logs = logs[-200:]
    details["logs"] = logs
    job.details = details


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
        details = dict(job.details or {})
        details.pop("backend", None)
        job.details = details
    job.updated_at = datetime.utcnow()
    if (job.status or "") in {"complete", "failed", "stopped"} and not job.finished_at:
        job.finished_at = datetime.utcnow()
    db.add(job)
    db.commit()


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
            _os.killpg(proc.pid, signal.SIGKILL)
        else:
            _os.killpg(proc.pid, signal.SIGTERM)
        return True
    except Exception:
        try:
            proc.kill() if force else proc.terminate()
            return True
        except Exception:
            return False


def _start_training_pipeline_thread(job_id: str) -> bool:
    global TRAIN_PIPELINE_THREAD
    with TRAIN_PIPELINE_LOCK:
        if TRAIN_PIPELINE_THREAD and TRAIN_PIPELINE_THREAD.is_alive():
            return False
        TRAIN_PIPELINE_STOP.clear()
        from routers._training_worker import run_training_pipeline_job
        TRAIN_PIPELINE_THREAD = threading.Thread(
            target=run_training_pipeline_job,
            args=(job_id, TRAIN_PIPELINE_STOP, _set_training_proc),
            daemon=True,
        )
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
) -> Dict:
    from routers.deps import create_notification
    running = _active_training_job(db)
    if running:
        _start_training_pipeline_thread(running.id)
        return {"ok": True, "job": _job_payload(running), "already_running": True}

    settings = _training_settings_payload(db)
    mode_resolved = (mode or ("new_only" if _as_bool(settings.get("train_new_only_default"), True) else "all")).strip().lower()
    if mode_resolved not in {"new_only", "all"}:
        mode_resolved = "new_only"
    chunk_size_resolved = max(100, min(5000, int(chunk_size or int(settings.get("train_chunk_size") or 1000))))
    chunk_epochs_resolved = max(1, min(50, int(chunk_epochs or int(settings.get("train_chunk_epochs") or 8))))
    ocr_prefill_resolved = _as_bool(run_ocr_prefill, True)
    ocr_learn_resolved = _as_bool(run_ocr_learn, True)

    job = _create_training_job(
        db, mode=mode_resolved, chunk_size=chunk_size_resolved,
        chunk_epochs=chunk_epochs_resolved, run_ocr_prefill=ocr_prefill_resolved,
        run_ocr_learn=ocr_learn_resolved, trigger=trigger,
    )
    _start_training_pipeline_thread(job.id)
    try:
        create_notification(
            db,
            title="Training queued",
            message=f"Training job {job.id} queued ({mode_resolved}, chunk={chunk_size_resolved})",
            level="info", kind="training",
            extra={"job_id": job.id, "mode": mode_resolved, "chunk_size": chunk_size_resolved},
        )
        db.commit()
    except Exception:
        pass
    return {"ok": True, "job": _job_payload(job), "already_running": False}


def _resume_training_pipeline_job(db: Session, job: TrainingJob) -> Dict:
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
    _append_training_job_log(job, "Resume requested")
    db.add(job)
    db.commit()
    started = _start_training_pipeline_thread(job.id)
    return {"ok": True, "job": _job_payload(job), "already_running": not started}


# ── OCR / Batch job helpers ───────────────────────────────────────────────────

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


def _batch_ocr_job_key(batch_id: str) -> str:
    return f"batch_ocr_job:{(batch_id or '').strip()[:80]}"


def _batch_ocr_stop_key(batch_id: str) -> str:
    return f"batch_ocr_stop:{(batch_id or '').strip()[:80]}"


def _batch_ocr_stop_requested(db: Session, batch_id: str) -> bool:
    return _as_bool(_get_app_setting(db, _batch_ocr_stop_key(batch_id), "0"), False)


def _set_batch_ocr_stop(db: Session, batch_id: str, value: bool) -> None:
    _set_app_setting(db, _batch_ocr_stop_key(batch_id), "1" if value else "0")


def _write_batch_ocr_job(db: Session, batch_id: str, payload: Dict) -> None:
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
        "message": str(payload.get("message") or "")[:80],
        "started_at": str(payload.get("started_at") or ""),
        "updated_at": str(payload.get("updated_at") or ""),
        "heartbeat_at": str(payload.get("heartbeat_at") or payload.get("updated_at") or ""),
        "finished_at": str(payload.get("finished_at") or ""),
        "error": str(payload.get("error") or "")[:80],
        "last_id": int(payload.get("last_id") or 0),
        "chunk_index": int(payload.get("chunk_index") or 0),
        "chunk_total": int(payload.get("chunk_total") or 0),
        "current_sample_id": int(payload.get("current_sample_id") or 0),
        "resumed_from": int(payload.get("resumed_from") or 0),
    }
    raw = json.dumps(compact, separators=(",", ":"))
    if len(raw) > 480:
        for k in ("current_sample_id", "chunk_total", "chunk_index", "resumed_from"):
            compact.pop(k, None)
        compact["message"] = compact["message"][:40]
        compact["error"] = compact["error"][:40]
        raw = json.dumps(compact, separators=(",", ":"))
    _set_app_setting(db, _batch_ocr_job_key(batch_id), raw)


def _finalize_batch_ocr_job_view(db: Session, batch_id: str, data: Dict, *, persist_if_stale: bool = True) -> Dict:
    status = str(data.get("status") or "").lower()
    updated_at = _parse_iso_datetime(data.get("updated_at"))
    started_at = _parse_iso_datetime(data.get("started_at"))
    finished_at = _parse_iso_datetime(data.get("finished_at"))
    processed = int(data.get("processed") or 0)
    total = max(0, int(data.get("total") or 0))
    now = datetime.utcnow()
    stale_seconds = int((now - updated_at).total_seconds()) if updated_at else None
    if status in {"running", "stopping"} and stale_seconds is not None and stale_seconds >= 180:
        data["status"] = "stale"
        data["error"] = data.get("error") or "Worker heartbeat stale"
        if persist_if_stale:
            _write_batch_ocr_job(db, batch_id, data)
            db.commit()
    elapsed = None
    if started_at:
        end = finished_at or now
        elapsed = max(1.0, (end - started_at).total_seconds())
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


def _get_batch_ocr_job(db: Session, batch_id: str) -> Optional[Dict]:
    raw = _get_app_setting(db, _batch_ocr_job_key(batch_id), "")
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return _finalize_batch_ocr_job_view(db, batch_id, data, persist_if_stale=True)


# ── OCR/learn helper ──────────────────────────────────────────────────────────

def _learn_ocr_corrections_from_db(db: Session) -> Dict:
    """Extract correction pairs from training samples and update the OCR char map."""
    rows = db.query(TrainingSample).filter(
        TrainingSample.plate_text.isnot(None),
        TrainingSample.plate_text != "",
        TrainingSample.notes.ilike("%OCR_%RAW:%"),
        TrainingSample.ignored.is_(False),
    ).all()

    pairs: Dict[str, str] = {}
    for row in rows:
        notes = row.notes or ""
        for prefix in ("OCR_PREFILL_RAW:", "OCR_REPROCESS_RAW:", "OCR_BATCH_RAW:"):
            idx = notes.find(prefix)
            if idx >= 0:
                raw = notes[idx + len(prefix):].split("\n")[0].strip().upper()
                correct = (row.plate_text or "").strip().upper()
                if raw and correct and raw != correct:
                    pairs[raw] = correct
    existing_raw = _get_app_setting(db, "ocr_char_map", "{}")
    try:
        existing: Dict = json.loads(existing_raw)
    except Exception:
        existing = {}
    existing.update(pairs)
    _set_app_setting(db, "ocr_char_map", json.dumps(existing))
    db.commit()
    return {"pairs": len(pairs), "learned_map": pairs, "replacements": len(existing)}


# ── Save training upload helper ───────────────────────────────────────────────

def _save_training_upload(content: bytes, original_name: str) -> Tuple[Optional[str], Optional[int], Optional[int]]:
    from services.file_utils import safe_filename as _safe_filename
    if not content:
        return None, None, None
    try:
        ext = Path(original_name).suffix.lower()
        if ext not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
            ext = ".jpg"
        filename = _safe_filename(original_name) or f"upload_{secrets.token_hex(6)}{ext}"
        rel = f"training/{filename}"
        abs_path = Path(MEDIA_DIR) / rel
        abs_path.parent.mkdir(parents=True, exist_ok=True)
        abs_path.write_bytes(content)
        size = _load_image_size(abs_path)
        w, h = (size or (None, None))
        return rel, w, h
    except Exception:
        return None, None, None


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/dataset_stats")
def dataset_stats(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    total = db.query(TrainingSample).count()
    annotated = db.query(TrainingSample).filter(
        TrainingSample.ignored.is_(False),
        or_(TrainingSample.bbox.isnot(None), TrainingSample.no_plate.is_(True)),
    ).count()
    with_bbox = db.query(TrainingSample).filter(TrainingSample.bbox.isnot(None), TrainingSample.ignored.is_(False)).count()
    with_text = db.query(TrainingSample).filter(
        TrainingSample.plate_text.isnot(None), TrainingSample.plate_text != "", TrainingSample.ignored.is_(False),
    ).count()
    negative = db.query(TrainingSample).filter(TrainingSample.no_plate.is_(True), TrainingSample.ignored.is_(False)).count()
    unclear = db.query(TrainingSample).filter(TrainingSample.unclear_plate.is_(True), TrainingSample.ignored.is_(False)).count()
    pending = db.query(TrainingSample).filter(
        TrainingSample.bbox.is_(None), TrainingSample.no_plate.is_(False), TrainingSample.ignored.is_(False),
    ).count()
    ignored = db.query(TrainingSample).filter(TrainingSample.ignored.is_(True)).count()
    trained = db.query(TrainingSample).filter(TrainingSample.last_trained_at.isnot(None)).count()
    from_system = db.query(TrainingSample).filter(TrainingSample.import_batch.is_(None)).count()
    from_dataset = db.query(TrainingSample).filter(TrainingSample.import_batch.isnot(None)).count()
    testable = db.query(TrainingSample).filter(
        TrainingSample.bbox.isnot(None),
        TrainingSample.plate_text.isnot(None),
        TrainingSample.plate_text != "",
        TrainingSample.ignored.is_(False),
    ).count()
    return {
        "total": total, "annotated": annotated, "with_bbox": with_bbox, "with_text": with_text,
        "negative": negative, "unclear": unclear, "pending": pending, "ignored": ignored,
        "trained": trained, "untrained": total - trained, "from_system": from_system,
        "from_dataset": from_dataset, "testable": testable,
        "annotation_rate": round(annotated / total * 100, 1) if total else 0,
        "trained_rate": round(trained / total * 100, 1) if total else 0,
    }


@router.post("/test_model")
def test_model(
    body: ApiModelTestBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    from difflib import SequenceMatcher
    from plate_detector import detect_plate

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
        return {"ok": False, "error": "No annotated samples with plate text found.", "results": [], "summary": {}}

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
            "sample_id": row.id, "image_path": row.image_path, "expected": expected,
            "predicted": None, "exact_match": False, "similarity": 0.0,
            "confidence": None, "detector": None, "error": None,
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
            exact = predicted == expected
            entry.update({
                "predicted": predicted, "exact_match": exact,
                "similarity": round(sim, 3),
                "confidence": round(float(conf), 3) if conf is not None else None,
                "detector": det.get("detector"),
            })
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
        "ok": True, "results": results,
        "summary": {
            "total_tested": tested, "detected": detected, "no_detection": no_detection,
            "exact_matches": exact_matches,
            "exact_accuracy": round(exact_matches / tested * 100, 1) if tested else 0,
            "fuzzy_accuracy": round(fuzzy_total / tested * 100, 1) if tested else 0,
            "avg_similarity": round(fuzzy_total / tested, 3) if tested else 0,
            "avg_confidence": round(conf_total / conf_count, 3) if conf_count else None,
            "detection_rate": round(detected / tested * 100, 1) if tested else 0,
        },
    }


@router.get("/status")
def training_status(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    active = _active_training_job(db)
    job = active or _latest_training_job(db)
    payload = _job_payload(job)
    return {**payload, "status": payload.get("status"), "message": payload.get("message"),
            "last_run_dir": payload.get("run_dir"), "last_model_path": payload.get("model_path")}


@router.get("/jobs")
def list_training_jobs(
    page: int = 1,
    limit: int = 20,
    status: str = "all",
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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
    page = min(page, pages)
    rows = qy.order_by(TrainingJob.started_at.desc(), TrainingJob.id.desc()).offset((page - 1) * limit).limit(limit).all()
    return {"items": [_job_history_payload(r) for r in rows], "total": int(total),
            "page": int(page), "pages": int(pages), "limit": int(limit), "status": status}


@router.post("/start")
def start_training(
    body: Optional[ApiTrainingStartBody] = None,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    return _start_training_pipeline_from_request(
        db,
        mode=(body.mode if body else None),
        chunk_size=(body.chunk_size if body else None),
        chunk_epochs=(body.chunk_epochs if body else None),
        run_ocr_prefill=(body.run_ocr_prefill if body else None),
        run_ocr_learn=(body.run_ocr_learn if body else None),
        trigger="api",
    )


@router.post("/stop")
def stop_training(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    job = _active_training_job(db)
    if not job:
        return {"ok": True, "stopped": False, "message": "No active job"}
    TRAIN_PIPELINE_STOP.set()
    _stop_training_proc(force=False)
    _touch_training_job(db, job, status="running", stage="stopping", message="Stop requested")
    return {"ok": True, "stopped": True, "job": _job_payload(job)}


@router.post("/resume")
def resume_training(
    job_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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


@router.get("/model/download")
def download_model(
    job_id: Optional[str] = None,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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
            candidates.extend([run_dir / "weights" / "best.pt", run_dir / "best.pt"])
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                model_path = candidate
                break
        if not model_path:
            raise HTTPException(status_code=404, detail="No model artifact found for this job")
    else:
        model_path = PROJECT_ROOT / "models" / "plate.pt"
    if not model_path or not model_path.exists():
        raise HTTPException(status_code=404, detail="Trained model not found")
    suffix = (str(job_id).strip() if job_id else datetime.utcnow().strftime("%Y%m%d_%H%M%S")).replace("/", "_")
    return FileResponse(str(model_path), media_type="application/octet-stream",
                        filename=f"carvision_plate_{suffix}.pt")


@router.post("/model/reset")
def reset_model(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    active = _active_training_job(db)
    if active:
        raise HTTPException(status_code=409, detail="Cannot reset model while training is active")
    model_path = PROJECT_ROOT / "models" / "plate.pt"
    existed = model_path.exists()
    if existed:
        try:
            model_path.unlink()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Failed to remove model: {exc}") from exc
    if _camera_manager:
        try:
            _camera_manager.sync()
        except Exception:
            logger.warning("camera_manager sync failed after model reset", exc_info=True)
    return {"ok": True, "removed": bool(existed), "path": str(model_path),
            "message": "Existing trained model removed. Future training will use the configured base model."}


@router.get("/settings")
def get_training_settings(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    return _training_settings_payload(db)


@router.post("/settings")
def update_training_settings(
    body: ApiTrainingSettingsBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    current = _training_settings_payload(db)
    incoming = body.dict(exclude_none=True)
    merged = {**current, **incoming}
    values = _sanitize_training_settings(merged)
    for key, val in values.items():
        _set_app_setting(db, key, val)
    db.commit()
    _refresh_anpr_config(db)
    return {"ok": True, "settings": _training_settings_payload(db)}


