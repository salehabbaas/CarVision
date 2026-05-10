"""routers/exports.py — full-system backup export and atomic import endpoints."""
from __future__ import annotations

import logging
import secrets
import shutil
import tempfile
import threading
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse

from routers._exports_state import (
    _CHUNK,
    _EXPORT_LOCK,
    _EXPORT_STATE,
    _get_export_state,
    _get_import_state,
    _set_export_state,
    _set_import_state,
)
from routers._export_worker import _run_export
from routers._import_worker import _run_import
from routers.deps import get_current_user

logger = logging.getLogger("carvision.routers.exports")
router = APIRouter(prefix="/api/v1/exports", tags=["exports"])

_EXPORT_THREAD: threading.Thread | None = None
_IMPORT_THREAD: threading.Thread | None = None


# ── Export endpoints ──────────────────────────────────────────────────────────

@router.post("/export/start")
def export_start(
    include_detection_images: bool = Query(default=False),
    _user: str = Depends(get_current_user),
) -> JSONResponse:
    """Start building a backup ZIP in the background. Poll /export/status for progress."""
    job_id = secrets.token_hex(8)

    with _EXPORT_LOCK:
        if _EXPORT_STATE["phase"] == "building":
            raise HTTPException(status_code=409, detail="An export is already in progress")

        # Clean up any previously built file before starting a new job
        old_file = _EXPORT_STATE.get("file_path")
        if old_file:
            Path(old_file).unlink(missing_ok=True)

        _EXPORT_STATE.update(
            phase="building",
            percent=0,
            message="Starting export…",
            error=None,
            job_id=job_id,
            file_path=None,
            filename=None,
        )

    global _EXPORT_THREAD
    _EXPORT_THREAD = threading.Thread(
        target=_run_export,
        args=(include_detection_images, job_id),
        daemon=True,
        name=f"carvision-export-{job_id}",
    )
    _EXPORT_THREAD.start()

    return JSONResponse({"ok": True, "job_id": job_id, "message": "Export started"})


@router.get("/export/status")
def export_status(_user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current export job state."""
    return _get_export_state()


@router.get("/download")
def export_download(_user: str = Depends(get_current_user)) -> FileResponse:
    """Serve the pre-built backup ZIP. Must call /export/start first.

    The file is kept on disk after serving so the user can download it again
    without rebuilding. It is deleted only when a new export is started.
    """
    state = _get_export_state()
    if state["phase"] not in {"ready", "done"} or not state.get("file_path"):
        raise HTTPException(
            status_code=409,
            detail="No backup is ready. Start an export with POST /export/start first.",
        )

    file_path = state["file_path"]
    if not Path(file_path).is_file():
        _set_export_state(phase="idle", percent=0, message="", error=None,
                          job_id=None, file_path=None, filename=None)
        raise HTTPException(
            status_code=404,
            detail="Backup file no longer exists. Please start a new export.",
        )

    filename = state["filename"] or "carvision-backup.zip"
    _set_export_state(phase="done", percent=100, message="Backup downloaded.")
    return FileResponse(file_path, media_type="application/zip", filename=filename)


# ── Import endpoints ──────────────────────────────────────────────────────────

@router.post("/import")
async def import_upload(
    file: UploadFile = File(...),
    _user: str = Depends(get_current_user),
) -> JSONResponse:
    """Upload a backup ZIP and import it atomically."""
    state = _get_import_state()
    if state["phase"] in {"validating", "importing", "uploading"}:
        raise HTTPException(status_code=409, detail="An import is already in progress")

    tmp_dir = Path(tempfile.mkdtemp(prefix="carvision_import_"))
    zip_path = tmp_dir / "upload.zip"

    try:
        # Stream upload to disk (avoids buffering large ZIPs in RAM)
        with zip_path.open("wb") as f:
            while True:
                chunk = await file.read(_CHUNK)
                if not chunk:
                    break
                f.write(chunk)

        # Basic ZIP integrity check + path-traversal guard before handing off
        try:
            with zipfile.ZipFile(zip_path) as zf:
                for info in zf.infolist():
                    name = info.filename.replace("\\", "/")
                    if name.startswith("..") or name.startswith("/"):
                        raise HTTPException(
                            status_code=400,
                            detail=f"Unsafe path in ZIP: {info.filename!r}",
                        )
                zf.extractall(tmp_dir / "extracted")
        except zipfile.BadZipFile:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise HTTPException(status_code=400, detail="Uploaded file is not a valid ZIP")

        zip_path.unlink(missing_ok=True)

    except HTTPException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Upload failed: {exc}") from exc

    job_id = secrets.token_hex(8)
    _set_import_state(phase="uploading", percent=20, message="Starting import…", error=None, job_id=job_id)

    global _IMPORT_THREAD
    _IMPORT_THREAD = threading.Thread(
        target=_run_import,
        args=(tmp_dir / "extracted", job_id),
        daemon=True,
        name=f"carvision-import-{job_id}",
    )
    _IMPORT_THREAD.start()

    return JSONResponse({"ok": True, "job_id": job_id, "message": "Import started"})


@router.get("/import/status")
def import_status(_user: str = Depends(get_current_user)) -> dict[str, Any]:
    """Return the current import job state."""
    return _get_import_state()
