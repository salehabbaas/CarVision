import threading
import time
import os
from typing import Dict, Optional

import cv2


class StreamWorker:
    def __init__(self, camera_id: int, camera_type: str, source: str):
        self.camera_id = camera_id
        self.camera_type = camera_type
        self.source = source
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._cap = None
        self._latest_frame = None
        self._latest_jpeg = None
        self._last_read = 0.0
        self._last_ok = 0.0
        self._retry_delay = 0.5

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap:
            self._cap.release()

    def _build_source_candidates(self):
        source = self.source
        if self.camera_type == "webcam":
            try:
                return [int(source)]
            except Exception:
                return [0]

        if not isinstance(source, str):
            return [source]

        source = source.strip()
        candidates = []

        def add_candidate(value):
            if value not in candidates:
                candidates.append(value)

        add_candidate(source)
        if source.startswith("tcp://"):
            add_candidate("http://" + source[len("tcp://") :])
            add_candidate("rtsp://" + source[len("tcp://") :])

        if self.camera_type == "http_mjpeg":
            if not source.startswith("http://") and not source.startswith("https://"):
                add_candidate("http://" + source.lstrip("/"))

        if self.camera_type == "rtsp":
            if not source.startswith("rtsp://") and "://" not in source:
                add_candidate("rtsp://" + source)

        return candidates

    @staticmethod
    def _open_capture_for_source(source):
        if isinstance(source, str) and source.startswith("rtsp://"):
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
        if isinstance(source, str) and (source.startswith("http://") or source.startswith("https://")):
            cap = cv2.VideoCapture(source)
        else:
            try:
                cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
            except Exception:
                cap = cv2.VideoCapture(source)
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        try:
            cap.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000)
            cap.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        except Exception:
            pass
        return cap

    def _open_capture(self):
        candidates = self._build_source_candidates()
        fallback = None
        for source in candidates:
            cap = self._open_capture_for_source(source)
            if not cap:
                continue
            fallback = cap
            if not cap.isOpened():
                cap.release()
                continue
            ret, frame = cap.read()
            if ret and frame is not None:
                return cap
            cap.release()
        if fallback is not None:
            return fallback
        return self._open_capture_for_source(self.source)

    def _run(self):
        self._cap = self._open_capture()
        while not self._stop.is_set():
            if not self._cap.isOpened():
                time.sleep(self._retry_delay)
                self._retry_delay = min(5.0, self._retry_delay * 1.5)
                self._cap.release()
                self._cap = self._open_capture()
                continue

            ret, frame = self._cap.read()
            if not ret or frame is None:
                # Reconnect if we haven't seen frames in a while
                if time.time() - self._last_ok > 2.0:
                    self._cap.release()
                    time.sleep(self._retry_delay)
                    self._retry_delay = min(5.0, self._retry_delay * 1.3)
                    self._cap = self._open_capture()
                else:
                    time.sleep(0.05)
                continue

            ret, buffer = cv2.imencode(".jpg", frame)
            if not ret:
                continue

            with self._lock:
                self._latest_frame = frame
                self._latest_jpeg = buffer.tobytes()
                now = time.time()
                self._last_read = now
                self._last_ok = now
                self._retry_delay = 0.4
            time.sleep(0.001)

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
    def __init__(self):
        self._workers: Dict[int, StreamWorker] = {}
        self._lock = threading.Lock()
        self._external: Dict[int, Dict] = {}
        self._detections: Dict[int, Dict] = {}

    def ensure_worker(self, camera_id: int, camera_type: str, source: str) -> StreamWorker:
        with self._lock:
            worker = self._workers.get(camera_id)
            if worker and (worker.camera_type != camera_type or worker.source != source):
                worker.stop()
                worker = None
            if worker is None:
                worker = StreamWorker(camera_id, camera_type, source)
                self._workers[camera_id] = worker
                worker.start()
            return worker

    def set_external_frame(self, camera_id: int, frame, jpeg: bytes):
        self._external[camera_id] = {
            "frame": frame,
            "jpeg": jpeg,
            "ts": time.time(),
        }

    def set_detection(self, camera_id: int, detection: Dict):
        with self._lock:
            self._detections[camera_id] = detection

    def get_detection(self, camera_id: int) -> Optional[Dict]:
        with self._lock:
            return self._detections.get(camera_id)

    def get_external_frame(self, camera_id: int):
        data = self._external.get(camera_id)
        if not data:
            return None
        return data.get("frame")

    def get_external_jpeg(self, camera_id: int) -> Optional[bytes]:
        data = self._external.get(camera_id)
        if not data:
            return None
        return data.get("jpeg")

    def get_external_last_ts(self, camera_id: int) -> Optional[float]:
        data = self._external.get(camera_id)
        if not data:
            return None
        return data.get("ts")

    def get_last_ok(self, camera_id: int, camera_type: str, source: str) -> Optional[float]:
        if camera_type == "browser":
            return self.get_external_last_ts(camera_id)
        worker = self.ensure_worker(camera_id, camera_type, source)
        return worker.last_ok()

    def is_external_online(self, camera_id: int, threshold_seconds: float = 5.0) -> bool:
        ts = self.get_external_last_ts(camera_id)
        if not ts:
            return False
        return (time.time() - ts) <= threshold_seconds

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
