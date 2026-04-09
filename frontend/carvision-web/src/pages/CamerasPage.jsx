import { useEffect, useRef, useState } from 'react';
import {
  Save, Plus, Trash2, ExternalLink, ChevronDown, ChevronUp,
  Wifi, WifiOff, RefreshCw, Play, Eye, EyeOff, CheckCircle, XCircle, Loader,
} from 'lucide-react';
import { request, apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';
import {
  toCameraDraft,
  buildCameraPatchPayload,
  CAMERA_DETECTOR_OPTIONS,
  DEFAULT_CLIP_MINUTES,
  DEFAULT_CLIP_SECONDS,
  secondsToMinutes,
  minutesToSeconds,
} from '../modules/cameraEditor';

// ── Defaults ────────────────────────────────────────────────────────────────
const defaultNewCamera = {
  name:          '',
  type:          'rtsp',
  source:        '',
  location:      '',
  enabled:       true,
  live_view:     true,
  detector_mode: 'inherit',
  save_clip:     false,
  clip_seconds:  60,
  onvif_xaddr:    '',
  onvif_username: '',
  onvif_password: '',
  onvif_profile:  '',
  // Structured IP camera fields (used to build source URL when type=rtsp)
  _ip: {
    brand: 'dahua', viaNvr: false,
    cameraIp: '', nvrIp: '', port: '554',
    user: '', pass: '', channel: '1', substream: false, customPath: '', unicast: false,
  },
};

// Camera brand definitions — each brand knows its RTSP URL pattern and common ports
const CAMERA_BRANDS = [
  { id: 'dahua',     label: 'Dahua',                ports: [554, 37777] },
  { id: 'hikvision', label: 'Hikvision / most DVRs', ports: [554, 8554] },
  { id: 'reolink',   label: 'Reolink',               ports: [554, 8554] },
  { id: 'axis',      label: 'Axis',                  ports: [554] },
  { id: 'amcrest',   label: 'Amcrest / Annke',       ports: [554, 37777] },
  { id: 'custom',    label: 'Custom / Other',         ports: [554, 8554, 1935] },
];


function buildBrandRtspUrl({ brand, host, port, user, pass, channel, substream, customPath, unicast }) {
  if (!host) return '';
  const p    = port ? `:${port}` : ':554';
  const auth = user ? `${encodeURIComponent(user)}:${encodeURIComponent(pass || '')}@` : '';
  const ch   = channel || 1;
  const sub  = substream ? 1 : 0;

  switch (brand) {
    case 'dahua':
    case 'amcrest': {
      const extra = unicast ? '&unicast=true' : '';
      return `rtsp://${auth}${host}${p}/cam/realmonitor?channel=${ch}&subtype=${sub}${extra}`;
    }
    case 'hikvision':
      return `rtsp://${auth}${host}${p}/Streaming/Channels/${ch}0${substream ? 2 : 1}`;
    case 'reolink':
      return `rtsp://${auth}${host}${p}//h264Preview_0${ch}_${substream ? 'sub' : 'main'}`;
    case 'axis':
      return `rtsp://${auth}${host}${p}/axis-media/media.amp`;
    case 'custom': {
      const path = customPath
        ? (customPath.startsWith('/') ? customPath : `/${customPath}`)
        : `/Streaming/Channels/${ch}0${substream ? 2 : 1}`;
      return `rtsp://${auth}${host}${p}${path}`;
    }
    default:
      return '';
  }
}

function toSecureCaptureUrl(captureUrl) {
  if (!captureUrl || typeof window === 'undefined') return '';
  try {
    const resolved = new URL(captureUrl, window.location.origin);
    if (resolved.protocol === 'https:') return resolved.toString();
    const secureOrigin = String(import.meta.env.VITE_CAPTURE_HTTPS_ORIGIN || '').trim();
    const securePort = String(import.meta.env.VITE_CAPTURE_HTTPS_PORT || '8443').trim() || '8443';
    if (secureOrigin) {
      const base = new URL(secureOrigin);
      base.pathname = resolved.pathname;
      base.search = resolved.search;
      return base.toString();
    }
    resolved.protocol = 'https:';
    if (resolved.port === '8081') {
      resolved.port = securePort;
    }
    return resolved.toString();
  } catch {
    return '';
  }
}

// ── step icon helper ─────────────────────────────────────────────────────────
function StepIcon({ ok }) {
  if (ok === true)  return <CheckCircle size={13} style={{ color: 'var(--ok)', flexShrink: 0 }} />;
  if (ok === false) return <XCircle     size={13} style={{ color: 'var(--bad)', flexShrink: 0 }} />;
  return <span style={{ width: 13, flexShrink: 0 }}>—</span>;
}

const STEP_LABELS = { ping: 'Ping', port: 'TCP Port', rtsp: 'RTSP Handshake', stream: 'Stream Open' };

function DetectorModeOptions({ inheritLabel = 'inherit' }) {
  return CAMERA_DETECTOR_OPTIONS.map((item) => (
    <option key={item.value} value={item.value}>
      {item.value === 'inherit' ? inheritLabel : item.label}
    </option>
  ));
}

// ── IpCameraForm ─────────────────────────────────────────────────────────────
function IpCameraForm({ value, onChange, token }) {
  const {
    brand = 'dahua', viaNvr = false,
    cameraIp = '', nvrIp = '', port = '554',
    user = '', pass = '', channel = '1', substream = false,
    customPath = '', unicast = false,
  } = value;

  const brandDef   = CAMERA_BRANDS.find((b) => b.id === brand) || CAMERA_BRANDS[0];
  const host       = viaNvr ? nvrIp : cameraIp;
  const generatedUrl = buildBrandRtspUrl({
    brand, host, port, user, pass,
    channel: Number(channel) || 1, substream, customPath, unicast,
  });

  function set(patch) { onChange({ ...value, ...patch }); }

  function setBrand(newBrand) {
    const def = CAMERA_BRANDS.find((b) => b.id === newBrand);
    set({ brand: newBrand, customPath: '', port: String(def?.ports[0] ?? 554) });
  }

  const [testState, setTestState] = useState('idle');
  const [testResult, setTestResult] = useState(null);

  async function testConnection() {
    if (!host) return;
    setTestState('loading');
    setTestResult(null);
    try {
      const res = await request('/api/v1/cameras/test_connection', {
        token,
        method: 'POST',
        body: { url: generatedUrl || `rtsp://${host}:${port}/`, host, port: Number(port) || 554 },
      });
      setTestState(res.ok ? 'ok' : 'error');
      setTestResult(res);
    } catch (err) {
      setTestState('error');
      setTestResult({ ok: false, message: err.message || 'Request failed', steps: [] });
    }
  }

  const showUnicast = (brand === 'dahua' || brand === 'amcrest') && viaNvr;

  return (
    <div className="stack" style={{ gap: 10 }}>
      {/* Row 1: Brand + Connection mode */}
      <div className="row two">
        <div>
          <label className="tiny muted">Camera Brand</label>
          <select value={brand} onChange={(e) => setBrand(e.target.value)}>
            {CAMERA_BRANDS.map((b) => (
              <option key={b.id} value={b.id}>{b.label}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="tiny muted">Connection</label>
          <select value={viaNvr ? 'nvr' : 'direct'} onChange={(e) => set({ viaNvr: e.target.value === 'nvr' })}>
            <option value="direct">Direct (camera IP)</option>
            <option value="nvr">Through NVR</option>
          </select>
        </div>
      </div>

      {/* Row 2: IP fields */}
      <div className="row two">
        {viaNvr ? (
          <>
            <div>
              <label className="tiny muted">NVR IP / Host</label>
              <input placeholder="e.g. 10.40.4.2" value={nvrIp}
                onChange={(e) => set({ nvrIp: e.target.value })} />
            </div>
            <div>
              <label className="tiny muted">Camera IP (on NVR, informational)</label>
              <input placeholder="e.g. 10.40.4.110" value={cameraIp}
                onChange={(e) => set({ cameraIp: e.target.value })} />
            </div>
          </>
        ) : (
          <div>
            <label className="tiny muted">Camera IP / Host</label>
            <input placeholder="e.g. 192.168.1.100" value={cameraIp}
              onChange={(e) => set({ cameraIp: e.target.value })} />
          </div>
        )}
      </div>

      {/* Row 3: Port with quick-pick buttons on same line */}
      <div>
        <label className="tiny muted">RTSP Port</label>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center', flexWrap: 'wrap', marginTop: 4 }}>
          <input
            type="number"
            placeholder="554"
            value={port}
            style={{ width: 90 }}
            onChange={(e) => set({ port: e.target.value })}
          />
          <span className="tiny muted">or pick:</span>
          {brandDef.ports.map((p) => (
            <button
              key={p}
              type="button"
              className="btn ghost"
              style={{
                padding: '3px 10px',
                fontSize: '0.78em',
                background: String(port) === String(p) ? 'var(--accent)' : undefined,
                color:      String(port) === String(p) ? '#fff' : undefined,
              }}
              onClick={() => set({ port: String(p) })}
            >
              {p}
            </button>
          ))}
          <span className="tiny muted" style={{ marginLeft: 2 }}>
            (common for {brandDef.label}: {brandDef.ports.join(', ')})
          </span>
        </div>
      </div>

      {/* Row 4: Credentials */}
      <div className="row two">
        <div>
          <label className="tiny muted">Username</label>
          <input placeholder="admin" value={user}
            autoComplete="off"
            onChange={(e) => set({ user: e.target.value })} />
        </div>
        <div>
          <label className="tiny muted">Password</label>
          <input type="password" placeholder="••••••••" value={pass}
            autoComplete="new-password"
            onChange={(e) => set({ pass: e.target.value })} />
        </div>
      </div>

      {/* Row 5: Channel + stream type + unicast (Dahua NVR only) */}
      <div className="row two">
        <div>
          <label className="tiny muted">Channel number</label>
          <input type="number" min={1} max={64} value={channel} style={{ width: 90 }}
            onChange={(e) => set({ channel: e.target.value })} />
        </div>
        <div>
          <label className="tiny muted">Stream type</label>
          <select value={substream ? 'sub' : 'main'} onChange={(e) => set({ substream: e.target.value === 'sub' })}>
            <option value="main">Main stream (HD)</option>
            <option value="sub">Sub-stream (lower bandwidth)</option>
          </select>
        </div>
      </div>

      {/* Dahua/Amcrest NVR options */}
      {showUnicast && (
        <label className="row tiny" style={{ gap: 6 }}
          title="Add &unicast=true to the RTSP URL — helps with some Dahua NVR models that don't respond on multicast">
          <input type="checkbox" checked={unicast}
            onChange={(e) => set({ unicast: e.target.checked })} />
          Add <code>&amp;unicast=true</code> (try this if stream times out)
        </label>
      )}

      {/* Custom path */}
      {brand === 'custom' && (
        <div>
          <label className="tiny muted">Custom stream path</label>
          <input placeholder="e.g. /live/ch01  or  /cam/realmonitor?channel=1&subtype=0"
            value={customPath} onChange={(e) => set({ customPath: e.target.value })} />
        </div>
      )}

      {/* Generated URL preview */}
      <div style={{ background: 'rgba(0,0,0,.18)', borderRadius: 6, padding: '8px 10px' }}>
        <label className="tiny muted">Generated RTSP URL</label>
        <code className="tiny mono" style={{ wordBreak: 'break-all', display: 'block', marginTop: 2 }}>
          {generatedUrl || <span className="muted">— fill in the fields above —</span>}
        </code>
      </div>

      {/* Test connection button */}
      <div>
        <button
          type="button"
          className="btn ghost"
          disabled={!host || testState === 'loading'}
          onClick={testConnection}
          title="Run a step-by-step network diagnostic from the server (ping, port, RTSP, stream)."
        >
          {testState === 'loading'
            ? <><Loader size={13} style={{ animation: 'spin 1s linear infinite' }} /> Diagnosing…</>
            : <><Wifi size={13} /> Test Connection</>}
        </button>
      </div>

      {/* Diagnostic results panel */}
      {testResult && (
        <div style={{
          background: 'rgba(0,0,0,.22)',
          borderRadius: 8,
          padding: '12px 14px',
          border: `1px solid ${testResult.ok ? 'rgba(28,217,164,.4)' : 'rgba(255,94,126,.3)'}`,
        }}>
          {/* Summary line */}
          <div style={{ display: 'flex', gap: 7, marginBottom: 10, alignItems: 'flex-start' }}>
            <StepIcon ok={testResult.ok} />
            <span className="tiny" style={{
              color: testResult.ok ? 'var(--ok)' : 'var(--bad)',
              fontWeight: 700, lineHeight: 1.4,
            }}>
              {testResult.message}
            </span>
          </div>

          {/* Per-step rows */}
          {(testResult.steps || []).map((s, i) => (
            <div key={i} style={{ display: 'flex', gap: 7, marginBottom: 5, alignItems: 'flex-start' }}>
              <StepIcon ok={s.ok} />
              <div className="tiny" style={{ lineHeight: 1.4 }}>
                <span style={{ opacity: 0.5, marginRight: 4 }}>{STEP_LABELS[s.step] ?? s.step}:</span>
                <span>{s.msg}</span>
              </div>
            </div>
          ))}

          {/* Hint for auth failure */}
          {!testResult.ok && (testResult.steps || []).some(
            (s) => s.step === 'stream' && s.msg?.toLowerCase().includes('auth')
          ) && (
            <div className="tiny muted" style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid rgba(255,255,255,.1)' }}>
              💡 For Dahua NVRs: use the NVR admin credentials (not the camera's credentials).
              If the password contains special characters like <code>#</code> or <code>@</code> they are handled automatically.
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// ── StreamTestButton ─────────────────────────────────────────────────────────
function StreamTestButton({ url, token }) {
  const [show, setShow] = useState(false);
  const [key, setKey]   = useState(0);
  if (!url) return null;
  const src = `${url}${url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`;
  return (
    <div>
      <button
        type="button"
        className="btn ghost"
        title="Open a quick test stream preview to verify the URL is reachable."
        onClick={() => { setKey((k) => k + 1); setShow((s) => !s); }}
      >
        {show ? <EyeOff size={13} /> : <Eye size={13} />}
        {show ? 'Hide Preview' : 'Test Stream'}
      </button>
      {show && (
        <div style={{ marginTop: 6 }}>
          <img
            key={key}
            src={apiPath(src)}
            alt="stream preview"
            style={{ maxWidth: '100%', maxHeight: 200, borderRadius: 6, display: 'block' }}
            onError={(e) => { e.target.alt = '⚠ Could not load stream – check URL and credentials.'; }}
          />
        </div>
      )}
    </div>
  );
}

// ── Main CamerasPage component ──────────────────────────────────────────────
export default function CamerasPage() {
  const { token } = useAuth();
  const [rows, setRows]             = useState([]);
  const [health, setHealth]         = useState({});
  const [saving, setSaving]         = useState({});
  const [layout, setLayout]         = useState(16);
  const [toast, setToast]           = useState('');
  const [error, setError]           = useState('');
  const [pageLoading, setPageLoading] = useState(true);  // true until first load completes
  const [newCamera, setNewCamera]   = useState(defaultNewCamera);
  const [showAdvNew, setShowAdvNew] = useState(false);
  const toastTimerRef = useRef(null);

  function showToast(msg) {
    setToast(msg);
    if (toastTimerRef.current) clearTimeout(toastTimerRef.current);
    toastTimerRef.current = setTimeout(() => setToast(''), 4000);
  }

  async function load() {
    const [cams, layoutRes, healthRes] = await Promise.all([
      request('/api/v1/cameras', { token }),
      request('/api/v1/cameras/layout', { token }),
      request('/api/v1/live/stream_health', { token }),
    ]);
    setRows(cams.items || []);
    setLayout(layoutRes.max_live_cameras || 16);
    setHealth(healthRes.items || {});
  }

  useEffect(() => {
    load()
      .catch((err) => setError(err.message || 'Failed to load cameras'))
      .finally(() => setPageLoading(false));
    const timer = setInterval(() => {
      request('/api/v1/live/stream_health', { token })
        .then((res) => setHealth(res.items || {}))
        .catch(() => {});
    }, 5000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function patchCamera(id, patch) {
    setSaving((s) => ({ ...s, [id]: true }));
    try {
      await request(`/api/v1/cameras/${id}`, { token, method: 'PATCH', body: patch });
      showToast(`Camera ${id} updated.`);
      await load();
    } catch (err) {
      setError(err.message || 'Update failed');
    } finally {
      setSaving((s) => ({ ...s, [id]: false }));
    }
  }

  async function removeCamera(id) {
    if (!window.confirm(`Delete camera ${id}?`)) return;
    try {
      await request(`/api/v1/cameras/${id}`, { token, method: 'DELETE' });
      showToast('Camera deleted.');
      await load();
    } catch (err) {
      setError(err.message || 'Delete failed');
    }
  }

  async function createCamera() {
    const needsSource = newCamera.type !== 'browser';

    // For RTSP cameras, build the source URL from the structured IP form
    let source = newCamera.source.trim();
    if (newCamera.type === 'rtsp') {
      const ip = newCamera._ip;
      const host = ip.viaNvr ? ip.nvrIp : ip.cameraIp;
      source = buildBrandRtspUrl({
        brand: ip.brand, host, port: ip.port,
        user: ip.user, pass: ip.pass,
        channel: Number(ip.channel) || 1, substream: ip.substream,
        customPath: ip.customPath, unicast: ip.unicast,
      });
    }

    if (!newCamera.name.trim() || (needsSource && !source)) {
      setError(newCamera.type === 'rtsp'
        ? 'Camera name and IP/host are required.'
        : needsSource ? 'Camera name and source URL are required.' : 'Camera name is required.');
      return;
    }

    try {
      await request('/api/v1/cameras', {
        token,
        method: 'POST',
        body: {
          name:           newCamera.name,
          type:           newCamera.type,
          source:         newCamera.type === 'browser' ? (source || 'browser') : source,
          location:       newCamera.location || null,
          enabled:        newCamera.enabled,
          live_view:      newCamera.live_view,
          detector_mode:  newCamera.detector_mode,
          save_clip:      newCamera.save_clip,
          clip_seconds:   newCamera.clip_seconds,
          onvif_xaddr:    newCamera.onvif_xaddr    || null,
          onvif_username: newCamera.onvif_username || null,
          onvif_password: newCamera.onvif_password || null,
          onvif_profile:  newCamera.onvif_profile  || null,
        },
      });
      showToast('Camera added.');
      setNewCamera(defaultNewCamera);
      setShowAdvNew(false);
      await load();
    } catch (err) {
      setError(err.message || 'Create camera failed');
    }
  }

  async function saveLayout() {
    try {
      await request('/api/v1/cameras/layout', {
        token, method: 'POST',
        body: { max_live_cameras: Number(layout) || 16 },
      });
      showToast('Live layout setting saved.');
    } catch (err) {
      setError(err.message || 'Save layout failed');
    }
  }

  // ── health helper ──────────────────────────────────────────────────────────
  function healthBadge(cam) {
    if (!cam.enabled) return <span className="tag muted">disabled</span>;
    if (cam.type === 'browser') {
      const h = health[cam.id];
      if (h?.reason) return <span className="tag warn" title={h.reason}>offline</span>;
      return cam.browser_online
        ? <span className="tag ok"><Wifi size={11} /> online</span>
        : <span className="tag bad"><WifiOff size={11} /> offline</span>;
    }
    const h = health[cam.id];
    if (!h) return <span className="tag muted">no data</span>;
    if (h.reason) return <span className="tag bad" title={h.reason}><WifiOff size={11} /> offline</span>;
    if (typeof h.age !== 'number') return <span className="tag muted">unknown</span>;
    if (h.age <= 3)  return <span className="tag ok"><Wifi size={11} /> live ({Math.round(h.age)}s)</span>;
    if (h.age <= 10) return <span className="tag warn"><RefreshCw size={11} /> slow ({Math.round(h.age)}s)</span>;
    return <span className="tag bad"><WifiOff size={11} /> stale ({Math.round(h.age)}s)</span>;
  }

  const sourcePlaceholder =
    newCamera.type === 'rtsp'      ? 'rtsp://user:pass@192.168.1.100:554/Streaming/Channels/101' :
    newCamera.type === 'http_mjpeg'? 'http://192.168.1.100/video.mjpg' :
    newCamera.type === 'webcam'    ? '0  (device index)' :
    newCamera.type === 'browser'   ? 'Leave blank for phone/browser capture' :
                                     'Source URL or path';

  if (pageLoading) return <LoadingState rows={4} message="Loading cameras…" />;
  if (error && rows.length === 0) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => load().catch(() => {})} />;

  return (
    <div className="stack">
      {error   ? <div className="alert error"   onClick={() => setError('')}>{error}</div>   : null}
      {toast   ? <div className="alert success">{toast}</div>                                 : null}

      {/* ── Global live limit ─────────────────────────────────────────────── */}
      <div className="panel glass toolbar between">
        <div>
          <h3>Global Live Limit</h3>
          <p className="tiny muted">How many cameras can be rendered at once in Live DVR.</p>
        </div>
        <div className="row">
          <input
            title="Maximum camera tiles shown in Live DVR."
            type="number" min={1} max={64}
            value={layout}
            onChange={(e) => setLayout(e.target.value)}
            style={{ width: 90 }}
          />
          <button className="btn primary" onClick={saveLayout}><Save size={15} /> Save</button>
        </div>
      </div>

      {/* ── Add camera ────────────────────────────────────────────────────── */}
      <div className="panel glass stack">
        <div className="panel-head"><h3>Add Camera</h3></div>
        <div className="row two">
          <input
            title="Friendly name shown across dashboards and events."
            placeholder="Name  e.g. Front Gate"
            value={newCamera.name}
            onChange={(e) => setNewCamera((c) => ({ ...c, name: e.target.value }))}
          />
          <select
            title="Camera input type."
            value={newCamera.type}
            onChange={(e) => setNewCamera((c) => ({ ...c, type: e.target.value, source: '' }))}
          >
            <option value="rtsp">RTSP  (IP camera / DVR / NVR)</option>
            <option value="http_mjpeg">HTTP MJPEG  (IP camera / webcam server)</option>
            <option value="webcam">Webcam  (local USB / built-in)</option>
            <option value="browser">Browser  (phone / tablet)</option>
            <option value="upload">Upload  (manual image/video)</option>
          </select>
        </div>

        {newCamera.type === 'rtsp' ? (
          <IpCameraForm
            token={token}
            value={newCamera._ip}
            onChange={(ip) => setNewCamera((c) => ({ ...c, _ip: ip }))}
          />
        ) : (
          <div className="stack" style={{ gap: 4 }}>
            <input
              title="Full stream URL for HTTP sources, or device index for webcam."
              placeholder={sourcePlaceholder}
              value={newCamera.source}
              onChange={(e) => setNewCamera((c) => ({ ...c, source: e.target.value }))}
            />
            {newCamera.type === 'http_mjpeg' && newCamera.source && (
              <StreamTestButton
                url={`/stream/preview?source=${encodeURIComponent(newCamera.source)}`}
                token={token}
              />
            )}
          </div>
        )}

        <div className="row two">
          <input
            title="Optional physical location label."
            placeholder="Location  e.g. Main entrance"
            value={newCamera.location}
            onChange={(e) => setNewCamera((c) => ({ ...c, location: e.target.value }))}
          />
          <select
            title="Detection pipeline mode."
            value={newCamera.detector_mode}
            onChange={(e) => setNewCamera((c) => ({ ...c, detector_mode: e.target.value }))}
          >
            <DetectorModeOptions inheritLabel="inherit (use global setting)" />
          </select>
        </div>

        <div className="row">
          <label className="tiny row" title="Enable this camera.">
            <input type="checkbox" checked={newCamera.enabled}
              onChange={(e) => setNewCamera((c) => ({ ...c, enabled: e.target.checked }))} />
            Enabled
          </label>
          <label className="tiny row" title="Show in Live DVR grid.">
            <input type="checkbox" checked={newCamera.live_view}
              onChange={(e) => setNewCamera((c) => ({ ...c, live_view: e.target.checked }))} />
            Live view
          </label>
          <label className="tiny row" title="Record MP4 clips on detection.">
            <input type="checkbox" checked={newCamera.save_clip}
              onChange={(e) => setNewCamera((c) => ({
                ...c,
                save_clip: e.target.checked,
                clip_seconds: e.target.checked ? (c.clip_seconds || DEFAULT_CLIP_SECONDS) : c.clip_seconds,
              }))} />
            Save clip
          </label>
          {newCamera.save_clip ? (
            <span className="tiny muted">Default clip length: {DEFAULT_CLIP_MINUTES} minute</span>
          ) : null}
        </div>

        {/* ── ONVIF / PTZ optional fields ─────────────────────────────────── */}
        <button
          type="button"
          className="btn ghost"
          style={{ alignSelf: 'flex-start' }}
          onClick={() => setShowAdvNew((s) => !s)}
          title="Expand ONVIF PTZ settings for this camera."
        >
          {showAdvNew ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
          ONVIF / PTZ settings (optional)
        </button>

        {showAdvNew && (
          <div className="row two" style={{ background: 'rgba(0,0,0,.15)', borderRadius: 6, padding: 10 }}>
            <input
              placeholder="ONVIF xAddr  e.g. http://192.168.1.100/onvif/device_service"
              title="ONVIF device service endpoint for PTZ control and profile resolution."
              value={newCamera.onvif_xaddr}
              onChange={(e) => setNewCamera((c) => ({ ...c, onvif_xaddr: e.target.value }))}
            />
            <input
              placeholder="ONVIF username"
              title="Username for ONVIF authentication."
              value={newCamera.onvif_username}
              onChange={(e) => setNewCamera((c) => ({ ...c, onvif_username: e.target.value }))}
            />
            <input
              placeholder="ONVIF password"
              type="password"
              title="Password for ONVIF authentication."
              value={newCamera.onvif_password}
              onChange={(e) => setNewCamera((c) => ({ ...c, onvif_password: e.target.value }))}
            />
            <input
              placeholder="ONVIF profile token (from Discovery)"
              title="Profile token returned by ONVIF profile resolution."
              value={newCamera.onvif_profile}
              onChange={(e) => setNewCamera((c) => ({ ...c, onvif_profile: e.target.value }))}
            />
          </div>
        )}

        <div>
          <button
            className="btn primary"
            onClick={() => createCamera().catch((err) => setError(err.message || 'Create camera failed'))}
          >
            <Plus size={15} /> Add Camera
          </button>
        </div>
      </div>

      {/* ── Camera list ───────────────────────────────────────────────────── */}
      <div className="panel glass">
        <div className="panel-head"><h3>Camera Control  ({rows.length})</h3></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name / Location</th>
                <th>Type</th>
                <th>Source</th>
                <th>Enabled</th>
                <th>Live</th>
                <th>Detector</th>
                <th>Status</th>
                <th>Save Clip</th>
                <th>Min</th>
                <th>Preview</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((cam) => (
                <CameraRow
                  key={cam.id}
                  cam={cam}
                  token={token}
                  saving={!!saving[cam.id]}
                  healthBadge={healthBadge(cam)}
                  health={health[cam.id]}
                  onPatch={(patch) => patchCamera(cam.id, patch)}
                  onDelete={() => removeCamera(cam.id)}
                />
              ))}
              {!rows.length && (
                <tr><td colSpan={12} className="empty">No cameras yet. Add one above.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ── Quick-reference: common RTSP URL patterns ───────────────────── */}
      <div className="panel glass stack">
        <div className="panel-head"><h3>Common RTSP URL Patterns</h3></div>
        <div className="tiny muted" style={{ lineHeight: 1.8 }}>
          <table style={{ width: '100%', fontSize: '0.82em' }}>
            <thead><tr><th style={{textAlign:'left'}}>Brand</th><th style={{textAlign:'left'}}>Main stream URL pattern</th></tr></thead>
            <tbody>
              <tr><td>Hikvision / most DVRs</td><td><code>rtsp://user:pass@IP:554/Streaming/Channels/101</code></td></tr>
              <tr><td>Hikvision sub-stream</td><td><code>rtsp://user:pass@IP:554/Streaming/Channels/102</code></td></tr>
              <tr><td>Dahua</td><td><code>rtsp://user:pass@IP:554/cam/realmonitor?channel=1&amp;subtype=0</code></td></tr>
              <tr><td>Reolink</td><td><code>rtsp://user:pass@IP:554//h264Preview_01_main</code></td></tr>
              <tr><td>Axis</td><td><code>rtsp://user:pass@IP/axis-media/media.amp</code></td></tr>
              <tr><td>Amcrest / Annke</td><td><code>rtsp://user:pass@IP:554/cam/realmonitor?channel=1&amp;subtype=0</code></td></tr>
              <tr><td>Generic / unknown</td><td>Use ONVIF Discovery page → Resolve RTSP to get exact URL</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Single camera table row ──────────────────────────────────────────────────
function CameraRow({ cam, token, saving, healthBadge, onPatch, onDelete }) {
  const [showONVIF, setShowONVIF] = useState(false);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(() => toCameraDraft(cam));
  const secureCaptureUrl = toSecureCaptureUrl(cam.capture_url);

  useEffect(() => {
    setDraft(toCameraDraft(cam));
  }, [cam]);

  async function saveEdit() {
    const payload = buildCameraPatchPayload(draft);
    await onPatch(payload);
    setEditing(false);
    setShowONVIF(false);
  }

  function cancelEdit() {
    setDraft(toCameraDraft(cam));
    setEditing(false);
  }

  return (
    <>
      <tr>
        <td className="mono">{cam.id}</td>
        <td>
          {editing ? (
            <div className="stack" style={{ gap: 6 }}>
              <input
                value={draft.name}
                onChange={(e) => setDraft((s) => ({ ...s, name: e.target.value }))}
                placeholder="Camera name"
              />
              <input
                value={draft.location}
                onChange={(e) => setDraft((s) => ({ ...s, location: e.target.value }))}
                placeholder="Location"
              />
            </div>
          ) : (
            <>
              <div>{cam.name}</div>
              {cam.location && <div className="tiny muted">{cam.location}</div>}
            </>
          )}
        </td>
        <td className="tiny">
          {editing ? (
            <select value={draft.type} onChange={(e) => setDraft((s) => ({ ...s, type: e.target.value }))}>
              <option value="rtsp">rtsp</option>
              <option value="http_mjpeg">http_mjpeg</option>
              <option value="webcam">webcam</option>
              <option value="browser">browser</option>
              <option value="upload">upload</option>
            </select>
          ) : (
            cam.type
          )}
        </td>
        <td className="tiny mono" style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title={editing ? draft.source : cam.source}>
          {editing ? (
            <input
              value={draft.source}
              onChange={(e) => setDraft((s) => ({ ...s, source: e.target.value }))}
              placeholder={draft.type === 'browser' ? 'browser (optional)' : 'Camera source'}
            />
          ) : (
            cam.source
          )}
        </td>
        <td>
          {editing ? (
            <input
              type="checkbox"
              checked={draft.enabled}
              onChange={(e) => setDraft((s) => ({ ...s, enabled: e.target.checked }))}
            />
          ) : (
            <input
              type="checkbox"
              checked={cam.enabled}
              disabled={saving}
              title="Enable or disable this camera."
              onChange={(e) => onPatch({ enabled: e.target.checked })}
            />
          )}
        </td>
        <td>
          {editing ? (
            <input
              type="checkbox"
              checked={draft.live_view}
              onChange={(e) => setDraft((s) => ({ ...s, live_view: e.target.checked }))}
            />
          ) : (
            <input
              type="checkbox"
              checked={cam.live_view}
              disabled={saving}
              title="Show in Live DVR grid."
              onChange={(e) => onPatch({ live_view: e.target.checked })}
            />
          )}
        </td>
        <td>
          {editing ? (
            <select
              value={draft.detector_mode}
              onChange={(e) => setDraft((s) => ({ ...s, detector_mode: e.target.value }))}
            >
              <DetectorModeOptions />
            </select>
          ) : (
            <select
              value={cam.detector_mode}
              disabled={saving}
              title="Per-camera detection mode."
              onChange={(e) => onPatch({ detector_mode: e.target.value })}
            >
              <DetectorModeOptions />
            </select>
          )}
        </td>
        <td>{healthBadge}</td>
        <td>
          {editing ? (
            <input
              type="checkbox"
              checked={!!draft.save_clip}
              onChange={(e) => setDraft((s) => ({ ...s, save_clip: e.target.checked }))}
            />
          ) : (
            <input
              type="checkbox"
              checked={!!cam.save_clip}
              disabled={saving}
              title="Enable MP4 clip recording on detection."
              onChange={(e) => onPatch({
                save_clip: e.target.checked,
                clip_seconds: e.target.checked ? (cam.clip_seconds || DEFAULT_CLIP_SECONDS) : cam.clip_seconds,
              })}
            />
          )}
        </td>
        <td>
          {editing ? (
            <input
              type="number" min={0} max={30} step={0.5} style={{ width: 70 }}
              value={secondsToMinutes(draft.clip_seconds)}
              onChange={(e) => setDraft((s) => ({ ...s, clip_seconds: minutesToSeconds(e.target.value) }))}
            />
          ) : (
            <input
              type="number" min={0} max={30} step={0.5} style={{ width: 70 }}
              value={secondsToMinutes(cam.clip_seconds)}
              disabled={saving}
              title="Detection clip duration in minutes."
              onChange={(e) => onPatch({ clip_seconds: minutesToSeconds(e.target.value) || 0 })}
            />
          )}
        </td>
        <td>
          {cam.enabled ? (
            <div className="camera-preview-cell">
              <img
                className="tiny-stream"
                src={apiPath(`${cam.stream_url}${cam.stream_url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`)}
                alt={`${cam.name} stream`}
                loading="lazy"
              />
            </div>
          ) : (
            <span className="tiny muted">disabled</span>
          )}
        </td>
        <td>
          <div className="row" style={{ gap: 4 }}>
            {editing ? (
              <>
                <button
                  className="btn primary"
                  disabled={saving}
                  onClick={() => saveEdit().catch(() => {})}
                  title="Save camera updates."
                >
                  <Save size={13} /> Save
                </button>
                <button className="btn ghost" disabled={saving} onClick={cancelEdit} title="Cancel edit mode.">
                  Cancel
                </button>
              </>
            ) : (
              <button
                className="btn ghost"
                disabled={saving}
                onClick={() => { setEditing(true); setShowONVIF(true); }}
                title="Edit camera settings."
              >
                Edit
              </button>
            )}
            <a
              className="btn"
              href={apiPath(`${cam.stream_url}${cam.stream_url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`)}
              target="_blank"
              rel="noreferrer"
              title="Open raw stream in new tab."
            >
              <ExternalLink size={13} /> Stream
            </a>
            {cam.capture_url
              ? <a className="btn" href={cam.capture_url} target="_blank" rel="noreferrer" title="Open browser-camera capture page."><Play size={13} /> Run Camera</a>
              : null}
            {cam.capture_url && secureCaptureUrl && secureCaptureUrl !== cam.capture_url
              ? <a className="btn primary" href={secureCaptureUrl} target="_blank" rel="noreferrer" title="Open secure browser-camera capture page (HTTPS)."><Play size={13} /> Secure</a>
              : null}
            {(cam.onvif_xaddr || editing)
              ? <button className="btn ghost" title="Toggle ONVIF settings." onClick={() => setShowONVIF((s) => !s)}>
                  {showONVIF ? <ChevronUp size={13} /> : <ChevronDown size={13} />} ONVIF
                </button>
              : null}
            <button
              className="btn ghost"
              title="Delete this camera."
              onClick={() => onDelete().catch(() => {})}
              disabled={saving}
            >
              <Trash2 size={13} />
            </button>
          </div>
        </td>
      </tr>
      {showONVIF && (
        <tr>
          <td colSpan={12}>
            <div className="stack" style={{ background: 'rgba(0,0,0,.15)', borderRadius: 6, padding: 10, gap: 6 }}>
              <strong className="tiny">ONVIF Settings for camera {cam.id}</strong>
              {editing ? (
                <div className="row two">
                  <input
                    placeholder="ONVIF xAddr"
                    value={draft.onvif_xaddr}
                    onChange={(e) => setDraft((s) => ({ ...s, onvif_xaddr: e.target.value }))}
                  />
                  <input
                    placeholder="ONVIF profile token"
                    value={draft.onvif_profile}
                    onChange={(e) => setDraft((s) => ({ ...s, onvif_profile: e.target.value }))}
                  />
                  <input
                    placeholder="ONVIF username"
                    value={draft.onvif_username}
                    onChange={(e) => setDraft((s) => ({ ...s, onvif_username: e.target.value }))}
                  />
                  <input
                    placeholder="ONVIF password (leave blank to keep existing)"
                    type="password"
                    value={draft.onvif_password}
                    onChange={(e) => setDraft((s) => ({ ...s, onvif_password: e.target.value }))}
                  />
                </div>
              ) : (
                <>
                  <div className="row two">
                    <div>
                      <label className="tiny muted">xAddr</label>
                      <code className="tiny mono">{cam.onvif_xaddr || '—'}</code>
                    </div>
                    <div>
                      <label className="tiny muted">Profile</label>
                      <code className="tiny mono">{cam.onvif_profile || '—'}</code>
                    </div>
                  </div>
                  <div className="tiny muted">Use Edit mode to update ONVIF credentials and profile.</div>
                </>
              )}
              {editing ? (
                <div className="row two">
                  <input
                    type="number"
                    min={1}
                    step={0.1}
                    placeholder="Scan interval (s)"
                    value={draft.scan_interval}
                    onChange={(e) => setDraft((s) => ({ ...s, scan_interval: Number(e.target.value) || 1 }))}
                  />
                  <input
                    type="number"
                    min={0}
                    step={0.1}
                    placeholder="Cooldown (s)"
                    value={draft.cooldown_seconds}
                    onChange={(e) => setDraft((s) => ({ ...s, cooldown_seconds: Number(e.target.value) || 0 }))}
                  />
                  <input
                    type="number"
                    min={0}
                    step={1}
                    placeholder="Live order"
                    value={draft.live_order}
                    onChange={(e) => setDraft((s) => ({ ...s, live_order: Number(e.target.value) || 0 }))}
                  />
                </div>
              ) : null}
            </div>
          </td>
        </tr>
      )}
    </>
  );
}
