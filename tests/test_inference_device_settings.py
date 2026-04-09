import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import anpr
import main
import plate_detector
from models import AppSetting


class FakeDB:
    def __init__(self):
        self.settings = {}
        self.committed = False

    def get(self, model, key):
        if model is AppSetting:
            return self.settings.get(key)
        return None

    def add(self, obj):
        if isinstance(obj, AppSetting):
            self.settings[obj.key] = obj

    def commit(self):
        self.committed = True


def test_update_settings_persists_inference_device(monkeypatch):
    db = FakeDB()
    monkeypatch.setattr(main, "_refresh_anpr_config", lambda current_db: None)

    response = main.update_settings(
        detector_mode="contour",
        max_live_cameras=16,
        inference_device="gpu",
        yolo_conf=0.25,
        yolo_imgsz=640,
        yolo_iou=0.45,
        yolo_max_det=5,
        ocr_max_width=1280,
        ocr_langs="en",
        contour_canny_low=30,
        contour_canny_high=200,
        contour_bilateral_d=11,
        contour_bilateral_sigma_color=17,
        contour_bilateral_sigma_space=17,
        contour_approx_eps=0.018,
        contour_pad_ratio=0.15,
        contour_pad_min=18,
        db=db,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/settings?saved=1"
    assert db.committed is True
    assert db.settings["inference_device"].value == "gpu"


def test_set_anpr_config_resets_reader_when_device_changes():
    original_reader = anpr._reader
    original_device = anpr._ANPR_CONFIG.get("inference_device")
    try:
        anpr._reader = object()
        anpr._ANPR_CONFIG["inference_device"] = "cpu"

        anpr.set_anpr_config({"inference_device": "gpu"})

        assert anpr._reader is None
        assert anpr._ANPR_CONFIG["inference_device"] == "gpu"
    finally:
        anpr._reader = original_reader
        anpr._ANPR_CONFIG["inference_device"] = original_device


def test_set_yolo_config_stores_device_preference(monkeypatch):
    original_device = plate_detector._YOLO_CONFIG.get("device")
    try:
        monkeypatch.setattr(plate_detector, "reload_yolo_model", lambda: None)
        plate_detector.set_yolo_config({"device": "gpu"})
        assert plate_detector._YOLO_CONFIG["device"] == "gpu"
    finally:
        plate_detector._YOLO_CONFIG["device"] = original_device
