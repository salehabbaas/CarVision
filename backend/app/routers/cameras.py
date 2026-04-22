"""routers/cameras.py — camera CRUD, connection testing, layout, live overlays & stream health."""
from __future__ import annotations

import ipaddress
import json
import re
import secrets
import socket
import subprocess
import time
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

import cv2
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api.schemas import ApiCameraCreateBody, ApiCameraPatchBody, ApiCameraTestBody, ApiLayoutBody
from core.config import MEDIA_DIR
from db import get_db
from models import AppSetting, Camera
from routers.deps import get_current_user, get_setting, set_setting
from services.camera_edit import (
    apply_camera_patch,
    normalize_camera_source,
    validate_camera_type,
    validate_detector_mode,
)

router = APIRouter(prefix="/api/v1", tags=["cameras"])

# Populated by main.py app factory after instantiation
_stream_manager = None
_manual_clip_manager = None


def _init(stream_manager, manual_clip_manager) -> None:
    global _stream_manager, _manual_clip_manager
    _stream_manager = stream_manager
    _manual_clip_manager = manual_clip_manager


def _ensure_capture_token(camera: Camera, db: Session) -> None:
    if camera.type == "browser" and not camera.capture_token:
        camera.capture_token = secrets.token_urlsafe(16)
        db.commit()


def _camera_payload(cam: Camera, global_mode: str, active_manual: set) -> dict:
    return {
        "id": cam.id,
        "name": cam.name,
        "type": cam.type,
        "source": cam.source,
        "location": cam.location,
        "model": cam.model,
        "enabled": bool(cam.enabled),
        "live_view": bool(cam.live_view),
        "live_order": cam.live_order,
        "scan_interval": cam.scan_interval,
        "cooldown_seconds": cam.cooldown_seconds,
        "save_clip": bool(cam.save_clip),
        "clip_seconds": int(cam.clip_seconds or 0),
        "onvif_xaddr": cam.onvif_xaddr,
        "onvif_username": cam.onvif_username,
        "onvif_profile": cam.onvif_profile,
        "detector_mode": cam.detector_mode,
        "effective_detector_mode": cam.detector_mode if cam.detector_mode != "inherit" else global_mode,
        "browser_online": _stream_manager.is_external_online(cam.id) if cam.type == "browser" and _stream_manager else None,
        "manual_recording": cam.id in active_manual,
        "stream_url": f"/stream/{cam.id}?overlay=1",
        "capture_token": cam.capture_token if cam.type == "browser" else None,
        "capture_url": f"/capture/{cam.id}?token={cam.capture_token}" if cam.type == "browser" and cam.capture_token else None,
    }


# ── Camera CRUD ───────────────────────────────────────────────────────────────

@router.get("/cameras")
def list_cameras(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    global_mode = get_setting(db, "detector_mode", "auto")
    rows = db.query(Camera).order_by(Camera.live_order.asc(), Camera.id.asc()).all()
    active_manual: set = set()
    if _manual_clip_manager:
        active_manual = {int(item["camera_id"]) for item in _manual_clip_manager.active()}
    for cam in rows:
        if cam.type == "browser":
            _ensure_capture_token(cam, db)
    return {"items": [_camera_payload(cam, global_mode, active_manual) for cam in rows]}


@router.post("/cameras", status_code=201)
def create_camera(
    body: ApiCameraCreateBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    cam_type = validate_camera_type(body.type or "")
    detector_mode = validate_detector_mode(body.detector_mode or "inherit")
    raw_source = body.source or ""
    if cam_type == "browser" and not raw_source.strip():
        raw_source = "browser"
    source = normalize_camera_source(cam_type, raw_source)
    if not source:
        raise HTTPException(status_code=400, detail="Source is required")

    camera = Camera(
        name=(body.name or "").strip()[:100],
        type=cam_type,
        source=source,
        location=(body.location or "").strip()[:200] if body.location else None,
        model=(body.model or "").strip()[:200] if body.model else None,
        enabled=bool(body.enabled),
        scan_interval=max(0.1, float(body.scan_interval)),
        cooldown_seconds=max(0.0, float(body.cooldown_seconds)),
        save_snapshot=bool(body.save_snapshot),
        save_clip=bool(body.save_clip),
        clip_seconds=max(0, int(body.clip_seconds)),
        live_view=bool(body.live_view),
        live_order=int(body.live_order),
        onvif_xaddr=(body.onvif_xaddr or "").strip()[:500] if body.onvif_xaddr else None,
        onvif_username=(body.onvif_username or "").strip()[:200] if body.onvif_username else None,
        onvif_password=(body.onvif_password or "").strip()[:200] if body.onvif_password else None,
        onvif_profile=(body.onvif_profile or "").strip()[:200] if body.onvif_profile else None,
        detector_mode=detector_mode,
    )
    if camera.type == "browser":
        camera.capture_token = secrets.token_urlsafe(16)
    db.add(camera)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Camera name already exists")
    return {"ok": True, "id": camera.id}


@router.patch("/cameras/{camera_id}")
def update_camera(
    camera_id: int,
    body: ApiCameraPatchBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    apply_camera_patch(cam, body.dict(exclude_unset=True))
    db.add(cam)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Camera name already exists")
    return {"ok": True}


@router.delete("/cameras/{camera_id}")
def delete_camera(
    camera_id: int,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    cam = db.get(Camera, camera_id)
    if not cam:
        raise HTTPException(status_code=404, detail="Camera not found")
    db.delete(cam)
    db.commit()
    return {"ok": True}


# ── Layout ────────────────────────────────────────────────────────────────────

@router.get("/cameras/layout")
def get_layout(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    return {"max_live_cameras": int(get_setting(db, "max_live_cameras", "16"))}


@router.post("/cameras/layout")
def save_layout(
    body: ApiLayoutBody,
    db: Session = Depends(get_db),
    _user: str = Depends(get_current_user),
):
    value = max(1, min(64, int(body.max_live_cameras)))
    set_setting(db, "max_live_cameras", str(value))
    db.commit()
    return {"ok": True, "max_live_cameras": value}


# ── Live overlays & stream health ─────────────────────────────────────────────

@router.get("/live/overlays")
def live_overlays(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    from services.debug_assets import debug_steps_from_paths

    cameras = (
        db.query(Camera.id)
        .filter(Camera.live_view.is_(True), Camera.enabled.is_(True))
        .all()
    )
    items = {}
    for (cam_id,) in cameras:
        if not _stream_manager:
            continue
        det = _stream_manager.get_detection(cam_id)
        if det:
            if isinstance(det, dict) and not det.get("debug_steps"):
                det["debug_steps"] = debug_steps_from_paths({
                    "color": det.get("debug_color_path"),
                    "bw": det.get("debug_bw_path"),
                    "gray": det.get("debug_gray_path"),
                    "edged": det.get("debug_edged_path"),
                    "mask": det.get("debug_mask_path"),
                })
            items[str(cam_id)] = det
    return {"items": items}


@router.get("/live/stream_health")
def stream_health(db: Session = Depends(get_db), _user: str = Depends(get_current_user)):
    cameras = db.query(Camera).filter(Camera.live_view.is_(True)).all()
    now = time.time()
    items = {}
    for cam in cameras:
        if not _stream_manager:
            items[cam.id] = {"online": False, "reason": "stream manager not initialised"}
            continue
        last_ok = _stream_manager.get_last_ok(cam.id, cam.type, cam.source)
        age = (now - last_ok) if last_ok else None
        online = bool(last_ok and age is not None and age <= 5.0)
        reason = None
        if cam.type == "webcam":
            try:
                idx = int(cam.source)
            except Exception:
                idx = 0
            if not Path(f"/dev/video{idx}").exists():
                online = False
                reason = f"webcam /dev/video{idx} not found"
        elif cam.type == "browser" and not _stream_manager.is_external_online(cam.id):
            online = False
            reason = "waiting for phone stream"
        items[cam.id] = {"last_ok": last_ok, "age": age, "online": online, "reason": reason}
    return {"items": items}


# ── Connection test ───────────────────────────────────────────────────────────

@router.post("/cameras/test_connection")
def test_connection(body: ApiCameraTestBody, _user: str = Depends(get_current_user)):
    """Step-by-step network diagnostic: ping → TCP port → RTSP handshake → ffprobe stream."""
    url = (body.url or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    parsed = urlparse(url)
    host = (body.host or "").strip() or parsed.hostname or ""
    port = body.port or parsed.port or 554
    if not host:
        raise HTTPException(status_code=400, detail="Cannot determine host from URL")

    steps: list = []

    # Step 1 – Ping
    try:
        pr = subprocess.run(
            ["ping", "-c", "1", "-W", "2", "-w", "4", host],
            capture_output=True, text=True, timeout=6,
        )
        ok = pr.returncode == 0
        rtt = ""
        if ok:
            m = re.search(r"time[=<]([\d.]+)\s*ms", pr.stdout)
            rtt = f" ({m.group(1)} ms)" if m else ""
        steps.append({"step": "ping", "ok": ok,
                      "msg": f"Host {host} is reachable{rtt}" if ok
                             else f"No ping response from {host} — host may be down or ICMP blocked"})
    except subprocess.TimeoutExpired:
        steps.append({"step": "ping", "ok": False, "msg": f"Ping to {host} timed out"})
    except FileNotFoundError:
        steps.append({"step": "ping", "ok": None, "msg": "ping not available — skipping"})
    except Exception as exc:
        steps.append({"step": "ping", "ok": False, "msg": f"Ping error: {exc}"})

    # Step 2 – TCP port
    port_ok = False
    try:
        with socket.create_connection((host, port), timeout=5):
            pass
        port_ok = True
        steps.append({"step": "port", "ok": True, "msg": f"Port {port}/tcp is open on {host}"})
    except socket.timeout:
        steps.append({"step": "port", "ok": False, "msg": f"Port {port}/tcp timed out — firewall or wrong port"})
    except ConnectionRefusedError:
        steps.append({"step": "port", "ok": False, "msg": f"Port {port}/tcp refused — try 554 or 8554"})
    except OSError as exc:
        steps.append({"step": "port", "ok": False, "msg": f"Port {port}/tcp unreachable: {exc}"})

    # Step 3 – RTSP OPTIONS probe
    rtsp_ok = False
    if port_ok:
        try:
            raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            raw.settimeout(5)
            raw.connect((host, port))
            raw.sendall(
                f"OPTIONS rtsp://{host}:{port}/ RTSP/1.0\r\nCSeq: 1\r\nUser-Agent: CarVision/2.0\r\n\r\n".encode()
            )
            resp = raw.recv(512).decode("utf-8", errors="replace")
            raw.close()
            first = resp.split("\r\n")[0] if resp else ""
            if "RTSP/1.0" in resp:
                rtsp_ok = True
                auth_needed = "401" in resp or "403" in resp
                steps.append({"step": "rtsp", "ok": True,
                              "msg": f"RTSP server running — auth {'required' if auth_needed else 'not required'}: {first}"})
            else:
                steps.append({"step": "rtsp", "ok": False,
                              "msg": f"Port open but not RTSP — first bytes: {resp[:80]!r}"})
        except Exception as exc:
            steps.append({"step": "rtsp", "ok": False, "msg": f"RTSP probe error: {exc}"})
    else:
        steps.append({"step": "rtsp", "ok": False, "msg": "Skipped — port not reachable"})

    # Step 4 – ffprobe stream
    stream: dict = {"ok": False, "msg": ""}
    try:
        import shutil as _shutil
        ffprobe_bin = _shutil.which("ffprobe")
        if not ffprobe_bin:
            raise FileNotFoundError
        pr = subprocess.run(
            [ffprobe_bin, "-v", "error", "-rtsp_transport", "tcp", "-timeout", "10000000",
             "-show_entries", "stream=codec_name,codec_type,width,height,r_frame_rate",
             "-of", "json", url],
            capture_output=True, text=True, timeout=14,
        )
        if pr.returncode == 0:
            streams = json.loads(pr.stdout or "{}").get("streams", [])
            video = next((s for s in streams if s.get("codec_type") == "video"), None)
            audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
            parts = []
            if video:
                w, h = video.get("width"), video.get("height")
                if w and h:
                    parts.append(f"{w}×{h}")
                if video.get("codec_name"):
                    parts.append(video["codec_name"].upper())
                fps_raw = video.get("r_frame_rate", "")
                if "/" in fps_raw:
                    try:
                        n, d = fps_raw.split("/")
                        parts.append(f"{round(int(n)/int(d), 1)} fps")
                    except Exception:
                        pass
            if audio:
                parts.append(f"+ audio ({audio.get('codec_name','?')})")
            stream = {"ok": bool(streams), "msg": "Stream live — " + (", ".join(parts) if parts else "connected")}
        else:
            stderr = pr.stderr or ""
            sl = stderr.lower()
            if "401" in stderr or "unauthorized" in sl:
                stream["msg"] = "Authentication failed — wrong credentials"
            elif "404" in stderr or "not found" in sl:
                stream["msg"] = "Stream path not found (404) — wrong channel/path"
            elif "timeout" in sl:
                stream["msg"] = "Stream timed out — check channel number and that camera is assigned"
            else:
                stream["msg"] = f"Stream error: {stderr[:200]}"
    except subprocess.TimeoutExpired:
        stream["msg"] = "ffprobe timed out — RTSP reachable but not delivering video"
    except FileNotFoundError:
        cap = cv2.VideoCapture(url)
        if cap.isOpened():
            ret, _ = cap.read()
            stream = {"ok": ret, "msg": "Stream live (OpenCV)" if ret else "Opened but no frame — check stream path"}
        else:
            stream["msg"] = "Could not open stream — check credentials and path"
        cap.release()
    except Exception as exc:
        stream["msg"] = f"Stream probe error: {exc}"

    steps.append({"step": "stream", "ok": stream["ok"], "msg": stream["msg"]})

    ping_ok = steps[0].get("ok")
    if stream["ok"]:
        summary = stream["msg"]
    elif ping_ok is False:
        summary = f"Cannot reach {host} — verify IP, VPN, and that the device is powered on"
    elif not port_ok:
        summary = f"Host up but port {port}/tcp closed — try 554 or 8554"
    elif not rtsp_ok:
        summary = f"Port open but not RTSP — make sure this is the RTSP port, not HTTP (80/443)"
    else:
        summary = stream["msg"]

    return {"ok": stream["ok"], "message": summary, "steps": steps, "host": host, "port": port}
