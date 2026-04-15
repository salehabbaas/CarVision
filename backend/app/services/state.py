import secrets
import threading
import time
from datetime import datetime
from typing import Dict, Optional

TRAINING_STATUS: Dict[str, Optional[str]] = {
    "status": "idle",
    "message": "Idle",
    "started_at": None,
    "updated_at": None,
    "last_run_dir": None,
    "last_model_path": None,
    "log": [],
}
TRAINING_LOCK = threading.Lock()

UPLOAD_JOBS: Dict[str, Dict[str, object]] = {}
UPLOAD_LOCK = threading.Lock()

# Track the latest OCR prefill job ID so the frontend can recover it after a page refresh
_LATEST_OCR_JOB_ID: Optional[str] = None
_LATEST_OCR_LOCK = threading.Lock()


def set_latest_ocr_job(job_id: str) -> None:
    global _LATEST_OCR_JOB_ID
    with _LATEST_OCR_LOCK:
        _LATEST_OCR_JOB_ID = job_id


def get_latest_ocr_job_id() -> Optional[str]:
    with _LATEST_OCR_LOCK:
        return _LATEST_OCR_JOB_ID


def set_training_status(status: str, message: str, run_dir: Optional[str] = None, model_path: Optional[str] = None):
    with TRAINING_LOCK:
        TRAINING_STATUS["status"] = status
        TRAINING_STATUS["message"] = message
        TRAINING_STATUS["updated_at"] = datetime.utcnow().isoformat()
        if status == "running":
            TRAINING_STATUS["started_at"] = datetime.utcnow().isoformat()
        if run_dir is not None:
            TRAINING_STATUS["last_run_dir"] = run_dir
        if model_path is not None:
            TRAINING_STATUS["last_model_path"] = model_path
        log = TRAINING_STATUS.get("log")
        if not isinstance(log, list):
            log = []
        ts = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        log.append(f"[{ts}] {status.upper()}: {message}")
        TRAINING_STATUS["log"] = log[-200:]


def get_training_status() -> Dict[str, Optional[str]]:
    with TRAINING_LOCK:
        return dict(TRAINING_STATUS)


def cleanup_upload_jobs(max_age_sec: int = 3600):
    now = time.time()
    with UPLOAD_LOCK:
        old_ids = []
        for job_id, job in UPLOAD_JOBS.items():
            updated_ts = float(job.get("updated_ts") or now)
            if now - updated_ts > max_age_sec:
                old_ids.append(job_id)
        for job_id in old_ids:
            UPLOAD_JOBS.pop(job_id, None)


def create_upload_job(filename: str) -> str:
    job_id = secrets.token_urlsafe(10)
    now = datetime.utcnow().isoformat()
    now_ts = time.time()
    with UPLOAD_LOCK:
        UPLOAD_JOBS[job_id] = {
            "id": job_id,
            "status": "queued",
            "progress": 0,
            "message": "Queued",
            "steps": [f"{now} · Upload queued for {filename}"],
            "result": None,
            "error": None,
            "created_at": now,
            "started_ts": now_ts,   # wall-clock seconds — used by frontend for ETA
            "updated_at": now,
            "updated_ts": now_ts,
        }
    return job_id


def update_upload_job(
    job_id: str,
    *,
    status: Optional[str] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    step: Optional[str] = None,
    result: Optional[Dict] = None,
    error: Optional[str] = None,
):
    now_iso = datetime.utcnow().isoformat()
    now_ts = time.time()
    with UPLOAD_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if not job:
            return
        if status:
            job["status"] = status
        if progress is not None:
            try:
                job["progress"] = max(0, min(100, int(progress)))
            except Exception:
                pass
        if message is not None:
            job["message"] = message
        if step:
            steps = job.get("steps") or []
            steps.append(f"{now_iso} · {step}")
            job["steps"] = steps[-120:]
        if result is not None:
            job["result"] = result
        if error is not None:
            job["error"] = error
        job["updated_at"] = now_iso
        job["updated_ts"] = now_ts


def get_upload_job(job_id: str) -> Optional[Dict[str, object]]:
    with UPLOAD_LOCK:
        job = UPLOAD_JOBS.get(job_id)
        if not job:
            return None
        return {
            "id": job.get("id"),
            "status": job.get("status"),
            "progress": job.get("progress"),
            "message": job.get("message"),
            "steps": list(job.get("steps") or []),
            "result": job.get("result"),
            "error": job.get("error"),
            "created_at": job.get("created_at"),
            "started_ts": job.get("started_ts"),
            "updated_at": job.get("updated_at"),
            "updated_ts": job.get("updated_ts"),
        }
