# CarVision Code Review

_Reviewed: 2026-05-08_

---

## Security

### 🔴 1. Hardcoded default credentials (`backend/app/core/config.py:19–21`)

`ADMIN_PASS` defaults to `"admin"` and `JWT_SECRET` to `"carvision-dev-secret"`. The server boots and serves traffic with these values unless `CARVISION_STRICT_SECRETS=1` is explicitly set.

**Fix:** Refuse startup if weak secrets are detected unless an explicit override flag is set.

---

### 🔴 2. SSRF via `test_connection` endpoint (`backend/app/routers/cameras.py:253–400`)

The `host` and `url` values from the request body are passed directly to `subprocess.run(["ping", ..., host])`, `socket.create_connection`, and `ffprobe`. An authenticated user can supply internal IPs to probe the internal network or cloud metadata endpoints.

**Fix:** Validate `host` against RFC-1918, loopback, and link-local ranges using `ipaddress` before any network operation.

---

### 🔴 3. Unbounded file upload — disk exhaustion / DoS (`backend/app/routers/upload.py:47`)

`await file.read()` loads the entire upload into memory with no size limit.

**Fix:** Check `file.size` before reading or stream in chunks with a ceiling (e.g., 500 MB).

---

### 🟡 4. JWT secret doubles as encryption key — silent data loss on rotation (`backend/app/core/crypto.py:43–48`)

ONVIF camera passwords are encrypted using a key derived from `JWT_SECRET`. Rotating the JWT secret silently breaks all stored camera credentials with no error surfaced.

**Fix:** Add a separate `FIELD_ENCRYPTION_KEY` env var, decoupled from the JWT secret.

---

### 🟡 5. Timing oracle on capture token comparison (`backend/app/main.py:221`)

`token != camera.capture_token` uses non-constant-time string comparison, enabling a potential timing side-channel.

**Fix:** Use `hmac.compare_digest(token, camera.capture_token)`.

---

### 🟡 6. JWT stored in `localStorage` — XSS-accessible (`frontend/src/context/AuthContext.tsx:71–73`)

Any XSS vector in a dependency can exfiltrate the JWT token.

**Fix:** Use `httpOnly` cookies, or enforce a strict CSP header.

---

## Bugs

### 🔴 7. Broken pagination — Python-side filtering after DB limit (`backend/app/routers/detections.py:232–241`)

Pagination uses `.limit(limit + offset)` then slices in Python. Post-fetch Python filters are applied after the DB cap, so results are short-changed and correctness breaks at scale.

**Fix:** Push all filters into SQLAlchemy before `.offset(offset).limit(limit)`.

---

### 🔴 8. Race condition: stopped `CameraWorker` still writes to DB (`backend/app/camera_manager.py:614–733`)

The `_background_io` closure captures `self` via `self._save_debug_images(...)`. After a worker is stopped and a new one started for the same camera, both can race to write duplicate detections.

**Fix:** Check `self._stop_event.is_set()` at the start of `_background_io` and return early.

---

### 🟡 9. `cv2.VideoCapture` leak on exception in upload job (`backend/app/main.py:280–341`)

An exception inside the frame processing loop bypasses `cap.release()`, leaking the OS file handle.

**Fix:** Wrap in `try/finally` to guarantee `cap.release()`.

---

### 🟡 10. `os.killpg(proc.pid, ...)` sends signal to wrong process group (`backend/app/routers/training.py:347–357`)

`proc.pid` is the PID, not the PGID. Without `start_new_session=True`, `killpg` may fail or signal an unrelated group.

**Fix:** Start subprocess with `start_new_session=True`; use `proc.terminate()` / `proc.kill()` as primary.

---

### 🟡 11. Webcam probe hardcoded to `/dev/video{idx}` — always fails on macOS (`backend/app/routers/cameras.py:236`)

`Path("/dev/videoN").exists()` only works on Linux. Running on `darwin` marks all webcams offline.

**Fix:** Gate with `if sys.platform == "linux"`.

---

## Performance

### 🟡 12. `_is_allowed` opens a new DB connection + full table scan per detection (`backend/app/camera_manager.py:103–112`)

At 4+ cameras scanning at 0.15s intervals, this is ~27 full `AllowedPlate` table reads per second. The class already has a 20-second cache pattern available.

**Fix:** Apply the same `_known_cache_ts` cache guard to `_is_allowed`.

---

## Data Integrity

### 🟡 13. Startup migration silently resets `scan_interval` on every boot (`backend/app/main.py:610–613`)

Any `scan_interval >= 1.0` is reset to `0.15` on every startup, even values intentionally set by the operator.

**Fix:** Move into a proper Alembic migration (runs once, tracked in `alembic_version`).

---

### 🟡 14. Tests hit the real database — no isolation (`tests/conftest.py`)

No DB fixtures, no `TestClient`, no `dependency_overrides`. Tests can corrupt dev/production data.

**Fix:** Add in-memory SQLite fixture with `Base.metadata.create_all()` and override `get_db`.

---

## Summary

| Priority | Count |
|----------|-------|
| 🔴 Blocking | 5 |
| 🟡 Important | 9 |
| **Total** | **14** |
