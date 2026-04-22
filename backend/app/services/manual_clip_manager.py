from __future__ import annotations

import secrets
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import cv2

from models import Camera
from stream_manager import StreamManager


class ManualClipManager:
    """Thread-safe on-demand clip recorder using StreamManager frames."""

    def __init__(self, media_dir: str, stream_manager: StreamManager):
        self.media_dir = Path(media_dir)
        self.media_dir.mkdir(parents=True, exist_ok=True)
        self.stream_manager = stream_manager
        self._lock = threading.Lock()
        self._sessions: Dict[int, Dict] = {}

    def start(self, camera: Camera) -> Dict:
        with self._lock:
            current = self._sessions.get(camera.id)
            if current and current.get("running"):
                return {"ok": True, "already_running": True, "camera_id": camera.id}

            started_at = datetime.utcnow()
            ts = started_at.strftime("%Y%m%d_%H%M%S")
            token = secrets.token_hex(4)
            rel_path = f"clips/{camera.id}_{ts}_{token}.mp4"
            abs_path = self.media_dir / rel_path
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            stop_event = threading.Event()
            session: Dict = {
                "camera_id": camera.id,
                "camera_type": camera.type,
                "source": camera.source,
                "started_at": started_at,
                "file_path": rel_path,
                "abs_path": abs_path,
                "stop_event": stop_event,
                "running": True,
                "frames": 0,
                "fps": 10.0,
                "writer_started": False,
                "stopped_at": None,
            }

            def _run():
                writer = None
                fps = float(session["fps"])
                frame_interval = 1.0 / max(1.0, fps)
                try:
                    while not stop_event.is_set():
                        frame = self.stream_manager.get_frame(camera.id, camera.type, camera.source)
                        if frame is None:
                            time.sleep(0.03)
                            continue
                        if writer is None:
                            h, w = frame.shape[:2]
                            writer = cv2.VideoWriter(
                                str(abs_path),
                                cv2.VideoWriter_fourcc(*"mp4v"),
                                fps,
                                (w, h),
                            )
                            session["writer_started"] = True
                        writer.write(frame)
                        session["frames"] += 1
                        time.sleep(frame_interval)
                finally:
                    if writer:
                        writer.release()
                    session["running"] = False
                    session["stopped_at"] = datetime.utcnow()

            t = threading.Thread(target=_run, daemon=True)
            session["thread"] = t
            self._sessions[camera.id] = session
            t.start()
            return {"ok": True, "already_running": False, "camera_id": camera.id, "file_path": rel_path}

    def stop(self, camera_id: int) -> Optional[Dict]:
        with self._lock:
            session = self._sessions.get(camera_id)
            if not session:
                return None
            session["stop_event"].set()
            thread = session.get("thread")
        if thread:
            thread.join(timeout=8)
        with self._lock:
            self._sessions.pop(camera_id, None)
        abs_path = Path(session["abs_path"])
        frames = int(session.get("frames") or 0)
        if not session.get("writer_started") or frames <= 0:
            try:
                abs_path.unlink(missing_ok=True)
            except Exception:
                pass
            return {
                "ok": False,
                "camera_id": camera_id,
                "error": "No frames captured",
                "started_at": session.get("started_at"),
                "ended_at": session.get("stopped_at") or datetime.utcnow(),
            }
        ended_at = session.get("stopped_at") or datetime.utcnow()
        started_at = session.get("started_at") or ended_at
        duration = max(0.0, (ended_at - started_at).total_seconds())
        size_bytes = abs_path.stat().st_size if abs_path.exists() else 0
        return {
            "ok": True,
            "camera_id": camera_id,
            "file_path": session.get("file_path"),
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration,
            "size_bytes": int(size_bytes),
        }

    def active(self) -> List[Dict]:
        with self._lock:
            return [
                {
                    "camera_id": cid,
                    "file_path": s.get("file_path"),
                    "started_at": s.get("started_at"),
                    "frames": int(s.get("frames") or 0),
                }
                for cid, s in self._sessions.items()
                if s.get("running")
            ]

    def stop_all(self):
        for item in list(self.active()):
            self.stop(int(item["camera_id"]))
