<div align="center">

<img src="https://img.shields.io/badge/CarVision-ANPR%20Platform-0f172a?style=for-the-badge&logo=camera&logoColor=white" alt="CarVision" height="40"/>

# 🚗 CarVision

### *Intelligent License Plate Recognition & Automated Gate Access*

**See every plate. Verify every vehicle. Open every gate automatically.**

CarVision is a full-stack Automatic Number Plate Recognition (ANPR) system that connects to your cameras, reads license plates in real time with AI, checks them against an allowed-vehicles list, and — **coming soon** — automatically opens a gate or barrier when an authorized vehicle is detected.

> 🚧 **Gate Control (coming soon):** Hardware relay / GPIO output to trigger physical gates, barriers, and boom arms will be added in the next release. The allowlist and detection engine are already fully in place.

<br/>

[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18.3-61DAFB?style=flat-square&logo=react&logoColor=black)](https://react.dev)
[![YOLOv8](https://img.shields.io/badge/YOLOv8-Detection-7c3aed?style=flat-square&logo=python&logoColor=white)](https://ultralytics.com)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://docker.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Database-336791?style=flat-square&logo=postgresql&logoColor=white)](https://postgresql.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.x-3178C6?style=flat-square&logo=typescript&logoColor=white)](https://typescriptlang.org)

</div>

---

## 🌟 What is CarVision?

Imagine plugging in any IP camera — from a Hikvision DVR to a simple USB webcam — and instantly having a system that **watches the feed, spots every car that drives by, reads its license plate, cross-checks it against your allowed-vehicles list, and opens a gate automatically**. That's CarVision.

The core purpose is **smart gate access control**: you define which plates are allowed to enter, and CarVision handles the rest — live detection, identity verification, logging, and (coming soon) sending the open signal directly to a physical gate or barrier.

It's built for **gated communities**, **private parking**, **warehouses**, **security checkpoints**, and **smart facilities** that need automated vehicle access control without the cost of enterprise systems.

You connect your cameras, optionally train a custom model on your local plate styles, and get a live multi-camera dashboard with detection history, alerts, and access control — all in one self-hosted package.

---

## 🎬 How It Works

Here's the full journey from a camera frame to a logged detection — in plain English, before we get into the code:

```
 📷  Your Camera (RTSP / MJPEG / USB / Webcam)
         │
         ▼
 ╔═══════════════════════════════════════════════════════════╗
 ║              🧠  AI Recognition Pipeline                  ║
 ║                                                           ║
 ║  Step 1  📸  Frame Selector    picks the sharpest frame   ║
 ║  Step 2  🔍  Plate Localizer   YOLOv8 finds the plate     ║
 ║  Step 3  ✂️   Plate Cropper    extracts the plate region  ║
 ║  Step 4  ⭐  Quality Scorer    filters blurry crops       ║
 ║  Step 5  📐  Plate Rectifier   corrects angle & skew      ║
 ║  Step 6  🏷️   Plate Classifier  identifies plate type      ║
 ║  Step 7  🔡  OCR Engine        reads the plate text       ║
 ║  Step 8  ✅  Post-Processor    normalizes & validates     ║
 ║  Step 9  🎯  Confidence Fuser  scores the final result    ║
 ║  Step 10 🔗  Tracker           links frames together      ║
 ╚═══════════════════════════════════════════════════════════╝
         │
         ▼
 💾  Detection saved to PostgreSQL
         │
         ├──▶  📊  Live Dashboard
         ├──▶  🔔  Alerts & Notifications
         └──▶  🔒  Access Control (whitelist check)
```

Every stage is modular — you can swap out the OCR engine, retrain the detector on your local plates, or add a new camera type without touching anything else.

---

## ✨ Feature Highlights

### 📡 Live Multi-Camera Monitoring
Watch all your cameras simultaneously in a DVR-style grid (4, 8, or 16 views). Plate detections appear as live overlays on each feed.

### 🔍 AI-Powered Plate Recognition
A deep pipeline using **YOLOv8** for plate localization and **EasyOCR** for text extraction. Handles angled plates, variable lighting, and different plate formats out of the box.

### 📋 Full Detection History
Every detected plate is logged with its timestamp, camera source, confidence score, and a cropped image of the plate. Fully searchable and filterable.

### 🎓 Custom Model Training — In-App
Upload your own annotated images, draw bounding boxes, label plates, and kick off a training run — entirely within the web UI. Your model, tuned to your location.

### 🔒 Access Control & Gate Trigger
Maintain an allowed-plates whitelist. When an authorized plate is detected, CarVision logs the entry and — **coming soon** — fires a relay/GPIO signal to open a physical gate or barrier. Unrecognized vehicles trigger instant notifications. All routes are secured with JWT authentication.

### 📷 Broad Camera Support
| Protocol | Examples |
|----------|---------|
| RTSP streams | Hikvision, Dahua, Axis, Uniview |
| HTTP MJPEG | Most IP cameras |
| USB / Webcam | Built-in laptop cam, USB cameras |
| Browser capture | No hardware required |
| ONVIF | Auto-discovery + PTZ control |

---

## 🛠️ Tech Stack

| Layer | Technology | Purpose |
|-------|-----------|---------|
| **Frontend UI** | React 18, TypeScript, Vite | Web dashboard |
| **Styling** | Tailwind CSS, Framer Motion, Radix UI | Design & animation |
| **Charts** | Chart.js + react-chartjs-2 | Analytics & graphs |
| **Backend API** | FastAPI, Python 3.11, uvicorn | REST API server |
| **AI Detection** | YOLOv8 (Ultralytics) | Plate localization |
| **AI OCR** | EasyOCR | Plate text reading |
| **Vision** | OpenCV 4.10 | Frame processing |
| **Database** | PostgreSQL + SQLAlchemy | Detection storage |
| **Auth** | PyJWT | Secure access |
| **Camera Protocol** | ONVIF / Zeep, FFmpeg | Camera discovery & streaming |
| **Infrastructure** | Docker, Docker Compose, Nginx | Deployment |

---

## 🚀 Quick Start

### Prerequisites
- Docker & Docker Compose installed
- A camera with an RTSP or MJPEG stream (or just a webcam)

### 1. Clone the repository
```bash
git clone https://github.com/your-username/carvision.git
cd carvision
```

### 2. Configure your environment
```bash
cp .env.example .env
# Edit .env — set your DB credentials, secret key, and camera URLs
```

### 3. Launch with Docker
```bash
docker compose -f deploy/compose/docker-compose.carvision.yml up -d
```

### 4. Open the dashboard
Visit `http://localhost` in your browser and log in with your admin credentials.

### 5. Add your first camera
Go to **Camera Management → Add Camera**, paste your RTSP URL, and CarVision will begin detecting plates immediately.

> 📖 For full setup instructions including HTTPS, remote access, and production hardening, see **[SETUP.md](./SETUP.md)**

---

## 📁 Project Structure

```
CarVision/
├── 🐍 backend/
│   └── app/
│       ├── main.py                  # FastAPI app & all route handlers
│       ├── core/config.py           # Environment & path configuration
│       ├── api/schemas.py           # Pydantic request/response models
│       ├── services/
│       │   ├── dataset.py           # YOLO dataset export & bbox helpers
│       │   ├── state.py             # Training & upload job state
│       │   ├── camera_edit.py       # Camera CRUD & validation
│       │   └── file_utils.py        # Filename & hash utilities
│       └── pipeline/                # 🧠 AI recognition pipeline
│           ├── orchestrator.py      # Pipeline controller
│           ├── frame_selector.py    # Best-frame selection
│           ├── plate_localizer.py   # YOLOv8 plate detection
│           ├── plate_cropper.py     # ROI extraction
│           ├── plate_quality.py     # Quality scoring & filtering
│           ├── plate_rectifier.py   # Geometric correction
│           ├── plate_classifier.py  # Plate type identification
│           ├── plate_ocr.py         # Text recognition (EasyOCR)
│           ├── postprocess.py       # Text normalization
│           ├── confidence.py        # Confidence fusion
│           └── tracker.py           # Cross-frame tracking
│
├── ⚛️  frontend/
│   └── web/
│       └── src/
│           ├── pages/               # Route-level screens
│           ├── components/          # Reusable UI components
│           ├── context/             # Auth & session context
│           ├── hooks/               # Custom React hooks
│           ├── design-system/       # UI component library
│           └── lib/api.ts           # Typed API client
│
├── 🛠️  tools/
│   ├── viewer.py                    # Standalone OpenCV diagnostics utility
│   └── README.md                    # Tool usage docs
│
├── 🐳 deploy/docker/backend.Dockerfile
├── 🐳 deploy/compose/docker-compose.carvision.yml
├── 📦 requirements.txt
└── 📖 SETUP.md
```

---

## 👨‍💻 About the Creator

**CarVision** was designed and built by **Saleh Abbas** ([@salehabbas](https://github.com/salehabbas) · salehabbas123@gmail.com).

The project started from a real need: reliable, affordable, self-hosted vehicle access control that doesn't require expensive proprietary hardware. The goal is a system you can deploy on a Raspberry Pi or a cloud VM, point at any camera, and have working gate automation in under an hour.

---

## 🤖 Built with AI Agentic Tools

CarVision was developed with the help of two cutting-edge AI coding agents that fundamentally changed how fast this project could be built:

### ⚡ [OpenAI Codex](https://openai.com/codex)
Used for rapid code generation, boilerplate scaffolding, and exploring implementation patterns across the backend pipeline. Codex helped generate initial implementations for each pipeline stage — frame selection, plate localization, OCR post-processing — which were then refined and integrated. What would have taken days of writing and looking up APIs took hours.

### 🤝 [Claude Cowork (Anthropic)](https://claude.ai)
Claude's **Cowork mode** acted as an AI pair programmer throughout the entire development lifecycle. With direct access to the project folder, Claude could read the codebase, understand its structure, and make multi-file changes with full context — refactoring services, writing documentation, debugging pipeline issues, and reviewing architectural decisions. Cowork was especially powerful for the complex React dashboard and the pipeline orchestration logic, where keeping context across many files at once is critical.

> These tools didn't replace engineering judgment — they *amplified* it. The architecture, domain logic, and design decisions were shaped by the developer. The AI agents handled the heavy lifting of implementation, boilerplate, documentation, and review — making it possible to build a production-grade system in a fraction of the usual time.

---

## 🔧 Local Development (without Docker)

### Backend
```bash
cd backend/app
pip install -r ../../requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm run dev
# Runs at http://localhost:5173
```

## 🧰 Utilities

### Standalone Camera Diagnostic Viewer
Runs independently of the web server for direct camera debugging.

```bash
cd /Users/salehabbas/Developer/CarVision
python tools/viewer.py
python tools/viewer.py --camera 1
python tools/viewer.py --source rtsp://user:pass@192.168.1.100/stream
```

---

## 📖 Documentation

| Document | Description |
|----------|-------------|
| [SETUP.md](./SETUP.md) | Full deployment guide: HTTPS, remote access, production hardening |
| [ARCHITECTURE_REVIEW.md](./ARCHITECTURE_REVIEW.md) | Architecture decisions & trade-offs |
| [backend/README.md](./backend/README.md) | Backend module layout |
| [frontend/README.md](./frontend/README.md) | Frontend structure & build instructions |

---

<div align="center">

Built with ❤️ by **[Saleh Abbas](https://github.com/salehabbas)**

using **FastAPI · React · YOLOv8 · EasyOCR**

and accelerated by **OpenAI Codex** and **Claude Cowork**

*CarVision — See every plate. Open every gate.*

</div>
