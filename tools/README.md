<div align="center">

# 🔧 CarVision — Tools

**Standalone developer & operations utilities**

</div>

---

## 🖥️ `viewer.py` — Native Diagnostics Viewer

A **standalone OpenCV-based camera viewer** that runs completely independently of the web stack. It connects directly to your cameras, runs the full YOLO + OCR detection pipeline inline, and displays a live tiled grid with plate overlays and ALLOWED/DENIED status — all in a native desktop window.

Use it when you want to:
- **Verify a new camera** works before adding it to the system
- **Debug detection quality** without spinning up the full Docker stack
- **Test model changes** immediately after retraining
- **Diagnose connectivity issues** from the command line

---

## Usage

```bash
# From the CarVision project root:

# Show all enabled cameras in a tiled grid
python tools/viewer.py

# Show a single camera by its database ID
python tools/viewer.py --camera 1

# Connect to any RTSP/webcam source directly (no DB needed)
python tools/viewer.py --source rtsp://user:pass@192.168.1.100/stream

# Force a specific detection mode
python tools/viewer.py --mode yolo      # YOLO only
python tools/viewer.py --mode contour   # Contour-based only
python tools/viewer.py --mode auto      # Auto-select (default)
```

Press **`Q`** or **`ESC`** to quit.

---

## What You See

```
┌─────────────────────────────────────────────────────────┐
│  Cap 30fps  Det 12fps              Camera #1 — Gate A   │
│                                                          │
│                                                          │
│           ┌─────────────────┐                           │
│           │   PLATE REGION  │   ← YOLOv8 bounding box  │
│           └─────────────────┘                           │
│                                                          │
│  ABC 1234  94%  [yolo]  → ALLOWED        ← status bar  │
└─────────────────────────────────────────────────────────┘
```

The status bar shows:
- **Plate text** — as read by OCR
- **Confidence** — fused YOLO + OCR score
- **Detector** — which detection mode was used
- **Status** — `ALLOWED` (green) or `DENIED` (red), based on your live allowlist

---

## How it Works

```
DB Camera Config  →  RTSP/USB Source
        │
        ▼
  Capture Thread  (per camera, daemon)
        │
        ▼
  detect_plate()  →  YOLOv8 + OCR pipeline
        │
        ▼
  Display Thread  →  OpenCV imshow() grid
        │
        ▼
  Allowlist Check  →  ALLOWED / DENIED overlay
```

Multi-camera mode tiles up to 3 columns × N rows at 640×360 per tile.

---

## Requirements

The viewer uses the same Python environment as the backend:

```bash
pip install -r requirements.txt
# Requires: opencv-python, ultralytics, easyocr, sqlalchemy
```

> **Note:** Needs a display (X11 or native macOS/Windows). For headless servers, use SSH with X forwarding (`ssh -X`) or run via the web dashboard instead.
