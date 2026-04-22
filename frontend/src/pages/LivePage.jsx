import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import {
  Maximize2, Pin, PinOff, Circle, Square, X,
  Camera as SnapIcon, WifiOff, ChevronRight, GripVertical,
} from 'lucide-react';
import { request, apiPath, mediaPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';

// ── Status → visual palette ───────────────────────────────────────────────────
const STATUS_PALETTE = {
  allowed: { fg: '#1cd9a4', bg: 'rgba(28,217,164,0.12)',  glow: 'rgba(28,217,164,0.36)', border: 'rgba(28,217,164,0.46)' },
  denied:  { fg: '#ff5e7e', bg: 'rgba(255,94,126,0.12)',  glow: 'rgba(255,94,126,0.36)', border: 'rgba(255,94,126,0.46)' },
  unknown: { fg: '#ff5e7e', bg: 'rgba(255,94,126,0.12)',  glow: 'rgba(255,94,126,0.36)', border: 'rgba(255,94,126,0.46)' },
  suspect: { fg: '#ffbf47', bg: 'rgba(255,191,71,0.12)',  glow: 'rgba(255,191,71,0.36)', border: 'rgba(255,191,71,0.46)' },
  pending: { fg: '#ffbf47', bg: 'rgba(255,191,71,0.12)',  glow: 'rgba(255,191,71,0.36)', border: 'rgba(255,191,71,0.46)' },
};
function pal(status) { return STATUS_PALETTE[status] || null; }

// ── Grid layouts ──────────────────────────────────────────────────────────────
const LAYOUTS = [
  { id: 1,  label: '1×1',  cols: 1 },
  { id: 4,  label: '2×2',  cols: 2 },
  { id: 9,  label: '3×3',  cols: 3 },
  { id: 16, label: '4×4',  cols: 4 },
];

// ── Persist state to localStorage ─────────────────────────────────────────────
function usePersist(key, def) {
  const [val, setRaw] = useState(() => {
    try { const s = localStorage.getItem(key); return s !== null ? JSON.parse(s) : def; }
    catch { return def; }
  });
  const set = useCallback((v) => {
    setRaw((prev) => {
      const next = typeof v === 'function' ? v(prev) : v;
      try { localStorage.setItem(key, JSON.stringify(next)); } catch {}
      return next;
    });
  }, [key]);
  return [val, set];
}

// ── Overlay / bbox drawing ────────────────────────────────────────────────────
function drawOverlay(canvas, img, det, accentColor, camName) {
  if (!canvas || !img) return;
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  const w = img.clientWidth || img.naturalWidth || 0;
  const h = img.clientHeight || img.naturalHeight || 0;
  if (!w || !h) return;
  if (canvas.width !== w || canvas.height !== h) { canvas.width = w; canvas.height = h; }
  ctx.clearRect(0, 0, w, h);

  const color = accentColor || '#1cd9a4';
  const now = new Date();
  const timeStr = now.toLocaleTimeString('en-GB', { hour12: false });

  // ── LIVE pill (top-right) ──────────────────────────────────────────────────
  const livePillW = 38, pillH = 20;
  const liveX = w - livePillW - 6;
  ctx.fillStyle = 'rgba(220,50,50,0.88)';
  _roundRect(ctx, liveX, 6, livePillW, pillH, 4);
  ctx.fillStyle = '#fff';
  ctx.font = 'bold 9px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('● LIVE', liveX + livePillW / 2, 19);
  ctx.textAlign = 'left';

  // ── Clock (top-right, left of LIVE pill) ──────────────────────────────────
  const clockW = 72;
  const clockX = liveX - clockW - 4;
  ctx.fillStyle = 'rgba(0,0,0,0.62)';
  _roundRect(ctx, clockX, 6, clockW, pillH, 4);
  ctx.fillStyle = '#c9dbf7';
  ctx.font = '10px monospace';
  ctx.textAlign = 'right';
  ctx.fillText(timeStr, clockX + clockW - 6, 20);
  ctx.textAlign = 'left';

  // ── Camera name (top-left) ────────────────────────────────────────────────
  if (camName) {
    ctx.font = 'bold 10px sans-serif';
    const nameW = Math.min(w - clockW - livePillW - 20, ctx.measureText(camName).width + 16);
    ctx.fillStyle = 'rgba(0,0,0,0.65)';
    _roundRect(ctx, 6, 6, nameW, pillH, 4);
    ctx.fillStyle = '#ddeeff';
    ctx.fillText(camName, 12, 20);
  }

  // ── BBox + plate label ────────────────────────────────────────────────────
  if (!det?.bbox) {
    // No active detection — show last-seen timestamp if available
    if (det?.ts) {
      const ageS = Math.round(Date.now() / 1000 - det.ts);
      const ageStr = ageS < 60 ? `Last: ${ageS}s ago` : `Last: ${Math.floor(ageS / 60)}m ago`;
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.font = '10px monospace';
      _roundRect(ctx, 6, h - 28, ctx.measureText(ageStr).width + 14, 20, 4);
      ctx.fillStyle = '#9bb2d1';
      ctx.fillText(ageStr, 12, h - 14);
    }
    return;
  }

  const sx = w / (img.naturalWidth || w);
  const sy = h / (img.naturalHeight || h);

  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = 2.5;
  ctx.shadowColor = color;
  ctx.shadowBlur = 10;

  let x1, y1;
  if (det.bbox.x1 !== undefined) {
    x1 = det.bbox.x1 * sx; y1 = det.bbox.y1 * sy;
    ctx.strokeRect(x1, y1, (det.bbox.x2 - det.bbox.x1) * sx, (det.bbox.y2 - det.bbox.y1) * sy);
  } else if (det.bbox.x !== undefined) {
    x1 = det.bbox.x * sx; y1 = det.bbox.y * sy;
    ctx.strokeRect(x1, y1, det.bbox.w * sx, det.bbox.h * sy);
  } else if (Array.isArray(det.bbox)) {
    const pts = det.bbox.map(p => ({ x: p[0] * sx, y: p[1] * sy }));
    if (pts.length > 1) {
      ctx.beginPath(); ctx.moveTo(pts[0].x, pts[0].y);
      pts.slice(1).forEach(p => ctx.lineTo(p.x, p.y));
      ctx.closePath(); ctx.stroke();
      x1 = Math.min(...pts.map(p => p.x));
      y1 = Math.min(...pts.map(p => p.y));
    }
  }
  ctx.restore();

  if (x1 === undefined) return;

  // Plate label above bbox
  const confStr = det.confidence != null ? `${Math.round(det.confidence * 100)}%` : '';
  const ageS = det.ts ? Math.round(Date.now() / 1000 - det.ts) : null;
  const ageStr = ageS != null ? (ageS < 60 ? `${ageS}s ago` : `${Math.floor(ageS / 60)}m ago`) : '';
  const parts = [det.plate_text, det.status, confStr, ageStr].filter(Boolean);
  const label = parts.join(' · ');
  if (!label) return;

  ctx.font = 'bold 11px monospace';
  const labelW = Math.min(w - x1, ctx.measureText(label).width + 14);
  const labelY = Math.max(0, y1 - 4);
  const lblBoxH = 22;
  ctx.fillStyle = 'rgba(0,0,0,0.82)';
  _roundRect(ctx, x1, Math.max(0, labelY - lblBoxH), labelW, lblBoxH, 4);
  ctx.fillStyle = color;
  ctx.fillText(label, x1 + 6, Math.max(15, labelY - 6));
}

function _roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.lineTo(x + w - r, y);
  ctx.quadraticCurveTo(x + w, y, x + w, y + r);
  ctx.lineTo(x + w, y + h - r);
  ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
  ctx.lineTo(x + r, y + h);
  ctx.quadraticCurveTo(x, y + h, x, y + h - r);
  ctx.lineTo(x, y + r);
  ctx.quadraticCurveTo(x, y, x + r, y);
  ctx.closePath();
  ctx.fill();
}

// ── Composite snapshot (img + overlay canvas) ─────────────────────────────────
function compositeSnapshot(imgEl, canvasEl, filename) {
  if (!imgEl) return;
  const cv  = document.createElement('canvas');
  cv.width  = imgEl.naturalWidth  || imgEl.clientWidth  || 1280;
  cv.height = imgEl.naturalHeight || imgEl.clientHeight || 720;
  const ctx = cv.getContext('2d');
  try {
    ctx.drawImage(imgEl, 0, 0, cv.width, cv.height);
    if (canvasEl && canvasEl.width > 0 && canvasEl.height > 0) {
      ctx.drawImage(canvasEl, 0, 0, cv.width, cv.height);
    }
    const a = document.createElement('a');
    a.download = `${(filename || 'cam').replace(/\s+/g, '-')}_${Date.now()}.png`;
    a.href = cv.toDataURL('image/png');
    a.click();
  } catch {
    // CORS fallback: open current frame URL in new tab
    window.open(imgEl.src, '_blank');
  }
}

// ── Small icon button ─────────────────────────────────────────────────────────
function TileBtn({ children, onClick, title, active, danger, disabled }) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onClick={onClick}
      style={{
        border: '1px solid',
        borderColor: danger ? 'rgba(255,94,126,0.5)' : active ? 'rgba(53,162,255,0.6)' : 'rgba(255,255,255,0.13)',
        background:  danger ? 'rgba(255,94,126,0.18)' : active ? 'rgba(53,162,255,0.2)' : 'rgba(255,255,255,0.06)',
        color: danger ? '#ff5e7e' : active ? '#35a2ff' : 'inherit',
        width: 24, height: 24, borderRadius: 6,
        display: 'grid', placeItems: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.5 : 1,
        flexShrink: 0, padding: 0,
      }}
    >
      {children}
    </button>
  );
}

// ── Fullscreen modal — rendered via Portal to escape stacking contexts ─────────
function FullscreenModal({ cam, src, tilePal, status, lastEvent, overlaysRef, camStatusRef, onClose, onSnapshot }) {
  const imgRef = useRef(null);
  const cvRef  = useRef(null);

  // Poll overlays independently inside the modal
  useEffect(() => {
    const sync = () => {
      const det = overlaysRef.current[String(cam.id)] || null;
      const p   = pal(det?.status || camStatusRef.current[cam.id]);
      drawOverlay(cvRef.current, imgRef.current, det, p?.fg, cam.name);
    };
    const t = setInterval(sync, 200);
    return () => clearInterval(t);
  }, [cam.id, cam.name, overlaysRef, camStatusRef]);

  useEffect(() => {
    const h = (e) => { if (e.key === 'Escape') onClose(); };
    window.addEventListener('keydown', h);
    return () => window.removeEventListener('keydown', h);
  }, [onClose]);

  // Portal renders directly on document.body — bypasses ALL stacking contexts
  return createPortal(
    <div style={{
      position: 'fixed', inset: 0, zIndex: 99999,
      background: 'rgba(2,6,14,0.97)',
      display: 'flex', flexDirection: 'column',
    }}>
      {/* FS header */}
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: '10px 18px', flexShrink: 0,
        background: 'rgba(0,0,0,0.65)',
        borderBottom: `1px solid ${tilePal?.border || 'rgba(255,255,255,0.1)'}`,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{
            width: 9, height: 9, borderRadius: '50%',
            background: tilePal?.fg || '#1cd9a4',
            boxShadow: `0 0 8px ${tilePal?.fg || '#1cd9a4'}`,
          }} />
          <span style={{ fontWeight: 700, fontSize: 15 }}>{cam.name}</span>
          {cam.location && <span style={{ color: 'var(--muted)', fontSize: 12 }}>· {cam.location}</span>}
          {status && (
            <span style={{
              fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 5,
              background: tilePal?.bg, color: tilePal?.fg,
              border: `1px solid ${tilePal?.border}`,
              letterSpacing: '0.5px',
            }}>
              {status.toUpperCase()}
            </span>
          )}
          {lastEvent?.plate_text && (
            <span style={{ fontFamily: 'monospace', fontSize: 14, color: tilePal?.fg || 'var(--text)', fontWeight: 700 }}>
              {lastEvent.plate_text}
            </span>
          )}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            type="button"
            className="btn ghost"
            style={{ fontSize: 12, height: 32 }}
            onClick={() => onSnapshot(imgRef.current, cvRef.current, cam.name)}
          >
            <SnapIcon size={13} /> Snapshot
          </button>
          <button type="button" className="btn ghost" style={{ fontSize: 12, height: 32 }} onClick={onClose}>
            <X size={13} /> Close <span style={{ opacity: 0.4, marginLeft: 3, fontSize: 10 }}>Esc</span>
          </button>
        </div>
      </div>
      {/* FS feed — fills remaining height, never exceeds screen */}
      <div style={{ flex: 1, position: 'relative', minHeight: 0, overflow: 'hidden', background: '#010610' }}>
        <img
          ref={imgRef}
          src={src}
          alt={cam.name}
          loading="eager"
          style={{ width: '100%', height: '100%', objectFit: 'contain', display: 'block' }}
          onLoad={() => {
            const det = overlaysRef.current[String(cam.id)] || null;
            const p   = pal(det?.status || camStatusRef.current[cam.id]);
            drawOverlay(cvRef.current, imgRef.current, det, p?.fg, cam.name);
          }}
        />
        <canvas
          ref={cvRef}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
          aria-hidden
        />
      </div>
    </div>,
    document.body,
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function LivePage() {
  const { token } = useAuth();

  // Persisted DVR preferences
  const [gridMax,      setGridMax]      = usePersist('dvr_grid',  4);
  const [pinnedId,     setPinnedId]     = usePersist('dvr_pin',   null);
  const [cameraOrder,  setCameraOrder]  = usePersist('dvr_order', []);

  // Live data
  const [cameras,           setCameras]   = useState([]);
  const [health,            setHealth]    = useState({});
  const [events,            setEvents]    = useState([]);
  const [recordingByCamera, setRecording] = useState({});
  const [clipBusy,          setClipBusy]  = useState({});
  const [stopAllBusy,       setStopAllBusy] = useState(false);
  const [streamRetry,       setStreamRetry] = useState({});
  const [tickNowMs,         setTickNowMs] = useState(() => Date.now());

  // UI state
  const [fullscreenCam, setFullscreenCam] = useState(null);
  const [eventFilter,   setEventFilter]   = useState('all');
  const [draggingId,    setDraggingId]    = useState(null);
  const [dragOverId,    setDragOverId]    = useState(null);
  const [error,  setError]  = useState('');
  const [notice, setNotice] = useState('');

  // Refs — readable inside effects without causing re-runs
  const overlaysRef   = useRef({});
  const camStatusRef  = useRef({});   // mirrors camStatus without effect deps
  const visibleRef    = useRef([]);   // mirrors visible without effect deps
  const camNamesRef   = useRef({});   // mirrors camera id→name without effect deps
  const imageRefs     = useRef(new Map());
  const canvasRefs    = useRef(new Map());
  const streamNonce   = useRef(Date.now());
  const dragSrcRef    = useRef(null);

  // ── Data polling ─────────────────────────────────────────────────────────────
  useEffect(() => {
    let timer; let alive = true;
    const load = async () => {
      try {
        const [camRes, healthRes, clipsRes] = await Promise.all([
          request('/api/v1/cameras',    { token }),
          request('/api/v1/live/stream_health', { token }),
          request('/api/v1/clips/active', { token }),
        ]);
        if (!alive) return;
        // Only update state when content actually changed to prevent
        // cascading re-renders that disrupt the MJPEG stream connections
        setCameras(prev => {
          const next = (camRes.items || []).filter(c => c.enabled && c.live_view);
          const same = prev.length === next.length && prev.every((c, i) => c.id === next[i]?.id);
          return same ? prev : next;
        });
        setHealth(healthRes.items || {});
        const map = {};
        (clipsRes.items || []).forEach(i => { map[i.camera_id] = i; });
        setRecording(map);
      } catch {}
      timer = setTimeout(load, 4000);
    };
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [token]);

  useEffect(() => {
    const t = setInterval(() => setTickNowMs(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => {
    let timer; let alive = true;
    const load = async () => {
      try {
        const res = await request('/api/v1/detections?limit=40', { token });
        if (!alive) return;
        setEvents(res.items || []);
      } catch {}
      timer = setTimeout(load, 2500);
    };
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [token]);

  // ── Derived data ──────────────────────────────────────────────────────────────
  const layout = LAYOUTS.find(l => l.id === gridMax) || LAYOUTS[1];

  // Cameras sorted by user-defined drag order
  const orderedCameras = useMemo(() => {
    if (cameraOrder.length === 0) return cameras;
    return [...cameras].sort((a, b) => {
      const ai = cameraOrder.indexOf(a.id);
      const bi = cameraOrder.indexOf(b.id);
      if (ai === -1 && bi === -1) return 0;
      if (ai === -1) return 1;
      if (bi === -1) return -1;
      return ai - bi;
    });
  }, [cameras, cameraOrder]);

  const visible = useMemo(() => {
    if (pinnedId) {
      const cam = orderedCameras.find(c => c.id === pinnedId);
      return cam ? [cam] : orderedCameras.slice(0, layout.id);
    }
    return orderedCameras.slice(0, layout.id);
  }, [orderedCameras, pinnedId, layout]);

  // Per-camera latest status (for colour-coding tiles and event cards)
  const camStatus = useMemo(() => {
    const map = {};
    [...events].reverse().forEach(e => { map[e.camera_id] = e.status; });
    return map;
  }, [events]);

  // Keep the ref in sync so overlay drawing uses the latest status without
  // making syncOverlay depend on camStatus (which would restart the effect)
  useEffect(() => { camStatusRef.current = camStatus; }, [camStatus]);
  useEffect(() => { visibleRef.current = visible; }, [visible]);
  useEffect(() => {
    const map = {};
    cameras.forEach(c => { map[c.id] = c.name; });
    camNamesRef.current = map;
  }, [cameras]);

  const camLatestEvent = useMemo(() => {
    const map = {};
    events.forEach(e => { if (!map[e.camera_id]) map[e.camera_id] = e; });
    return map;
  }, [events]);

  const liveCamIds = useMemo(() => new Set(cameras.map(c => c.id)), [cameras]);

  const filteredEvents = useMemo(() => {
    let evs = events.filter(e => liveCamIds.has(e.camera_id));
    if (eventFilter !== 'all') evs = evs.filter(e => e.status === eventFilter);
    return evs.slice(0, 30);
  }, [events, liveCamIds, eventFilter]);

  // ── Overlay sync — stable: reads everything from refs ─────────────────────────
  // No state in deps → this function is created once and never changes.
  // This prevents the overlay polling effect from restarting every 2.5 s
  // (which was causing streams to flicker/go black).
  const syncOverlay = useCallback((camId) => {
    const img     = imageRefs.current.get(camId);
    const canvas  = canvasRefs.current.get(camId);
    const det     = overlaysRef.current[String(camId)] || null;
    const p       = pal(det?.status || camStatusRef.current[camId]);
    const camName = camNamesRef.current[camId] || '';
    drawOverlay(canvas, img, det, p?.fg, camName);
  }, []); // ← intentionally empty deps — reads from refs

  // Overlay polling — restarts only when token changes
  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      while (!ctrl.signal.aborted) {
        const hidden = typeof document !== 'undefined' && document.visibilityState !== 'visible';
        const hasVisibleCams = visibleRef.current.length > 0;
        const delayMs = hidden ? 4000 : hasVisibleCams ? 1000 : 2500;
        try {
          if (!hidden && hasVisibleCams) {
            const res = await request('/api/v1/live/overlays', { token, signal: ctrl.signal });
            if (!ctrl.signal.aborted) {
              overlaysRef.current = res.items || {};
              visibleRef.current.forEach(cam => syncOverlay(cam.id));
            }
          }
        } catch (e) {
          if (e?.name === 'AbortError') break;
        }
        await new Promise(r => setTimeout(r, delayMs));
      }
    })();
    return () => ctrl.abort();
  }, [token, syncOverlay]); // syncOverlay is stable → effect only restarts on auth change

  // Redraw overlays when visible set or status changes
  useEffect(() => { visible.forEach(cam => syncOverlay(cam.id)); }, [visible, camStatus, syncOverlay]);

  useEffect(() => {
    const h = () => visible.forEach(cam => syncOverlay(cam.id));
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, [visible, syncOverlay]);

  // ── Stable stream URLs — memoized per camera, only changes on error/auth ──────
  const streamUrls = useMemo(() => {
    const urls = {};
    cameras.forEach(cam => {
      const retry = Number(streamRetry[cam.id] || 0);
      const nonce = streamNonce.current + retry;
      const base  = `/stream/${cam.id}?overlay=0`;
      urls[cam.id] = token && retry % 2 === 0
        ? apiPath(`${base}&token=${encodeURIComponent(token)}&v=${nonce}`)
        : apiPath(`${base}&v=${nonce}`);
    });
    return urls;
  }, [cameras, streamRetry, token]);

  // ── Clip actions ──────────────────────────────────────────────────────────────
  async function startClip(camId) {
    setClipBusy(p => ({ ...p, [camId]: true }));
    try {
      const res = await request('/api/v1/clips/start', { token, method: 'POST', body: { camera_id: camId } });
      setRecording(p => ({ ...p, [camId]: { camera_id: camId, file_path: res.file_path, started_at: new Date().toISOString() } }));
      setNotice(`Recording started — ${res.camera_name || `Camera ${camId}`}`);
    } catch (err) { setError(err.message || 'Failed to start recording'); }
    finally { setClipBusy(p => ({ ...p, [camId]: false })); }
  }

  async function stopClip(camId) {
    setClipBusy(p => ({ ...p, [camId]: true }));
    try {
      const res = await request('/api/v1/clips/stop', { token, method: 'POST', body: { camera_id: camId } });
      setRecording(p => { const n = { ...p }; delete n[camId]; return n; });
      setNotice(`Clip saved — ${res?.item?.detection_count || 0} detections`);
    } catch (err) { setError(err.message || 'Failed to stop recording'); }
    finally { setClipBusy(p => ({ ...p, [camId]: false })); }
  }

  async function stopAllClips() {
    const activeIds = Object.keys(recordingByCamera).map((v) => Number(v)).filter(Number.isFinite);
    if (!activeIds.length || stopAllBusy) return;
    setStopAllBusy(true);
    const busyMap = {};
    activeIds.forEach((id) => { busyMap[id] = true; });
    setClipBusy((p) => ({ ...p, ...busyMap }));
    let saved = 0;
    let failed = 0;
    try {
      await Promise.all(activeIds.map(async (camId) => {
        try {
          await request('/api/v1/clips/stop', { token, method: 'POST', body: { camera_id: camId } });
          saved += 1;
        } catch {
          failed += 1;
        }
      }));
      setRecording((p) => {
        const next = { ...p };
        activeIds.forEach((id) => { delete next[id]; });
        return next;
      });
      if (saved > 0) {
        setNotice(`Saved ${saved} clip${saved === 1 ? '' : 's'}${failed ? `, failed ${failed}` : ''}`);
      } else if (failed > 0) {
        setError(`Failed to stop active recordings (${failed})`);
      }
    } finally {
      setStopAllBusy(false);
      setClipBusy((p) => {
        const next = { ...p };
        activeIds.forEach((id) => { delete next[id]; });
        return next;
      });
    }
  }

  // ── Snapshot with overlay compositing ────────────────────────────────────────
  function handleSnapshot(imgEl, canvasEl, name) {
    compositeSnapshot(
      imgEl   || imageRefs.current.get(fullscreenCam?.id),
      canvasEl || canvasRefs.current.get(fullscreenCam?.id),
      name,
    );
  }

  // ── Drag-and-drop reordering ─────────────────────────────────────────────────
  function onDragStart(e, camId) {
    dragSrcRef.current = camId;
    setDraggingId(camId);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', String(camId));
  }

  function onDragOver(e, camId) {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragOverId !== camId) setDragOverId(camId);
  }

  function onDrop(e, targetId) {
    e.preventDefault();
    setDragOverId(null);
    const srcId = dragSrcRef.current;
    if (!srcId || srcId === targetId) return;
    // Build new order from the currently ordered camera list
    const ids = orderedCameras.map(c => c.id);
    const si  = ids.indexOf(srcId);
    const ti  = ids.indexOf(targetId);
    if (si === -1 || ti === -1) return;
    ids.splice(si, 1);
    ids.splice(ti, 0, srcId);
    setCameraOrder(ids);
    dragSrcRef.current = null;
    setDraggingId(null);
  }

  function onDragEnd() { setDragOverId(null); setDraggingId(null); dragSrcRef.current = null; }

  // ── Helpers ───────────────────────────────────────────────────────────────────
  function fmtTime(v) {
    if (!v) return '--';
    const d = new Date(v);
    return isNaN(d) ? '--' : d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  function fmtAge(age) {
    if (typeof age !== 'number') return null;
    return age < 60 ? `${Math.round(age)}s ago` : `${Math.round(age / 60)}m ago`;
  }

  function fmtDuration(sec) {
    const total = Math.max(0, Math.floor(Number(sec) || 0));
    const h = Math.floor(total / 3600);
    const m = Math.floor((total % 3600) / 60);
    const s = total % 60;
    if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
    return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
  }

  // ── Grid geometry ─────────────────────────────────────────────────────────────
  const cols       = pinnedId ? 1 : layout.cols;
  const rows       = Math.ceil((pinnedId ? 1 : layout.id) / cols) || 1;
  const emptySlots = pinnedId ? 0 : Math.max(0, layout.id - visible.length);
  const recCount   = Object.keys(recordingByCamera).length;

  // ── Render ────────────────────────────────────────────────────────────────────
  return (
    <div className="dvr-page">

      {/* Alerts */}
      {error  && <div className="alert error"   style={{ flexShrink: 0 }}>{error}  <button className="btn ghost" style={{ marginLeft: 8, padding: '2px 8px' }} onClick={() => setError('')}>×</button></div>}
      {notice && <div className="alert success" style={{ flexShrink: 0 }}>{notice} <button className="btn ghost" style={{ marginLeft: 8, padding: '2px 8px' }} onClick={() => setNotice('')}>×</button></div>}

      {/* ── Toolbar ── */}
      <div className="dvr-toolbar panel glass">
        {/* Grid selectors */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--muted)', marginRight: 2, letterSpacing: '0.5px', textTransform: 'uppercase' }}>Grid</span>
          {LAYOUTS.map(l => (
            <button key={l.id} type="button" title={`${l.id}-camera grid`}
              onClick={() => { setGridMax(l.id); setPinnedId(null); }}
              style={{
                width: 42, height: 28, fontSize: 11, fontWeight: 700, cursor: 'pointer',
                border: '1px solid', borderRadius: 7,
                borderColor: gridMax === l.id ? 'var(--accent)' : 'var(--glass-border)',
                background:  gridMax === l.id ? 'rgba(53,162,255,0.18)' : 'rgba(255,255,255,0.04)',
                color:       gridMax === l.id ? 'var(--accent)' : 'var(--muted)',
              }}
            >
              {l.label}
            </button>
          ))}
        </div>

        {/* Center: live count + unpin */}
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <span style={{ fontSize: 11, color: 'var(--muted)' }}>
            <span style={{ color: 'var(--ok)', fontWeight: 700 }}>
              {cameras.filter(c => { const h = health[c.id]; return h && typeof h.age === 'number' && h.age <= 5; }).length}
            </span>
            /{cameras.length} live
          </span>
          {recCount > 0 && (
            <span style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: 11 }}>
              <span className="dvr-rec-dot" />
              <span style={{ color: '#ff5e7e', fontWeight: 700 }}>{recCount}</span>
              <span style={{ color: 'var(--muted)' }}>recording</span>
            </span>
          )}
          {pinnedId && (
            <button type="button" className="btn ghost" style={{ height: 26, padding: '0 10px', fontSize: 11 }}
              onClick={() => setPinnedId(null)}>
              <PinOff size={11} /> Unpin
            </button>
          )}
          {cameraOrder.length > 0 && (
            <button type="button" className="btn ghost" style={{ height: 26, padding: '0 10px', fontSize: 11 }}
              onClick={() => setCameraOrder([])}>
              Reset order
            </button>
          )}
        </div>

        {/* Right */}
        <div style={{ display: 'flex', gap: 6 }}>
          {recCount > 0 && (
            <button
              type="button"
              className="btn ghost"
              style={{ height: 28, padding: '0 10px', fontSize: 11 }}
              onClick={() => stopAllClips()}
              disabled={stopAllBusy}
            >
              <Square size={11} /> {stopAllBusy ? 'Stopping…' : 'Stop all'}
            </button>
          )}
          <a href="/clips" className="btn ghost" style={{ height: 28, padding: '0 10px', fontSize: 11 }}>
            Clips <ChevronRight size={11} />
          </a>
          <a href="/detections" className="btn ghost" style={{ height: 28, padding: '0 10px', fontSize: 11 }}>
            Detections <ChevronRight size={11} />
          </a>
        </div>
      </div>

      {/* ── DVR main: grid + sidebar ── */}
      <div className="dvr-main">

        {/* Camera grid */}
        <div
          className="dvr-grid"
          style={{
            gridTemplateColumns: `repeat(${cols}, 1fr)`,
            gridTemplateRows:    `repeat(${rows}, 1fr)`,
          }}
        >
          {visible.map((cam) => {
            const camHealth = health[cam.id] || {};
            const age       = camHealth.age;
            const isLive    = typeof age !== 'number' || age <= 5;
            const status    = camStatus[cam.id];
            const tilePal   = pal(status);
            const lastEv    = camLatestEvent[cam.id];
            const isRec     = !!recordingByCamera[cam.id];
            const recInfo   = recordingByCamera[cam.id] || null;
            const startedMs = recInfo?.started_at ? Date.parse(recInfo.started_at) : NaN;
            const elapsedS  = Number.isFinite(startedMs) ? Math.max(0, Math.floor((tickNowMs - startedMs) / 1000)) : null;
            const recFrames = Number(recInfo?.frames || 0);
            const recSizeMb = recInfo?.size_bytes != null ? (Number(recInfo.size_bytes) / (1024 * 1024)) : null;
            const src       = streamUrls[cam.id] || '';
            const isPinned  = pinnedId === cam.id;
            const isDragging = draggingId === cam.id;
            const isDragOver = dragOverId === cam.id && !isDragging;

            return (
              <div
                key={cam.id}
                className="dvr-tile"
                draggable
                onDragStart={(e) => onDragStart(e, cam.id)}
                onDragOver={(e)  => onDragOver(e, cam.id)}
                onDragLeave={() => { if (dragOverId === cam.id) setDragOverId(null); }}
                onDrop={(e)      => onDrop(e, cam.id)}
                onDragEnd={onDragEnd}
                style={{
                  border: isDragOver
                    ? '2px solid var(--accent)'
                    : `1px solid ${tilePal ? tilePal.border : 'var(--glass-border)'}`,
                  boxShadow: isDragOver
                    ? '0 0 24px rgba(53,162,255,0.5)'
                    : tilePal
                      ? `0 0 20px ${tilePal.glow}, 0 0 0 1px ${tilePal.border} inset`
                      : '0 4px 24px rgba(0,0,0,0.35)',
                  opacity: isDragging ? 0.45 : 1,
                  transition: 'border-color 0.4s, box-shadow 0.4s, opacity 0.2s',
                  cursor: 'grab',
                }}
              >
                {/* Recording indicator bar */}
                {isRec && <div className="dvr-rec-bar" />}

                {/* Tile header */}
                <div style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                  padding: '5px 7px', flexShrink: 0,
                  background: 'rgba(3,10,22,0.55)',
                  borderBottom: `1px solid ${tilePal ? tilePal.border : 'rgba(255,255,255,0.06)'}`,
                  gap: 5,
                }}>
                  {/* Drag handle + name */}
                  <div style={{ minWidth: 0, flex: 1, display: 'flex', alignItems: 'center', gap: 5 }}>
                    <GripVertical size={11} style={{ color: 'rgba(255,255,255,0.25)', flexShrink: 0, cursor: 'grab' }} />
                    <span style={{
                      width: 7, height: 7, borderRadius: '50%', flexShrink: 0,
                      background: isLive ? (tilePal?.fg || '#1cd9a4') : '#444',
                      boxShadow: isLive ? `0 0 6px ${tilePal?.fg || '#1cd9a4'}` : 'none',
                      transition: 'background 0.5s',
                    }} />
                    <div style={{ minWidth: 0 }}>
                      <div style={{ fontSize: 11, fontWeight: 700, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                        {cam.name}
                      </div>
                      {cam.location && (
                        <div style={{ fontSize: 9, color: 'var(--muted)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {cam.location}
                        </div>
                      )}
                      {isRec && (
                        <div style={{ fontSize: 9, color: '#ff9aab', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          REC {elapsedS != null ? fmtDuration(elapsedS) : '--:--'} · {recFrames}f{recSizeMb != null ? ` · ${recSizeMb.toFixed(1)}MB` : ''}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Controls */}
                  <div style={{ display: 'flex', gap: 3, flexShrink: 0 }}>
                    {cam.save_clip && (isRec
                      ? <TileBtn title="Stop recording and save clip" danger disabled={!!clipBusy[cam.id] || stopAllBusy} onClick={() => stopClip(cam.id)}><Square size={10} /></TileBtn>
                      : <TileBtn title="Start recording clip" disabled={!!clipBusy[cam.id] || stopAllBusy} onClick={() => startClip(cam.id)}><Circle size={10} /></TileBtn>
                    )}
                    <TileBtn title="Save snapshot (with overlay)" onClick={() => {
                      compositeSnapshot(imageRefs.current.get(cam.id), canvasRefs.current.get(cam.id), cam.name);
                    }}>
                      <SnapIcon size={10} />
                    </TileBtn>
                    <TileBtn title={isPinned ? 'Unpin' : 'Pin (solo view)'} active={isPinned} onClick={() => setPinnedId(isPinned ? null : cam.id)}>
                      {isPinned ? <PinOff size={10} /> : <Pin size={10} />}
                    </TileBtn>
                    <TileBtn title="Fullscreen" onClick={() => setFullscreenCam(cam)}>
                      <Maximize2 size={10} />
                    </TileBtn>
                  </div>
                </div>

                {/* Feed */}
                <div className="dvr-feed">
                  <img
                    ref={node => { if (node) imageRefs.current.set(cam.id, node); else imageRefs.current.delete(cam.id); }}
                    src={src}
                    alt={cam.name}
                    loading="eager"
                    style={{ width: '100%', height: '100%', objectFit: 'cover', display: 'block' }}
                    onLoad={() => syncOverlay(cam.id)}
                    onError={() => setStreamRetry(p => ({ ...p, [cam.id]: (p[cam.id] || 0) + 1 }))}
                  />
                  <canvas
                    ref={node => { if (node) canvasRefs.current.set(cam.id, node); else canvasRefs.current.delete(cam.id); }}
                    style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none' }}
                    aria-hidden
                  />
                  {/* Stale overlay */}
                  {!isLive && (
                    <div style={{
                      position: 'absolute', inset: 0,
                      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
                      background: 'rgba(0,0,0,0.6)', gap: 5,
                    }}>
                      <WifiOff size={18} style={{ color: '#555' }} />
                      <span style={{ fontSize: 10, color: '#555' }}>{fmtAge(age)}</span>
                    </div>
                  )}
                  {/* Drag-over highlight */}
                  {isDragOver && (
                    <div style={{
                      position: 'absolute', inset: 0, pointerEvents: 'none',
                      background: 'rgba(53,162,255,0.18)',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                    }}>
                      <span style={{ fontSize: 12, color: 'var(--accent)', fontWeight: 700 }}>Drop here</span>
                    </div>
                  )}
                </div>

                {/* Detection footer */}
                {lastEv ? (
                  <div style={{
                    padding: '3px 8px', flexShrink: 0, display: 'flex', alignItems: 'center', gap: 6,
                    background: tilePal ? tilePal.bg : 'rgba(0,0,0,0.3)',
                    borderTop: `1px solid ${tilePal ? tilePal.border : 'rgba(255,255,255,0.05)'}`,
                  }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: tilePal?.fg, letterSpacing: '0.4px', textTransform: 'uppercase', flexShrink: 0 }}>
                      {lastEv.status || '?'}
                    </span>
                    <span style={{ fontSize: 10, fontFamily: 'monospace', fontWeight: 700, flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {lastEv.plate_text || `#${lastEv.id}`}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--muted)', flexShrink: 0 }}>{fmtTime(lastEv.detected_at)}</span>
                  </div>
                ) : (
                  <div style={{ height: 4, flexShrink: 0 }} />
                )}
                {isRec && (
                  <div style={{
                    padding: '3px 8px',
                    flexShrink: 0,
                    display: 'flex',
                    alignItems: 'center',
                    gap: 8,
                    background: 'rgba(255,94,126,0.08)',
                    borderTop: '1px solid rgba(255,94,126,0.28)',
                  }}>
                    <span style={{ fontSize: 9, fontWeight: 800, color: '#ff5e7e', letterSpacing: '0.4px', textTransform: 'uppercase' }}>
                      Recording
                    </span>
                    <span style={{ fontSize: 10, fontFamily: 'monospace', color: '#ffc2cf' }}>
                      {elapsedS != null ? fmtDuration(elapsedS) : '--:--'}
                    </span>
                    <span style={{ fontSize: 9, color: 'var(--muted)' }}>
                      {recFrames} frames
                    </span>
                    {recInfo?.file_path && (
                      <span style={{ fontSize: 9, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {recInfo.file_path}
                      </span>
                    )}
                  </div>
                )}
              </div>
            );
          })}

          {/* Empty slots */}
          {Array.from({ length: emptySlots }).map((_, i) => (
            <div key={`empty-${i}`} className="dvr-empty-slot"><span>No camera</span></div>
          ))}
        </div>

        {/* Detection Events sidebar */}
        <div className="dvr-sidebar panel glass">
          <div className="dvr-sidebar-head">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontWeight: 700, fontSize: 13 }}>Detection Events</span>
              <span style={{
                minWidth: 22, textAlign: 'center', fontSize: 10, fontWeight: 700,
                padding: '2px 7px', borderRadius: 5,
                background: 'rgba(28,217,164,0.15)', color: '#1cd9a4',
                border: '1px solid rgba(28,217,164,0.3)',
              }}>{filteredEvents.length}</span>
            </div>
            {/* Filter tabs */}
            <div style={{ display: 'flex', gap: 4, marginTop: 8 }}>
              {[
                { key: 'all',     label: 'All',    color: 'var(--accent)' },
                { key: 'allowed', label: 'Allowed', color: '#1cd9a4' },
                { key: 'denied',  label: 'Denied',  color: '#ff5e7e' },
                { key: 'unknown', label: 'Unknown', color: '#ffbf47' },
              ].map(f => {
                const active = eventFilter === f.key;
                return (
                  <button key={f.key} type="button" onClick={() => setEventFilter(f.key)} style={{
                    flex: 1, padding: '4px 0', fontSize: 10, fontWeight: 700,
                    borderRadius: 6, border: '1px solid', cursor: 'pointer',
                    borderColor: active ? f.color : 'var(--glass-border)',
                    background:  active ? `${f.color}22` : 'transparent',
                    color:       active ? f.color : 'var(--muted)',
                  }}>
                    {f.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="dvr-sidebar-list">
            {filteredEvents.length === 0 && (
              <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '32px 16px', fontSize: 13 }}>
                No events
              </div>
            )}
            {filteredEvents.map((ev, idx) => {
              const evPal = pal(ev.status);
              const isNew = idx === 0;
              return (
                <a
                  key={ev.id}
                  href={`/detections?detection_id=${ev.id}`}
                  target="_blank"
                  rel="noreferrer"
                  className="dvr-event-card"
                  style={{
                    borderLeftColor: evPal?.fg || 'var(--glass-border)',
                    borderColor:     isNew ? (evPal?.border || 'var(--glass-border)') : 'var(--glass-border)',
                    background:      isNew ? (evPal?.bg || 'rgba(255,255,255,0.02)') : 'rgba(255,255,255,0.02)',
                  }}
                >
                  <div style={{ borderRadius: 6, overflow: 'hidden', background: 'rgba(0,0,0,0.4)', flexShrink: 0 }}>
                    <img
                      src={mediaPath(ev.image_path)}
                      alt={ev.plate_text || `#${ev.id}`}
                      style={{ width: 76, height: 52, objectFit: 'cover', display: 'block' }}
                    />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0, flex: 1 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 4 }}>
                      <span style={{ fontFamily: 'monospace', fontWeight: 700, fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {ev.plate_text || `#${ev.id}`}
                      </span>
                      <span style={{
                        fontSize: 9, fontWeight: 700, padding: '2px 5px', borderRadius: 4, flexShrink: 0,
                        background: evPal?.bg || 'rgba(255,255,255,0.08)',
                        color:      evPal?.fg || 'var(--muted)',
                        border:     `1px solid ${evPal?.border || 'var(--glass-border)'}`,
                        letterSpacing: '0.4px',
                      }}>
                        {(ev.status || 'unknown').toUpperCase()}
                      </span>
                    </div>
                    <span style={{ fontSize: 10, color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {ev.camera_name || `Camera ${ev.camera_id}`}
                    </span>
                    <span style={{ fontSize: 10, color: 'var(--muted)' }}>{fmtTime(ev.detected_at)}</span>
                  </div>
                </a>
              );
            })}
          </div>

          <div className="dvr-sidebar-footer">
            <a className="btn ghost" href="/detections" style={{ width: '100%', justifyContent: 'center', fontSize: 12 }}>
              All Detections →
            </a>
          </div>
        </div>
      </div>

      {/* Fullscreen — Portal to document.body to escape backdrop-filter stacking contexts */}
      {fullscreenCam && (
        <FullscreenModal
          cam={fullscreenCam}
          src={streamUrls[fullscreenCam.id] || ''}
          tilePal={pal(camStatus[fullscreenCam.id])}
          status={camStatus[fullscreenCam.id]}
          lastEvent={camLatestEvent[fullscreenCam.id]}
          overlaysRef={overlaysRef}
          camStatusRef={camStatusRef}
          onClose={() => setFullscreenCam(null)}
          onSnapshot={handleSnapshot}
        />
      )}
    </div>
  );
}
