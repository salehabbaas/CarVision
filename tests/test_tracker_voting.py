"""Unit tests for pipeline tracker: stub returns 'candidate' status."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "backend" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from pipeline.tracker import track_plate
from pipeline.schemas import TrackerResult


def test_track_plate_returns_tracker_result():
    result = track_plate("ABC123")
    assert isinstance(result, TrackerResult)


def test_track_plate_stage_name():
    result = track_plate("ABC123")
    assert result.stage_name == "tracker"


def test_track_plate_status_is_candidate():
    result = track_plate("ABC123")
    assert result.status == "candidate"


def test_track_plate_timing_ms_is_non_negative():
    result = track_plate("ABC123")
    assert result.timing_ms >= 0.0


def test_track_plate_with_none_input():
    result = track_plate(None)
    assert isinstance(result, TrackerResult)
    assert result.status == "candidate"


def test_track_plate_confidence_is_none():
    result = track_plate("XY999")
    assert result.confidence is None


def test_track_plate_debug_has_note():
    result = track_plate("TEST")
    assert "note" in (result.debug or {})
