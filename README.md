# CarVision

CarVision is a license-plate monitoring platform with a FastAPI backend, React admin panel, multi-camera ingestion (RTSP, ONVIF, browser, webcam, MJPEG), and local media storage.

## Stack

- Backend: FastAPI + SQLAlchemy + OpenCV
- Frontend: React (Vite)
- Database: PostgreSQL (Docker) or SQLite (local)
- AI: YOLO-based plate detection (optional custom model)

## Features

- Multi-camera management (webcam, RTSP, HTTP MJPEG, browser stream)
- ONVIF discovery and RTSP profile resolution
- Live view, detections, snapshots, clips, uploads
- Allowed-plates workflow
- JWT-based API auth for the modern frontend

## Repository Layout

```text
backend/                 FastAPI app
frontend/carvision-web/  React admin UI
datasets/media/          Runtime media output
models/                  Detection models
old/python_frontend/     Legacy UI templates
```

## Security Before Publishing Public

This project includes values/files that should be treated as sensitive before public release:

- Local env file `.env.carvision` (can contain real credentials; keep it untracked)
- Weak/default credentials in config examples (`admin/admin`, placeholder JWT)
- Camera credentials may be stored in database records at runtime

Before making the repo public:

1. Remove tracked secrets/config snapshots from git history if they were used with real credentials.
2. Keep only `.env.carvision.example` in git; do not commit real `.env*` files.
3. Rotate all credentials that may have been exposed:
   - Admin username/password
   - `JWT_SECRET`
   - Database password
   - Any RTSP/ONVIF camera credentials
4. Review deployment files for hardcoded internal IPs, VPN ranges, or hostnames you do not want public.
5. Run a secret scan (for example `gitleaks`) before publishing.

## Quick Start (Docker)

1. Copy example env:

```bash
cp .env.carvision.example .env.carvision
```

2. Edit `.env.carvision` and set strong values at minimum:

- `API_ADMIN_USER`
- `API_ADMIN_PASS`
- `JWT_SECRET`
- `POSTGRES_PASSWORD`
- `VITE_API_URL` (if accessing from another machine)

3. Build and run:

```bash
docker compose -f docker-compose.carvision.yml --env-file .env.carvision up -d --build
```

4. Open:

- Frontend: `http://localhost:8081`
- Backend/API: `http://localhost:8000`

## Local Development (No Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend/app
uvicorn main:app --reload
```

If needed, set `DATABASE_URL`, `MEDIA_DIR`, and auth env vars before starting.

## Camera Types

- `webcam`: local index (example: `0`)
- `rtsp`: full RTSP URL
- `http_mjpeg`: MJPEG endpoint URL
- `browser`: web capture from phone/laptop via `/capture/<camera-id>`

## ONVIF Notes

- ONVIF discovery relies on local network multicast and may be limited in containerized/network-restricted environments.
- PTZ controls require camera `xaddr`, username, and password.

## Production Checklist

- Set non-default credentials and long random JWT secret
- Restrict CORS (`API_CORS_ORIGINS`) to known origins
- Use HTTPS behind a reverse proxy
- Do not expose database ports publicly
- Back up `datasets/media` and database volumes
- Add monitoring/log retention for incident review

## Additional Docs

- Setup details: `SETUP.md`
- Architecture review: `ARCHITECTURE_REVIEW.md`
- Backend notes: `backend/README.md`
