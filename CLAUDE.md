# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CarVision is a self-hosted, full-stack Automatic Number Plate Recognition (ANPR) platform for automated gate and vehicle access control. It consists of a FastAPI Python backend, a React/TypeScript frontend, and a PostgreSQL database.

## Development Commands

### Backend (Python / FastAPI)

```bash
# Install dependencies
pip install -r requirements.txt

# Run dev server (from backend/app/)
cd backend/app && uvicorn main:app --reload --port 8000

# Apply database migrations
alembic upgrade head

# Run tests
python -m pytest -q

# Run a single test file
python -m pytest tests/test_pipeline.py -q
```

### Frontend (React / TypeScript)

```bash
# From frontend/
npm install
npm run dev          # Dev server at http://localhost:5173
npm run build        # Production build → dist/
npm run typecheck    # Type-check without building (tsc --noEmit)
npm run preview      # Preview production build
```

### Docker (full stack)

```bash
docker compose -f deploy/compose/docker-compose.carvision.yml \
  --env-file .env.carvision up -d --build
```

## Architecture

### Backend

The backend uses an **app factory pattern**: `backend/app/main.py` exports `create_app()` which wires shared services into routers via per-router `_init()` calls, avoiding globals and circular imports.

Functionality is split into 12 APIRouter modules under `backend/app/routers/`:
`auth`, `cameras`, `detections`, `training`, `clips`, `allowed`, `notifications`, `discovery`, `dashboard`, `upload`, `training_samples`, `deps`

The ANPR pipeline (`backend/app/pipeline/`) is a 10-stage modular chain: `frame_selector → plate_localizer → OCR → postprocess → tracker`. Each stage is independently testable.

Model training runs in a daemon thread with a subprocess worker, guarded by `TRAIN_PIPELINE_LOCK` and `TRAIN_PIPELINE_STOP` for thread safety.

Security: JWT HS256 tokens, Fernet-encrypted ONVIF camera credentials, Bcrypt password hashing. Database schema is managed exclusively through Alembic migrations — never modify the schema manually.

### Frontend

React 18 + TypeScript with Vite. Path alias `@/*` maps to `src/*`.

- `src/lib/api.ts` — typed API client wrapping all backend endpoints
- `src/context/` — React context providers (auth, etc.)
- `src/hooks/` — custom data-fetching hooks
- `src/pages/` — route-level screens (9 pages)
- `src/components/` — shared UI components
- `src/design-system/` — primitive UI building blocks (Button, Card, Modal, etc.)

Styling: Tailwind CSS. Animation: Framer Motion. Charts: Chart.js via react-chartjs-2. Routing: react-router-dom v6.

### Key Environment Variables

Set in `.env.carvision` (see `.env.carvision.example`):

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET` | Must be 32+ random characters |
| `VITE_API_URL` | Backend URL baked into frontend at build time |
| `API_CORS_ORIGINS` | Comma-separated allowed origins |
| `INFERENCE_DEVICE` | `cpu`, `cuda`, or `mps` |
| `MEDIA_DIR` | Path for storing video clips and snapshots |

### CI

GitHub Actions (`.github/workflows/ci.yml`) runs on push to `main` and all PRs:
- Backend: Python 3.11, pytest, `scripts/check_file_sizes.py`
- Frontend: Node 20, `npm run build`

## Deployment

- **Single-node**: Docker Compose in `deploy/compose/`
- **Multi-node**: Kubernetes manifests with HPA in `deploy/k8s/`
- **Diagnostics**: Standalone OpenCV viewer at `tools/viewer.py` for camera debugging without the full stack

YOLOv8 model weights live in `models/` (`.pt` files). Training datasets are in `datasets/`.
