# CarVision by SpinelTech

This project turns the notebook into a live CarVision platform with multi-camera support, a web admin panel, and a local database in Docker.

## Project structure

```text
backend/
  app/
    core/         # settings/config
    api/          # request schemas
    services/     # dataset + state helpers
    main.py       # FastAPI routes (being split incrementally)
frontend/
  carvision-web/ # React frontend (Vite)
datasets/
  media/          # snapshots, uploads, training sets, exports
old/
  python_frontend/ # legacy Jinja templates/static
models/
  plate.pt
```

## Quick start (Docker)

```bash
docker compose up --build
```

Open `http://localhost:8000/admin`.

Note: Postgres is exposed on host port `5433` to avoid conflicts with local port `5432`.

## Access From Other Devices

1. Find your computer's LAN IP address.
2. Open `http://<LAN-IP>:8000/login` on the other device.

Examples:
- macOS: `ipconfig getifaddr en0`
- Linux: `hostname -I`
- Windows: `ipconfig` (look for IPv4 Address)

Make sure your firewall allows inbound connections to port `8000` and both devices are on the same network.

## Browser Camera (Phone/Laptop)

Create a camera with type `browser`. The Cameras page shows a connect URL like:
`http://<LAN-IP>:8000/capture/<camera-id>?token=...`

You can also open `http://<LAN-IP>:8000/capture` (admin login required) to see offline browser cameras and pick one to connect.

Note: Webcam/HTTP MJPEG cameras do not appear in the browser capture list unless you switch them to `browser` type. Use `browser` when you want to stream from the device itself (phone/laptop).

## Camera configuration

Add cameras in **Cameras**:

- **Laptop webcam**: type `webcam`, source `0`
- **Mobile (IP webcam app)**: type `http_mjpeg`, source like `http://<phone-ip>:8080/video`
- **Browser camera (phone/laptop)**: type `browser`, then open `/capture/<camera-id>` from the device
- **Dahua / NVR / DVR**: type `rtsp`, source like
  `rtsp://user:pass@<ip>:554/cam/realmonitor?channel=1&subtype=0`

Settings are applied live. The service polls for changes every 5 seconds.

## Admin panel

- **Allowed Plates**: manage the allow list
- **Dashboard**: shows logs from all cameras with green (allowed) and red (denied) rows
- **Live View**: grid view for up to 16 live cameras with zoom controls and a live detection list
- **PTZ controls**: ONVIF cameras with XAddr + credentials show pan/tilt/zoom controls
- **Snapshots/Clips**: enable per camera in settings
- **ONVIF Discovery**: scan local network and resolve RTSP per device
- **Settings**: toggle detector mode (auto/yolo) and max live cameras
- **Upload**: run detection on uploaded images or videos
- **Browser Camera**: open `/capture/<camera-id>` on a phone or laptop to stream into Live View

Note: ONVIF discovery uses UDP multicast. If you run in Docker, use `--network host` (Linux) or run locally for best results.

## Local (without Docker)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd backend/app
uvicorn main:app --reload
```

Set `DATABASE_URL` and `MEDIA_DIR` if needed.

## Login

Default credentials are `admin` / `admin`. Set `ADMIN_USER`, `ADMIN_PASS`, and `SESSION_SECRET` in the environment for production.

## ONVIF PTZ

To enable PTZ controls on Live View, set `ONVIF XAddr`, `ONVIF Username`, and `ONVIF Password` on the camera.

## YOLO plate detector (optional, higher accuracy)

1. Place a YOLO plate detection model at `models/plate.pt` (or set `YOLO_PLATE_MODEL`).
2. Use **Settings** in the admin panel to switch detector mode (auto/yolo).
3. Ensure `ultralytics` and its dependencies (including `torch`) are installed.
