import secrets
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2

from anpr import build_debug_bundle
from core.config import MEDIA_DIR
from services.dataset import bbox_xywh_to_xyxy

DEBUG_STEP_LABELS = {
    "color": "Color Crop",
    "bw": "Threshold",
    "gray": "Gray",
    "edged": "Edges",
    "mask": "Mask",
}


def write_debug_frame(image, rel_path: str) -> Optional[str]:
    if image is None:
        return None
    try:
        out_path = Path(MEDIA_DIR) / rel_path
        out_path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out_path), image)
        return rel_path
    except Exception:
        return None


def debug_steps_from_paths(paths: Dict[str, Optional[str]]) -> List[Dict[str, str]]:
    steps: List[Dict[str, str]] = []
    for key in ("color", "bw", "gray", "edged", "mask"):
        path = paths.get(key)
        if not path:
            continue
        steps.append({"key": key, "label": DEBUG_STEP_LABELS.get(key, key), "path": path})
    return steps


def build_debug_steps(frame, bbox, prefix: str, folder: str = "debug") -> Dict[str, Optional[str]]:
    if frame is None:
        return {"color": None, "bw": None, "gray": None, "edged": None, "mask": None}
    try:
        bundle = build_debug_bundle(frame, bbox)
    except Exception:
        return {"color": None, "bw": None, "gray": None, "edged": None, "mask": None}

    return {
        "color": write_debug_frame(bundle.get("color"), f"{folder}/{prefix}_color.jpg"),
        "bw": write_debug_frame(bundle.get("bw"), f"{folder}/{prefix}_bw.jpg"),
        "gray": write_debug_frame(bundle.get("gray"), f"{folder}/{prefix}_gray.jpg"),
        "edged": write_debug_frame(bundle.get("edged"), f"{folder}/{prefix}_edged.jpg"),
        "mask": write_debug_frame(bundle.get("mask"), f"{folder}/{prefix}_mask.jpg"),
    }


def detection_debug_map(det) -> Dict[str, Optional[str]]:
    return {
        "color": det.debug_color_path,
        "bw": det.debug_bw_path,
        "gray": det.debug_gray_path,
        "edged": det.debug_edged_path,
        "mask": det.debug_mask_path,
    }


def normalize_bbox_for_debug(bbox):
    if not bbox:
        return None
    if not isinstance(bbox, dict):
        return bbox
    try:
        if all(k in bbox for k in ("x1", "y1", "x2", "y2")):
            return {
                "x1": int(bbox.get("x1", 0)),
                "y1": int(bbox.get("y1", 0)),
                "x2": int(bbox.get("x2", 0)),
                "y2": int(bbox.get("y2", 0)),
            }
        if all(k in bbox for k in ("x", "y", "w", "h")):
            return bbox_xywh_to_xyxy(bbox)
    except Exception:
        return None
    return bbox


def ensure_detection_debug_assets(det, force: bool = False) -> Tuple[Dict[str, Optional[str]], bool]:
    current = detection_debug_map(det)
    if not force and any(current.values()):
        return current, False
    if not det.image_path:
        return current, False

    image_path = Path(MEDIA_DIR) / det.image_path
    if not image_path.exists():
        return current, False
    image = cv2.imread(str(image_path))
    if image is None:
        return current, False

    bbox = normalize_bbox_for_debug(det.bbox)
    paths = build_debug_steps(
        image,
        bbox,
        prefix=f"detection_{det.id}",
        folder="debug_detection",
    )
    if not any(paths.values()):
        return current, False

    det.debug_color_path = paths.get("color")
    det.debug_bw_path = paths.get("bw")
    det.debug_gray_path = paths.get("gray")
    det.debug_edged_path = paths.get("edged")
    det.debug_mask_path = paths.get("mask")
    return paths, True


def save_upload_debug(frame, detection, plate_text: str, safe_filename) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
    if frame is None or not detection:
        return None, None, None, None, None
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    token = secrets.token_hex(3)
    safe_plate = safe_filename(plate_text)
    prefix = f"upload_{safe_plate}_{ts}_{token}"
    paths = build_debug_steps(frame, detection.get("bbox"), prefix=prefix, folder="debug")
    return (
        paths.get("color"),
        paths.get("bw"),
        paths.get("gray"),
        paths.get("edged"),
        paths.get("mask"),
    )


def build_training_debug(sample) -> List[Dict[str, str]]:
    if not sample:
        return []
    image_path = Path(MEDIA_DIR) / sample.image_path
    if not image_path.exists():
        return []
    image = cv2.imread(str(image_path))
    if image is None:
        return []
    bbox = None
    if sample.bbox:
        bbox = bbox_xywh_to_xyxy(sample.bbox)
    prefix = f"sample_{sample.id}"
    paths = build_debug_steps(image, bbox, prefix=prefix, folder="debug_training")
    return debug_steps_from_paths(paths)
