<div align="center">

# ⚙️ CarVision — Backend

**FastAPI · Python 3.11 · YOLOv8 · PostgreSQL · Alembic**

[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-7c3aed?style=flat-square&logo=python&logoColor=white)](https://ultralytics.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Alembic](https://img.shields.io/badge/Alembic-Migrations-orange?style=flat-square)](https://alembic.sqlalchemy.org)

</div>

---

## 📁 Directory Layout

```
backend/
├── app/
│   ├── main.py                  # App factory + shared service wiring  (660 lines)
│   │
│   ├── routers/                 # 12 domain APIRouter modules
│   │   ├── deps.py              #   Shared auth helpers & payload builders
│   │   ├── auth.py              #   POST /api/v1/auth/login  · GET /me
│   │   ├── cameras.py           #   Camera CRUD, streams, PTZ, overlays
│   │   ├── detections.py        #   Detection history, reprocess, feedback
│   │   ├── training.py          #   YOLO training pipeline API (full)
│   │   ├── _training_worker.py  #   Subprocess-based YOLO training worker
│   │   ├── training_samples.py  #   Training sample management
│   │   ├── clips.py             #   On-demand clip recording
│   │   ├── allowed.py           #   Allowlist CRUD
│   │   ├── notifications.py     #   Event notifications
│   │   ├── discovery.py         #   ONVIF camera discovery & RTSP resolve
│   │   ├── dashboard.py         #   24h analytics summary
│   │   └── upload.py            #   Video/image upload jobs
│   │
│   ├── pipeline/                # 10-stage ANPR recognition pipeline
│   │   ├── orchestrator.py      #   Pipeline entry point
│   │   ├── frame_selector.py    #   Sharpest-frame selector
│   │   ├── plate_localizer.py   #   YOLOv8 plate detection
│   │   ├── plate_cropper.py     #   Region extraction
│   │   ├── plate_quality.py     #   Blur/quality filter
│   │   ├── plate_rectifier.py   #   Perspective & skew correction
│   │   ├── plate_classifier.py  #   Plate type classification
│   │   ├── plate_ocr.py         #   EasyOCR character recognition
│   │   ├── postprocess.py       #   Normalisation & validation
│   │   ├── confidence.py        #   Multi-signal score fusion
│   │   ├── tracker.py           #   Cross-frame plate tracking
│   │   └── schemas.py           #   Pipeline Pydantic schemas
│   │
│   ├── services/                # Business logic — no HTTP concerns
│   │   ├── camera_edit.py       #   Camera validation & patching helpers
│   │   ├── dataset.py           #   YOLO dataset build, bbox utils, export
│   │   ├── debug_assets.py      #   Debug image & step-asset generation
│   │   ├── file_utils.py        #   Filename sanitisation & file hashing
│   │   ├── manual_clip_manager.py # Thread-safe on-demand clip recorder
│   │   ├── state.py             #   Training/upload runtime state
│   │   └── yolo_train_worker.py #   YOLO subprocess worker entrypoint
│   │
│   └── core/                    # Infrastructure
│       ├── config.py            #   All env vars & path constants
│       ├── db.py                #   SQLAlchemy engine & session factory
│       └── models.py            #   ORM models (Camera, Detection, etc.)
│
└── migrations/                  # Alembic versioned migrations
    ├── env.py
    ├── script.py.mako
    └── versions/
```

---

## 🧠 App Factory Pattern

`main.py` uses a **`create_app()` factory** that wires shared services into each router via `_init()` before registering routes — eliminating globals and circular imports:

```python
def create_app() -> FastAPI:
    application = FastAPI(title="CarVision by Saleh Abbaas")

    # Inject shared state into routers
    cameras._init(stream_manager, manual_clip_manager)
    clips._init(manual_clip_manager)
    detections._init(detect_plate, read_plate_text, _copy_training_image, _load_image_size)
    training._init(camera_manager, read_plate_text, crop_from_bbox, set_anpr_config)
    upload._init(_run_upload_job)

    # Register all routers
    for r in [auth.router, dashboard.router, cameras.router, ...]:
        application.include_router(r)

    return application
```

---

## 🛣️ API Routes

| Method | Path | Router | Description |
|---|---|---|---|
| `POST` | `/api/v1/auth/login` | auth | JWT login |
| `GET` | `/api/v1/auth/me` | auth | Current user |
| `GET` | `/api/v1/dashboard/summary` | dashboard | 24h analytics |
| `GET/POST/PATCH/DELETE` | `/api/v1/cameras` | cameras | Camera management |
| `GET` | `/api/v1/cameras/{id}/stream` | cameras | MJPEG live stream |
| `GET` | `/api/v1/detections` | detections | Detection history |
| `POST` | `/api/v1/detections/{id}/reprocess` | detections | Re-run pipeline |
| `GET/POST/PATCH/DELETE` | `/api/v1/allowed` | allowed | Allowlist management |
| `GET` | `/api/v1/notifications` | notifications | Event notifications |
| `GET` | `/api/v1/discovery/run` | discovery | ONVIF scan |
| `POST` | `/api/v1/discovery/resolve` | discovery | RTSP profile resolve |
| `GET/POST/DELETE` | `/api/v1/clips` | clips | Clip recording |
| `POST` | `/api/v1/upload/start` | upload | Upload video/image |
| `GET` | `/api/v1/training/status` | training | Training job status |
| `POST` | `/api/v1/training/start` | training | Start training |
| `POST` | `/api/v1/training/stop` | training | Stop training |
| `GET` | `/api/v1/training/samples` | training | Training samples |

Full interactive docs available at **`/docs`** (Swagger UI) when the server is running.

---

## 🔬 Recognition Pipeline — Stage by Stage

```
Frame In
   │
   ▼
┌──────────────────┐
│  frame_selector  │  Scores frames by sharpness (Laplacian variance)
│                  │  and picks the best candidate
└────────┬─────────┘
         ▼
┌──────────────────┐
│ plate_localizer  │  YOLOv8 detects plate bounding boxes
│                  │  Supports YOLO / contour / auto mode
└────────┬─────────┘
         ▼
┌──────────────────┐
│  plate_cropper   │  Crops and pads each detected region
└────────┬─────────┘
         ▼
┌──────────────────┐
│  plate_quality   │  Rejects blurry or too-small crops
└────────┬─────────┘
         ▼
┌──────────────────┐
│ plate_rectifier  │  Corrects perspective skew via homography
└────────┬─────────┘
         ▼
┌──────────────────┐
│plate_classifier  │  Classifies plate type (region / format)
└────────┬─────────┘
         ▼
┌──────────────────┐
│   plate_ocr      │  EasyOCR reads characters with configurable
│                  │  language pack, max-width, and device
└────────┬─────────┘
         ▼
┌──────────────────┐
│  postprocess     │  Normalises text, removes noise, validates
│                  │  format against known plate patterns
└────────┬─────────┘
         ▼
┌──────────────────┐
│   confidence     │  Fuses YOLO confidence + OCR confidence
│                  │  + quality score into a single result score
└────────┬─────────┘
         ▼
┌──────────────────┐
│    tracker       │  Groups detections across frames using
│                  │  IoU overlap — reduces duplicate events
└────────┬─────────┘
         ▼
Detection Result  →  DB  +  Allowlist Check  +  Notification
```

---

## 🎓 Training Pipeline

The training system runs in a **daemon thread** with a subprocess-based YOLO worker:

```
POST /api/v1/training/start
         │
         ▼
training.py  →  _start_training_pipeline_thread()
         │
         ▼
_training_worker.py  →  run_training_pipeline_job()
         │
         ├── 1. Build YOLO dataset from labelled samples
         ├── 2. Chunk-based training loop (yolo_train_worker.py subprocess)
         │       └── Stall watchdog + heartbeat monitoring
         ├── 3. OCR prefill pass on new detections
         ├── 4. OCR correction learning from feedback
         ├── 5. Reload model into live detection pipeline
         └── 6. Send completion notification
```

Thread safety is managed via:
- `TRAIN_PIPELINE_LOCK` — prevents concurrent training runs
- `TRAIN_PIPELINE_STOP` — `threading.Event()` for graceful cancellation
- `TRAIN_PIPELINE_PROC_LOCK` + `TRAIN_PIPELINE_PROC` — subprocess handle for kill

---

## 🔒 Security

| Concern | Implementation |
|---|---|
| Authentication | JWT HS256 tokens via `python-jose`, expiry configurable |
| ONVIF credentials | Fernet-encrypted at rest, key derived from `JWT_SECRET` |
| Password storage | Bcrypt hashing (`passlib`) |
| DB migrations | Alembic versioned — no ad-hoc `CREATE TABLE IF NOT EXISTS` |
| Thread safety | `threading.Lock()` guards on all shared mutable state |

---

## 🚀 Running Locally

```bash
cd CarVision/backend/app

# Install dependencies
pip install -r ../../requirements.txt

# Run database migrations
alembic upgrade head

# Start the server
uvicorn main:app --reload --port 8000
```

Environment variables (copy `.env.carvision.example` → `.env.carvision`):

| Variable | Description | Default |
|---|---|---|
| `DATABASE_URL` | PostgreSQL connection string | required |
| `JWT_SECRET` | JWT signing secret | required |
| `API_ADMIN_USER` | Admin username | `admin` |
| `API_ADMIN_PASS` | Admin password | required |
| `MEDIA_DIR` | Media storage path | `datasets/media` |
| `INFERENCE_DEVICE` | `cpu` / `cuda` / `mps` | `cpu` |

---

## 🤖 Refactored with AI Agents

This backend was refactored from a **7,155-line monolithic `main.py`** into the clean 12-module architecture you see here using **Claude Cowork** (Anthropic's desktop AI agent):

- Extracted all 120+ route handlers into domain-specific `APIRouter` modules
- Applied the `_init()` dependency injection pattern throughout
- Fixed thread safety, credential security, and pipeline error handling
- Migrated to Alembic migrations
- All cross-file imports verified — zero circular dependencies

*The result: `main.py` went from 7,155 lines to 660 lines.*
