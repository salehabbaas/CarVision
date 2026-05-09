"""Unit tests for runtime settings validation and hardware probe."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from routers.settings import _apply_update, _probe_hardware, _VALID_PROFILES, _VALID_DEVICES


class FakeRuntimeRow:
    runtime_profile = "cpu"
    inference_device = "cpu"
    training_device = "cpu"
    model_backend = "pytorch"
    target_detection_fps = 2.0
    batch_inference = False
    max_live_cameras = 8
    jpeg_quality = 82
    plate_region = "generic"
    ocr_engine = "easyocr"


# ── _apply_update validation ─────────────────────────────────────────────────

def test_valid_profile_is_accepted():
    row = FakeRuntimeRow()
    _apply_update(row, {"runtime_profile": "nvidia"})
    assert row.runtime_profile == "nvidia"


def test_invalid_profile_is_rejected():
    row = FakeRuntimeRow()
    _apply_update(row, {"runtime_profile": "superchip"})
    assert row.runtime_profile == "cpu"


def test_valid_inference_device_accepted():
    row = FakeRuntimeRow()
    _apply_update(row, {"inference_device": "cuda"})
    assert row.inference_device == "cuda"


def test_invalid_inference_device_rejected():
    row = FakeRuntimeRow()
    _apply_update(row, {"inference_device": "tpu"})
    assert row.inference_device == "cpu"


def test_fps_clamped_to_min():
    row = FakeRuntimeRow()
    _apply_update(row, {"target_detection_fps": 0.01})
    assert row.target_detection_fps == 0.5


def test_fps_clamped_to_max():
    row = FakeRuntimeRow()
    _apply_update(row, {"target_detection_fps": 999.0})
    assert row.target_detection_fps == 30.0


def test_fps_midrange_accepted():
    row = FakeRuntimeRow()
    _apply_update(row, {"target_detection_fps": 5.0})
    assert row.target_detection_fps == 5.0


def test_max_live_cameras_clamped():
    row = FakeRuntimeRow()
    _apply_update(row, {"max_live_cameras": 0})
    assert row.max_live_cameras == 1
    _apply_update(row, {"max_live_cameras": 200})
    assert row.max_live_cameras == 64


def test_jpeg_quality_clamped():
    row = FakeRuntimeRow()
    _apply_update(row, {"jpeg_quality": 5})
    assert row.jpeg_quality == 10
    _apply_update(row, {"jpeg_quality": 200})
    assert row.jpeg_quality == 100


def test_plate_region_truncated_to_50():
    row = FakeRuntimeRow()
    _apply_update(row, {"plate_region": "x" * 100})
    assert len(row.plate_region) == 50


def test_invalid_ocr_engine_rejected():
    row = FakeRuntimeRow()
    _apply_update(row, {"ocr_engine": "magic_ocr"})
    assert row.ocr_engine == "easyocr"


def test_valid_ocr_engine_accepted():
    row = FakeRuntimeRow()
    _apply_update(row, {"ocr_engine": "paddleocr"})
    assert row.ocr_engine == "paddleocr"


def test_batch_inference_coerced_to_bool():
    row = FakeRuntimeRow()
    _apply_update(row, {"batch_inference": 1})
    assert row.batch_inference is True
    _apply_update(row, {"batch_inference": 0})
    assert row.batch_inference is False


# ── hardware probe fallback ───────────────────────────────────────────────────

def test_hardware_probe_always_returns_cpu(monkeypatch):
    """Even if torch is missing, cpu must be True."""
    import builtins
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "torch":
            raise ImportError("torch not available")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    result = _probe_hardware()
    assert result["cpu"] is True
    assert result["pytorch_available"] is False
    assert result["cuda"] is False
    assert result["mps"] is False
    assert "pytorch" in result["usable_backends"]


def test_hardware_probe_structure():
    result = _probe_hardware()
    for key in ("cpu", "cuda", "mps", "gpu_names", "pytorch_available", "usable_backends"):
        assert key in result, f"Missing key: {key}"
    assert isinstance(result["gpu_names"], list)
    assert isinstance(result["usable_backends"], list)
