<div align="center">

<br/>

```
 ██████╗ █████╗ ██████╗ ██╗   ██╗██╗███████╗██╗ ██████╗ ███╗   ██╗
██╔════╝██╔══██╗██╔══██╗██║   ██║██║██╔════╝██║██╔═══██╗████╗  ██║
██║     ███████║██████╔╝██║   ██║██║███████╗██║██║   ██║██╔██╗ ██║
██║     ██╔══██║██╔══██╗╚██╗ ██╔╝██║╚════██║██║██║   ██║██║╚██╗██║
╚██████╗██║  ██║██║  ██║ ╚████╔╝ ██║███████║██║╚██████╔╝██║ ╚████║
 ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝  ╚═══╝  ╚═╝╚══════╝╚═╝ ╚═════╝ ╚═╝  ╚═══╝
```

### *Intelligent License Plate Recognition & Automated Gate Access Control*

**See every plate. Verify every vehicle. Open every gate — automatically.**

<br/>

[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18.3-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Ultralytics-7c3aed?style=for-the-badge&logo=python&logoColor=white)](https://ultralytics.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-17-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=for-the-badge&logo=docker&logoColor=white)](https://docker.com)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)
[![License](https://img.shields.io/badge/License-MIT-green?style=for-the-badge)](LICENSE)

<br/>

> 🚧 **Gate Control** — hardware relay / GPIO output to trigger physical barriers is coming in the next release.
> The allowlist, detection engine, and access decisions are **fully implemented today.**

</div>

---

## 🌟 What is CarVision?

CarVision is a **self-hosted, full-stack Automatic Number Plate Recognition (ANPR) platform** built for automated gate and barrier access control. Connect any IP camera, define which plates are authorized, and CarVision handles everything — live detection, identity verification, event logging, instant alerts, and (coming soon) physically opening a gate when an authorized vehicle arrives.

Built for **gated communities, private parking lots, warehouses, security checkpoints, and smart facilities** that need enterprise-grade vehicle access control — without the enterprise price tag.

```
  📷  Camera  ──►  🧠  AI Pipeline  ──►  ✅  Allowlist Check  ──►  🚪  Gate Signal
```

---

## 🎬 How the AI Pipeline Works

Every frame from your camera travels through a **10-stage recognition pipeline**:

```
 📷  Your Camera  (RTSP · MJPEG · ONVIF · USB · Webcam)
         │
         ▼
 ┌─────────────────────────────────────────────────────────┐
 │               🧠  AI Recognition Pipeline               │
 │                                                         │
 │  Stage 1   📸  Frame Selector    sharpest frame wins    │
 │  Stage 2   🔍  Plate Localizer   YOLOv8 finds the plate │
 │  Stage 3   ✂️   Plate Cropper    extracts the region    │
 │  Stage 4   ⭐  Quality Scorer    rejects blurry crops   │
 │  Stage 5   📐  Plate Rectifier   corrects skew & angle  │
 │  Stage 6   🏷️   Plate Classifier  identifies plate type │
 │  Stage 7   🔡  OCR Engine        reads the characters   │
 │  Stage 8   ✅  Post-Processor    normalises & validates │
 │  Stage 9   🎯  Confidence Fuser  scores the result      │
 │  Stage 10  🔗  Tracker           links frames together  │
 └─────────────────────────────────────────────────────────┘
         │
         ▼
 🗄️  DB Log  +  🔔  Notification  +  🚪  Gate Signal (coming soon)
```

---

## ✨ Features

| Category | What it does |
|---|---|
| 📷 **Multi-Camera** | RTSP, ONVIF auto-discovery, MJPEG, USB webcam, browser capture |
| 🧠 **AI Detection** | YOLOv8 plate localiser + multi-engine OCR with confidence fusion |
| 🚗 **Access Control** | Allowlist management, ALLOWED/DENIED classification, full event log |
| 🎓 **Model Training** | Dataset import, annotation, chunk-based YOLO training, export |
| 📊 **Dashboard** | Real-time multi-camera view, 24h analytics, detection history |
| 🔔 **Alerts** | Instant notifications on denied plates or detection events |
| 🎥 **Clip Recording** | On-demand manual clip recording from any live camera |
| 🔧 **Diagnostics** | Standalone OpenCV viewer for direct camera debugging |
| 🔒 **Security** | JWT auth, Fernet-encrypted ONVIF credentials, Alembic migrations |
| 🚀 **Deployment** | Docker Compose (single node) · Kubernetes with HPA (multi-node) |

---

## 🤖 Built with AI Agents

CarVision was built with **AI agentic workflows** at the core of the development process — not just autocomplete, but real autonomous coding agents doing architectural work:

<table>
<tr>
<td width="50%" valign="top">

### 🟣 Claude Cowork — Anthropic

*Desktop AI agent for architecture & deep refactoring*

- Refactored a **7,155-line monolithic `main.py`** into 12 clean, domain-specific router modules with proper separation of concerns
- Audited and fixed critical production issues: thread safety, Fernet credential encryption, pipeline error handling
- Migrated fragile ad-hoc SQL schema creation to **versioned Alembic migrations**
- Updated all 40+ dependencies to latest stable versions with compatibility verification
- Cross-referenced imports across the entire codebase and caught bugs before they hit production
- Reasoned about architectural trade-offs like a senior engineer would

</td>
<td width="50%" valign="top">

### 🟢 Codex — OpenAI

*Cloud AI agent for feature development & boilerplate*

- Generated new API endpoints, Pydantic schema definitions, and service-layer helpers
- Built React components, TypeScript hooks, and API client bindings
- Produced test stubs, inline documentation, and docstrings at scale
- Accelerated iteration on the YOLO training pipeline configuration
- Helped bootstrap the frontend design system components

</td>
</tr>
</table>

> 💡 **The result:** Production-grade code shipped significantly faster — not by replacing engineering judgment, but by amplifying what one engineer can build and maintain.

---

## 🏗️ Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                          CarVision System                            │
│                                                                      │
│  ┌───────────────┐    ┌───────────────────────────────────────────┐ │
│  │   Frontend    │    │              Backend  (FastAPI)           │ │
│  │               │    │                                           │ │
│  │  React 18     │◄──►│  routers/              pipeline/         │ │
│  │  TypeScript   │    │  ├─ auth               ├─ frame_selector  │ │
│  │  Tailwind CSS │    │  ├─ cameras            ├─ plate_localizer │ │
│  │  Vite         │    │  ├─ detections         ├─ plate_cropper   │ │
│  │  Chart.js     │    │  ├─ training           ├─ plate_quality   │ │
│  │  Framer Motion│    │  ├─ _training_worker   ├─ plate_rectifier │ │
│  └───────────────┘    │  ├─ clips              ├─ plate_classifier│ │
│                       │  ├─ allowed            ├─ plate_ocr       │ │
│  ┌───────────────┐    │  ├─ notifications      ├─ postprocess     │ │
│  │   Database    │    │  ├─ discovery          ├─ confidence      │ │
│  │               │◄──►│  ├─ dashboard          └─ tracker         │ │
│  │  PostgreSQL   │    │  ├─ upload                                │ │
│  │  SQLAlchemy   │    │  └─ deps               services/         │ │
│  │  Alembic      │    │                        ├─ camera_edit     │ │
│  └───────────────┘    │  main.py               ├─ dataset         │ │
│                       │  (app factory)         ├─ state           │ │
│  ┌───────────────┐    │  660 lines             └─ manual_clip_mgr │ │
│  │   Cameras     │◄──►│                                           │ │
│  │  RTSP · ONVIF │    └───────────────────────────────────────────┘ │
│  │  MJPEG · USB  │                                                  │
│  └───────────────┘                                                  │
└──────────────────────────────────────────────────────────────────────┘
```

---

## 🗂️ Repository Structure

```
CarVision/
│
├── 📁 backend/
│   ├── app/
│   │   ├── main.py                  # App factory + shared services (660 lines)
│   │   ├── routers/                 # 12 domain APIRouter modules
│   │   │   ├── auth.py              #   JWT login & /me
│   │   │   ├── cameras.py           #   Camera CRUD, streams, PTZ
│   │   │   ├── detections.py        #   Detection history & reprocess
│   │   │   ├── training.py          #   Full YOLO training pipeline API
│   │   │   ├── _training_worker.py  #   Subprocess training worker
│   │   │   ├── clips.py             #   On-demand clip recording
│   │   │   ├── allowed.py           #   Allowlist CRUD
│   │   │   ├── notifications.py     #   Event notifications
│   │   │   ├── discovery.py         #   ONVIF camera discovery
│   │   │   ├── dashboard.py         #   Analytics summary
│   │   │   ├── upload.py            #   Video/image upload jobs
│   │   │   └── deps.py              #   Shared auth & payload builders
│   │   ├── pipeline/                # 10-stage ANPR recognition pipeline
│   │   │   ├── frame_selector.py    #   Selects sharpest frame
│   │   │   ├── plate_localizer.py   #   YOLOv8 detection
│   │   │   ├── plate_cropper.py     #   Region extraction
│   │   │   ├── plate_quality.py     #   Blur/quality filter
│   │   │   ├── plate_rectifier.py   #   Perspective correction
│   │   │   ├── plate_classifier.py  #   Plate type classification
│   │   │   ├── plate_ocr.py         #   Character recognition
│   │   │   ├── postprocess.py       #   Normalisation & validation
│   │   │   ├── confidence.py        #   Score fusion
│   │   │   └── tracker.py           #   Cross-frame tracking
│   │   ├── services/                # Business logic helpers
│   │   └── core/                    # Config, DB engine, ORM models
│   └── migrations/                  # Alembic versioned migrations
│
├── 📁 frontend/
│   └── src/
│       ├── pages/                   # Route-level screens
│       ├── components/              # Shared UI components
│       ├── design-system/           # Design primitives
│       ├── hooks/                   # Custom React hooks
│       └── lib/                     # API client & utilities
│
├── 📁 deploy/
│   ├── compose/                     # Docker Compose manifests
│   ├── docker/                      # Dockerfiles (backend + frontend)
│   ├── k8s/                         # Kubernetes base manifests + HPA
│   └── scripts/                     # deploy.sh
│
├── 📁 tools/
│   └── viewer.py                    # Standalone OpenCV diagnostics viewer
│
├── 📁 models/                       # YOLO detection models (.pt files)
└── 📁 datasets/                     # Training datasets & runtime media
```

---

## 🚀 Quick Start

### Option 1 — Docker Compose *(Recommended)*

```bash
git clone https://github.com/salehabbas/CarVision.git
cd CarVision

# Copy and edit environment file
cp .env.carvision.example .env.carvision
# Set JWT_SECRET, POSTGRES_PASSWORD, etc.

docker compose -f deploy/compose/docker-compose.carvision.yml \
  --env-file .env.carvision up -d --build
```

| Service | URL |
|---|---|
| 🖥️ Frontend Dashboard | http://localhost:8081 |
| ⚙️ Backend API | http://localhost:8000 |
| 📖 API Docs (Swagger) | http://localhost:8000/docs |

---

### Option 2 — Local Development

**Backend**
```bash
cd CarVision/backend/app
pip install -r ../../requirements.txt
uvicorn main:app --reload --port 8000
```

**Frontend**
```bash
cd CarVision/frontend
npm install
npm run dev          # → http://localhost:5173
```

---

## 🔧 Diagnostics Viewer

Debug cameras directly — no web stack needed. Opens a native OpenCV window with live overlay:

```bash
python tools/viewer.py                                        # all cameras
python tools/viewer.py --camera 1                            # one by ID
python tools/viewer.py --source rtsp://user:pass@ip/stream   # ad-hoc
python tools/viewer.py --mode yolo                           # force YOLO
```

Press **Q** or **ESC** to quit.

---

## ☸️ Kubernetes Deployment

```bash
kubectl create namespace carvision
kubectl -n carvision create secret generic carvision-secrets \
  --from-literal=database_url=postgresql://... \
  --from-literal=jwt_secret=your-secret \
  --from-literal=api_admin_user=admin \
  --from-literal=api_admin_pass=yourpassword

kubectl apply -k deploy/k8s/base
kubectl -n carvision get pods
```

See [deploy/k8s/README.md](./deploy/k8s/README.md) for the full guide.

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|---|---|---|
| 🖥️ Frontend | React 18 + TypeScript + Vite | Dashboard UI |
| 🎨 Styling | Tailwind CSS + Framer Motion | Design system & animations |
| 📊 Charts | Chart.js + react-chartjs-2 | Detection analytics |
| ⚙️ Backend | FastAPI 0.136 + Python 3.11 | REST API & MJPEG streaming |
| 🧠 Detection | Ultralytics YOLOv8 | Plate localisation |
| 🔡 OCR | EasyOCR + custom post-processing | Character recognition |
| 🗄️ Database | PostgreSQL 17 + SQLAlchemy + Alembic | Persistence & migrations |
| 🔒 Auth | JWT HS256 + Fernet encryption | Security |
| 📷 Cameras | OpenCV + ONVIF + RTSP/MJPEG | Stream capture |
| 🐳 Containers | Docker + Docker Compose | Local deployment |
| ☸️ Orchestration | Kubernetes + HPA | Production scaling |

---

## 🗺️ Roadmap

- [x] Multi-camera live detection dashboard
- [x] ONVIF auto-discovery & RTSP profile resolution
- [x] 10-stage AI recognition pipeline
- [x] Custom YOLO model training pipeline (chunk-based)
- [x] Allowlist & ALLOWED/DENIED access control
- [x] JWT auth + Fernet-encrypted credentials
- [x] Docker Compose + Kubernetes deployment
- [x] Alembic versioned database migrations
- [x] Clean 12-module router architecture (refactored from 7,000-line monolith)
- [ ] 🚧 **Gate / barrier hardware relay output** *(in progress)*
- [ ] Mobile push notifications
- [ ] Multi-tenant / multi-site support
- [ ] Edge deployment (Jetson Nano / Raspberry Pi)

---

## 📖 Documentation

| Doc | Description |
|---|---|
| [backend/README.md](./backend/README.md) | Backend architecture, router modules, pipeline stages |
| [frontend/README.md](./frontend/README.md) | Frontend structure, components, dev workflow |
| [tools/README.md](./tools/README.md) | Standalone diagnostics viewer usage |
| [deploy/k8s/README.md](./deploy/k8s/README.md) | Kubernetes deployment guide |

---

## 👤 About the Creator

<table>
<tr>
<td width="65%" valign="top">

**Saleh Abbas** is a software engineer passionate about computer vision, AI systems, and building practical tools that solve real-world problems. CarVision was born from the challenge of bringing enterprise-grade automated gate control to any facility — without the enterprise price tag.

This project was built using modern **AI-agentic workflows**, pairing engineering judgment with:
- **[Claude Cowork](https://claude.ai)** (Anthropic) — for architectural refactoring, security hardening, and deep code review
- **[Codex](https://openai.com/codex)** (OpenAI) — for feature development, component generation, and documentation

The combination demonstrates how AI agents can elevate what a single engineer ships — not by replacing judgment, but by amplifying it.

</td>
<td width="35%" align="center" valign="top">

📧 [salehabbas123@gmail.com](mailto:salehabbas123@gmail.com)

🐙 [github.com/salehabbas](https://github.com/salehabbaas)

💼 [LinkedIn](https://linkedin.com/in/salehabbaas)

</td>
</tr>
</table>

---

<div align="center">

Built with ❤️ by **[Saleh Abbas](https://github.com/salehabbas)**

*Powered by AI agents — [Claude Cowork](https://claude.ai) · [Codex](https://openai.com/codex)*

**⭐ Star this repo if you find it useful!**

</div>
