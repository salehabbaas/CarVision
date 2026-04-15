import hashlib
import logging
import threading
import time
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from collections import Counter, deque
from difflib import SequenceMatcher

import cv2
import numpy as np

from plate_detector import detect_plate, set_yolo_config
from anpr import set_anpr_config
from pipeline import PlateInferencePipeline
from anpr import build_debug_bundle, crop_from_bbox, read_plate_text
from db import SessionLocal
from models import Camera, AllowedPlate, Detection, AppSetting, Notification, TrainingSample

# Thread pool for background I/O tasks (snapshot saving, DB writes, clip recording).
# These are offloaded so the detection loop can push the overlay immediately.
_io_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="cam-io")
logger = logging.getLogger(__name__)


class CameraWorker:
    def __init__(self, camera: Camera, media_dir: Path, mode_provider=None, stream_manager=None, stationary_policy_provider=None):
        self.camera = camera
        self.media_dir = media_dir
        self._stop_event = threading.Event()
        self._thread = None
        self._recent = {}
        self._history = deque(maxlen=16)
        self._mode_provider = mode_provider or (lambda: "auto")
        self._stream_manager = stream_manager
        self._stationary_policy_provider = stationary_policy_provider or (
            lambda: {"enabled": True, "motion_threshold": 7.0, "hold_seconds": 0.0}
        )
        self._pipeline = PlateInferencePipeline()
        self._known_cache = []
        self._known_cache_ts = 0.0
        self._policy_cache = {"min_len": 5, "max_len": 8}
        self._policy_cache_ts = 0.0
        self._allowed_stationary_hold: Optional[Dict] = None
        # Frame-motion guard: stores a tiny thumbnail of the last scanned frame
        # to skip re-detection when the stream is frozen or the scene is static.
        self._last_scan_thumb: Optional[np.ndarray] = None

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _open_capture(self):
        source = self.camera.source
        if self.camera.type == "webcam":
            try:
                source = int(source)
            except ValueError:
                source = 0
        if self.camera.type == "http_mjpeg" and isinstance(source, str):
            source = source.strip()
            if source.startswith("tcp://"):
                source = "http://" + source[len("tcp://") :]
            if not source.startswith("http://") and not source.startswith("https://"):
                source = "http://" + source
        if isinstance(source, str) and source.startswith("rtsp://"):
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
        if isinstance(source, int):
            cap = cv2.VideoCapture(source)
        elif isinstance(source, str) and (source.startswith("http://") or source.startswith("https://")):
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

    def _is_allowed(self, plate_text: str) -> bool:
        with SessionLocal() as db:
            allowed = (
                db.query(AllowedPlate)
                .filter(AllowedPlate.active.is_(True))
                .all()
            )
            allowed_set = {a.plate_text.upper() for a in allowed}
        return plate_text.upper() in allowed_set

    def _known_plate_candidates(self):
        now = time.time()
        if self._known_cache and now - self._known_cache_ts < 20:
            return self._known_cache
        with SessionLocal() as db:
            allowed = (
                db.query(AllowedPlate.plate_text)
                .filter(AllowedPlate.active.is_(True))
                .all()
            )
            training = (
                db.query(TrainingSample.plate_text)
                .filter(TrainingSample.ignored.is_(False))
                .filter(TrainingSample.no_plate.is_(False))
                .filter(TrainingSample.plate_text.isnot(None))
                .all()
            )
            try:
                min_len_setting = db.get(AppSetting, "plate_min_length")
                max_len_setting = db.get(AppSetting, "plate_max_length")
                min_len = int(min_len_setting.value) if min_len_setting and min_len_setting.value else 5
                max_len = int(max_len_setting.value) if max_len_setting and max_len_setting.value else 8
                if min_len > max_len:
                    min_len, max_len = max_len, min_len
                self._policy_cache = {"min_len": max(1, min_len), "max_len": max(1, max_len)}
                self._policy_cache_ts = now
            except Exception:
                self._policy_cache = {"min_len": 5, "max_len": 8}
                self._policy_cache_ts = now
        pool = {str(v[0]).strip().upper() for v in allowed + training if v and v[0]}
        min_len = int(self._policy_cache.get("min_len", 5))
        max_len = int(self._policy_cache.get("max_len", 8))
        self._known_cache = [p for p in pool if min_len <= len(p) <= max_len]
        self._known_cache_ts = now
        return self._known_cache

    def _match_known_plate(self, plate_text: str) -> str:
        normalized = (plate_text or "").strip().upper()
        min_len = int(self._policy_cache.get("min_len", 5))
        max_len = int(self._policy_cache.get("max_len", 8))
        if len(normalized) < min_len:
            return normalized
        if len(normalized) > max_len:
            normalized = normalized[:max_len]
        candidates = self._known_plate_candidates()
        if not candidates or normalized in candidates:
            return normalized
        best = normalized
        best_score = 0.0
        for cand in candidates:
            if abs(len(cand) - len(normalized)) > 1:
                continue
            score = SequenceMatcher(None, normalized, cand).ratio()
            if score > best_score:
                best_score = score
                best = cand
        return best if (best_score >= 0.93 and len(best) == len(normalized)) else normalized

    @staticmethod
    def _refine_detection_from_crop(frame, detection: Dict) -> Dict:
        if frame is None or not isinstance(detection, dict):
            return detection
        bbox = detection.get("bbox")
        if not bbox:
            return detection
        try:
            crop = crop_from_bbox(frame, bbox)
        except Exception:
            crop = None
        if crop is None:
            return detection
        ocr = read_plate_text(crop)
        if not ocr or not ocr.get("plate_text"):
            return detection
        detection["plate_text"] = ocr.get("plate_text")
        det_conf = float(detection.get("confidence") or 0.0)
        ocr_conf = float(ocr.get("confidence") or 0.0)
        detection["confidence"] = max(det_conf, ocr_conf)
        detection["raw_text"] = ocr.get("raw_text")
        detection["candidates"] = ocr.get("candidates")
        return detection

    def _save_snapshot(self, frame, plate_text: str) -> Optional[str]:
        if not self.camera.save_snapshot:
            return None
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.camera.id}_{plate_text}_{ts}.jpg"
        path = self.media_dir / filename
        cv2.imwrite(str(path), frame)
        return filename

    def _save_clip(self, cap, plate_text: str) -> Optional[str]:
        if not self.camera.save_clip or self.camera.clip_seconds <= 0:
            return None
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.camera.id}_{plate_text}_{ts}.mp4"
        path = self.media_dir / filename

        fps = cap.get(cv2.CAP_PROP_FPS)
        if not fps or fps != fps or fps <= 0:
            fps = 10.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 640)
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 480)

        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        frames_to_write = int(self.camera.clip_seconds * fps)
        written = 0
        while written < frames_to_write and not self._stop_event.is_set():
            ret, frame = cap.read()
            if not ret:
                break
            writer.write(frame)
            written += 1
        writer.release()
        return filename if written > 0 else None

    def _save_clip_from_stream(self, plate_text: str) -> Optional[str]:
        if not self.camera.save_clip or self.camera.clip_seconds <= 0:
            return None
        if not self._stream_manager:
            return None
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.camera.id}_{plate_text}_{ts}.mp4"
        path = self.media_dir / filename

        fps = 10.0
        frames_to_write = int(self.camera.clip_seconds * fps)
        first = self._stream_manager.get_external_frame(self.camera.id) if self.camera.type == "browser" else self._stream_manager.get_frame(self.camera.id, self.camera.type, self.camera.source)
        if first is None:
            return None
        height, width = first.shape[:2]
        writer = cv2.VideoWriter(
            str(path),
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps,
            (width, height),
        )
        written = 0
        while written < frames_to_write and not self._stop_event.is_set():
            frame = self._stream_manager.get_external_frame(self.camera.id) if self.camera.type == "browser" else self._stream_manager.get_frame(self.camera.id, self.camera.type, self.camera.source)
            if frame is not None:
                writer.write(frame)
                written += 1
            time.sleep(1 / fps)
        writer.release()
        return filename if written > 0 else None

    def _save_debug_images(
        self,
        frame,
        detection: Dict,
        plate_text: str,
    ) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str], Optional[str]]:
        if frame is None or not detection:
            return None, None, None, None, None
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        debug_dir = self.media_dir / "debug"
        debug_dir.mkdir(parents=True, exist_ok=True)
        base = f"{self.camera.id}_{plate_text}_{ts}"
        color_name = f"debug/{base}_color.jpg"
        bw_name = f"debug/{base}_bw.jpg"
        gray_name = f"debug/{base}_gray.jpg"
        edged_name = f"debug/{base}_edged.jpg"
        mask_name = f"debug/{base}_mask.jpg"
        try:
            bundle = build_debug_bundle(frame, detection.get("bbox"))
            debug_color = bundle.get("color")
            debug_bw = bundle.get("bw")
            debug_gray = bundle.get("gray")
            debug_edged = bundle.get("edged")
            debug_mask = bundle.get("mask")
            if debug_color is not None:
                cv2.imwrite(str(self.media_dir / color_name), debug_color)
            if debug_bw is not None:
                cv2.imwrite(str(self.media_dir / bw_name), cv2.cvtColor(debug_bw, cv2.COLOR_GRAY2BGR))
            if debug_gray is not None:
                cv2.imwrite(str(self.media_dir / gray_name), debug_gray)
            if debug_edged is not None:
                cv2.imwrite(str(self.media_dir / edged_name), debug_edged)
            if debug_mask is not None:
                cv2.imwrite(str(self.media_dir / mask_name), debug_mask)
        except Exception:
            logger.exception("Camera %s debug asset generation failed", self.camera.id)
            return None, None, None, None, None

        return (
            color_name if debug_color is not None else None,
            bw_name if debug_bw is not None else None,
            gray_name if debug_gray is not None else None,
            edged_name if debug_edged is not None else None,
            mask_name if debug_mask is not None else None,
        )

    @staticmethod
    def _normalize_live_mode(mode: Optional[str]) -> str:
        normalized = str(mode or "auto").strip().lower()
        if normalized not in {"auto", "contour", "yolo"}:
            return "auto"
        return normalized

    def _resolve_live_detection(self, frame) -> Tuple[Optional[Dict], str]:
        mode_override = self._mode_provider()
        if self.camera.detector_mode and self.camera.detector_mode != "inherit":
            mode_override = self.camera.detector_mode
        resolved_mode = self._normalize_live_mode(mode_override)

        detection = None
        if self._pipeline and self._pipeline.enabled:
            try:
                result = self._pipeline.run(frame, camera_id=self.camera.id, mode_override=resolved_mode)
                detection = result.to_legacy_detection() if result else None
            except Exception:
                logger.exception("Camera %s pipeline detection failed for mode %s", self.camera.id, resolved_mode)

        if not detection:
            try:
                detection = detect_plate(frame, mode_override=resolved_mode)
            except Exception:
                logger.exception("Camera %s detector failed for mode %s", self.camera.id, resolved_mode)

        return detection, resolved_mode

    def _stabilize_plate(self, plate_text: str, now: float) -> str:
        self._history.append((plate_text, now))
        recent = [p for p, ts in self._history if now - ts <= 4.0]
        if not recent:
            return plate_text
        counts = Counter(recent)
        best, count = counts.most_common(1)[0]
        if count >= 2:
            return best
        return plate_text

    @staticmethod
    def _bbox_to_rect(bbox, frame_shape) -> Optional[Tuple[int, int, int, int]]:
        if bbox is None:
            return None
        h, w = frame_shape[:2]
        x1 = y1 = x2 = y2 = None
        if isinstance(bbox, dict):
            if all(k in bbox for k in ("x1", "y1", "x2", "y2")):
                x1 = int(bbox.get("x1", 0))
                y1 = int(bbox.get("y1", 0))
                x2 = int(bbox.get("x2", 0))
                y2 = int(bbox.get("y2", 0))
            elif all(k in bbox for k in ("x", "y", "w", "h")):
                x = int(bbox.get("x", 0))
                y = int(bbox.get("y", 0))
                bw = int(bbox.get("w", 0))
                bh = int(bbox.get("h", 0))
                x1, y1, x2, y2 = x, y, x + bw, y + bh
        elif isinstance(bbox, list):
            try:
                pts = np.array(bbox, dtype=np.int32)
                if pts.ndim == 3 and pts.shape[1] == 1 and pts.shape[2] == 2:
                    pts = pts.reshape(-1, 2)
                if pts.ndim == 2 and pts.shape[1] == 2:
                    rx, ry, rw, rh = cv2.boundingRect(pts)
                    x1, y1, x2, y2 = rx, ry, rx + rw, ry + rh
            except Exception:
                return None
        if x1 is None or y1 is None or x2 is None or y2 is None:
            return None
        x1 = max(0, min(int(x1), w - 1))
        y1 = max(0, min(int(y1), h - 1))
        x2 = max(x1 + 1, min(int(x2), w))
        y2 = max(y1 + 1, min(int(y2), h))
        if x2 <= x1 or y2 <= y1:
            return None
        return (x1, y1, x2, y2)

    @staticmethod
    def _crop_rect(frame, rect: Tuple[int, int, int, int]):
        x1, y1, x2, y2 = rect
        return frame[y1:y2, x1:x2]

    def _current_stationary_policy(self) -> Dict[str, float]:
        raw = {}
        try:
            raw = self._stationary_policy_provider() or {}
        except Exception:
            raw = {}
        enabled = bool(raw.get("enabled", True))
        try:
            motion_threshold = float(raw.get("motion_threshold", 7.0))
        except Exception:
            motion_threshold = 7.0
        try:
            hold_seconds = float(raw.get("hold_seconds", 0.0))
        except Exception:
            hold_seconds = 0.0
        motion_threshold = max(0.5, min(50.0, motion_threshold))
        hold_seconds = max(0.0, min(3600.0, hold_seconds))
        if hold_seconds <= 0.0:
            hold_seconds = max(30.0, float(self.camera.cooldown_seconds or 10.0) * 12.0)
        return {
            "enabled": enabled,
            "motion_threshold": motion_threshold,
            "hold_seconds": hold_seconds,
        }

    def _set_allowed_stationary_hold(self, frame, detection: Dict, plate_text: str, now_ts: float):
        rect = self._bbox_to_rect(detection.get("bbox"), frame.shape)
        if not rect:
            self._allowed_stationary_hold = None
            return
        crop = self._crop_rect(frame, rect)
        if crop is None or crop.size == 0:
            self._allowed_stationary_hold = None
            return
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        self._allowed_stationary_hold = {
            "plate_text": plate_text,
            "rect": rect,
            "roi_gray": gray,
            "set_at": now_ts,
        }

    def _is_allowed_stationary_now(self, frame, now_ts: float) -> bool:
        policy = self._current_stationary_policy()
        if not bool(policy.get("enabled", True)):
            self._allowed_stationary_hold = None
            return False
        hold = self._allowed_stationary_hold
        if not hold:
            return False
        if now_ts - float(hold.get("set_at") or now_ts) > float(policy.get("hold_seconds", 30.0)):
            self._allowed_stationary_hold = None
            return False
        rect = hold.get("rect")
        ref_gray = hold.get("roi_gray")
        if not rect or ref_gray is None:
            self._allowed_stationary_hold = None
            return False
        x1, y1, x2, y2 = rect
        h, w = frame.shape[:2]
        # Slightly expand ROI to tolerate tiny bbox drift.
        pad_x = max(4, int((x2 - x1) * 0.08))
        pad_y = max(4, int((y2 - y1) * 0.08))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(w, x2 + pad_x)
        y2 = min(h, y2 + pad_y)
        if x2 <= x1 or y2 <= y1:
            self._allowed_stationary_hold = None
            return False
        crop = frame[y1:y2, x1:x2]
        if crop is None or crop.size == 0:
            self._allowed_stationary_hold = None
            return False
        cur_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if cur_gray.shape != ref_gray.shape:
            cur_gray = cv2.resize(cur_gray, (ref_gray.shape[1], ref_gray.shape[0]))
        score = float(cv2.mean(cv2.absdiff(cur_gray, ref_gray))[0])
        if score < float(policy.get("motion_threshold", 7.0)):
            return True
        self._allowed_stationary_hold = None
        return False

    def _run(self):
        cap = None if self._stream_manager else self._open_capture()
        last_scan = 0.0
        capture_retry_delay = 1.0
        while not self._stop_event.is_set():
            if self._stream_manager:
                if self.camera.type == "browser":
                    frame = self._stream_manager.get_external_frame(self.camera.id)
                else:
                    frame = self._stream_manager.get_frame(self.camera.id, self.camera.type, self.camera.source)
                if frame is None:
                    time.sleep(0.1)
                    continue
            else:
                if not cap.isOpened():
                    if self.camera.type == "webcam":
                        try:
                            webcam_idx = int(self.camera.source)
                        except Exception:
                            webcam_idx = 0
                        if not Path(f"/dev/video{webcam_idx}").exists():
                            time.sleep(15.0)
                            continue
                    time.sleep(capture_retry_delay)
                    cap = self._open_capture()
                    capture_retry_delay = min(15.0, capture_retry_delay * 1.5)
                    continue
                capture_retry_delay = 1.0

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.5)
                    continue

            now = time.time()
            # If we just recognized an allowed plate and the car has not moved,
            # pause new detections/snapshots until movement is seen again.
            if self._is_allowed_stationary_now(frame, now):
                time.sleep(0.05)
                continue

            scan_interval = max(0.1, float(self.camera.scan_interval or 1.0))
            if now - last_scan < scan_interval:
                time.sleep(min(0.05, max(0.0, scan_interval - (now - last_scan))))
                continue

            last_scan = now

            # ── Frame-motion guard ──────────────────────────────────────────
            # Compute a tiny 16×9 grayscale thumbnail of the current frame and
            # compare it to the last scanned frame.  If the mean pixel difference
            # is below the threshold (< 1.5 / 255 ≈ 0.6%) the stream is either
            # frozen or the scene is completely static — skip detection to avoid
            # false positives from road markings, building text, sky patterns.
            try:
                thumb = cv2.cvtColor(
                    cv2.resize(frame, (16, 9), interpolation=cv2.INTER_AREA),
                    cv2.COLOR_BGR2GRAY,
                )
                if self._last_scan_thumb is not None:
                    motion = float(np.mean(cv2.absdiff(thumb, self._last_scan_thumb)))
                    if motion < 1.5:
                        time.sleep(0.02)
                        continue
                self._last_scan_thumb = thumb
            except Exception:
                pass  # if thumbnail fails, proceed with detection anyway

            detection, resolved_mode = self._resolve_live_detection(frame)
            if not detection:
                continue
            detection = self._refine_detection_from_crop(frame, detection)
            if not detection.get("detector"):
                detection["detector"] = resolved_mode

            plate_text = self._match_known_plate(detection["plate_text"])
            detection["plate_text"] = plate_text
            plate_text = self._stabilize_plate(plate_text, now)
            last_seen = self._recent.get(plate_text, 0)
            if now - last_seen < self.camera.cooldown_seconds:
                continue

            self._recent[plate_text] = now
            allowed = self._is_allowed(plate_text)
            status = "allowed" if allowed else "denied"
            if allowed:
                self._set_allowed_stationary_hold(frame, detection, plate_text, now)
            else:
                self._allowed_stationary_hold = None

            # ── Push overlay to the frontend IMMEDIATELY ────────────────────
            # Snapshot saving, debug-image generation, clip recording, and DB
            # writes are all slow I/O operations.  Doing them before pushing
            # the overlay would add hundreds of milliseconds of visible lag.
            # Instead we push the overlay with what we already know, then
            # offload all I/O to the background thread pool.
            if self._stream_manager:
                self._stream_manager.set_detection(
                    self.camera.id,
                    {
                        "id": None,          # filled in later by the background task
                        "plate_text": plate_text,
                        "status": status,
                        "confidence": detection.get("confidence"),
                        "bbox": detection.get("bbox"),
                        "detector": detection.get("detector"),
                        "debug_steps": [],   # updated once debug images are ready
                        "ts": time.time(),
                    },
                )

            # ── Background I/O task ─────────────────────────────────────────
            # Capture everything we need by value (frame copy, detection copy)
            # so the detection loop can continue immediately.
            _frame_copy     = frame.copy()
            _detection_copy = dict(detection)
            _camera         = self.camera
            _media_dir      = self.media_dir
            _stream_manager = self._stream_manager
            _cap_ref        = cap if not self._stream_manager else None

            def _background_io(
                frame=_frame_copy,
                detection=_detection_copy,
                camera=_camera,
                media_dir=_media_dir,
                stream_manager=_stream_manager,
                plate_text=plate_text,
                status=status,
                allowed=allowed,
                cap=_cap_ref,
            ):
                try:
                    # Snapshot
                    image_path = None
                    if camera.save_snapshot:
                        ts_str   = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                        filename = f"{camera.id}_{plate_text}_{ts_str}.jpg"
                        path     = media_dir / filename
                        cv2.imwrite(str(path), frame)
                        image_path = filename

                    # Debug images
                    debug_color_path, debug_bw_path, debug_gray_path, debug_edged_path, debug_mask_path = self._save_debug_images(
                        frame,
                        detection,
                        plate_text,
                    )

                    # Detection-triggered clip writes are intentionally disabled.
                    # Clip recording is handled through explicit manual start/stop
                    # from the Live page to avoid multiple files per incident.
                    video_path = None

                    # Image hash
                    image_hash = None
                    if image_path:
                        try:
                            image_hash = hashlib.sha256(
                                (media_dir / image_path).read_bytes()
                            ).hexdigest()
                        except Exception:
                            logger.exception("Camera %s image hash generation failed", camera.id)

                    # DB write
                    det_id = None
                    with SessionLocal() as db:
                        det_row = Detection(
                            camera_id=camera.id,
                            plate_text=plate_text,
                            confidence=detection.get("confidence"),
                            status=status,
                            image_path=image_path,
                            video_path=video_path,
                            debug_color_path=debug_color_path,
                            debug_bw_path=debug_bw_path,
                            debug_gray_path=debug_gray_path,
                            debug_edged_path=debug_edged_path,
                            debug_mask_path=debug_mask_path,
                            bbox=detection.get("bbox"),
                            raw_text=str(detection.get("candidates") or detection.get("raw_text")),
                            detector=detection.get("detector"),
                            image_hash=image_hash,
                        )
                        db.add(det_row)
                        db.flush()
                        if status == "denied":
                            db.add(Notification(
                                title=f"Denied plate {plate_text}",
                                message=(
                                    f"Camera {camera.name}"
                                    + (f" - {camera.location}" if camera.location else "")
                                ),
                                level="warn",
                                kind="detection",
                                camera_id=camera.id,
                                detection_id=det_row.id,
                                is_read=False,
                                created_at=datetime.utcnow(),
                            ))
                        db.commit()
                        det_id = det_row.id

                    # Update overlay with full debug info now that images exist
                    if stream_manager:
                        debug_steps = [
                            s for s in [
                                {"key": "color", "label": "Color Crop", "path": debug_color_path} if debug_color_path else None,
                                {"key": "bw",    "label": "Threshold",  "path": debug_bw_path}    if debug_bw_path    else None,
                                {"key": "gray",  "label": "Gray",       "path": debug_gray_path}  if debug_gray_path  else None,
                                {"key": "edged", "label": "Edges",      "path": debug_edged_path} if debug_edged_path else None,
                                {"key": "mask",  "label": "Mask",       "path": debug_mask_path}  if debug_mask_path  else None,
                            ] if s
                        ]
                        stream_manager.set_detection(
                            camera.id,
                            {
                                "id": det_id,
                                "plate_text": plate_text,
                                "status": status,
                                "confidence": detection.get("confidence"),
                                "bbox": detection.get("bbox"),
                                "detector": detection.get("detector"),
                                "debug_color_path": debug_color_path,
                                "debug_bw_path":    debug_bw_path,
                                "debug_gray_path":  debug_gray_path,
                                "debug_edged_path": debug_edged_path,
                                "debug_mask_path":  debug_mask_path,
                                "debug_steps": debug_steps,
                                "ts": time.time(),
                            },
                        )
                except Exception:
                    logger.exception(
                        "Camera %s background detection persistence failed for plate %s using detector %s",
                        camera.id,
                        plate_text,
                        detection.get("detector") or "unknown",
                    )

            _io_pool.submit(_background_io)

        if cap:
            cap.release()


class CameraManager:
    def __init__(self, media_dir: str, poll_seconds: float = 5.0, stream_manager=None):
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.poll_seconds = poll_seconds
        self._workers: Dict[int, CameraWorker] = {}
        self._stop_event = threading.Event()
        self._thread = None
        self._snapshots: Dict[int, datetime] = {}
        self._detector_mode = "auto"
        self._stationary_policy = {
            "enabled": True,
            "motion_threshold": 7.0,
            "hold_seconds": 0.0,
        }
        self._stream_manager = stream_manager

    def get_detector_mode(self) -> str:
        return self._detector_mode

    def get_stationary_policy(self) -> Dict[str, float]:
        return dict(self._stationary_policy)

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        for worker in list(self._workers.values()):
            worker.stop()

    def _run(self):
        while not self._stop_event.is_set():
            self.sync()
            time.sleep(self.poll_seconds)

    def sync(self):
        with SessionLocal() as db:
            cameras = db.query(Camera).all()
            setting = db.get(AppSetting, "detector_mode")
            if setting and setting.value:
                self._detector_mode = setting.value
            else:
                self._detector_mode = "auto"
            stationary_enabled = db.get(AppSetting, "allowed_stationary_enabled")
            stationary_motion_threshold = db.get(AppSetting, "allowed_stationary_motion_threshold")
            stationary_hold_seconds = db.get(AppSetting, "allowed_stationary_hold_seconds")
            enabled_raw = str(stationary_enabled.value).strip().lower() if stationary_enabled and stationary_enabled.value is not None else "1"
            try:
                motion_threshold = float(stationary_motion_threshold.value) if stationary_motion_threshold and stationary_motion_threshold.value else 7.0
            except Exception:
                motion_threshold = 7.0
            try:
                hold_seconds = float(stationary_hold_seconds.value) if stationary_hold_seconds and stationary_hold_seconds.value else 0.0
            except Exception:
                hold_seconds = 0.0
            self._stationary_policy = {
                "enabled": enabled_raw in {"1", "true", "yes", "on"},
                "motion_threshold": max(0.5, min(50.0, motion_threshold)),
                "hold_seconds": max(0.0, min(3600.0, hold_seconds)),
            }

            yolo_conf = db.get(AppSetting, "yolo_conf")
            yolo_imgsz = db.get(AppSetting, "yolo_imgsz")
            yolo_iou = db.get(AppSetting, "yolo_iou")
            yolo_max_det = db.get(AppSetting, "yolo_max_det")
            inference_device = db.get(AppSetting, "inference_device")
            _default_model = Path(__file__).resolve().parents[3] / "models" / "plate.pt"
            _model_path = str(_default_model) if _default_model.exists() else ""
            set_yolo_config(
                {
                    "conf": float(yolo_conf.value) if yolo_conf and yolo_conf.value else 0.25,
                    "imgsz": int(yolo_imgsz.value) if yolo_imgsz and yolo_imgsz.value else 640,
                    "iou": float(yolo_iou.value) if yolo_iou and yolo_iou.value else 0.45,
                    "max_det": int(yolo_max_det.value) if yolo_max_det and yolo_max_det.value else 5,
                    "device": inference_device.value if inference_device and inference_device.value else "cpu",
                    "model_path": _model_path,
                }
            )

            ocr_max_width = db.get(AppSetting, "ocr_max_width")
            ocr_langs = db.get(AppSetting, "ocr_langs")
            contour_canny_low = db.get(AppSetting, "contour_canny_low")
            contour_canny_high = db.get(AppSetting, "contour_canny_high")
            contour_bilateral_d = db.get(AppSetting, "contour_bilateral_d")
            contour_bilateral_sigma_color = db.get(AppSetting, "contour_bilateral_sigma_color")
            contour_bilateral_sigma_space = db.get(AppSetting, "contour_bilateral_sigma_space")
            contour_approx_eps = db.get(AppSetting, "contour_approx_eps")
            contour_pad_ratio = db.get(AppSetting, "contour_pad_ratio")
            contour_pad_min = db.get(AppSetting, "contour_pad_min")
            plate_min_length = db.get(AppSetting, "plate_min_length")
            plate_max_length = db.get(AppSetting, "plate_max_length")
            plate_charset = db.get(AppSetting, "plate_charset")
            plate_pattern_regex = db.get(AppSetting, "plate_pattern_regex")
            plate_shape_hint = db.get(AppSetting, "plate_shape_hint")
            plate_reference_date = db.get(AppSetting, "plate_reference_date")
            set_anpr_config(
                {
                    "inference_device": inference_device.value if inference_device and inference_device.value else "cpu",
                    "ocr_max_width": int(ocr_max_width.value) if ocr_max_width and ocr_max_width.value else 1280,
                    "ocr_langs": ocr_langs.value if ocr_langs and ocr_langs.value else "en",
                    "contour_canny_low": int(contour_canny_low.value) if contour_canny_low and contour_canny_low.value else 30,
                    "contour_canny_high": int(contour_canny_high.value) if contour_canny_high and contour_canny_high.value else 200,
                    "contour_bilateral_d": int(contour_bilateral_d.value) if contour_bilateral_d and contour_bilateral_d.value else 11,
                    "contour_bilateral_sigma_color": int(contour_bilateral_sigma_color.value) if contour_bilateral_sigma_color and contour_bilateral_sigma_color.value else 17,
                    "contour_bilateral_sigma_space": int(contour_bilateral_sigma_space.value) if contour_bilateral_sigma_space and contour_bilateral_sigma_space.value else 17,
                    "contour_approx_eps": float(contour_approx_eps.value) if contour_approx_eps and contour_approx_eps.value else 0.018,
                    "contour_pad_ratio": float(contour_pad_ratio.value) if contour_pad_ratio and contour_pad_ratio.value else 0.15,
                    "contour_pad_min": int(contour_pad_min.value) if contour_pad_min and contour_pad_min.value else 18,
                    "plate_min_length": int(plate_min_length.value) if plate_min_length and plate_min_length.value else 5,
                    "plate_max_length": int(plate_max_length.value) if plate_max_length and plate_max_length.value else 8,
                    "plate_charset": plate_charset.value if plate_charset and plate_charset.value else "alnum",
                    "plate_pattern_regex": plate_pattern_regex.value if plate_pattern_regex and plate_pattern_regex.value else "",
                    "plate_shape_hint": plate_shape_hint.value if plate_shape_hint and plate_shape_hint.value else "standard",
                    "plate_reference_date": plate_reference_date.value if plate_reference_date and plate_reference_date.value else "",
                }
            )

        active_ids = set()
        for camera in cameras:
            active_ids.add(camera.id)
            if not camera.enabled:
                if camera.id in self._workers:
                    self._workers[camera.id].stop()
                    del self._workers[camera.id]
                continue

            snapshot = camera.updated_at or camera.created_at
            if camera.id not in self._workers:
                worker = CameraWorker(
                    camera,
                    self.media_dir,
                    mode_provider=self.get_detector_mode,
                    stream_manager=self._stream_manager,
                    stationary_policy_provider=self.get_stationary_policy,
                )
                self._workers[camera.id] = worker
                self._snapshots[camera.id] = snapshot
                worker.start()
                continue

            if self._snapshots.get(camera.id) != snapshot:
                self._workers[camera.id].stop()
                worker = CameraWorker(
                    camera,
                    self.media_dir,
                    mode_provider=self.get_detector_mode,
                    stream_manager=self._stream_manager,
                    stationary_policy_provider=self.get_stationary_policy,
                )
                self._workers[camera.id] = worker
                self._snapshots[camera.id] = snapshot
                worker.start()

        # Remove workers for deleted cameras
        for camera_id in list(self._workers.keys()):
            if camera_id not in active_ids:
                self._workers[camera_id].stop()
                del self._workers[camera_id]
