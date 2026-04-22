import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { Camera, RefreshCw, Play, Square, Upload, ShieldAlert } from 'lucide-react';
import { useParams, useSearchParams } from 'react-router-dom';
import { mediaPath } from '../lib/api';

// Raised from 8 → 15 FPS for smoother real-time detection.
// The backend receives more frames per second, giving the detector more
// opportunities to catch a plate mid-motion.
const TARGET_FPS = 15;

// ─── overlay drawing ────────────────────────────────────────────────────────
// Kept outside the component so it is never re-created on render.
// Accepts a pre-allocated OffscreenCanvas ctx when available.
function drawOverlay(canvas, video, detection) {
  if (!canvas || !video) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const width = video.videoWidth || video.clientWidth || 0;
  const height = video.videoHeight || video.clientHeight || 0;
  if (!width || !height) return;

  // Only resize the canvas backing store when the stream resolution changes
  // (avoids expensive GPU texture re-allocation on every frame).
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (!detection?.bbox) return;

  const bbox = detection.bbox;
  let x1, y1, x2, y2;

  if (bbox.x1 !== undefined) {
    x1 = bbox.x1; y1 = bbox.y1; x2 = bbox.x2; y2 = bbox.y2;
  } else if (bbox.x !== undefined) {
    x1 = bbox.x; y1 = bbox.y; x2 = bbox.x + bbox.w; y2 = bbox.y + bbox.h;
  } else {
    return;
  }

  // Scale bbox coordinates from the frame resolution to the canvas size.
  const scaleX = canvas.width / (video.videoWidth || canvas.width);
  const scaleY = canvas.height / (video.videoHeight || canvas.height);
  x1 *= scaleX; y1 *= scaleY; x2 *= scaleX; y2 *= scaleY;

  ctx.strokeStyle = 'rgba(56, 235, 180, 0.92)';
  ctx.lineWidth = 2;
  ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);

  const label = [detection.plate_text, detection.status, detection.detector]
    .filter(Boolean)
    .join(' ');
  if (!label) return;

  ctx.fillStyle = 'rgba(0, 0, 0, 0.68)';
  ctx.fillRect(x1, Math.max(0, y1 - 22), Math.min(canvas.width - x1, 220), 22);
  ctx.fillStyle = '#fff';
  ctx.font = '12px sans-serif';
  ctx.fillText(label, x1 + 6, Math.max(14, y1 - 7));
}

export default function CapturePage() {
  const { cameraId } = useParams();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') || '';
  const [camera, setCamera] = useState(null);
  const [status, setStatus] = useState('Preparing camera...');
  const [statusTone, setStatusTone] = useState('warn');
  const [fps, setFps] = useState(0);
  const [streaming, setStreaming] = useState(false);
  const [secureHelp, setSecureHelp] = useState(false);
  const [debugSteps, setDebugSteps] = useState([]);
  const [error, setError] = useState('');
  const [facingMode, setFacingMode] = useState('environment');

  const videoRef = useRef(null);
  const overlayRef = useRef(null);
  // Hidden canvas used only for JPEG encoding – never shown in the DOM.
  const encodeCanvasRef = useRef(null);
  const fileInputRef = useRef(null);
  const streamRef = useRef(null);

  // Use a single rAF loop instead of two setInterval timers so frame capture
  // and overlay sync stay aligned to the display refresh rate and don't
  // accumulate timer drift.
  const rafIdRef = useRef(null);
  const uploadBusyRef = useRef(false);
  const frameCountRef = useRef(0);
  const lastFpsAtRef = useRef(Date.now());
  // Timestamp of the last sent frame (used to throttle to TARGET_FPS).
  const lastSendAtRef = useRef(0);
  // Minimum milliseconds between frame uploads.
  const frameMsRef = useRef(Math.round(1000 / TARGET_FPS));

  // Keep a stable reference to the latest overlay detection so the rAF loop
  // can read it without closing over a stale value from useState.
  const latestDetectionRef = useRef(null);

  // ── URL memos ──────────────────────────────────────────────────────────────
  const apiSessionUrl = useMemo(
    () => `/api/v1/capture/${cameraId}?token=${encodeURIComponent(token)}`,
    [cameraId, token],
  );
  const apiIngestUrl = useMemo(
    () => `/api/v1/capture/${cameraId}/ingest?token=${encodeURIComponent(token)}`,
    [cameraId, token],
  );
  const apiOverlayUrl = useMemo(
    () => `/api/v1/capture/${cameraId}/overlay?token=${encodeURIComponent(token)}`,
    [cameraId, token],
  );
  const legacySessionUrl = useMemo(
    () => `/capture/${cameraId}/session?token=${encodeURIComponent(token)}`,
    [cameraId, token],
  );
  const legacyIngestUrl = useMemo(
    () => `/ingest/${cameraId}?token=${encodeURIComponent(token)}`,
    [cameraId, token],
  );
  const legacyOverlayUrl = useMemo(
    () => `/capture/${cameraId}/overlay?token=${encodeURIComponent(token)}`,
    [cameraId, token],
  );
  const secureOriginOverride = String(import.meta.env.VITE_CAPTURE_HTTPS_ORIGIN || '').trim();
  const securePortOverride = String(import.meta.env.VITE_CAPTURE_HTTPS_PORT || '8443').trim() || '8443';
  // `api` means /api/v1/capture/* routes; `legacy` means /capture|/ingest routes.
  const endpointModeRef = useRef('api');
  const secureCaptureUrl = useMemo(() => {
    if (typeof window === 'undefined') return '';
    try {
      const current = new URL(window.location.href);
      if (current.protocol === 'https:') {
        return current.toString();
      }
      if (secureOriginOverride) {
        const secureBase = new URL(secureOriginOverride);
        secureBase.pathname = current.pathname;
        secureBase.search = current.search;
        return secureBase.toString();
      }
      current.protocol = 'https:';
      if (current.port === '8081') {
        current.port = securePortOverride;
      }
      return current.toString();
    } catch {
      return '';
    }
  }, [secureOriginOverride, securePortOverride]);

  // ── helpers ────────────────────────────────────────────────────────────────
  const updateStatus = useCallback((message, tone = 'ok') => {
    setStatus(message);
    setStatusTone(tone);
  }, []);

  function stopTracks() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
  }

  function stopLoop() {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
  }

  function resizeOverlay() {
    const video = videoRef.current;
    const overlay = overlayRef.current;
    if (!video || !overlay) return;
    const width = video.videoWidth || video.clientWidth || 0;
    const height = video.videoHeight || video.clientHeight || 0;
    if (width && height) {
      overlay.width = width;
      overlay.height = height;
    }
  }

  // ── frame loop (rAF-driven) ────────────────────────────────────────────────
  // A single requestAnimationFrame loop replaces the two previous setInterval
  // timers.  This has three benefits:
  //   1. Aligned to the browser's vsync – no timer drift or double-fires.
  //   2. Automatically pauses when the tab is hidden (saves CPU/battery).
  //   3. The overlay draw happens synchronously in the same callback, so the
  //      bounding box always reflects the most recent detection without a
  //      second async round-trip.
  function startLoop() {
    stopLoop();

    const loop = (now) => {
      rafIdRef.current = requestAnimationFrame(loop);

      const video = videoRef.current;
      const encodeCanvas = encodeCanvasRef.current;
      const overlay = overlayRef.current;

      // ── Draw overlay on every frame (smooth, vsync-locked) ──
      if (overlay && video) {
        drawOverlay(overlay, video, latestDetectionRef.current);
      }

      // ── Throttle frame uploads to TARGET_FPS ──
      if (now - lastSendAtRef.current < frameMsRef.current) return;
      if (!video || !encodeCanvas || !video.videoWidth || uploadBusyRef.current) return;

      lastSendAtRef.current = now;

      // Re-use the hidden canvas; only update dimensions when resolution changes.
      if (encodeCanvas.width !== video.videoWidth || encodeCanvas.height !== video.videoHeight) {
        encodeCanvas.width = video.videoWidth;
        encodeCanvas.height = video.videoHeight;
      }

      const ctx = encodeCanvas.getContext('2d');
      if (!ctx) return;

      ctx.drawImage(video, 0, 0);
      uploadBusyRef.current = true;

      // toBlob is async – it runs off the main thread in most browsers so it
      // does not block the next animation frame.
      encodeCanvas.toBlob(async (blob) => {
        if (!blob) { uploadBusyRef.current = false; return; }
        try {
          const primaryIngestUrl = endpointModeRef.current === 'legacy' ? legacyIngestUrl : apiIngestUrl;
          let response = await fetch(primaryIngestUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'image/jpeg' },
            body: blob,
          });
          if (!response.ok && endpointModeRef.current === 'api') {
            const fallback = await fetch(legacyIngestUrl, {
              method: 'POST',
              headers: { 'Content-Type': 'image/jpeg' },
              body: blob,
            });
            if (fallback.ok) {
              endpointModeRef.current = 'legacy';
              response = fallback;
            }
          }
          if (!response.ok) {
            throw new Error(`ingest failed (${response.status})`);
          }
          frameCountRef.current += 1;
          const ts = Date.now();
          if (ts - lastFpsAtRef.current >= 1000) {
            setFps(frameCountRef.current);
            frameCountRef.current = 0;
            lastFpsAtRef.current = ts;
          }
        } catch (err) {
          const msg = err?.message || 'network error';
          updateStatus(`Capture/upload error (${msg})`, 'bad');
        } finally {
          uploadBusyRef.current = false;
        }
      }, 'image/jpeg', 0.75);  // Slightly higher quality (0.75) → more detail for OCR
    };

    rafIdRef.current = requestAnimationFrame(loop);
  }

  // ── overlay polling (background, decoupled from render) ───────────────────
  // Runs independently in a lightweight async loop so a slow backend response
  // never blocks the rAF render loop or causes React re-renders on every tick.
  const overlayAbortRef = useRef(null);

  function startOverlayPoll() {
    stopOverlayPoll();
    const controller = new AbortController();
    overlayAbortRef.current = controller;

    (async () => {
      while (!controller.signal.aborted) {
        try {
          const primaryOverlayUrl = endpointModeRef.current === 'legacy' ? legacyOverlayUrl : apiOverlayUrl;
          let res = await fetch(primaryOverlayUrl, { signal: controller.signal });
          if (!res.ok && endpointModeRef.current === 'api') {
            const fallback = await fetch(legacyOverlayUrl, { signal: controller.signal });
            if (fallback.ok) {
              endpointModeRef.current = 'legacy';
              res = fallback;
            }
          }
          const data = await res.json().catch(() => ({}));
          if (!controller.signal.aborted && res.ok && data?.ok) {
            const detection = data.detection || null;
            // Write to the ref – the rAF loop reads it on the next frame
            // without triggering a React re-render.
            latestDetectionRef.current = detection;
            // Only update debugSteps (a visible UI element) when the value
            // actually changed to avoid unnecessary React re-renders.
            setDebugSteps((prev) => {
              const next = (detection?.debug_steps || []).filter((s) => s?.path);
              const same =
                prev.length === next.length &&
                prev.every((s, i) => s.path === next[i].path);
              return same ? prev : next;
            });
          }
        } catch (e) {
          if (e?.name === 'AbortError') break;
          // Keep going on transient network errors.
        }
        // Poll every 200 ms for snappier overlay updates (was 500 ms).
        // 150 ms → overlay updates ~7× per second, fast enough to feel live
        await new Promise((resolve) => setTimeout(resolve, 150));
      }
    })();
  }

  function stopOverlayPoll() {
    if (overlayAbortRef.current) {
      overlayAbortRef.current.abort();
      overlayAbortRef.current = null;
    }
  }

  // ── camera init ───────────────────────────────────────────────────────────
  async function fetchSession() {
    if (!token) {
      setError('Missing capture token in the URL.');
      updateStatus('Missing token', 'bad');
      return false;
    }
    const candidates = [
      ['api', apiSessionUrl],
      ['legacy', legacySessionUrl],
    ];
    for (const [mode, url] of candidates) {
      const response = await fetch(url).catch(() => null);
      if (!response) continue;
      const data = await response.json().catch(() => ({}));
      if (!response.ok || !data?.ok) {
        if (response.status === 401 || response.status === 403) {
          const message = data?.detail || data?.error || `Capture token rejected (${response.status})`;
          throw new Error(message);
        }
        continue;
      }
      endpointModeRef.current = mode;
      setCamera(data.camera || null);
      return true;
    }
    throw new Error('Capture session failed. Check network/proxy for this URL.');
  }

  async function startCamera() {
    if (!navigator.mediaDevices?.getUserMedia) {
      updateStatus('Camera is blocked in this browser context.', 'bad');
      setSecureHelp(true);
      return false;
    }

    try {
      stopTracks();
      const mediaStream = await navigator.mediaDevices.getUserMedia({
        video: {
          facingMode,
          // Request 720 p for a good balance of detail vs. upload bandwidth.
          // frameRate: ideal 30 keeps the viewfinder smooth even when we only
          // upload at TARGET_FPS; the browser buffers frames for us.
          width: { ideal: 1280 },
          height: { ideal: 720 },
          frameRate: { ideal: 30, min: 15 },
          // Low-latency hint (Chrome/Edge) – prevents internal buffering.
          latency: { ideal: 0 },
        },
        audio: false,
      });
      streamRef.current = mediaStream;

      if (videoRef.current) {
        videoRef.current.srcObject = mediaStream;
        // Force immediate play – important on iOS where autoPlay may stall.
        videoRef.current.play().catch(() => {});
      }
      setSecureHelp(false);
      updateStatus('Camera ready', 'warn');
      return true;
    } catch (err) {
      const blockedByHttp =
        window.location.protocol !== 'https:' || !window.isSecureContext;
      setSecureHelp(blockedByHttp);
      updateStatus(
        blockedByHttp
          ? 'Camera needs HTTPS on the phone.'
          : `Camera error: ${err.message || 'unknown error'}`,
        'bad',
      );
      return false;
    }
  }

  async function beginStreaming() {
    const ok = await startCamera();
    if (!ok) return;
    stopLoop();
    stopOverlayPoll();
    setStreaming(true);
    frameCountRef.current = 0;
    lastFpsAtRef.current = Date.now();
    lastSendAtRef.current = 0;
    latestDetectionRef.current = null;
    startLoop();
    startOverlayPoll();
    updateStatus('Streaming live to CarVision', 'ok');
  }

  function stopStreaming() {
    stopLoop();
    stopOverlayPoll();
    stopTracks();
    setStreaming(false);
    setFps(0);
    updateStatus('Stopped', 'bad');
  }

  async function flipCamera() {
    setFacingMode((prev) => (prev === 'environment' ? 'user' : 'environment'));
  }

  async function uploadFallback(event) {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      updateStatus('Uploading fallback frame...', 'warn');
      const primaryIngestUrl = endpointModeRef.current === 'legacy' ? legacyIngestUrl : apiIngestUrl;
      let response = await fetch(primaryIngestUrl, {
        method: 'POST',
        headers: { 'Content-Type': file.type || 'image/jpeg' },
        body: await file.arrayBuffer(),
      });
      if (!response.ok && endpointModeRef.current === 'api') {
        const fallback = await fetch(legacyIngestUrl, {
          method: 'POST',
          headers: { 'Content-Type': file.type || 'image/jpeg' },
          body: await file.arrayBuffer(),
        });
        if (fallback.ok) {
          endpointModeRef.current = 'legacy';
          response = fallback;
        }
      }
      if (!response.ok) throw new Error(`fallback upload failed (${response.status})`);
      updateStatus('Fallback frame uploaded', 'ok');
      // Trigger a single overlay poll immediately after the upload.
      const primaryOverlayUrl = endpointModeRef.current === 'legacy' ? legacyOverlayUrl : apiOverlayUrl;
      const res = await fetch(primaryOverlayUrl);
      const data = await res.json().catch(() => ({}));
      if (res.ok && data?.ok) {
        latestDetectionRef.current = data.detection || null;
        drawOverlay(overlayRef.current, videoRef.current, latestDetectionRef.current);
      }
    } catch (err) {
      const msg = err?.message || 'network error';
      updateStatus(`Fallback upload failed (${msg})`, 'bad');
    } finally {
      event.target.value = '';
    }
  }

  // ── lifecycle ──────────────────────────────────────────────────────────────
  useEffect(() => {
    let alive = true;
    fetchSession()
      .then((ok) => {
        if (!alive || !ok) return;
        return beginStreaming();
      })
      .catch((err) => {
        if (!alive) return;
        setError(err.message || 'Failed to open capture session.');
        updateStatus('Capture session failed', 'bad');
      });

    return () => {
      alive = false;
      stopLoop();
      stopOverlayPoll();
      stopTracks();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, token]);

  // Re-start camera when the user flips front/back.
  useEffect(() => {
    if (!camera) return;
    if (streaming) {
      beginStreaming().catch(() => {});
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [facingMode]);

  // Keep overlay canvas in sync with the window size.
  useEffect(() => {
    const onResize = () => resizeOverlay();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
  }, []);

  // ── render ─────────────────────────────────────────────────────────────────
  return (
    <div className="capture-page">
      <div className="capture-shell glass">
        <div className="capture-header">
          <div className="row">
            <div className="capture-icon"><Camera size={18} /></div>
            <div>
              <div className="capture-title">{camera?.name || `Camera ${cameraId}`}</div>
              <div className="tiny muted">{camera?.location || 'Phone capture device'}</div>
            </div>
          </div>
          <div className="capture-fps">{fps} fps</div>
        </div>

        <div className="capture-stage">
          <video
            ref={videoRef}
            className="capture-video"
            autoPlay
            muted
            playsInline
            // disablePictureInPicture keeps the video pinned to the page.
            disablePictureInPicture
            onLoadedMetadata={resizeOverlay}
          />
          <canvas ref={overlayRef} className="capture-overlay" aria-hidden="true" />
        </div>

        <div className="capture-status">
          <div className="row">
            <span className={`status-dot ${statusTone}`} />
            <span>{status}</span>
          </div>
        </div>

        {secureHelp ? (
          <div className="capture-help">
            <div className="row">
              <ShieldAlert size={16} />
              <strong>Phone camera needs HTTPS</strong>
            </div>
            <div className="tiny muted">
              Open this page with <code>https://</code> on the phone. Mobile Safari and Android
              browsers block camera access on plain HTTP.
            </div>
            <div className="tiny muted">
              If your frontend runs on HTTP port <code>8081</code>, expose HTTPS on another port
              (default <code>8443</code>) and use that secure URL.
            </div>
            {secureCaptureUrl ? (
              <a className="btn primary" href={secureCaptureUrl}>
                Open Secure Capture (HTTPS)
              </a>
            ) : null}
          </div>
        ) : null}

        {error ? <div className="alert error">{error}</div> : null}

        <div className="capture-controls">
          {!streaming ? (
            <button className="btn primary" onClick={() => beginStreaming().catch(() => {})}>
              <Play size={15} /> Start Streaming
            </button>
          ) : (
            <button className="btn" onClick={stopStreaming}>
              <Square size={15} /> Stop
            </button>
          )}
          <button className="btn ghost" onClick={flipCamera}>
            <RefreshCw size={15} /> Flip Camera
          </button>
          <button className="btn ghost" onClick={() => fileInputRef.current?.click()}>
            <Upload size={15} /> Fallback Upload
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            capture="environment"
            title="Fallback mode: upload a photo if live camera capture is not available."
            style={{ display: 'none' }}
            onChange={uploadFallback}
          />
        </div>

        <div className="capture-debug">
          {debugSteps.length
            ? debugSteps.map((step) => (
                <a
                  key={step.path}
                  className="capture-debug-card"
                  href={mediaPath(step.path)}
                  target="_blank"
                  rel="noreferrer"
                >
                  <img src={mediaPath(step.path)} alt={step.label} />
                  <span>{step.label}</span>
                </a>
              ))
            : <div className="tiny muted">Debug frames will appear here after a detection.</div>}
        </div>
      </div>

      {/* Hidden canvas used only for JPEG encoding – not rendered visually */}
      <canvas ref={encodeCanvasRef} style={{ display: 'none' }} />
    </div>
  );
}
