"""routers/training_samples.py — sample import/annotation/OCR batch routes."""
from __future__ import annotations

import secrets
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import case, func, or_
from sqlalchemy.orm import Session

from api.schemas import ApiTrainingAnnotateBody, ApiTrainingIgnoreBody, ApiTrainingSampleIdsBody
from db import get_db
from models import TrainingSample
from routers import training as core
from routers.deps import get_current_user, training_sample_payload

router = APIRouter(prefix="/api/v1/training", tags=["training"])

@router.get("/samples")
def list_samples(
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
    _user: str = Depends(get_current_user),
):
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
            TrainingSample.bbox.is_(None), TrainingSample.no_plate.is_(False), TrainingSample.ignored.is_(False),
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
        qy = qy.filter(TrainingSample.bbox.is_(None), TrainingSample.no_plate.is_(False), TrainingSample.ignored.is_(False))
    elif status == "ignored":
        qy = qy.filter(TrainingSample.ignored.is_(True))
    elif status == "unclear":
        qy = qy.filter(TrainingSample.unclear_plate.is_(True), TrainingSample.ignored.is_(False))

    if q:
        q_like = f"%{q.strip()}%"
        qy = qy.filter(or_(
            TrainingSample.plate_text.ilike(q_like),
            TrainingSample.image_path.ilike(q_like),
            TrainingSample.notes.ilike(q_like),
        ))
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
    page = min(page, pages)
    sort_map = {
        "id": TrainingSample.id, "created_at": TrainingSample.created_at,
        "updated_at": TrainingSample.updated_at, "plate_text": TrainingSample.plate_text,
        "processed_at": TrainingSample.processed_at, "last_trained_at": TrainingSample.last_trained_at,
    }
    sort_col = sort_map.get(sort_by, TrainingSample.created_at)
    sort_expr = sort_col.asc() if sort_dir == "asc" else sort_col.desc()
    rows = qy.order_by(sort_expr).offset((page - 1) * page_size).limit(page_size).all()
    return {
        "counts": counts,
        "items": [training_sample_payload(r) for r in rows],
        "batch": batch_filter or None, "source": source, "has_text": has_text,
        "processed": processed, "trained": trained, "sort_by": sort_by, "sort_dir": sort_dir,
        "pagination": {"page": page, "page_size": page_size, "total_items": total_filtered, "total_pages": pages},
    }


@router.get("/samples/{sample_id}")
def get_sample(sample_id: int, db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    row = db.get(TrainingSample, sample_id)
    if not row:
        raise HTTPException(status_code=404, detail="Sample not found")
    return {"item": training_sample_payload(row), "debug_steps": core._build_training_debug(row)}


@router.post("/upload")
async def upload_samples(
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    created_ids: List[int] = []
    batch_id = f"img_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    for file in files:
        if not file.content_type or not file.content_type.startswith("image/"):
            continue
        content = await file.read()
        if not content:
            continue
        image_hash = core._hash_bytes(content)
        rel_path, width, height = core._save_training_upload(content, file.filename or "upload.jpg")
        if not rel_path:
            continue
        sample = TrainingSample(
            image_path=rel_path, image_hash=image_hash,
            image_width=width, image_height=height, import_batch=batch_id,
        )
        db.add(sample)
        db.flush()
        created_ids.append(sample.id)
    if created_ids:
        db.commit()
    return {"ok": True, "created": len(created_ids), "ids": created_ids,
            "batch_id": batch_id if created_ids else None}


@router.post("/import")
async def import_samples(
    files: Optional[List[UploadFile]] = File(None),
    dataset_zip: Optional[UploadFile] = File(None),
    has_annotations: bool = Form(False),
    annotations_format: str = Form("yolo"),
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    image_files = files or []
    if not image_files and dataset_zip is None:
        raise HTTPException(status_code=400, detail="Provide images and/or a ZIP dataset")
    fmt = (annotations_format or "yolo").strip().lower()
    if bool(has_annotations) and fmt != "yolo":
        raise HTTPException(status_code=400, detail="Only YOLO annotations are currently supported")

    batch_id = f"import_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(3)}"
    created_ids: List[int] = []
    updated_existing = 0
    annotated = negatives = pending = 0
    annotations_detected = False
    existing_by_hash: Dict[str, Optional[TrainingSample]] = {}

    def _resolve_size(sample: TrainingSample, w: int, h: int) -> Tuple[int, int]:
        if (w <= 0 or h <= 0) and sample.image_path:
            try:
                sz = core._load_image_size(Path(core.MEDIA_DIR) / str(sample.image_path))
                if sz:
                    sample.image_width, sample.image_height = int(sz[0]), int(sz[1])
                    return sample.image_width, sample.image_height
            except Exception:
                pass
        return int(w or 0), int(h or 0)

    def _label_to_entries(label_text: Optional[str], w: int, h: int) -> List[Dict]:
        text = (label_text or "").strip()
        if not text:
            return [{"kind": "negative"}]
        boxes = core._extract_yolo_bboxes(text, w, h)
        if boxes:
            return [{"kind": "bbox", "bbox": b} for b in boxes]
        return [{"kind": "pending"}]

    def _apply_entry(sample: TrainingSample, entry: Dict, w: int, h: int) -> str:
        w, h = _resolve_size(sample, w, h)
        kind = str(entry.get("kind") or "pending")
        if kind == "negative":
            sample.no_plate = True; sample.unclear_plate = False
            sample.bbox = None; sample.plate_text = None
            sample.notes = "Imported as negative sample from empty YOLO label."
            return "negative"
        if kind == "bbox":
            bbox = entry.get("bbox")
            if isinstance(bbox, dict):
                sample.no_plate = False; sample.unclear_plate = False; sample.bbox = bbox
                sample.notes = "Imported YOLO bbox. Add/correct plate text before training."
                return "annotated"
        sample.notes = "Imported sample pending annotation."
        return "pending"

    def add_sample(image_bytes: bytes, filename: str, label_text: Optional[str] = None):
        nonlocal annotated, negatives, pending, updated_existing
        if not image_bytes:
            return
        image_hash = core._hash_bytes(image_bytes)
        existing = existing_by_hash.get(image_hash)
        if image_hash not in existing_by_hash:
            existing = db.query(TrainingSample).filter(TrainingSample.image_hash == image_hash).order_by(
                TrainingSample.updated_at.desc(), TrainingSample.id.desc()
            ).first()
            existing_by_hash[image_hash] = existing
        if existing is not None:
            if label_text is not None:
                entries = _label_to_entries(label_text, int(existing.image_width or 0), int(existing.image_height or 0))
                state = _apply_entry(existing, entries[0], int(existing.image_width or 0), int(existing.image_height or 0))
                if state == "annotated": annotated += 1
                elif state == "negative": negatives += 1
                else: pending += 1
                updated_existing += 1
                db.add(existing)
                for extra in entries[1:]:
                    es = TrainingSample(image_path=existing.image_path, image_hash=existing.image_hash,
                                       image_width=existing.image_width, image_height=existing.image_height,
                                       import_batch=batch_id)
                    state = _apply_entry(es, extra, int(existing.image_width or 0), int(existing.image_height or 0))
                    if state == "annotated": annotated += 1
                    elif state == "negative": negatives += 1
                    else: pending += 1
                    db.add(es); db.flush(); created_ids.append(es.id)
            return
        rel_path, width, height = core._save_training_upload(image_bytes, filename or "import.jpg")
        if not rel_path:
            return
        entries = _label_to_entries(label_text, int(width or 0), int(height or 0)) if label_text is not None else [{"kind": "pending"}]
        first_sample = None
        for idx, entry in enumerate(entries):
            sample = TrainingSample(image_path=rel_path, image_hash=image_hash, image_width=width,
                                    image_height=height, import_batch=batch_id)
            state = _apply_entry(sample, entry, int(width or 0), int(height or 0))
            if state == "annotated": annotated += 1
            elif state == "negative": negatives += 1
            else: pending += 1
            db.add(sample); db.flush(); created_ids.append(sample.id)
            if idx == 0:
                first_sample = sample
        if first_sample:
            existing_by_hash[image_hash] = first_sample

    if image_files:
        text_map: Dict[str, str] = {}
        image_payloads: List[Tuple[str, bytes]] = []
        for file in image_files:
            name = (file.filename or "upload").strip()
            content = await file.read()
            if not content:
                continue
            if core._is_image_filename(name) or (file.content_type and file.content_type.startswith("image/")):
                image_payloads.append((name, content))
            elif Path(name).suffix.lower() == ".txt":
                text_map[Path(name).stem.lower()] = content.decode("utf-8", errors="ignore")
        if text_map:
            annotations_detected = True
        use_annotations = bool(has_annotations) or bool(text_map)
        for name, content in image_payloads:
            label = text_map.get(Path(name).stem.lower()) if use_annotations else None
            add_sample(content, name, label)

    if dataset_zip is not None:
        temp_dir = Path(core.MEDIA_DIR) / "temp_imports"
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
                        if core._is_image_filename(low):
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
                            for cand in core._zip_label_candidates(name):
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
        "ok": True, "created": len(created_ids), "ids": created_ids,
        "batch_id": batch_id if (created_ids or updated_existing) else None,
        "has_annotations": bool(has_annotations) or bool(annotations_detected),
        "annotations_detected": bool(annotations_detected),
        "updated_existing": updated_existing,
        "annotated": annotated, "negatives": negatives, "pending": pending,
    }


@router.get("/import_batches")
def list_import_batches(
    limit: int = 200,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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
        annotated_count = int(row.annotated or 0)
        items.append({
            "batch": row.batch, "total": total, "annotated": annotated_count, "negatives": negatives,
            "pending": max(0, total - negatives - annotated_count),
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            "ocr_job": core._get_batch_ocr_job(db, row.batch),
        })
    return {"items": items}


@router.delete("/import_batches/{batch_id}")
def delete_import_batch(
    batch_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    batch = (batch_id or "").strip()
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    rows = db.query(TrainingSample).filter(TrainingSample.import_batch == batch).order_by(TrainingSample.id.asc()).all()
    if not rows:
        raise HTTPException(status_code=404, detail="Import batch not found")
    image_paths = {str(r.image_path or "").strip() for r in rows if r.image_path}
    deleted = len(rows)
    for row in rows:
        db.delete(row)
    db.flush()
    removed_files = 0
    for rel in image_paths:
        if db.query(TrainingSample.id).filter(TrainingSample.image_path == rel).first():
            continue
        abs_path = Path(core.MEDIA_DIR) / rel
        try:
            if abs_path.exists():
                abs_path.unlink()
                removed_files += 1
        except Exception:
            pass
    db.commit()
    return {"ok": True, "batch_id": batch, "deleted": deleted, "removed_files": removed_files}


@router.post("/import_batches/{batch_id}/ocr/reprocess")
def core_reprocess_batch_ocr(
    batch_id: str,
    chunk_size: int = 1000,
    resume: bool = True,
    force_restart: bool = False,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    batch = (batch_id or "").strip()[:80]
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    safe_chunk = max(100, min(int(chunk_size or 1000), 2000))

    total = db.query(TrainingSample.id).filter(
        TrainingSample.import_batch == batch,
        TrainingSample.ignored.is_(False),
        TrainingSample.no_plate.is_(False),
        TrainingSample.bbox.isnot(None),
    ).count()
    if total <= 0:
        raise HTTPException(status_code=404, detail="No annotated import samples found for this batch")

    existing = core._get_batch_ocr_job(db, batch)
    if existing:
        existing_status = str(existing.get("status") or "").lower()
        stale_seconds = int(existing.get("stale_seconds") or 0)
        if existing_status in {"running", "stopping"} and stale_seconds < 180:
            return {"ok": True, "job": existing, "already_running": True}

    resumed_from = initial_processed = initial_updated = initial_skipped = 0
    if existing and resume and not force_restart:
        resumed_from = max(0, int(existing.get("last_id") or 0))
        initial_processed = max(0, int(existing.get("processed") or 0))
        initial_updated = max(0, int(existing.get("updated") or 0))
        initial_skipped = max(0, int(existing.get("skipped") or 0))

    core._set_batch_ocr_stop(db, batch, False)
    now_iso = core._utc_iso_now()
    job_id = secrets.token_urlsafe(10)
    chunk_total = max(1, (int(total) + safe_chunk - 1) // safe_chunk)
    job = {
        "id": job_id, "batch": batch, "status": "running",
        "progress": int((initial_processed / max(1, int(total))) * 100),
        "processed": initial_processed, "updated": initial_updated, "skipped": initial_skipped,
        "total": int(total), "chunk_size": safe_chunk,
        "message": "Queued (resuming)" if resumed_from > 0 else "Queued",
        "started_at": now_iso, "updated_at": now_iso, "heartbeat_at": now_iso, "finished_at": "",
        "error": "", "last_id": resumed_from, "chunk_index": initial_processed // safe_chunk,
        "chunk_total": chunk_total, "speed_sps": 0.0, "eta_seconds": 0,
        "current_sample_id": 0, "resumed_from": resumed_from,
    }
    core._write_batch_ocr_job(db, batch, job)
    db.commit()

    def _run_batch_ocr():
        local_db = core.SessionLocal()
        try:
            processed = int(initial_processed)
            updated = int(initial_updated)
            skipped = int(initial_skipped)
            last_id = int(resumed_from)
            chunk_index = int(processed // safe_chunk)
            started_dt = core._parse_iso_datetime(now_iso) or datetime.utcnow()
            while True:
                if core._batch_ocr_stop_requested(local_db, batch):
                    core._write_batch_ocr_job(local_db, batch, {**job, "status": "stopped", "message": "Stopped by admin",
                                                             "finished_at": core._utc_iso_now(), "updated_at": core._utc_iso_now()})
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
                for sample in rows:
                    if core._batch_ocr_stop_requested(local_db, batch):
                        break
                    last_id = sample.id
                    processed += 1
                    if (sample.plate_text or "").strip():
                        skipped += 1
                        continue
                    try:
                        frame = cv2.imread(str(Path(core.MEDIA_DIR) / str(sample.image_path or "")))
                        if frame is None:
                            skipped += 1
                            continue
                        if core._crop_from_bbox_fn:
                            crop = core._crop_from_bbox_fn(frame, core._bbox_xywh_to_xyxy(sample.bbox or {}))
                        else:
                            crop = frame
                        if crop is None:
                            skipped += 1
                            continue
                        ocr = (core._read_plate_text_fn(crop) or {}) if core._read_plate_text_fn else {}
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
                core._write_batch_ocr_job(local_db, batch, {
                    **job, "status": "running",
                    "progress": int((processed / max(1, total)) * 100),
                    "processed": processed, "updated": updated, "skipped": skipped,
                    "message": f"Processed {processed}/{total}", "updated_at": core._utc_iso_now(),
                    "heartbeat_at": core._utc_iso_now(), "last_id": last_id, "chunk_index": chunk_index,
                    "speed_sps": speed_sps, "eta_seconds": eta_seconds,
                })
                local_db.commit()
            core._write_batch_ocr_job(local_db, batch, {
                **job, "status": "complete", "progress": 100, "processed": processed,
                "updated": updated, "skipped": skipped,
                "message": f"Completed: {updated} updated, {skipped} skipped",
                "finished_at": core._utc_iso_now(), "updated_at": core._utc_iso_now(), "last_id": last_id,
            })
            local_db.commit()
        except Exception as exc:
            try:
                local_db.rollback()
            except Exception:
                pass
            core._write_batch_ocr_job(local_db, batch, {**job, "status": "failed", "error": str(exc),
                                                     "finished_at": core._utc_iso_now(), "updated_at": core._utc_iso_now()})
            try:
                local_db.commit()
            except Exception:
                pass
        finally:
            local_db.close()

    threading.Thread(target=_run_batch_ocr, daemon=True).start()
    return {"ok": True, "job": job, "already_running": False}


@router.get("/import_batches/{batch_id}/ocr/reprocess")
def get_batch_ocr_status(
    batch_id: str,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    batch = (batch_id or "").strip()[:80]
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    job = core._get_batch_ocr_job(db, batch)
    if not job:
        raise HTTPException(status_code=404, detail="No OCR job found for this batch")
    return {"ok": True, "job": job}


@router.post("/import_batches/{batch_id}/ocr/control")
def control_batch_ocr(
    batch_id: str,
    action: str = "stop",
    chunk_size: int = 1000,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    batch = (batch_id or "").strip()[:80]
    if not batch:
        raise HTTPException(status_code=400, detail="Batch id is required")
    action_norm = (action or "stop").strip().lower()
    if action_norm not in {"stop", "resume", "restart", "clear"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    if action_norm == "stop":
        core._set_batch_ocr_stop(db, batch, True)
        job = core._get_batch_ocr_job(db, batch)
        if job and str(job.get("status") or "").lower() == "running":
            job["status"] = "stopping"
            job["message"] = "Stop requested by admin"
            job["updated_at"] = core._utc_iso_now()
            core._write_batch_ocr_job(db, batch, job)
        db.commit()
        return {"ok": True, "action": action_norm, "job": core._get_batch_ocr_job(db, batch)}
    if action_norm == "clear":
        core._set_app_setting(db, core._batch_ocr_job_key(batch), "")
        core._set_batch_ocr_stop(db, batch, False)
        db.commit()
        return {"ok": True, "action": action_norm}
    # resume or restart
    return core_reprocess_batch_ocr(
        batch_id=batch,
        chunk_size=chunk_size,
        resume=(action_norm == "resume"),
        force_restart=(action_norm == "restart"),
        db=db,
        _user="admin",
    )


@router.post("/ocr/prefill")
def ocr_prefill(
    batch: str = "",
    source: str = "all",
    limit: int = 0,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    batch_norm = batch.strip()[:80]
    source_norm = (source or "all").strip().lower()
    safe_limit = max(0, int(limit or 0))

    core._cleanup_upload_jobs()
    job_id = core._create_upload_job("ocr_prefill")
    core._set_latest_ocr_job(job_id)

    def _run():
        local_db = core.SessionLocal()
        try:
            core._update_upload_job(job_id, status="running", progress=1, message="Starting OCR prefill", step="Preparing")
            q = local_db.query(TrainingSample).filter(
                TrainingSample.ignored.is_(False), TrainingSample.no_plate.is_(False),
                TrainingSample.bbox.isnot(None),
                or_(TrainingSample.plate_text.is_(None), TrainingSample.plate_text == ""),
            )
            if batch_norm:
                q = q.filter(TrainingSample.import_batch == batch_norm)
            elif source_norm == "system":
                q = q.filter(TrainingSample.import_batch.is_(None))
            elif source_norm == "dataset":
                q = q.filter(TrainingSample.import_batch.isnot(None))
            q = q.order_by(TrainingSample.id.asc())
            samples = q.limit(safe_limit).all() if safe_limit > 0 else q.all()
            total = len(samples)
            scanned = updated = skipped = 0
            if total == 0:
                core._update_upload_job(job_id, status="complete", progress=100, message="No samples found",
                                   result={"scanned": 0, "updated": 0, "skipped": 0, "total": 0})
                return
            for sample in samples:
                scanned += 1
                try:
                    path = Path(core.MEDIA_DIR) / str(sample.image_path)
                    frame = cv2.imread(str(path))
                    if frame is None:
                        skipped += 1
                    else:
                        crop = (core._crop_from_bbox_fn(frame, core._bbox_xywh_to_xyxy(sample.bbox or {}))
                                if core._crop_from_bbox_fn else frame)
                        if crop is None:
                            skipped += 1
                        else:
                            ocr = (core._read_plate_text_fn(crop) or {}) if core._read_plate_text_fn else {}
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
                    core._update_upload_job(job_id, status="running",
                                       progress=int((scanned / total) * 100),
                                       message=f"Processed {scanned}/{total} — updated {updated}",
                                       step=f"Updated {updated}, skipped {skipped}",
                                       result={"scanned": scanned, "updated": updated, "skipped": skipped, "total": total})
            local_db.commit()
            core._update_upload_job(job_id, status="complete", progress=100,
                               message=f"OCR prefill completed ({updated} updated)",
                               step="Finished",
                               result={"scanned": scanned, "updated": updated, "skipped": skipped, "total": total})
        except Exception as exc:
            try:
                local_db.rollback()
            except Exception:
                pass
            core._update_upload_job(job_id, status="failed", progress=100,
                               message=f"OCR prefill failed: {exc}", error=str(exc))
        finally:
            local_db.close()

    threading.Thread(target=_run, daemon=True).start()
    return {"ok": True, "job_id": job_id}


@router.get("/ocr/prefill/latest")
def ocr_prefill_latest(_user: str = Depends(get_current_user)):
    job_id = core._get_latest_ocr_job_id()
    if not job_id:
        return {"ok": True, "job": None}
    job = core._get_upload_job(job_id)
    return {"ok": True, "job": job}


@router.get("/ocr/prefill/{job_id}")
def ocr_prefill_status(job_id: str, _user: str = Depends(get_current_user)):
    core._cleanup_upload_jobs()
    job = core._get_upload_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {"ok": True, "job": job}


@router.post("/ocr/learn")
def ocr_learn(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    result = core._learn_ocr_corrections_from_db(db)
    return {
        "ok": True,
        "pairs": int(result.get("pairs") or 0),
        "learned_map": result.get("learned_map") or {},
        "replacements": int(result.get("replacements") or 0),
    }


@router.patch("/samples/{sample_id}/annotate")
def annotate_sample(
    sample_id: int,
    body: ApiTrainingAnnotateBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if body.no_plate:
        sample.no_plate = True; sample.unclear_plate = False
        sample.bbox = None; sample.plate_text = None
    else:
        sample.no_plate = False
        sample.unclear_plate = bool(body.unclear_plate)
        if (body.bbox_x is not None and body.bbox_y is not None
                and body.bbox_w is not None and body.bbox_h is not None
                and body.bbox_w > 0 and body.bbox_h > 0):
            sample.bbox = {"x": int(body.bbox_x), "y": int(body.bbox_y),
                           "w": int(body.bbox_w), "h": int(body.bbox_h)}
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
    return {"ok": True, "item": training_sample_payload(sample), "debug_steps": core._build_training_debug(sample)}


@router.post("/samples/{sample_id}/reprocess")
def reprocess_sample(
    sample_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if sample.no_plate:
        raise HTTPException(status_code=400, detail="Sample is marked as no-plate")
    if not sample.bbox:
        raise HTTPException(status_code=400, detail="Sample has no bbox")
    if not core._read_plate_text_fn:
        raise HTTPException(status_code=503, detail="OCR service not initialised")
    path = Path(core.MEDIA_DIR) / str(sample.image_path or "")
    frame = cv2.imread(str(path))
    if frame is None:
        raise HTTPException(status_code=400, detail="Could not read sample image")
    crop = core._crop_from_bbox_fn(frame, core._bbox_xywh_to_xyxy(sample.bbox or {})) if core._crop_from_bbox_fn else frame
    if crop is None:
        raise HTTPException(status_code=400, detail="Could not crop sample bbox")
    ocr = core._read_plate_text_fn(crop) or {}
    plate_text = str(ocr.get("plate_text") or "").strip().upper()
    raw_text = str(ocr.get("raw_text") or plate_text).strip()
    if plate_text:
        sample.plate_text = plate_text[:50]
        sample.unclear_plate = False
    sample.notes = f"OCR_REPROCESS_RAW:{raw_text}\n{(sample.notes or '').strip()}".strip()
    sample.processed_at = datetime.utcnow()
    sample.ignored = False
    db.add(sample)
    db.commit()
    return {"ok": True, "plate_text": sample.plate_text, "raw_text": raw_text,
            "item": training_sample_payload(sample), "debug_steps": core._build_training_debug(sample)}


@router.post("/samples/reprocess")
def bulk_reprocess_samples(
    body: ApiTrainingSampleIdsBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    ids = [int(x) for x in (body.sample_ids or []) if int(x) > 0]
    if not ids:
        return {"ok": True, "processed": 0, "updated": 0, "failed": 0}
    updated = failed = processed = 0
    for sid in ids:
        sample = db.get(TrainingSample, sid)
        if not sample or sample.no_plate or not sample.bbox:
            failed += 1
            continue
        path = Path(core.MEDIA_DIR) / str(sample.image_path or "")
        frame = cv2.imread(str(path))
        if frame is None:
            failed += 1
            continue
        crop = core._crop_from_bbox_fn(frame, core._bbox_xywh_to_xyxy(sample.bbox or {})) if core._crop_from_bbox_fn else frame
        if crop is None:
            failed += 1
            continue
        ocr = (core._read_plate_text_fn(crop) or {}) if core._read_plate_text_fn else {}
        plate_text = str(ocr.get("plate_text") or "").strip().upper()
        raw_text = str(ocr.get("raw_text") or plate_text).strip()
        if plate_text:
            sample.plate_text = plate_text[:50]
            sample.unclear_plate = False
            updated += 1
        sample.notes = f"OCR_REPROCESS_RAW:{raw_text}\n{(sample.notes or '').strip()}".strip()
        sample.processed_at = datetime.utcnow()
        db.add(sample)
        processed += 1
    db.commit()
    return {"ok": True, "processed": processed, "updated": updated, "failed": failed}


@router.post("/samples/{sample_id}/ignore")
def toggle_sample_ignore(
    sample_id: int,
    body: ApiTrainingIgnoreBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if body.ignored is None:
        sample.ignored = not bool(sample.ignored)
    else:
        sample.ignored = bool(body.ignored)
    db.add(sample)
    db.commit()
    return {"ok": True, "item": training_sample_payload(sample)}


@router.delete("/samples/{sample_id}")
def delete_sample(
    sample_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    sample = db.get(TrainingSample, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    try:
        path = Path(core.MEDIA_DIR) / sample.image_path
        path.unlink(missing_ok=True)
    except Exception:
        pass
    db.delete(sample)
    db.commit()
    return {"ok": True}


@router.get("/export_yolo")
def export_yolo(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    counts = core._build_yolo_dataset(db)
    return {"ok": True, "counts": counts}
