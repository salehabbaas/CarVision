import threading
import time
import os
from typing import Dict, Optional
from pathlib import Path

import cv2

LIVE_JPEG_QUALITY = 82

# Low-latency FFMPEG flags for RTSP cameras and DVR streams.
# Pulled from env so the docker-compose file can override them without
# rebuilding the image (see OPENCV_FFMPEG_CAPTURE_OPTIONS in compose).
_ENV_FFMPEG_OPTS = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
LOW_LATENCY_RTSP_CAPTURE_OPTIONS = _ENV_FFMPEG_OPTS or (
    "rtsp_transport;tcp"
    "|fflags;nobuffer"
    "|flags;low_delay"
    "|max_delay;0"
    "|reorder_queue_size;0"
    "|buffer_size;204800"
    "|stimeout;10000000"   # 10-second connection timeout for slow/WAN cameras
)


class StreamWorker:
    """
    Dedicated background thread that keeps a VideoCapture open for one camera
    and caches the most-recent JPEG and raw frame.

    Reconnect strategy (exponential back-off):
      - After the first failed read the worker waits 0.5 s before reconnecting.
      - Each subsequent failure doubles the delay, capped at 15 s.
      - A successful read resets the delay back to 0.5 s.
    """

    def __init__(self, camera_id: int, camera_type: str, source: str):
        self.camera_id   = camera_id
        self.camera_type = camera_type
        self.source      = source

        self._lock         = threading.Lock()
        self._stop         = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._cap          = None
        self._latest_frame = None
        self._latest_jpeg: Optional[bytes] = None
        self._last_read    = 0.0
        self._last_ok      = 0.0
        self._retry_delay  = 0.5   # start at 0.5 s, doubles on failure up to 15 s

    # ── lifecycle ─────────────────────────────────────────────────────────────
    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"stream-{self.camera_id}")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        if self._cap:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    # ── source resolution ─────────────────────────────────────────────────────
    def _build_source_candidates(self):
        """Return a prioritised list of source strings to try when opening."""
        source = self.source

        # Webcam: use integer index
        if self.camera_type == "webcam":
            try:
                return [int(source)]
            except Exception:
                return [0]

        if not isinstance(source, str):
            return [source]

        source = source.strip()
        candidates = []

        def add(value):
            if value not in candidates:
                candidates.append(value)

        add(source)

        # tcp:// → try both http:// and rtsp://
        if source.startswith("tcp://"):
            add("http://"  + source[len("tcp://"):])
            add("rtsp://"  + source[len("tcp://"):])

        # http_mjpeg without scheme
        if self.camera_type == "http_mjpeg":
            if not source.startswith(("http://", "https://")):
                add("http://" + source.lstrip("/"))

        # rtsp without scheme
        if self.camera_type == "rtsp":
            if not source.startswith("rtsp://") and "://" not in source:
                add("rtsp://" + source)

        return candidates

    @staticmethod
    def _open_capture_for_source(source) -> cv2.VideoCapture:
        """Open a single VideoCapture source with all low-latency settings applied."""
        # For RTSP sources inject the low-latency FFMPEG options via env var
        # (OpenCV reads OPENCV_FFMPEG_CAPTURE_OPTIONS automatically).
        if isinstance(source, str) and source.startswith("rtsp://"):
            os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = LOW_LATENCY_RTSP_CAPTURE_OPTIONS

        # Numeric webcam indices should use the default backend, not FFMPEG.
        # Forcing FFMPEG on integer indexes triggers noisy warnings in Docker.
        if isinstance(source, int):
            cap = cv2.VideoCapture(source)
        elif isinstance(source, str) and source.startswith(("http://", "https://")):
            cap = cv2.VideoCapture(source)
        else:
            try:
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            except Exception:
                cap = cv2.VideoCapture(source)

        # Minimise internal frame queue so we always get the newest frame
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        # Aggressive connect / read timeouts (5 s each)
        for prop in (cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, cv2.CAP_PROP_READ_TIMEOUT_MSEC):
            try:
                cap.set(prop, 5000)
            except Exception:
                pass

        return cap

    def _open_capture(self) -> cv2.VideoCapture:
        """Try each candidate source in order; return the first that gives a frame."""
        candidates = self._build_source_candidates()
        fallback = None

        for source in candidates:
            cap = self._open_capture_for_source(source)
            if cap is None:
                continue
            if fallback is None:
                fallback = cap
            if not cap.isOpened():
                cap.release()
                continue
            ret, frame = cap.read()
            if ret and frame is not None:
                return cap
            cap.release()

        # Nothing worked – return the last attempted capture (may reconnect later)
        if fallback is not None:
            return fallback
        return self._open_capture_for_source(self.source)

    # ── main loop ─────────────────────────────────────────────────────────────
    def _run(self):
        self._cap = self._open_capture()

        while not self._stop.is_set():
            # ── reconnect if the capture is closed ──
            if not self._cap or not self._cap.isOpened():
                if self.camera_type == "webcam":
                    try:
                        webcam_idx = int(self.source)
                    except Exception:
                        webcam_idx = 0
                    if not Path(f"/dev/video{webcam_idx}").exists():
                        time.sleep(15.0)
                        continue
                time.sleep(self._retry_delay)
                self._retry_delay = min(15.0, self._retry_delay * 2)
                if self._cap:
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                self._cap = self._open_capture()
                continue

            ret, frame = self._cap.read()

            if not ret or frame is None:
                # Give the stream a brief chance to recover before reconnecting
                if time.time() - self._last_ok > 3.0:
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                    time.sleep(self._retry_delay)
                    self._retry_delay = min(15.0, self._retry_delay * 1.5)
                    self._cap = self._open_capture()
                else:
                    time.sleep(0.05)
                continue

            # ── successful read ──
            ret_enc, buffer = cv2.imencode(
                ".jpg",
                frame,
                [int(cv2.IMWRITE_JPEG_QUALITY), LIVE_JPEG_QUALITY],
            )
            if not ret_enc:
                continue

            with self._lock:
                self._latest_frame = frame
                self._latest_jpeg  = buffer.tobytes()
                now = time.time()
                self._last_read    = now
                self._last_ok      = now
                self._retry_delay  = 0.5   # reset back-off on success

            # Yield briefly so other threads get CPU time
            time.sleep(0.001)

    # ── accessors (thread-safe) ───────────────────────────────────────────────
    def get_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._latest_jpeg

    def get_frame(self):
        with self._lock:
            return self._latest_frame

    def last_read(self) -> float:
        with self._lock:
            return self._last_read

    def last_ok(self) -> float:
        with self._lock:
            return self._last_ok


class StreamManager:
    """
    Singleton that owns one StreamWorker per native camera and holds the
    latest frame/detection for browser-based cameras (which push frames
    via HTTP POST rather than being pulled by a worker thread).
    """

    def __init__(self):
        self._workers:    Dict[int, StreamWorker] = {}
        self._lock        = threading.Lock()
        self._external:   Dict[int, Dict] = {}   # browser-camera frames
        self._detections: Dict[int, Dict] = {}   # latest plate-detection per camera

    # ── worker management ────────────────────────────────────────────────────
    def ensure_worker(self, camera_id: int, camera_type: str, source: str) -> StreamWorker:
        with self._lock:
            worker = self._workers.get(camera_id)
            # Restart worker if the source/type changed (camera was edited)
            if worker and (worker.camera_type != camera_type or worker.source != source):
                worker.stop()
                worker = None
            if worker is None:
                worker = StreamWorker(camera_id, camera_type, source)
                self._workers[camera_id] = worker
                worker.start()
            return worker

    def stop_worker(self, camera_id: int):
        """Stop and remove the worker for a deleted/disabled camera."""
        with self._lock:
            worker = self._workers.pop(camera_id, None)
        if worker:
            worker.stop()

    # ── browser-camera (external) frames ────────────────────────────────────
    def set_external_frame(self, camera_id: int, frame, jpeg: bytes):
        self._external[camera_id] = {
            "frame": frame,
            "jpeg":  jpeg,
            "ts":    time.time(),
        }

    def get_external_frame(self, camera_id: int):
        data = self._external.get(camera_id)
        return data.get("frame") if data else None

    def get_external_jpeg(self, camera_id: int) -> Optional[bytes]:
        data = self._external.get(camera_id)
        return data.get("jpeg") if data else None

    def get_external_last_ts(self, camera_id: int) -> Optional[float]:
        data = self._external.get(camera_id)
        return data.get("ts") if data else None

    def is_external_online(self, camera_id: int, threshold_seconds: float = 5.0) -> bool:
        ts = self.get_external_last_ts(camera_id)
        return bool(ts and (time.time() - ts) <= threshold_seconds)

    # ── detection overlay ────────────────────────────────────────────────────
    def set_detection(self, camera_id: int, detection: Dict):
        with self._lock:
            self._detections[camera_id] = detection

    def get_detection(self, camera_id: int) -> Optional[Dict]:
        with self._lock:
            return self._detections.get(camera_id)

    # ── unified accessors ────────────────────────────────────────────────────
    def get_last_ok(self, camera_id: int, camera_type: str, source: str) -> Optional[float]:
        if camera_type == "browser":
            return self.get_external_last_ts(camera_id)
        worker = self.ensure_worker(camera_id, camera_type, source)
        return worker.last_ok()

    def get_jpeg(self, camera_id: int, camera_type: str, source: str) -> Optional[bytes]:
        if camera_type == "browser":
            return self.get_external_jpeg(camera_id)
        worker = self.ensure_worker(camera_id, camera_type, source)
        return worker.get_jpeg()

    def get_frame(self, camera_id: int, camera_type: str, source: str):
        if camera_type == "browser":
            return self.get_external_frame(camera_id)
        worker = self.ensure_worker(camera_id, camera_type, source)
        return worker.get_frame()
