"""Verify plate_detector._detect_with_yolo returns bbox only (no OCR text)."""
import sys
from pathlib import Path
import types

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


def _make_fake_yolo_result(x1=10, y1=10, x2=100, y2=50, conf=0.9):
    """Build a minimal fake Ultralytics result object."""
    import numpy as np

    class FakeConf:
        def cpu(self):
            return self
        def numpy(self):
            return np.array([conf])

    class FakeXyxyItem:
        def cpu(self):
            return self
        def numpy(self):
            return np.array([x1, y1, x2, y2])
        def tolist(self):
            return [x1, y1, x2, y2]

    class FakeBoxes:
        def __init__(self):
            self.conf = FakeConf()
            self.xyxy = [FakeXyxyItem()]
        def __len__(self):
            return 1

    result = types.SimpleNamespace(boxes=FakeBoxes())
    return [result]


def test_yolo_detect_returns_bbox_only_no_plate_text(monkeypatch):
    """_detect_with_yolo must not contain 'plate_text' or 'candidates' keys."""
    import numpy as np
    import plate_detector as pd_module

    fake_results = _make_fake_yolo_result()

    class FakeModel:
        def predict(self, *args, **kwargs):
            return fake_results

    detector = pd_module.PlateDetector()
    detector._model = FakeModel()

    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    result = detector._detect_with_yolo(frame)

    assert result is not None, "Expected a detection result"
    assert "bbox" in result, "bbox key must be present"
    assert "detector" in result, "detector key must be present"
    assert result["detector"] == "yolo"

    # Must NOT contain OCR output keys
    assert "plate_text" not in result, "plate_text must not be in YOLO detector output"
    assert "candidates" not in result, "candidates must not be in YOLO detector output"
    assert "text" not in result, "text must not be in YOLO detector output"


def test_yolo_detect_bbox_has_required_fields(monkeypatch):
    """bbox dict must have x1, y1, x2, y2, detector_conf."""
    import numpy as np
    import plate_detector as pd_module

    fake_results = _make_fake_yolo_result(x1=5, y1=5, x2=80, y2=40, conf=0.75)

    class FakeModel:
        def predict(self, *args, **kwargs):
            return fake_results

    detector = pd_module.PlateDetector()
    detector._model = FakeModel()

    frame = np.zeros((200, 400, 3), dtype=np.uint8)
    result = detector._detect_with_yolo(frame)

    bbox = result["bbox"]
    for field in ("x1", "y1", "x2", "y2", "detector_conf"):
        assert field in bbox, f"Missing bbox field: {field}"
    assert 0.0 <= bbox["detector_conf"] <= 1.0


def test_yolo_detect_returns_none_when_model_unavailable():
    import numpy as np
    import plate_detector as pd_module

    detector = pd_module.PlateDetector()
    detector._model = None
    # Prevent loading a real model
    original_load = detector._load_model
    detector._load_model = lambda: None

    frame = np.zeros((100, 100, 3), dtype=np.uint8)
    result = detector._detect_with_yolo(frame)
    assert result is None
