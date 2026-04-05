import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from main import _extract_yolo_bbox, _zip_label_candidates


def test_extract_yolo_bbox_valid_line():
    bbox = _extract_yolo_bbox("0 0.5 0.5 0.2 0.1", 1000, 500)
    assert bbox is not None
    assert bbox["w"] == 200
    assert bbox["h"] == 50
    assert bbox["x"] == 400
    assert bbox["y"] == 225


def test_extract_yolo_bbox_invalid_line():
    bbox = _extract_yolo_bbox("hello world", 1000, 500)
    assert bbox is None


def test_zip_label_candidates_images_to_labels():
    candidates = _zip_label_candidates("dataset/images/train/car_001.jpg")
    assert "dataset/images/train/car_001.txt" in candidates
    assert "dataset/labels/train/car_001.txt" in candidates
