# CarVision – Complete Setup & IP Camera / DVR / Internet Access Guide

## Quick Start (local machine)

```bash
# 1. Clone and enter the project
cd CarVision

# 2. Start everything with Docker Compose
docker compose -f deploy/compose/docker-compose.carvision.yml --env-file .env.carvision up -d --build

# 3. Open the web UI
#    http://localhost:8081      ← frontend
#    https://localhost:8443     ← frontend (secure capture, self-signed cert)
#    http://localhost:8000      ← backend API (direct)
#    Login:  admin / admin  (change these – see Security section)
```

---

## 1. Environment File (.env.carvision)

Edit `.env.carvision` before deploying.  Key variables:

| Variable | What it does | Example |
|---|---|---|
| `API_ADMIN_USER` | Admin login username | `admin` |
| `API_ADMIN_PASS` | Admin login password | `MyStr0ngPass!` |
| `JWT_SECRET` | Signs JWT tokens – **must be random 32+ chars** | `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `VITE_API_URL` | URL the **browser** uses to reach the backend | `http://192.168.1.50:8000` |
| `VITE_CAPTURE_HTTPS_ORIGIN` | Optional explicit secure frontend origin for capture page button | `https://192.168.1.50:8443` |
| `VITE_CAPTURE_HTTPS_PORT` | Secure frontend port used by capture button when origin is not set | `8443` |
| `API_CORS_ORIGINS` | Allowed browser origins (comma-separated) | `http://192.168.1.50:8081` |
| `PUBLIC_BASE_URL` | Full URL for browser-camera QR codes | `https://carvision.example.com` |
| `FRONTEND_PUBLIC_BASE_URL` | Optional explicit frontend base URL used in backend capture redirects | `http://192.168.1.50:8081` |
| `FRONTEND_PUBLIC_SCHEME` / `FRONTEND_PUBLIC_PORT` | Fallback frontend scheme/port for backend capture redirects | `http` / `8081` |
| `SSL_CERTFILE` / `SSL_KEYFILE` | TLS certs for direct HTTPS (optional) | `/certs/fullchain.pem` |

### LAN access from other computers / phones

1. Find your server's LAN IP: `ip addr` or `ifconfig` – e.g. `192.168.1.50`
2. Edit `.env.carvision`:
   ```
   VITE_API_URL=http://192.168.1.50:8000
   API_CORS_ORIGINS=http://192.168.1.50:8081,http://192.168.1.50:8000
   PUBLIC_BASE_URL=http://192.168.1.50:8081
   ```
3. Rebuild the frontend (which bakes the API URL in at build time):
   ```bash
   docker compose -f deploy/compose/docker-compose.carvision.yml --env-file .env.carvision up -d --build carvision-frontend
   ```
4. Open `http://192.168.1.50:8081` from any device on the network.
   For secure phone camera access, use `https://192.168.1.50:8443`.
   Do not use `https://...:8081` (8081 is HTTP).

---

## 2. Connecting IP Cameras & DVRs

### 2a. RTSP cameras (most IP cameras and DVRs)

**In the Cameras page → Add Camera:**
- Type: `RTSP`
- Source: the full RTSP URL of the camera

**Click "RTSP Builder"** if you don't know the URL – fill in IP, port, credentials, channel number and it builds the URL for you.

### Common RTSP URL patterns by brand

| Brand | Main stream | Sub-stream (lower bandwidth) |
|---|---|---|
| **Hikvision** | `rtsp://user:pass@IP:554/Streaming/Channels/101` | `.../Channels/102` |
| **Dahua / Amcrest** | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` | `subtype=1` |
| **Reolink** | `rtsp://user:pass@IP:554//h264Preview_01_main` | `_sub` |
| **Axis** | `rtsp://user:pass@IP/axis-media/media.amp` | `?resolution=640x480` |
| **Uniview / UNV** | `rtsp://user:pass@IP:554/media/video1` | `video2` |
| **Hanwha / Samsung** | `rtsp://user:pass@IP:554/profile1/media.smp` | `profile2` |
| **Annke** | `rtsp://user:pass@IP:554/cam/realmonitor?channel=1&subtype=0` | same as Dahua |
| **Generic** | Use ONVIF Discovery to auto-detect | |

### DVR / NVR channel numbering (Hikvision-style)

Most DVR/NVR brands number streams as:
```
Channel 1 main:  /Streaming/Channels/101
Channel 1 sub:   /Streaming/Channels/102
Channel 2 main:  /Streaming/Channels/201
Channel 2 sub:   /Streaming/Channels/202
...
Channel N main:  /Streaming/Channels/N01
```

### 2b. HTTP MJPEG cameras

Some cheap IP cameras serve MJPEG directly over HTTP (not RTSP).
- Type: `HTTP MJPEG`
- Source: `http://user:pass@IP/video.mjpg`  (exact path varies by camera)

### 2c. Local webcam / USB camera

- Type: `Webcam`
- Source: `0` for the first webcam, `1` for the second, etc.
- The backend container must have access to `/dev/video0` – add this to the backend service in docker-compose if needed:
  ```yaml
  devices:
    - /dev/video0:/dev/video0
  ```

### 2d. Phone / tablet browser camera

1. Add camera → Type: **Browser** → click **Add Camera**
2. In the camera list, click **Run Camera** to get the capture URL
3. Open that URL on the phone – it starts streaming frames to the server

> **Important:** Phone browsers require HTTPS for camera access.
> Local secure endpoint is `https://<server-ip>:8443` (self-signed by default).
> Do not open `https://<server-ip>:8081`; that port is HTTP and will fail.

---

## 3. ONVIF Auto-Discovery

ONVIF lets you scan your network for cameras/DVRs and get their RTSP URLs automatically.

1. Go to **Discovery** page
2. Click **Scan** – CarVision sends WS-Discovery multicast packets
3. If cameras don't appear, enter your subnet in the filter (e.g. `192.168.1.0/24`) and scan again
4. Enter **ONVIF username / password** for each found device
5. Click **Resolve RTSP** – this fetches all RTSP profiles from the device
6. Click **Add Camera** next to the profile you want

> **Note:** ONVIF discovery works best when the backend container has host-network access.
> The docker-compose file sets `network_mode: host` on the backend for this reason.
> If that causes issues on your setup, remove it and manually enter IPs in the subnet filter.

---

## 4. Internet Access (Remote / WAN)

### Option A: Port forwarding (simplest)

1. In your **router admin** page, add port forwarding rules:
   - External port `8081` → Internal IP `192.168.1.50` port `8081` (frontend)
   - External port `8000` → Internal IP `192.168.1.50` port `8000` (API)
2. Find your public IP: `curl ifconfig.me`
3. Edit `.env.carvision`:
   ```
   VITE_API_URL=http://YOUR_PUBLIC_IP:8000
   API_CORS_ORIGINS=http://YOUR_PUBLIC_IP:8081
   PUBLIC_BASE_URL=http://YOUR_PUBLIC_IP:8081
   ```
4. Rebuild and access via `http://YOUR_PUBLIC_IP:8081`

> ⚠ HTTP over the internet is not secure. Use Option B or C for real deployments.

### Option B: DDNS + reverse nginx proxy with SSL (recommended)

1. **Get a domain** (or use a free DDNS service like DuckDNS, No-IP, Cloudflare Tunnel)
2. **Get a TLS certificate** (Let's Encrypt / Certbot is free)
3. **Install nginx on the host** as a reverse proxy:

```nginx
# /etc/nginx/sites-available/carvision
server {
    listen 443 ssl;
    server_name carvision.yourdomain.com;

    ssl_certificate     /etc/letsencrypt/live/carvision.yourdomain.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/carvision.yourdomain.com/privkey.pem;

    # Frontend
    location / {
        proxy_pass http://127.0.0.1:8081;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto https;
    }

    # MJPEG stream (no buffering!)
    location /stream/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_buffering    off;
        proxy_cache        off;
        proxy_read_timeout 3600s;
        add_header         X-Accel-Buffering no;
    }

    # Media files
    location /media/ {
        proxy_pass http://127.0.0.1:8000;
    }
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name carvision.yourdomain.com;
    return 301 https://$host$request_uri;
}
```

4. Edit `.env.carvision`:
   ```
   VITE_API_URL=https://carvision.yourdomain.com
   API_CORS_ORIGINS=https://carvision.yourdomain.com
   PUBLIC_BASE_URL=https://carvision.yourdomain.com
   ```
5. Rebuild and open `https://carvision.yourdomain.com`

### Option C: Cloudflare Tunnel (zero open ports)

If you can't forward ports, use a Cloudflare Tunnel:

```bash
# Install cloudflared
curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 -o cloudflared
chmod +x cloudflared && sudo mv cloudflared /usr/local/bin/

# Authenticate
cloudflared login

# Create a tunnel
cloudflared tunnel create carvision

# Route traffic
cloudflared tunnel route dns carvision carvision.yourdomain.com

# Start tunnel (routes HTTPS → local port 8081)
cloudflared tunnel run --url http://localhost:8081 carvision
```

Edit `.env.carvision` with the Cloudflare URL as shown in Option B.

---

## 5. RTSP Cameras Over the Internet (Remote Cameras)

### Direct RTSP over WAN

If the camera's router forwards RTSP port 554 to the camera:
```
rtsp://user:pass@YOUR_PUBLIC_IP:554/Streaming/Channels/101
```

> ⚠ Raw RTSP over the internet is unencrypted and slow on high-latency links.
> Use a VPN or SSH tunnel for better reliability.

### RTSP via SSH tunnel

On the CarVision server:
```bash
ssh -L 5540:CAMERA_LAN_IP:554 user@REMOTE_SERVER -N -f
```
Then add the camera with source: `rtsp://user:pass@127.0.0.1:5540/Streaming/Channels/101`

### RTSP via VPN (WireGuard / OpenVPN)

Connect both the CarVision server and the remote site to a VPN.
Use the camera's VPN IP address in the RTSP URL.

---

## 6. Security Checklist

Before exposing CarVision to the internet:

- [ ] Change `API_ADMIN_PASS` from `admin` to something strong
- [ ] Change `JWT_SECRET` to a random 32+ character string:
  ```bash
  python3 -c "import secrets; print(secrets.token_hex(32))"
  ```
- [ ] Change `POSTGRES_PASSWORD` from `carvision`
- [ ] Use HTTPS (Option B or C above)
- [ ] Set `API_CORS_ORIGINS` to your exact frontend URL (not `*`)
- [ ] Ensure the database port (5434) is NOT exposed to the internet – remove the `ports` entry from carvision-db in production
- [ ] Consider placing the entire stack behind a VPN

---

## 7. Troubleshooting

### Camera shows "stale" or "no signal"

1. Check the RTSP URL is correct – open it in VLC: `Media → Open Network Stream`
2. Check firewall: `telnet CAMERA_IP 554` should connect
3. For RTSP over WAN: increase the stimeout in the env file:
   ```
   OPENCV_FFMPEG_CAPTURE_OPTIONS=rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0|reorder_queue_size;0|buffer_size;204800|stimeout;20000000
   ```
4. Check backend logs: `docker logs carvision-backend -f`

### ONVIF Discovery finds nothing

1. The backend must be on the same LAN as the cameras (or `network_mode: host`)
2. Check your router doesn't block multicast to `239.255.255.250:3702`
3. Enter the camera IP/subnet manually in the Subnet Filter field
4. Some cameras have ONVIF disabled by default – enable it in the camera's web UI

### Phone camera doesn't work

- Mobile browsers require HTTPS for `getUserMedia()` (camera access)
- Set up SSL (Option B or C) and make sure `PUBLIC_BASE_URL` is set to the HTTPS URL

### Detection is slow

- Switch detector mode to `yolo` if you have a GPU
- Switch to `contour` for fastest CPU-only detection
- Reduce video resolution in the RTSP URL (use sub-stream)
- Increase `scan_interval` in the camera settings (detects every N seconds)

### Stream lag / stuttering

- Use sub-stream (lower resolution): append `102` instead of `101` for Hikvision
- Add `rtsp_transport;tcp` to FFMPEG options if on WiFi
- Check if the server has enough CPU: `docker stats carvision-backend`

---

## 8. Quick Commands

```bash
# Start everything
docker compose -f deploy/compose/docker-compose.carvision.yml --env-file .env.carvision up -d --build

# Stop
docker compose -f deploy/compose/docker-compose.carvision.yml down

# View live backend logs
docker logs carvision-backend -f

# View live frontend logs
docker logs carvision-frontend -f

# Restart only the backend (after editing Python files)
docker compose -f deploy/compose/docker-compose.carvision.yml restart carvision-backend

# Rebuild just the frontend (after editing .env VITE_API_URL)
docker compose -f deploy/compose/docker-compose.carvision.yml up -d --build carvision-frontend

# Open a database shell
docker exec -it carvision-db psql -U carvision -d carvision

# Backup the database
docker exec carvision-db pg_dump -U carvision carvision > backup_$(date +%Y%m%d).sql
```
