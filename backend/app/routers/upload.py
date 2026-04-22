"""routers/upload.py — video/image upload job management."""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

from core.config import MEDIA_DIR
from routers.deps import get_current_user
from services.state import (
    cleanup_upload_jobs as _cleanup_upload_jobs,
    create_upload_job as _create_upload_job,
    get_upload_job as _get_upload_job,
    update_upload_job as _update_upload_job,
)

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])

# Populated by main.py app factory
_run_upload_job_fn = None


def _init(run_upload_job) -> None:
    global _run_upload_job_fn
    _run_upload_job_fn = run_upload_job


@router.post("/start")
async def upload_start(
    file: UploadFile = File(...),
    sample_seconds: float = Form(1.0),
    max_frames: int = Form(300),
    show_debug: Optional[bool] = Form(False),
    _user: str = Depends(get_current_user),
):
    if not _run_upload_job_fn:
        raise HTTPException(status_code=503, detail="Upload service not initialised")

    _cleanup_upload_jobs()
    filename = f"uploads/{int(time.time())}_{file.filename}"
    file_path = Path(MEDIA_DIR) / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    file_path.write_bytes(content)

    job_id = _create_upload_job(file.filename or file_path.name)
    thread = threading.Thread(
        target=_run_upload_job_fn,
        args=(job_id, file_path, file.content_type or "", float(sample_seconds), int(max_frames), bool(show_debug)),
        daemon=True,
    )
    thread.start()
    return {"ok": True, "job_id": job_id}


@router.get("/status/{job_id}")
def upload_status(
    job_id: str,
    _user: str = Depends(get_current_user),
):
    _cleanup_upload_jobs()
    job = _get_upload_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}
