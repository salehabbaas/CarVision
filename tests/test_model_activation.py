"""Unit tests for model_export: should_activate, profile_to_format, export_model path guards."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.model_export import should_activate, profile_to_format, export_model, register_model_version, activate_model_version


# ── should_activate ───────────────────────────────────────────────────────────

def test_activate_when_no_current_model():
    assert should_activate({"mAP50": 0.1}, None) is True
    assert should_activate({"mAP50": 0.1}, {}) is True


def test_activate_when_new_map_is_higher():
    assert should_activate({"mAP50": 0.85}, {"mAP50": 0.80}) is True


def test_no_activate_when_new_map_is_lower():
    assert should_activate({"mAP50": 0.70}, {"mAP50": 0.80}) is False


def test_no_activate_when_maps_equal():
    assert should_activate({"mAP50": 0.80}, {"mAP50": 0.80}) is False


def test_activate_handles_alternate_key_names():
    assert should_activate({"metrics/mAP50(B)": 0.9}, {"metrics/mAP50(B)": 0.85}) is True
    assert should_activate({"map50": 0.9}, {"map50": 0.85}) is True
    assert should_activate({"mAP_0.5": 0.9}, {"mAP_0.5": 0.85}) is True


def test_no_activate_when_new_metrics_missing_map():
    assert should_activate({"precision": 0.9}, {"mAP50": 0.8}) is False


def test_activate_when_current_missing_map_but_new_has_it():
    assert should_activate({"mAP50": 0.8}, {"precision": 0.9}) is True


# ── profile_to_format ────────────────────────────────────────────────────────

def test_cpu_profile_maps_to_onnx():
    assert profile_to_format("cpu") == "onnx"


def test_nvidia_profile_maps_to_engine():
    assert profile_to_format("nvidia") == "engine"


def test_mac_profile_maps_to_coreml():
    assert profile_to_format("mac") == "coreml"


def test_unknown_profile_falls_back_to_onnx():
    assert profile_to_format("unknown_runtime") == "onnx"


def test_profile_is_case_insensitive():
    assert profile_to_format("CPU") == "onnx"
    assert profile_to_format("NVIDIA") == "engine"
    assert profile_to_format("Mac") == "coreml"


# ── export_model path guard ───────────────────────────────────────────────────

def test_export_model_missing_file_returns_error():
    path, err = export_model("/nonexistent/model.pt", "onnx")
    assert path is None
    assert err is not None
    assert "not found" in err.lower() or "model" in err.lower()


def test_export_model_pt_format_returns_path_unchanged(tmp_path):
    fake_pt = tmp_path / "model.pt"
    fake_pt.write_bytes(b"fake")
    path, err = export_model(str(fake_pt), "pt")
    assert err is None
    assert path == str(fake_pt)


def test_export_model_pytorch_format_returns_path_unchanged(tmp_path):
    fake_pt = tmp_path / "model.pt"
    fake_pt.write_bytes(b"fake")
    path, err = export_model(str(fake_pt), "pytorch")
    assert err is None
    assert path == str(fake_pt)


def test_export_model_empty_format_returns_path_unchanged(tmp_path):
    fake_pt = tmp_path / "model.pt"
    fake_pt.write_bytes(b"fake")
    path, err = export_model(str(fake_pt), "")
    assert err is None
    assert path == str(fake_pt)


# ── register_model_version + activate_model_version (in-memory DB) ───────────

def _make_db():
    """Return an in-memory SQLAlchemy session with model_versions table."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from db import Base

    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    return Session()


def test_register_creates_inactive_version():
    db = _make_db()
    mv = register_model_version(db, path="/tmp/best.pt", fmt="pytorch", profile="cpu", metrics={"mAP50": 0.8})
    assert mv.id is not None
    assert mv.active is False
    assert mv.path == "/tmp/best.pt"
    db.close()


def test_activate_sets_only_target_active():
    db = _make_db()
    mv1 = register_model_version(db, path="/tmp/v1.pt", fmt="pytorch", profile="cpu")
    mv2 = register_model_version(db, path="/tmp/v2.pt", fmt="pytorch", profile="cpu")

    result = activate_model_version(db, mv2.id)
    assert result is True

    db.expire_all()
    from models import ModelVersion
    r1 = db.get(ModelVersion, mv1.id)
    r2 = db.get(ModelVersion, mv2.id)
    assert r1.active is False
    assert r2.active is True
    db.close()


def test_activate_returns_false_for_missing_id():
    db = _make_db()
    result = activate_model_version(db, 9999)
    assert result is False
    db.close()


def test_rollback_source_id_stored():
    db = _make_db()
    mv1 = register_model_version(db, path="/tmp/v1.pt", fmt="pytorch", profile="cpu")
    mv2 = register_model_version(db, path="/tmp/v2.pt", fmt="pytorch", profile="cpu", rollback_source_id=mv1.id)
    assert mv2.rollback_source_id == mv1.id
    db.close()
