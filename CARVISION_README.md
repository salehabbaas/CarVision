# CarVision by SpinelTech (React + Python + JWT)

This repo now includes a modern React frontend and JWT-secured Python API on top of the existing backend.

## Stack
- Backend: FastAPI (`backend/app/main.py`) + `/api/v1/*` JWT endpoints
  - `backend/app/core/` config
  - `backend/app/api/` request models
  - `backend/app/services/` dataset/state/file helpers
- Frontend: React + Vite + Framer Motion + Lucide icons (`frontend/carvision-web/`)
- Legacy Python/Jinja frontend: removed
- Dataset/media storage: `datasets/media/`
- Database: PostgreSQL
- Containers: `docker-compose.carvision.yml`

## React features now included
- Dashboard summary + training status
- Live DVR grid (4/8/16), pin camera, stream health indicator
- Detections page with filters, bulk reprocess, bulk feedback
- Upload & Test with live processing steps, progress, and debug links
- Training Data page:
  - multi-image upload
  - sample filters/search
  - annotation save (plate + bbox + no-plate + notes)
  - ignore/unignore and delete sample
  - YOLO export + start training
- Cameras page:
  - add camera
  - enable/live/detector controls
  - open stream
  - run browser camera
  - delete camera
- Allowed Plates management (add/edit/delete)
- ONVIF Discovery page:
  - scan devices
  - resolve RTSP profiles
  - add discovered stream as camera
- Notification Center (read / read all)

## JWT Auth
- Login endpoint: `POST /api/v1/auth/login`
- Token type: `Bearer`
- Configure credentials via env:
  - `API_ADMIN_USER`
  - `API_ADMIN_PASS`
  - `JWT_SECRET`

## Main API endpoints
- `GET /api/v1/dashboard/summary`
- `GET /api/v1/cameras`
- `PATCH /api/v1/cameras/{camera_id}`
- `GET /api/v1/live/stream_health`
- `GET /api/v1/detections`
- `POST /api/v1/detections/bulk/reprocess`
- `POST /api/v1/detections/bulk/feedback`
- `GET /api/v1/training/status`
- `POST /api/v1/training/start`
- `GET /api/v1/notifications`
- `POST /api/v1/notifications/{id}/read`

Additional endpoints:
- `POST /api/v1/upload/start`
- `GET /api/v1/upload/status/{job_id}`
- `GET /api/v1/training/samples`
- `GET /api/v1/training/samples/{id}`
- `POST /api/v1/training/upload`
- `PATCH /api/v1/training/samples/{id}/annotate`
- `POST /api/v1/training/samples/{id}/ignore`
- `DELETE /api/v1/training/samples/{id}`
- `GET /api/v1/training/export_yolo`
- `GET /api/v1/allowed`
- `POST /api/v1/allowed`
- `PATCH /api/v1/allowed/{id}`
- `DELETE /api/v1/allowed/{id}`
- `GET /api/v1/discovery/run`
- `POST /api/v1/discovery/resolve`

## Run with Docker
1. Copy env file:
   - `cp .env.carvision.example .env`
2. Build and run:
   - `docker compose -f docker-compose.carvision.yml up --build`
3. Open:
   - Frontend: `http://localhost:8081`
   - Backend API: `http://localhost:8000`

## Local dev (without Docker)
- Backend:
  - `pip install -r requirements.txt`
  - `cd backend/app && uvicorn main:app --reload --host 0.0.0.0 --port 8000`
- Frontend:
  - `cd frontend/carvision-web && npm install && npm run dev`
  - Open `http://localhost:5173`

## Notes
- Existing server-rendered admin UI still works.
- React frontend uses API polling for live status/training updates.
- Live streams are shown using the existing MJPEG endpoint (`/stream/{camera_id}`).
