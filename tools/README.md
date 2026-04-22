# Tools

This directory contains standalone developer and operations utilities.

## `viewer.py`

Native OpenCV diagnostics viewer that runs independently of the web stack.

- Reads camera config from the local DB
- Connects directly to camera sources
- Runs YOLO + OCR inline
- Shows live grid with plate overlays and ALLOWED/DENIED labels

Usage:

```bash
cd /Users/salehabbas/Developer/CarVision
python tools/viewer.py
python tools/viewer.py --camera 1
python tools/viewer.py --source rtsp://user:pass@192.168.1.100/stream
```
