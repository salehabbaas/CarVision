"""routers/detections.py — detection CRUD, reprocess, feedback, and bulk operations."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import cv2
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.schemas import ApiBulkFeedbackBody, ApiBulkIdsBody
from core.config import MEDIA_DIR
from db import get_db
from models import AppSetting, Camera, ClipRecord, Detection, Notification, TrainingSample
from routers.deps import get_current_user
from services.dataset import bbox_to_xywh as _bbox_to_xywh, bbox_xywh_to_xyxy as _bbox_xywh_to_xyxy
from services.debug_assets import (
    debug_steps_from_paths as _debug_steps_from_paths,
    ensure_detection_debug_assets as _ensure_detection_debug_assets,
    save_upload_debug as _save_upload_debug,
)
from services.file_utils import hash_bytes as _hash_bytes, hash_file as _hash_file, safe_filename as _safe_filename

logger = logging.getLogger("carvision.routers.detections")

router = APIRouter(prefix="/api/v1", tags=["detections"])

# Populated by main.py app factory
_detect_plate_fn = None
_read_plate_text_fn = None
_copy_training_image_fn = None
_load_image_size_fn = None


def _init(detect_plate, read_plate_text, copy_training_image, load_image_size) -> None:
    global _detect_plate_fn, _read_plate_text_fn, _copy_training_image_fn, _load_image_size_fn
    _detect_plate_fn = detect_plate
    _read_plate_text_fn = read_plate_text
    _copy_training_image_fn = copy_training_image
    _load_image_size_fn = load_image_size


# ── Internal helpers ──────────────────────────────────────────────────────────

def _is_allowed(db: Session, plate_text: str) -> bool:
    from models import AllowedPlate
    if not plate_text:
        return False
    norm = "".join(ch for ch in plate_text if ch.isalnum()).upper()
    if not norm:
        return False
    row = db.query(AllowedPlate).filter(
        AllowedPlate.plate_text == norm,
        AllowedPlate.active.is_(True),
    ).first()
    return row is not None


def _match_known_plate(db: Session, plate_text: str):
    """Return (matched_text, similarity) — placeholder that just normalises the text."""
    from difflib import SequenceMatcher
    norm = "".join(ch for ch in (plate_text or "") if ch.isalnum()).upper()
    return norm, None


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

    detection = None
    if _detect_plate_fn:
        detection = _detect_plate_fn(image, mode_override=detector_mode)
    used_ocr_fallback = False
    if not detection and _read_plate_text_fn:
        detection = _read_plate_text_fn(image)
        used_ocr_fallback = True
    if not detection:
        return None
    if not detection.get("detector"):
        detection["detector"] = "ocr" if used_ocr_fallback else detector_mode

    plate_text, _ = _match_known_plate(db, detection.get("plate_text") or "")
    detection["plate_text"] = plate_text
    status = "allowed" if _is_allowed(db, plate_text) else "denied"

    debug_color_path = debug_bw_path = debug_gray_path = debug_edged_path = debug_mask_path = None
    try:
        (debug_color_path, debug_bw_path, debug_gray_path, debug_edged_path, debug_mask_path) = (
            _save_upload_debug(image, detection, plate_text, _safe_filename)
        )
    except Exception:
        pass

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
        if not _copy_training_image_fn:
            return None
        rel_path = _copy_training_image_fn(src_path, prefix="det")
        if not rel_path:
            return None
        size = _load_image_size_fn(Path(MEDIA_DIR) / rel_path) if _load_image_size_fn else None
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


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/detections")
def list_detections(
    q: str = "",
    status: str = "",
    feedback: str = "",
    trained: str = "",
    camera_id: Optional[int] = None,
    limit: int = 100,
    offset: int = 0,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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

        out.append({
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
            } if sample else None,
            "debug": {
                "color": debug_map.get("color"),
                "bw": debug_map.get("bw"),
                "gray": debug_map.get("gray"),
                "edged": debug_map.get("edged"),
                "mask": debug_map.get("mask"),
            },
            "debug_steps": _debug_steps_from_paths(debug_map),
        })

    if changed:
        db.commit()
    return {"items": out, "count": len(out)}


@router.post("/detections/{det_id}/reprocess")
def reprocess_detection(
    det_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")
    new_id = _reprocess_detection_row(db, det)
    if not new_id:
        raise HTTPException(status_code=400, detail="Reprocess failed")
    return {"ok": True, "new_detection_id": new_id}


@router.post("/detections/bulk/reprocess")
def bulk_reprocess_detections(
    body: ApiBulkIdsBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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


@router.delete("/detections/{det_id}")
def delete_detection(
    det_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")
    _delete_detection_row(db, det)
    db.commit()
    return {"ok": True}


@router.post("/detections/bulk/delete")
def bulk_delete_detections(
    body: ApiBulkIdsBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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


@router.post("/detections/{det_id}/debug/regenerate")
def regenerate_detection_debug(
    det_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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


@router.post("/detections/{det_id}/feedback")
def feedback_detection(
    det_id: int,
    body: ApiBulkFeedbackBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    det = db.get(Detection, det_id)
    if not det:
        raise HTTPException(status_code=404, detail="Detection not found")
    mode = (body.mode or "correct").strip().lower()
    if mode not in {"correct", "corrected", "no_plate"}:
        raise HTTPException(status_code=400, detail="Invalid mode")
    sample_id = _create_training_from_detection(db, det, mode, body.expected_plate, body.notes)
    return {"ok": True, "sample_id": sample_id}


@router.post("/detections/bulk/feedback")
def bulk_feedback_detections(
    body: ApiBulkFeedbackBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
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
