#!/usr/bin/env python3
"""
CarVision standalone viewer — real-time plate detection in an OpenCV window.

Reads cameras directly from the SQLite DB, connects to RTSP/webcam sources,
runs YOLO + OCR detection inline, and displays results with no web/HTTP overhead.

Usage:
    cd /path/to/CarVision
    python viewer.py              # show all enabled cameras
    python viewer.py --camera 1   # show a specific camera by ID
    python viewer.py --source rtsp://user:pass@192.168.1.100/stream  # ad-hoc source

Press  Q  or  ESC  to quit.
"""

import sys
import os
import argparse
import time
import threading
from pathlib import Path

# ── Make backend modules importable ──────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend" / "app"))
os.chdir(ROOT / "backend" / "app")  # so relative DB path resolves correctly

import cv2
import numpy as np

# ── Load detection stack ──────────────────────────────────────────────────────
from plate_detector import detect_plate, set_yolo_config
from anpr import set_anpr_config

# ── Load DB to read camera config ─────────────────────────────────────────────
from db import SessionLocal
from models import Camera, AllowedPlate, AppSetting


# ─────────────────────────────────────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────────────────────────────────────

def _load_settings():
    """Push DB settings into the detection stack."""
    with SessionLocal() as db:
        def _get(key, default):
            s = db.get(AppSetting, key)
            return s.value if s and s.value else default

        model_path = str(ROOT / "models" / "plate.pt")
        set_yolo_config({
            "conf":       float(_get("yolo_conf", "0.25")),
            "imgsz":      int(_get("yolo_imgsz", "640")),
            "iou":        float(_get("yolo_iou", "0.45")),
            "max_det":    int(_get("yolo_max_det", "5")),
            "device":     _get("inference_device", "cpu"),
            "model_path": model_path if Path(model_path).exists() else "",
        })
        set_anpr_config({
            "inference_device": _get("inference_device", "cpu"),
            "ocr_max_width":    int(_get("ocr_max_width", "1280")),
            "ocr_langs":        _get("ocr_langs", "en"),
        })

        cameras = (
            db.query(Camera)
            .filter(Camera.enabled.is_(True))
            .order_by(Camera.id)
            .all()
        )
        allowed = {
            a.plate_text.upper()
            for a in db.query(AllowedPlate).filter(AllowedPlate.active.is_(True)).all()
        }
    return cameras, allowed


def _get_camera_by_id(camera_id: int):
    with SessionLocal() as db:
        return db.get(Camera, camera_id)


# ─────────────────────────────────────────────────────────────────────────────
# Detection result (shared between capture thread and display thread)
# ─────────────────────────────────────────────────────────────────────────────

class _State:
    def __init__(self):
        self.lock      = threading.Lock()
        self.frame     = None        # latest raw frame
        self.detection = None        # latest detection dict
        self.fps_cap   = 0.0
        self.fps_det   = 0.0


# ─────────────────────────────────────────────────────────────────────────────
# Capture + detection thread
# ─────────────────────────────────────────────────────────────────────────────

RTSP_OPTIONS = (
    "rtsp_transport;tcp"
    "|fflags;nobuffer"
    "|flags;low_delay"
    "|max_delay;0"
    "|reorder_queue_size;0"
    "|buffer_size;204800"
)


def _open_cap(source):
    if isinstance(source, int) or (isinstance(source, str) and source.isdigit()):
        return cv2.VideoCapture(int(source))
    cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
    cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10_000)
    cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5_000)
    os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = RTSP_OPTIONS
    return cap


def _detection_thread(source, state: _State, stop: threading.Event, mode: str):
    cap = _open_cap(source)
    if not cap.isOpened():
        print(f"[viewer] Cannot open source: {source}", flush=True)
        stop.set()
        return

    t_cap_prev = time.time()
    t_det_prev = time.time()
    det_count  = 0
    cap_count  = 0
    retry_delay = 0.5

    while not stop.is_set():
        ret, frame = cap.read()
        if not ret:
            cap.release()
            time.sleep(retry_delay)
            retry_delay = min(10.0, retry_delay * 1.5)
            cap = _open_cap(source)
            continue
        retry_delay = 0.5
        cap_count += 1

        now = time.time()
        if now - t_cap_prev >= 1.0:
            with state.lock:
                state.fps_cap = cap_count / (now - t_cap_prev)
            cap_count  = 0
            t_cap_prev = now

        # Run detection on every frame (no scan-interval throttle here)
        detection = None
        try:
            detection = detect_plate(frame, mode_override=mode)
        except Exception as e:
            print(f"[viewer] detection error: {e}", flush=True)

        det_count += 1
        now = time.time()
        if now - t_det_prev >= 1.0:
            with state.lock:
                state.fps_det = det_count / (now - t_det_prev)
            det_count  = 0
            t_det_prev = now

        with state.lock:
            state.frame     = frame.copy()
            state.detection = detection

    cap.release()


# ─────────────────────────────────────────────────────────────────────────────
# Overlay drawing
# ─────────────────────────────────────────────────────────────────────────────

_GREEN  = (0, 220, 0)
_RED    = (0, 50, 220)
_YELLOW = (0, 200, 220)
_WHITE  = (255, 255, 255)
_BLACK  = (0, 0, 0)
_FONT   = cv2.FONT_HERSHEY_SIMPLEX


def _draw(frame, detection, allowed: set, fps_cap: float, fps_det: float, label: str):
    out = frame.copy()
    h, w = out.shape[:2]

    # FPS overlay (top-left)
    cv2.putText(out, f"Cap {fps_cap:.0f}fps  Det {fps_det:.0f}fps",
                (8, 22), _FONT, 0.55, _BLACK, 3, cv2.LINE_AA)
    cv2.putText(out, f"Cap {fps_cap:.0f}fps  Det {fps_det:.0f}fps",
                (8, 22), _FONT, 0.55, _WHITE, 1, cv2.LINE_AA)

    # Camera label (top-right)
    (tw, th), _ = cv2.getTextSize(label, _FONT, 0.5, 1)
    cv2.putText(out, label, (w - tw - 8, 20), _FONT, 0.5, _BLACK, 3, cv2.LINE_AA)
    cv2.putText(out, label, (w - tw - 8, 20), _FONT, 0.5, _WHITE, 1, cv2.LINE_AA)

    if not detection:
        return out

    plate_text = detection.get("plate_text") or ""
    confidence = float(detection.get("confidence") or 0.0)
    detector   = detection.get("detector", "")
    is_allowed = plate_text.upper() in allowed
    color      = _GREEN if is_allowed else _RED
    status     = "ALLOWED" if is_allowed else "DENIED"

    # Bounding box
    bbox = detection.get("bbox")
    if bbox:
        if isinstance(bbox, dict):
            x1 = int(bbox.get("x1", 0)); y1 = int(bbox.get("y1", 0))
            x2 = int(bbox.get("x2", w)); y2 = int(bbox.get("y2", h))
        elif isinstance(bbox, list) and bbox:
            pts = np.array(bbox, dtype=np.int32)
            if pts.ndim == 2 and pts.shape[1] == 2:
                x1, y1 = pts[:, 0].min(), pts[:, 1].min()
                x2, y2 = pts[:, 0].max(), pts[:, 1].max()
            else:
                x1 = y1 = 0; x2 = w; y2 = h
        else:
            x1 = y1 = 0; x2 = w; y2 = h
        cv2.rectangle(out, (x1, y1), (x2, y2), color, 2)

    # Plate text banner
    banner = f"{plate_text}  {confidence:.0%}  [{detector}]  {status}"
    (bw, bh), baseline = cv2.getTextSize(banner, _FONT, 0.7, 2)
    bx, by = 8, h - 12
    cv2.rectangle(out, (bx - 4, by - bh - baseline - 4), (bx + bw + 4, by + baseline), _BLACK, -1)
    cv2.putText(out, banner, (bx, by), _FONT, 0.7, color, 2, cv2.LINE_AA)

    return out


# ─────────────────────────────────────────────────────────────────────────────
# Single-camera display loop
# ─────────────────────────────────────────────────────────────────────────────

def run_camera(source, label: str, allowed: set, mode: str):
    state = _State()
    stop  = threading.Event()

    t = threading.Thread(
        target=_detection_thread,
        args=(source, state, stop, mode),
        daemon=True,
        name=f"det-{label}",
    )
    t.start()

    win = f"CarVision — {label}"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)

    print(f"[viewer] Opened: {label}  (press Q or ESC to quit)", flush=True)

    while not stop.is_set():
        with state.lock:
            frame     = state.frame
            detection = state.detection
            fps_cap   = state.fps_cap
            fps_det   = state.fps_det

        if frame is None:
            time.sleep(0.02)
            continue

        out = _draw(frame, detection, allowed, fps_cap, fps_det, label)

        if detection:
            plate = detection.get("plate_text", "")
            det   = detection.get("detector", "")
            conf  = float(detection.get("confidence") or 0)
            status = "ALLOWED" if plate.upper() in allowed else "DENIED"
            print(f"[{label}] {plate}  {conf:.0%}  {det}  → {status}", flush=True)

        cv2.imshow(win, out)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27):  # Q or ESC
            break

    stop.set()
    cv2.destroyWindow(win)
    t.join(timeout=3)


# ─────────────────────────────────────────────────────────────────────────────
# Multi-camera tiled display
# ─────────────────────────────────────────────────────────────────────────────

class _CameraThread:
    def __init__(self, source, label, mode):
        self.label  = label
        self.state  = _State()
        self.stop   = threading.Event()
        self._t     = threading.Thread(
            target=_detection_thread,
            args=(source, self.state, self.stop, mode),
            daemon=True,
            name=f"det-{label}",
        )
        self._t.start()

    def latest(self):
        with self.state.lock:
            return (
                self.state.frame,
                self.state.detection,
                self.state.fps_cap,
                self.state.fps_det,
            )

    def shutdown(self):
        self.stop.set()
        self._t.join(timeout=3)


def run_multi(cameras_sources: list, allowed: set, mode: str):
    workers = [
        _CameraThread(src, label, mode)
        for src, label in cameras_sources
    ]

    win = "CarVision — All Cameras"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    print(f"[viewer] Showing {len(workers)} camera(s). Press Q or ESC to quit.", flush=True)

    TILE_W, TILE_H = 640, 360
    COLS = min(len(workers), 3)
    ROWS = (len(workers) + COLS - 1) // COLS

    while True:
        tiles = []
        for w in workers:
            frame, detection, fps_cap, fps_det = w.latest()
            if frame is None:
                tile = np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8)
                cv2.putText(tile, f"Waiting: {w.label}", (10, TILE_H // 2),
                            _FONT, 0.6, _YELLOW, 1, cv2.LINE_AA)
            else:
                tile = _draw(frame, detection, allowed, fps_cap, fps_det, w.label)
                tile = cv2.resize(tile, (TILE_W, TILE_H))
                if detection:
                    plate = detection.get("plate_text", "")
                    det   = detection.get("detector", "")
                    conf  = float(detection.get("confidence") or 0)
                    status = "ALLOWED" if plate.upper() in allowed else "DENIED"
                    print(f"[{w.label}] {plate}  {conf:.0%}  {det}  → {status}", flush=True)
            tiles.append(tile)

        # Pad to fill grid
        while len(tiles) < ROWS * COLS:
            tiles.append(np.zeros((TILE_H, TILE_W, 3), dtype=np.uint8))

        rows_imgs = []
        for r in range(ROWS):
            row_tiles = tiles[r * COLS: r * COLS + COLS]
            rows_imgs.append(np.hstack(row_tiles))
        grid = np.vstack(rows_imgs)

        cv2.imshow(win, grid)
        key = cv2.waitKey(1) & 0xFF
        if key in (ord("q"), ord("Q"), 27):
            break

    for w in workers:
        w.shutdown()
    cv2.destroyAllWindows()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="CarVision standalone viewer")
    parser.add_argument("--camera", type=int, default=None,
                        help="Camera ID from DB (default: all enabled cameras)")
    parser.add_argument("--source", type=str, default=None,
                        help="Override RTSP/webcam source URL directly")
    parser.add_argument("--mode", type=str, default="auto",
                        choices=["auto", "yolo", "contour"],
                        help="Detection mode (default: auto)")
    args = parser.parse_args()

    print("[viewer] Loading settings from DB …", flush=True)
    cameras, allowed = _load_settings()
    print(f"[viewer] {len(allowed)} allowed plates loaded.", flush=True)

    if args.source:
        # Ad-hoc source — no DB camera needed
        run_camera(args.source, args.source, allowed, args.mode)
        return

    if args.camera is not None:
        cam = _get_camera_by_id(args.camera)
        if not cam:
            print(f"[viewer] Camera ID {args.camera} not found in DB.", flush=True)
            sys.exit(1)
        run_camera(cam.source, f"#{cam.id} {cam.name}", allowed, args.mode)
        return

    if not cameras:
        print("[viewer] No enabled cameras found in DB. "
              "Use --source <url> to specify one directly.", flush=True)
        sys.exit(1)

    if len(cameras) == 1:
        cam = cameras[0]
        run_camera(cam.source, f"#{cam.id} {cam.name}", allowed, args.mode)
    else:
        sources = [(cam.source, f"#{cam.id} {cam.name}") for cam in cameras]
        run_multi(sources, allowed, args.mode)


if __name__ == "__main__":
    main()
