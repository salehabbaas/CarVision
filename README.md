# CarVision

CarVision is a self-hosted ANPR platform for real-time license plate detection, camera monitoring, and access-control workflows.

## Core Features

- Multi-camera support: RTSP, ONVIF, MJPEG, webcam, browser capture
- Real-time detection pipeline: YOLO localization + OCR + post-processing
- Access-control primitives: allowlist + allowed/denied classification
- Training workflows: dataset import, annotation, model test/train/export
- Operational tooling: standalone OpenCV diagnostics viewer

## Repository Structure

```text
CarVision/
├── backend/                     # FastAPI backend
│   ├── app/
│   │   ├── routers/             # API route modules
│   │   ├── services/            # Business logic helpers
│   │   ├── pipeline/            # ANPR processing pipeline
│   │   └── workers/             # Worker entrypoints
│   └── migrations/              # Alembic migrations
├── frontend/                    # React + Vite frontend app
├── deploy/
│   ├── compose/                 # Docker Compose manifests
│   ├── docker/                  # Dockerfiles
│   ├── k8s/                     # Kubernetes manifests
│   └── scripts/                 # Deployment scripts
├── tools/                       # Standalone dev/ops utilities
├── datasets/media/              # Runtime media output
└── models/                      # Detection models
```

## Quick Start (Docker Compose)

```bash
cd /Users/salehabbas/Developer/CarVision
cp .env.carvision.example .env.carvision
docker compose -f deploy/compose/docker-compose.carvision.yml --env-file .env.carvision up -d --build
```

Open:

- Frontend: `http://localhost:8081`
- Backend API: `http://localhost:8000`

## Local Development

### Backend

```bash
cd /Users/salehabbas/Developer/CarVision/backend/app
pip install -r ../../requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend

```bash
cd /Users/salehabbas/Developer/CarVision/frontend
npm install
npm run dev
```

## Utilities

### Standalone Viewer

Use the native diagnostics viewer when you want direct camera debugging without running the web stack.

```bash
cd /Users/salehabbas/Developer/CarVision
python tools/viewer.py
python tools/viewer.py --camera 1
python tools/viewer.py --source rtsp://user:pass@192.168.1.100/stream
```

## Deployment Paths

- Compose (main): `deploy/compose/docker-compose.carvision.yml`
- Compose (dev/simple): `deploy/compose/docker-compose.yml`
- Backend Dockerfile: `deploy/docker/backend.Dockerfile`
- Deploy script: `deploy/scripts/deploy.sh`
- Kubernetes manifests: `deploy/k8s/base/`

## Documentation

- [SETUP.md](./SETUP.md)
- [backend/README.md](./backend/README.md)
- [frontend/README.md](./frontend/README.md)
- [deploy/k8s/README.md](./deploy/k8s/README.md)
- [tools/README.md](./tools/README.md)
