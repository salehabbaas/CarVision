import threading
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple
from collections import Counter, deque
from difflib import SequenceMatcher

import cv2

from plate_detector import detect_plate, set_yolo_config
from anpr import set_anpr_config
from pipeline import PlateInferencePipeline
from anpr import build_debug_bundle, crop_from_bbox, read_plate_text
from db import SessionLocal
from models import Camera, AllowedPlate, Detection, AppSetting, Notification, TrainingSample


class CameraWorker:
    def __init__(self, camera: Camera, media_dir: Path, mode_provider=None, stream_manager=None):
        self.camera = camera
        self.media_dir = media_dir
        self._stop_event = threading.Event()
        self._thread = None
        self._recent = {}
        self._history = deque(maxlen=16)
        self._mode_provider = mode_provider or (lambda: "auto")
        self._stream_manager = stream_manager
        self._pipeline = PlateInferencePipeline()
        self._known_cache = []
        self._known_cache_ts = 0.0

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
        pool = {str(v[0]).strip().upper() for v in allowed + training if v and v[0]}
        self._known_cache = [p for p in pool if len(p) >= 5]
        self._known_cache_ts = now
        return self._known_cache

    def _match_known_plate(self, plate_text: str) -> str:
        normalized = (plate_text or "").strip().upper()
        if len(normalized) < 5:
            return normalized
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
            return None, None, None, None, None

        return (
            color_name if debug_color is not None else None,
            bw_name if debug_bw is not None else None,
            gray_name if debug_gray is not None else None,
            edged_name if debug_edged is not None else None,
            mask_name if debug_mask is not None else None,
        )

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

    def _run(self):
        cap = None if self._stream_manager else self._open_capture()
        last_scan = 0.0
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
                    time.sleep(1)
                    cap = self._open_capture()
                    continue

                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.5)
                    continue

            now = time.time()
            if now - last_scan < self.camera.scan_interval:
                continue

            last_scan = now
            mode_override = self._mode_provider()
            if self.camera.detector_mode and self.camera.detector_mode != "inherit":
                mode_override = self.camera.detector_mode
            detection = None
            if self._pipeline and self._pipeline.enabled:
                try:
                    result = self._pipeline.run(frame, camera_id=self.camera.id, mode_override=mode_override)
                    detection = result.to_legacy_detection() if result else None
                except Exception:
                    detection = detect_plate(frame, mode_override=mode_override)
            else:
                detection = detect_plate(frame, mode_override=mode_override)
            if not detection:
                continue
            detection = self._refine_detection_from_crop(frame, detection)

            plate_text = self._match_known_plate(detection["plate_text"])
            detection["plate_text"] = plate_text
            plate_text = self._stabilize_plate(plate_text, now)
            last_seen = self._recent.get(plate_text, 0)
            if now - last_seen < self.camera.cooldown_seconds:
                continue

            self._recent[plate_text] = now
            allowed = self._is_allowed(plate_text)
            status = "allowed" if allowed else "denied"

            image_path = self._save_snapshot(frame, plate_text)
            (
                debug_color_path,
                debug_bw_path,
                debug_gray_path,
                debug_edged_path,
                debug_mask_path,
            ) = self._save_debug_images(frame, detection, plate_text)
            if self._stream_manager:
                video_path = self._save_clip_from_stream(plate_text)
            else:
                video_path = self._save_clip(cap, plate_text) if cap else None

            image_hash = None
            if image_path:
                try:
                    image_hash = (self.media_dir / image_path).read_bytes()
                    import hashlib
                    image_hash = hashlib.sha256(image_hash).hexdigest()
                except Exception:
                    image_hash = None

            det_id = None
            with SessionLocal() as db:
                det_row = Detection(
                    camera_id=self.camera.id,
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
                    db.add(
                        Notification(
                            title=f"Denied plate {plate_text}",
                            message=f"Camera {self.camera.name}{' - ' + self.camera.location if self.camera.location else ''}",
                            level="warn",
                            kind="detection",
                            camera_id=self.camera.id,
                            detection_id=det_row.id,
                            is_read=False,
                            created_at=datetime.utcnow(),
                        )
                    )
                db.commit()
                det_id = det_row.id
            if self._stream_manager:
                debug_steps = [
                    step
                    for step in [
                        {"key": "color", "label": "Color Crop", "path": debug_color_path} if debug_color_path else None,
                        {"key": "bw", "label": "Threshold", "path": debug_bw_path} if debug_bw_path else None,
                        {"key": "gray", "label": "Gray", "path": debug_gray_path} if debug_gray_path else None,
                        {"key": "edged", "label": "Edges", "path": debug_edged_path} if debug_edged_path else None,
                        {"key": "mask", "label": "Mask", "path": debug_mask_path} if debug_mask_path else None,
                    ]
                    if step
                ]
                self._stream_manager.set_detection(
                    self.camera.id,
                    {
                        "id": det_id,
                        "plate_text": plate_text,
                        "status": status,
                        "confidence": detection.get("confidence"),
                        "bbox": detection.get("bbox"),
                        "detector": detection.get("detector"),
                        "debug_color_path": debug_color_path,
                        "debug_bw_path": debug_bw_path,
                        "debug_gray_path": debug_gray_path,
                        "debug_edged_path": debug_edged_path,
                        "debug_mask_path": debug_mask_path,
                        "debug_steps": debug_steps,
                        "ts": time.time(),
                    },
                )

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
        self._stream_manager = stream_manager

    def get_detector_mode(self) -> str:
        return self._detector_mode

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

            yolo_conf = db.get(AppSetting, "yolo_conf")
            yolo_imgsz = db.get(AppSetting, "yolo_imgsz")
            yolo_iou = db.get(AppSetting, "yolo_iou")
            yolo_max_det = db.get(AppSetting, "yolo_max_det")
            set_yolo_config(
                {
                    "conf": float(yolo_conf.value) if yolo_conf and yolo_conf.value else 0.25,
                    "imgsz": int(yolo_imgsz.value) if yolo_imgsz and yolo_imgsz.value else 640,
                    "iou": float(yolo_iou.value) if yolo_iou and yolo_iou.value else 0.45,
                    "max_det": int(yolo_max_det.value) if yolo_max_det and yolo_max_det.value else 5,
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
            set_anpr_config(
                {
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
                worker = CameraWorker(camera, self.media_dir, mode_provider=self.get_detector_mode, stream_manager=self._stream_manager)
                self._workers[camera.id] = worker
                self._snapshots[camera.id] = snapshot
                worker.start()
                continue

            if self._snapshots.get(camera.id) != snapshot:
                self._workers[camera.id].stop()
                worker = CameraWorker(camera, self.media_dir, mode_provider=self.get_detector_mode, stream_manager=self._stream_manager)
                self._workers[camera.id] = worker
                self._snapshots[camera.id] = snapshot
                worker.start()

        # Remove workers for deleted cameras
        for camera_id in list(self._workers.keys()):
            if camera_id not in active_ids:
                self._workers[camera_id].stop()
                del self._workers[camera_id]
