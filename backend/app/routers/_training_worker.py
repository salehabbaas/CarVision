"""
routers/_training_worker.py — background worker for the YOLO training pipeline.

This module contains the long-running training job thread that is launched by
training.py via _start_training_pipeline_thread().  It is kept separate to
avoid circular imports and to keep training.py focused on the HTTP layer.
"""
from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import cv2
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from anpr import crop_from_bbox, read_plate_text
from core.config import MEDIA_DIR, PROJECT_ROOT
from db import SessionLocal
from models import AppSetting, TrainingSample, TrainingJob
from plate_detector import reload_yolo_model
from services.dataset import (
    bbox_xywh_to_xyxy as _bbox_xywh_to_xyxy,
    build_yolo_dataset_for_sample_ids as _build_yolo_dataset_for_sample_ids,
)
from services.state import set_training_status as _set_training_status

logger = logging.getLogger("carvision.training_worker")

# Stall watchdog — if training makes no progress for this many seconds, abort.
TRAIN_PIPELINE_STALL_TIMEOUT_SECONDS = int(
    __import__("os").getenv("TRAIN_PIPELINE_STALL_TIMEOUT_SECONDS", "1800") or "1800"
)


# ── Tiny helpers ──────────────────────────────────────────────────────────────

def _get_app_setting(db: Session, key: str, default: str = "") -> str:
    setting = db.get(AppSetting, key)
    if not setting or setting.value is None:
        return default
    return str(setting.value)


def _as_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _touch_job(db: Session, job: TrainingJob, **kwargs) -> None:
    """Thin wrapper — delegates to routers.training._touch_training_job."""
    from routers.training import _touch_training_job
    _touch_training_job(db, job, **kwargs)


def _resolve_train_device(requested: str) -> str:
    requested = (requested or "auto").strip().lower()
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
        files = list(api.list_repo_files(repo_id=repo_id, repo_type="model"))
        preferred = ["best.pt", "weights/best.pt", "model.pt", "last.pt", "weights/last.pt"]
        for candidate in preferred:
            if candidate in files:
                filename = candidate
                break
        if not filename:
            pt_files = [f for f in files if str(f).lower().endswith(".pt")]
            if not pt_files:
                raise RuntimeError(f"No .pt weight file found in Hugging Face repo '{repo_id}'.")
            filename = pt_files[0]

    local_dir = PROJECT_ROOT / "models" / "hf_cache"
    local_dir.mkdir(parents=True, exist_ok=True)
    return hf_hub_download(
        repo_id=repo_id, filename=filename, repo_type="model",
        local_dir=str(local_dir), local_dir_use_symlinks=False,
    )


def _training_pending_filter(mode: str, run_started_at: datetime):
    if mode == "all":
        return or_(
            TrainingSample.last_trained_at.is_(None),
            TrainingSample.last_trained_at < run_started_at,
        )
    return or_(
        TrainingSample.last_trained_at.is_(None),
        and_(
            TrainingSample.processed_at.isnot(None),
            or_(
                TrainingSample.last_trained_at.is_(None),
                TrainingSample.last_trained_at < TrainingSample.processed_at,
            ),
        ),
    )


def _compact_training_error_text(raw: object, fallback: str = "Training process failed") -> str:
    text = str(raw or "").replace("\r", "\n")
    lines = [line.strip() for line in text.splitlines() if line and line.strip()]
    if not lines:
        return fallback
    cleaned = []
    for line in lines:
        low = line.lower()
        if ("complete" in low and "|" in line and "%" in line) or \
           ("<?, ?b/s]" in low) or ("/s]" in low and "%" in low and "|" in line) or \
           "futurewarning:" in low or "deprecationwarning:" in low:
            continue
        cleaned.append(line)
    if not cleaned:
        return fallback
    preferred = None
    for line in reversed(cleaned):
        low = line.lower()
        if any(t in low for t in ("error", "exception", "failed", "not found", "no module named", "out of memory")):
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
    set_proc_fn: Optional[Callable] = None,
) -> Tuple[Path, Path]:
    worker = Path(__file__).resolve().parent.parent / "services" / "yolo_train_worker.py"
    with tempfile.NamedTemporaryFile(prefix="carvision_train_", suffix=".json", delete=False) as fh:
        result_path = Path(fh.name)

    cmd = [
        sys.executable, str(worker),
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
        cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        text=True, start_new_session=True,
    )
    if set_proc_fn:
        set_proc_fn(proc)

    started_at = time.time()
    stall_timeout = max(300, TRAIN_PIPELINE_STALL_TIMEOUT_SECONDS)
    result_csv = Path(run_root) / str(run_name) / "results.csv"
    last_progress_at = started_at
    last_results_mtime: Optional[float] = None
    last_beat = 0.0

    try:
        while proc.poll() is None:
            if stop_event and stop_event.is_set():
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise InterruptedError("Training stop requested")
            now = time.time()
            if result_csv.exists():
                try:
                    mtime = result_csv.stat().st_mtime
                    if last_results_mtime is None or mtime > last_results_mtime:
                        last_results_mtime = mtime
                        last_progress_at = now
                except Exception:
                    pass
            if now - last_progress_at >= stall_timeout:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                raise RuntimeError(
                    f"Training stalled for {int(now - last_progress_at)}s — chunk watchdog triggered."
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
        if set_proc_fn:
            set_proc_fn(None)
        try:
            result_path.unlink(missing_ok=True)
        except Exception:
            pass


# ── Main training pipeline worker ────────────────────────────────────────────

def run_training_pipeline_job(
    job_id: str,
    stop_event: threading.Event,
    set_proc_fn: Optional[Callable] = None,
) -> None:
    """Execute a full training pipeline job. Runs in a daemon thread."""
    local_db = SessionLocal()
    try:
        job = local_db.get(TrainingJob, job_id)
        if not job or (job.status or "") not in {"queued", "running"}:
            return

        from routers.training import _training_settings_payload, _get_app_setting as _gs
        run_started_at = job.run_started_at or datetime.utcnow()
        job.run_started_at = run_started_at
        _touch_job(local_db, job, status="running", stage="prepare", progress=1,
                   message="Preparing training pipeline")

        settings = _training_settings_payload(local_db)
        mode = (job.mode or "new_only").strip().lower()
        if mode not in {"new_only", "all"}:
            mode = "new_only"
        chunk_size = max(100, min(5000, int(job.chunk_size or int(settings.get("train_chunk_size") or 1000))))
        chunk_epochs = max(1, min(50, int((job.details or {}).get("chunk_epochs") or int(settings.get("train_chunk_epochs") or 8))))
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
            _touch_job(local_db, job, status="failed", stage="prepare", progress=100,
                       message="No positive annotated samples available for training",
                       error="no_positive_samples")
            return
        if total_samples <= 0:
            _touch_job(local_db, job, status="complete", stage="complete", progress=100,
                       message="No pending samples to train")
            return

        job.total_samples = int(total_samples)
        job.chunk_size = int(chunk_size)
        job.chunk_total = int((total_samples + chunk_size - 1) // chunk_size)
        job.details = {**(job.details or {}), "chunk_epochs": chunk_epochs,
                       "run_ocr_prefill": run_ocr_prefill, "run_ocr_learn": run_ocr_learn}
        local_db.add(job)
        local_db.commit()

        run_root = Path(MEDIA_DIR) / "training_runs"
        run_root.mkdir(parents=True, exist_ok=True)
        job.run_dir = str(run_root)
        model_name = settings.get("train_model") or "yolo26n.pt"

        try:
            from ultralytics import YOLO  # noqa: F401 — verify availability
        except Exception:
            _touch_job(local_db, job, status="failed", stage="prepare", progress=100,
                       message="Ultralytics not available", error="ultralytics_missing")
            return

        try:
            plate_model = PROJECT_ROOT / "models" / "plate.pt"
            current_model_source = str(plate_model) if plate_model.exists() else _resolve_train_model_source(model_name)
        except Exception as exc:
            _touch_job(local_db, job, status="failed", stage="prepare", progress=100,
                       message=f"Model source error: {exc}", error=str(exc))
            return

        epochs = int(settings.get("train_epochs") or 50)
        imgsz = int(settings.get("train_imgsz") or 640)
        batch = int(settings.get("train_batch") or -1)
        device = _resolve_train_device(settings.get("train_device") or "auto")
        patience = int(settings.get("train_patience") or 15)
        aug = {
            "hsv_h": float(_gs(local_db, "train_hsv_h", "0.015")),
            "hsv_s": float(_gs(local_db, "train_hsv_s", "0.7")),
            "hsv_v": float(_gs(local_db, "train_hsv_v", "0.4")),
            "degrees": float(_gs(local_db, "train_degrees", "5.0")),
            "translate": float(_gs(local_db, "train_translate", "0.1")),
            "scale": float(_gs(local_db, "train_scale", "0.5")),
            "shear": float(_gs(local_db, "train_shear", "2.0")),
            "perspective": float(_gs(local_db, "train_perspective", "0.0005")),
            "fliplr": float(_gs(local_db, "train_fliplr", "0.5")),
            "mosaic": float(_gs(local_db, "train_mosaic", "0.5")),
            "mixup": float(_gs(local_db, "train_mixup", "0.1")),
        }

        _touch_job(local_db, job, status="running", stage="detect_train", progress=5,
                   message=f"Detection training started ({total_samples} samples, chunk={chunk_size}, mode={mode})")

        trained_samples = int(job.trained_samples or 0)
        chunk_index = int(job.chunk_index or 0)

        # ── Chunk training loop ───────────────────────────────────────────────
        while True:
            if stop_event.is_set():
                _touch_job(local_db, job, status="stopped", stage="stopped",
                           progress=job.progress or 0, message="Training stop requested by admin")
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
            _touch_job(local_db, job, status="running", stage="detect_train",
                       progress=10 + ((chunk_index - 1) / max(1, job.chunk_total)) * 65,
                       message=f"Chunk {chunk_index}/{job.chunk_total}: preparing dataset ({len(chunk_ids)} samples)")

            dataset_subdir = f"training_yolo_jobs/{job.id}/chunk_{chunk_index:04d}"
            counts = _build_yolo_dataset_for_sample_ids(local_db, chunk_ids, dataset_subdir=dataset_subdir)

            if chunk_positive > 0 and int(counts.get("positives") or 0) > 0:
                run_name = f"{job.id}_c{chunk_index:04d}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
                _touch_job(local_db, job, status="running", stage="detect_train",
                           progress=12 + ((chunk_index - 1) / max(1, job.chunk_total)) * 65,
                           message=f"Chunk {chunk_index}/{job.chunk_total}: training detector for {chunk_epochs} epochs")

                def _heartbeat(pid: int, elapsed: int, _ci=chunk_index, _ct=job.chunk_total) -> None:
                    details = dict(job.details or {})
                    details["backend"] = {"activity": "detector_training", "pid": pid,
                                          "elapsed_seconds": elapsed, "chunk_index": _ci, "chunk_total": _ct}
                    job.details = details
                    local_db.add(job)
                    local_db.commit()
                    _touch_job(local_db, job, status="running", stage="detect_train",
                               progress=12 + ((_ci - 1) / max(1, _ct)) * 65,
                               message=f"Chunk {_ci}/{_ct}: detector training running ({elapsed}s, pid {pid})")

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
                    stop_event=stop_event,
                    heartbeat=_heartbeat,
                    set_proc_fn=set_proc_fn,
                )
                model_dest = PROJECT_ROOT / "models" / "plate.pt"
                model_dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(best, model_dest)
                current_model_source = str(model_dest)
                job.run_dir = str(save_dir)
                job.model_path = str(model_dest)
                details = dict(job.details or {})
                details["backend"] = {"activity": "detector_training_complete",
                                      "chunk_index": chunk_index, "chunk_total": int(job.chunk_total or 0)}
                job.details = details
                local_db.add(job)
                local_db.commit()

            now = datetime.utcnow()
            local_db.query(TrainingSample).filter(TrainingSample.id.in_(chunk_ids)).update(
                {TrainingSample.last_trained_at: now}, synchronize_session=False,
            )
            local_db.commit()
            trained_samples += len(chunk_ids)
            job.trained_samples = int(trained_samples)
            local_db.add(job)
            local_db.commit()
            _touch_job(local_db, job, status="running", stage="detect_train",
                       progress=10 + (trained_samples / max(1, total_samples)) * 70,
                       message=f"Chunk {chunk_index}/{job.chunk_total} complete ({trained_samples}/{total_samples} samples)")

        # ── OCR prefill pass ─────────────────────────────────────────────────
        if run_ocr_prefill:
            _touch_job(local_db, job, status="running", stage="ocr_prefill", progress=82,
                       message="OCR pass: extracting plate text from annotated boxes")
            ocr_scanned = 0
            ocr_updated = 0
            last_ocr_id = 0
            while True:
                if stop_event.is_set():
                    _touch_job(local_db, job, status="stopped", stage="stopped",
                               progress=job.progress or 0, message="Training stop requested")
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
                _touch_job(local_db, job, status="running", stage="ocr_prefill",
                           progress=82 + min(10, (ocr_scanned / max(1, total_samples)) * 10),
                           message=f"OCR prefill: scanned {ocr_scanned}, updated {ocr_updated}")

        # ── OCR correction learning ───────────────────────────────────────────
        if run_ocr_learn:
            _touch_job(local_db, job, status="running", stage="ocr_learn", progress=95,
                       message="Learning OCR corrections from manual fixes")
            from routers.training import _learn_ocr_corrections_from_db
            learn = _learn_ocr_corrections_from_db(local_db)
            details = dict(job.details or {})
            details["ocr_learn"] = {"pairs": int(learn.get("pairs") or 0),
                                     "replacements": int(learn.get("replacements") or 0)}
            job.details = details
            local_db.add(job)
            local_db.commit()

        # ── Finalise ──────────────────────────────────────────────────────────
        try:
            reload_yolo_model()
        except Exception:
            pass

        _touch_job(local_db, job, status="complete", stage="complete", progress=100,
                   message="Training pipeline completed successfully")

        try:
            from routers.deps import create_notification
            create_notification(
                local_db,
                title="Training completed",
                message=f"New model saved to {job.model_path or (PROJECT_ROOT / 'models' / 'plate.pt')}",
                level="success", kind="training",
                extra={"job_id": job.id, "run_dir": job.run_dir, "model_path": job.model_path},
            )
            local_db.commit()
        except Exception:
            pass

    except InterruptedError:
        try:
            job = local_db.get(TrainingJob, job_id)
            if job:
                _touch_job(local_db, job, status="stopped", stage="stopped",
                           progress=job.progress or 0, message="Training stopped")
        except Exception:
            pass
    except Exception as exc:
        logger.exception("Training job %s failed", job_id)
        try:
            job = local_db.get(TrainingJob, job_id)
            if job:
                summary = _compact_training_error_text(exc)
                _touch_job(local_db, job, status="failed", stage="failed", progress=100,
                           message=f"Training failed: {summary}", error=summary)
        except Exception:
            pass
    finally:
        local_db.close()
