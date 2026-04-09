import hashlib
import os
import secrets
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np
from sqlalchemy.orm import Session

from core.config import MEDIA_DIR
from models import TrainingSample
from services.file_utils import safe_filename


def stable_split(sample_id: int) -> str:
    digest = hashlib.md5(str(sample_id).encode("utf-8")).hexdigest()
    bucket = int(digest[:6], 16) % 100
    return "train" if bucket < 80 else "val"


def load_image_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        image = cv2.imread(str(path))
        if image is None:
            return None
        h, w = image.shape[:2]
        return w, h
    except Exception:
        return None


def copy_training_image(src_path: Path, prefix: str = "det") -> Optional[str]:
    if not src_path.exists():
        return None
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(3)
    safe_name = safe_filename(src_path.name)
    filename = f"training/{prefix}_{ts}_{token}_{safe_name}"
    dest = Path(MEDIA_DIR) / filename
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src_path, dest)
    return filename


def bbox_to_xywh(bbox: object) -> Optional[Dict[str, int]]:
    if isinstance(bbox, dict):
        if {"x", "y", "w", "h"}.issubset(bbox.keys()):
            return {
                "x": int(bbox.get("x", 0)),
                "y": int(bbox.get("y", 0)),
                "w": int(bbox.get("w", 0)),
                "h": int(bbox.get("h", 0)),
            }
        if {"x1", "y1", "x2", "y2"}.issubset(bbox.keys()):
            x1 = int(bbox.get("x1", 0))
            y1 = int(bbox.get("y1", 0))
            x2 = int(bbox.get("x2", 0))
            y2 = int(bbox.get("y2", 0))
            return {
                "x": x1,
                "y": y1,
                "w": max(0, x2 - x1),
                "h": max(0, y2 - y1),
            }
    if isinstance(bbox, (list, tuple)) and bbox:
        try:
            pts = np.array(bbox, dtype=np.int32)
            if pts.ndim == 3 and pts.shape[1] == 1 and pts.shape[2] == 2:
                pts = pts.reshape(-1, 2)
            if pts.ndim == 2 and pts.shape[1] == 2:
                min_xy = pts.min(axis=0)
                max_xy = pts.max(axis=0)
                x1, y1 = int(min_xy[0]), int(min_xy[1])
                x2, y2 = int(max_xy[0]), int(max_xy[1])
                return {
                    "x": x1,
                    "y": y1,
                    "w": max(0, x2 - x1),
                    "h": max(0, y2 - y1),
                }
        except Exception:
            return None
    return None


def bbox_xywh_to_xyxy(bbox: Dict[str, int]) -> Dict[str, int]:
    x = int(bbox.get("x", 0))
    y = int(bbox.get("y", 0))
    w = int(bbox.get("w", 0))
    h = int(bbox.get("h", 0))
    return {"x1": x, "y1": y, "x2": x + w, "y2": y + h}


def _build_yolo_dataset_from_rows(
    db: Session,
    samples: List[TrainingSample],
    dataset_root: Path,
) -> Dict[str, object]:
    images_train = dataset_root / "images" / "train"
    images_val = dataset_root / "images" / "val"
    labels_train = dataset_root / "labels" / "train"
    labels_val = dataset_root / "labels" / "val"

    shutil.rmtree(dataset_root, ignore_errors=True)
    images_train.mkdir(parents=True, exist_ok=True)
    images_val.mkdir(parents=True, exist_ok=True)
    labels_train.mkdir(parents=True, exist_ok=True)
    labels_val.mkdir(parents=True, exist_ok=True)

    counts = {
        "total": len(samples),
        "ignored": 0,
        "pending": 0,
        "positives": 0,
        "negatives": 0,
        "exported": 0,
        "train": 0,
        "val": 0,
    }
    used_sample_ids: List[int] = []

    for sample in samples:
        if sample.ignored:
            counts["ignored"] += 1
            continue
        if not sample.bbox and not sample.no_plate:
            counts["pending"] += 1
            continue

        split = stable_split(sample.id)
        img_dir = images_train if split == "train" else images_val
        label_dir = labels_train if split == "train" else labels_val

        src_path = Path(MEDIA_DIR) / sample.image_path
        if not src_path.exists():
            continue

        ext = src_path.suffix or ".jpg"
        image_name = f"sample_{sample.id}{ext}"
        dest_image = img_dir / image_name
        dest_label = label_dir / f"sample_{sample.id}.txt"

        shutil.copy2(src_path, dest_image)

        width = sample.image_width
        height = sample.image_height
        if not width or not height:
            size = load_image_size(src_path)
            if size:
                width, height = size
                sample.image_width = width
                sample.image_height = height
                db.add(sample)
        if width and height and sample.bbox and not sample.no_plate:
            bbox = sample.bbox or {}
            x = float(bbox.get("x", 0))
            y = float(bbox.get("y", 0))
            w = float(bbox.get("w", 0))
            h = float(bbox.get("h", 0))
            cx = (x + w / 2.0) / float(width)
            cy = (y + h / 2.0) / float(height)
            nw = w / float(width)
            nh = h / float(height)
            line = f"0 {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}\n"
            dest_label.write_text(line)
            counts["positives"] += 1
        else:
            dest_label.write_text("")
            counts["negatives"] += 1

        counts["exported"] += 1
        counts[split] += 1
        used_sample_ids.append(sample.id)

    db.commit()

    data_yaml = dataset_root / "data.yaml"
    train_ref = "images/train" if counts.get("train", 0) > 0 else "images/val"
    val_ref = "images/val" if counts.get("val", 0) > 0 else train_ref
    yaml_contents = "\n".join(
        [
            f"path: {dataset_root.as_posix()}",
            f"train: {train_ref}",
            f"val: {val_ref}",
            "nc: 1",
            "names: [plate]",
            "",
        ]
    )
    data_yaml.write_text(yaml_contents)

    counts["dataset_root"] = str(dataset_root)
    counts["data_yaml"] = str(data_yaml)
    counts["sample_ids"] = used_sample_ids
    return counts


def build_yolo_dataset(db: Session) -> Dict[str, object]:
    dataset_root = Path(MEDIA_DIR) / "training_yolo"
    samples = db.query(TrainingSample).order_by(TrainingSample.id.asc()).all()
    return _build_yolo_dataset_from_rows(db, samples, dataset_root)


def build_yolo_dataset_for_sample_ids(
    db: Session,
    sample_ids: List[int],
    dataset_subdir: str = "training_yolo",
) -> Dict[str, object]:
    ids = [int(x) for x in sample_ids if int(x) > 0]
    if not ids:
        dataset_root = Path(MEDIA_DIR) / dataset_subdir
        shutil.rmtree(dataset_root, ignore_errors=True)
        (dataset_root / "images" / "train").mkdir(parents=True, exist_ok=True)
        (dataset_root / "images" / "val").mkdir(parents=True, exist_ok=True)
        (dataset_root / "labels" / "train").mkdir(parents=True, exist_ok=True)
        (dataset_root / "labels" / "val").mkdir(parents=True, exist_ok=True)
        data_yaml = dataset_root / "data.yaml"
        data_yaml.write_text(
            "\n".join(
                [
                    f"path: {dataset_root.as_posix()}",
                    "train: images/train",
                    "val: images/val",
                    "nc: 1",
                    "names: [plate]",
                    "",
                ]
            )
        )
        return {
            "total": 0,
            "ignored": 0,
            "pending": 0,
            "positives": 0,
            "negatives": 0,
            "exported": 0,
            "train": 0,
            "val": 0,
            "dataset_root": str(dataset_root),
            "data_yaml": str(data_yaml),
            "sample_ids": [],
        }

    dataset_root = Path(MEDIA_DIR) / dataset_subdir
    order_case = {sid: idx for idx, sid in enumerate(ids)}
    rows = db.query(TrainingSample).filter(TrainingSample.id.in_(ids)).all()
    rows.sort(key=lambda row: order_case.get(int(row.id), 10**9))
    return _build_yolo_dataset_from_rows(db, rows, dataset_root)


def is_image_filename(name: str) -> bool:
    ext = Path(name.lower()).suffix
    return ext in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}


def extract_yolo_bbox(label_text: str, width: int, height: int) -> Optional[Dict[str, int]]:
    if not label_text:
        return None
    for raw_line in label_text.splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cx = float(parts[1])
            cy = float(parts[2])
            nw = float(parts[3])
            nh = float(parts[4])
        except Exception:
            continue
        if width <= 0 or height <= 0 or nw <= 0 or nh <= 0:
            continue
        w = int(round(nw * width))
        h = int(round(nh * height))
        x = int(round((cx - nw / 2.0) * width))
        y = int(round((cy - nh / 2.0) * height))
        x = max(0, min(x, max(0, width - 1)))
        y = max(0, min(y, max(0, height - 1)))
        w = max(1, min(w, width - x))
        h = max(1, min(h, height - y))
        return {"x": x, "y": y, "w": w, "h": h}
    return None


def extract_yolo_bboxes(label_text: str, width: int, height: int) -> List[Dict[str, int]]:
    boxes: List[Dict[str, int]] = []
    if not label_text:
        return boxes
    for raw_line in label_text.splitlines():
        line = (raw_line or "").strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cx = float(parts[1])
            cy = float(parts[2])
            nw = float(parts[3])
            nh = float(parts[4])
        except Exception:
            continue
        if width <= 0 or height <= 0 or nw <= 0 or nh <= 0:
            continue
        w = int(round(nw * width))
        h = int(round(nh * height))
        x = int(round((cx - nw / 2.0) * width))
        y = int(round((cy - nh / 2.0) * height))
        x = max(0, min(x, max(0, width - 1)))
        y = max(0, min(y, max(0, height - 1)))
        w = max(1, min(w, width - x))
        h = max(1, min(h, height - y))
        boxes.append({"x": x, "y": y, "w": w, "h": h})
    return boxes


def zip_label_candidates(path: str) -> List[str]:
    p = path.replace("\\", "/").strip("/")
    low = p.lower()
    base, _ = os.path.splitext(low)
    candidates = [f"{base}.txt"]

    # Handle common YOLO dataset layouts:
    # - images/train/a.jpg <-> labels/train/a.txt
    # - dataset/images/train/a.jpg <-> dataset/labels/train/a.txt
    # - images/a.jpg <-> labels/a.txt
    if "/images/" in low:
        candidates.append(f"{base.replace('/images/', '/labels/', 1)}.txt")
    if low.startswith("images/"):
        candidates.append(f"{base.replace('images/', 'labels/', 1)}.txt")

    return list(dict.fromkeys(candidates))
