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
} from '../modules/cameraEditor';
import FormField   from '../design-system/components/FormField';
import Input       from '../design-system/components/Input';
import Select      from '../design-system/components/Select';
import Checkbox    from '../design-system/components/Checkbox';
import Button      from '../design-system/components/Button';
import Alert       from '../design-system/components/Alert';
import FormSection from '../design-system/components/FormSection';
import FormModal   from '../design-system/components/FormModal';
import CollapsibleToolbar from '../components/admin/CollapsibleToolbar';
import SortableHeader from '../components/admin/SortableHeader';
import TablePagination from '../components/admin/TablePagination';
import { compareTableValues, useTableSorting } from '../hooks/useTableSorting';

// ── Defaults ────────────────────────────────────────────────────────────────
const defaultNewCamera = {
  name:          '',
  type:          'rtsp',
  source:        '',
  location:      '',
  model:         '',
  enabled:       true,
  live_view:     true,
  detector_mode: 'inherit',
  save_clip:     false,
  clip_seconds:  0,
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
  const [newCameraOpen, setNewCameraOpen] = useState(false);
  const [tableSearch, setTableSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
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
          model:          newCamera.model || null,
          enabled:        newCamera.enabled,
          live_view:      newCamera.live_view,
          detector_mode:  newCamera.detector_mode,
          save_clip:      newCamera.save_clip,
          clip_seconds:   0,
          onvif_xaddr:    newCamera.onvif_xaddr    || null,
          onvif_username: newCamera.onvif_username || null,
          onvif_password: newCamera.onvif_password || null,
          onvif_profile:  newCamera.onvif_profile  || null,
        },
      });
      showToast('Camera added.');
      setNewCamera(defaultNewCamera);
      setShowAdvNew(false);
      setNewCameraOpen(false);
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

  const filteredRows = rows.filter((cam) => {
    const query = tableSearch.trim().toLowerCase();
    const matchesSearch =
      !query ||
      [cam.id, cam.name, cam.location, cam.type, cam.source].some((value) => String(value ?? '').toLowerCase().includes(query));
    const matchesType = typeFilter === 'all' || cam.type === typeFilter;
    return matchesSearch && matchesType;
  });

  const { sortKey, sortDirection, sortedRows, requestSort } = useTableSorting(filteredRows, {
    initialKey: 'id',
    sorters: {
      id: (a, b) => compareTableValues(a.id, b.id),
      name: (a, b) => compareTableValues(a.name, b.name),
      type: (a, b) => compareTableValues(a.type, b.type),
      enabled: (a, b) => compareTableValues(a.enabled, b.enabled),
      live_view: (a, b) => compareTableValues(a.live_view, b.live_view),
      detector_mode: (a, b) => compareTableValues(a.detector_mode, b.detector_mode),
    },
  });
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const pagedRows = sortedRows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [tableSearch, typeFilter]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  if (pageLoading) return <LoadingState rows={4} message="Loading cameras…" />;
  if (error && rows.length === 0) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => load().catch(() => {})} />;

  return (
    <div className="stack">
      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}
      {toast && <Alert variant="success" onDismiss={() => setToast('')}>{toast}</Alert>}

      {/* ── Global live limit ─────────────────────────────────────────────── */}
      <CollapsibleToolbar title="Live Layout" summary="Top control panels stay collapsed by default.">
        <div className="row" style={{ justifyContent: 'space-between', width: '100%', flexWrap: 'wrap' }}>
          <div>
            <div className="tiny muted">Max cameras rendered simultaneously in Live DVR.</div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <Input
              type="number" min={1} max={64}
              value={layout}
              onChange={(e) => setLayout(e.target.value)}
              style={{ width: 90 }}
            />
            <Button variant="primary" icon={<Save size={14} />} onClick={saveLayout}>Save</Button>
          </div>
        </div>
      </CollapsibleToolbar>

      <div className="panel glass" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ margin: '0 0 2px' }}>Add Camera</h3>
          <p className="tiny muted" style={{ margin: 0 }}>Create camera connections in a modal form instead of inline page chrome.</p>
        </div>
        <Button
          variant="primary"
          icon={<Plus size={14} />}
          onClick={() => setNewCameraOpen(true)}
        >
          New Camera
        </Button>
      </div>

      <FormModal
        open={newCameraOpen}
        onClose={() => setNewCameraOpen(false)}
        title="Add Camera"
        subtitle="Create a new camera source and connection profile"
        size="xl"
        submitLabel="Add Camera"
        onSubmitClick={() => createCamera().catch((err) => setError(err.message || 'Create camera failed'))}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <FormSection title="Identity">
            <div className="ds-grid-2">
              <FormField label="Name" required>
                <Input
                  placeholder="e.g. Front Gate"
                  value={newCamera.name}
                  onChange={(e) => setNewCamera((c) => ({ ...c, name: e.target.value }))}
                />
              </FormField>
              <FormField label="Type">
                <Select
                  value={newCamera.type}
                  onChange={(e) => setNewCamera((c) => ({ ...c, type: e.target.value, source: '' }))}
                >
                  <option value="rtsp">RTSP  (IP camera / DVR / NVR)</option>
                  <option value="http_mjpeg">HTTP MJPEG  (IP camera / webcam server)</option>
                  <option value="webcam">Webcam  (local USB / built-in)</option>
                  <option value="browser">Browser  (phone / tablet)</option>
                  <option value="upload">Upload  (manual image/video)</option>
                </Select>
              </FormField>
              <FormField label="Location" hint="Optional physical label">
                <Input
                  placeholder="e.g. Main entrance"
                  value={newCamera.location}
                  onChange={(e) => setNewCamera((c) => ({ ...c, location: e.target.value }))}
                />
              </FormField>
              <FormField label="Model" hint="Optional camera model name">
                <Input
                  placeholder="e.g. Hikvision DS-2CD2143G2-I"
                  value={newCamera.model}
                  onChange={(e) => setNewCamera((c) => ({ ...c, model: e.target.value }))}
                />
              </FormField>
              <FormField label="Detector mode">
                <Select
                  value={newCamera.detector_mode}
                  onChange={(e) => setNewCamera((c) => ({ ...c, detector_mode: e.target.value }))}
                >
                  <DetectorModeOptions inheritLabel="inherit (use global setting)" />
                </Select>
              </FormField>
            </div>
          </FormSection>

          <FormSection title="Connection">
            {newCamera.type === 'rtsp' ? (
              <IpCameraForm
                token={token}
                value={newCamera._ip}
                onChange={(ip) => setNewCamera((c) => ({ ...c, _ip: ip }))}
              />
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                <FormField label="Source URL / device index">
                  <Input
                    placeholder={sourcePlaceholder}
                    value={newCamera.source}
                    onChange={(e) => setNewCamera((c) => ({ ...c, source: e.target.value }))}
                  />
                </FormField>
                {newCamera.type === 'http_mjpeg' && newCamera.source && (
                  <StreamTestButton
                    url={`/stream/preview?source=${encodeURIComponent(newCamera.source)}`}
                    token={token}
                  />
                )}
              </div>
            )}
          </FormSection>

          <FormSection title="Options">
            <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap' }}>
              <Checkbox
                checked={newCamera.enabled}
                onChange={(e) => setNewCamera((c) => ({ ...c, enabled: e.target.checked }))}
                label="Enabled"
              />
              <Checkbox
                checked={newCamera.live_view}
                onChange={(e) => setNewCamera((c) => ({ ...c, live_view: e.target.checked }))}
                label="Show in Live DVR"
              />
              <Checkbox
                checked={newCamera.save_clip}
                onChange={(e) => setNewCamera((c) => ({ ...c, save_clip: e.target.checked, clip_seconds: 0 }))}
                label="Save clip"
                hint="Manual start/stop from Live view"
              />
            </div>
          </FormSection>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            icon={showAdvNew ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
            style={{ alignSelf: 'flex-start' }}
            onClick={() => setShowAdvNew((s) => !s)}
          >
            ONVIF / PTZ settings (optional)
          </Button>

          {showAdvNew && (
            <FormSection title="ONVIF / PTZ">
              <div className="ds-grid-2">
                <FormField label="ONVIF xAddr" hint="Device service endpoint">
                  <Input
                    placeholder="http://192.168.1.100/onvif/device_service"
                    value={newCamera.onvif_xaddr}
                    onChange={(e) => setNewCamera((c) => ({ ...c, onvif_xaddr: e.target.value }))}
                  />
                </FormField>
                <FormField label="ONVIF username">
                  <Input
                    placeholder="admin"
                    value={newCamera.onvif_username}
                    onChange={(e) => setNewCamera((c) => ({ ...c, onvif_username: e.target.value }))}
                  />
                </FormField>
                <FormField label="ONVIF password">
                  <Input
                    type="password"
                    placeholder="••••••••"
                    value={newCamera.onvif_password}
                    onChange={(e) => setNewCamera((c) => ({ ...c, onvif_password: e.target.value }))}
                  />
                </FormField>
                <FormField label="ONVIF profile token" hint="From Discovery page">
                  <Input
                    placeholder="Profile_1"
                    value={newCamera.onvif_profile}
                    onChange={(e) => setNewCamera((c) => ({ ...c, onvif_profile: e.target.value }))}
                  />
                </FormField>
              </div>
            </FormSection>
          )}
        </div>
      </FormModal>

      <CollapsibleToolbar title="Camera Filters" summary="Filter controls are collapsed by default.">
        <input
          title="Filter cameras by id, name, location, type, or source."
          placeholder="Filter cameras"
          value={tableSearch}
          onChange={(e) => setTableSearch(e.target.value)}
        />
        <select title="Filter cameras by source type." value={typeFilter} onChange={(e) => setTypeFilter(e.target.value)}>
          <option value="all">All types</option>
          <option value="rtsp">RTSP</option>
          <option value="http_mjpeg">HTTP MJPEG</option>
          <option value="webcam">Webcam</option>
          <option value="browser">Browser</option>
          <option value="upload">Upload</option>
        </select>
      </CollapsibleToolbar>

      {/* ── Camera list ───────────────────────────────────────────────────── */}
      <div className="panel glass">
        <div className="panel-head">
          <h3>Camera Control  ({sortedRows.length})</h3>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><SortableHeader label="ID" sortKey="id" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Name / Location" sortKey="name" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Type" sortKey="type" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Source</th>
                <th><SortableHeader label="Enabled" sortKey="enabled" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Live" sortKey="live_view" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Detector" sortKey="detector_mode" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Status</th>
                <th>Save Clip</th>
                <th>Preview</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((cam) => (
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
              {!sortedRows.length && (
                <tr><td colSpan={11} className="empty">No cameras match the current filters.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <TablePagination
          page={page}
          totalPages={totalPages}
          totalItems={sortedRows.length}
          pageSize={pageSize}
          currentCount={pagedRows.length}
          itemLabel="cameras"
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>

    </div>
  );
}

// ── Single camera table row ──────────────────────────────────────────────────
function CameraRow({ cam, token, saving, healthBadge, onPatch, onDelete }) {
  const [editOpen, setEditOpen] = useState(false);
  const [draft, setDraft] = useState(() => toCameraDraft(cam));
  const secureCaptureUrl = toSecureCaptureUrl(cam.capture_url);

  useEffect(() => {
    setDraft(toCameraDraft(cam));
  }, [cam]);

  async function saveEdit() {
    const payload = buildCameraPatchPayload(draft);
    await onPatch(payload);
    setEditOpen(false);
  }

  function cancelEdit() {
    setDraft(toCameraDraft(cam));
    setEditOpen(false);
  }

  return (
    <>
      <tr>
        <td className="mono">{cam.id}</td>
        <td>
          <>
            <div>{cam.name}</div>
            {cam.location && <div className="tiny muted">{cam.location}</div>}
            {cam.model && <div className="tiny muted">{cam.model}</div>}
          </>
        </td>
        <td className="tiny">{cam.type}</td>
        <td className="tiny mono" style={{ maxWidth: 180, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}
          title={cam.source}>
          {cam.source}
        </td>
        <td>
          <input
            type="checkbox"
            checked={cam.enabled}
            disabled={saving}
            title="Enable or disable this camera."
            onChange={(e) => onPatch({ enabled: e.target.checked })}
          />
        </td>
        <td>
          <input
            type="checkbox"
            checked={cam.live_view}
            disabled={saving}
            title="Show in Live DVR grid."
            onChange={(e) => onPatch({ live_view: e.target.checked })}
          />
        </td>
        <td>
          <select
            value={cam.detector_mode}
            disabled={saving}
            title="Per-camera detection mode."
            onChange={(e) => onPatch({ detector_mode: e.target.value })}
          >
            <DetectorModeOptions />
          </select>
        </td>
        <td>{healthBadge}</td>
        <td>
          <input
            type="checkbox"
            checked={!!cam.save_clip}
            disabled={saving}
            title="Enable manual MP4 recording from Live view."
            onChange={(e) => onPatch({ save_clip: e.target.checked, clip_seconds: 0 })}
          />
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
            <button
              className="btn ghost"
              disabled={saving}
              onClick={() => setEditOpen(true)}
              title="Edit camera settings."
            >
              Edit
            </button>
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
      <FormModal
        open={editOpen}
        onClose={cancelEdit}
        title={`Edit Camera #${cam.id}`}
        subtitle="Update camera settings in a dedicated modal"
        size="xl"
        submitLabel="Save Changes"
        onSubmitClick={() => saveEdit().catch(() => {})}
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <FormSection title="Identity">
            <div className="ds-grid-2">
              <FormField label="Name" required>
                <Input
                  placeholder="Camera name"
                  value={draft.name}
                  onChange={(e) => setDraft((s) => ({ ...s, name: e.target.value }))}
                />
              </FormField>
              <FormField label="Type">
                <Select value={draft.type} onChange={(e) => setDraft((s) => ({ ...s, type: e.target.value }))}>
                  <option value="rtsp">RTSP</option>
                  <option value="http_mjpeg">HTTP MJPEG</option>
                  <option value="webcam">Webcam</option>
                  <option value="browser">Browser</option>
                  <option value="upload">Upload</option>
                </Select>
              </FormField>
              <FormField label="Location">
                <Input
                  placeholder="Location"
                  value={draft.location}
                  onChange={(e) => setDraft((s) => ({ ...s, location: e.target.value }))}
                />
              </FormField>
              <FormField label="Model">
                <Input
                  placeholder="Camera model"
                  value={draft.model || ''}
                  onChange={(e) => setDraft((s) => ({ ...s, model: e.target.value }))}
                />
              </FormField>
              <FormField label="Detector mode">
                <Select
                  value={draft.detector_mode}
                  onChange={(e) => setDraft((s) => ({ ...s, detector_mode: e.target.value }))}
                >
                  <DetectorModeOptions />
                </Select>
              </FormField>
              <FormField label="Source">
                <Input
                  placeholder={draft.type === 'browser' ? 'browser (optional)' : 'Camera source'}
                  value={draft.source}
                  onChange={(e) => setDraft((s) => ({ ...s, source: e.target.value }))}
                />
              </FormField>
            </div>
          </FormSection>

          <FormSection title="Flags">
            <div className="ds-grid-2">
              <FormField label="Enabled">
                <Checkbox
                  checked={draft.enabled}
                  onCheckedChange={(checked) => setDraft((s) => ({ ...s, enabled: Boolean(checked) }))}
                  label="Camera is active"
                />
              </FormField>
              <FormField label="Live view">
                <Checkbox
                  checked={draft.live_view}
                  onCheckedChange={(checked) => setDraft((s) => ({ ...s, live_view: Boolean(checked) }))}
                  label="Show in Live DVR"
                />
              </FormField>
              <FormField label="Save clip">
                <Checkbox
                  checked={!!draft.save_clip}
                  onCheckedChange={(checked) => setDraft((s) => ({ ...s, save_clip: Boolean(checked) }))}
                  label="Enable manual clip recording"
                />
              </FormField>
              <FormField label="Live order">
                <Input
                  type="number"
                  min={0}
                  step={1}
                  value={draft.live_order}
                  onChange={(e) => setDraft((s) => ({ ...s, live_order: Number(e.target.value) || 0 }))}
                />
              </FormField>
              <FormField label="Scan interval (s)">
                <Input
                  type="number"
                  min={0.1}
                  step={0.1}
                  value={draft.scan_interval}
                  onChange={(e) => setDraft((s) => ({ ...s, scan_interval: Number(e.target.value) || 1 }))}
                />
              </FormField>
              <FormField label="Cooldown (s)">
                <Input
                  type="number"
                  min={0}
                  step={0.1}
                  value={draft.cooldown_seconds}
                  onChange={(e) => setDraft((s) => ({ ...s, cooldown_seconds: Number(e.target.value) || 0 }))}
                />
              </FormField>
            </div>
          </FormSection>

          <FormSection title="ONVIF">
            <div className="ds-grid-2">
              <FormField label="ONVIF xAddr">
                <Input
                  placeholder="http://camera/onvif/device_service"
                  value={draft.onvif_xaddr}
                  onChange={(e) => setDraft((s) => ({ ...s, onvif_xaddr: e.target.value }))}
                />
              </FormField>
              <FormField label="ONVIF profile token">
                <Input
                  placeholder="Profile_1"
                  value={draft.onvif_profile}
                  onChange={(e) => setDraft((s) => ({ ...s, onvif_profile: e.target.value }))}
                />
              </FormField>
              <FormField label="ONVIF username">
                <Input
                  placeholder="Username"
                  value={draft.onvif_username}
                  onChange={(e) => setDraft((s) => ({ ...s, onvif_username: e.target.value }))}
                />
              </FormField>
              <FormField label="ONVIF password" hint="Leave blank to keep existing password">
                <Input
                  type="password"
                  placeholder="••••••••"
                  value={draft.onvif_password}
                  onChange={(e) => setDraft((s) => ({ ...s, onvif_password: e.target.value }))}
                />
              </FormField>
            </div>
          </FormSection>
        </div>
      </FormModal>
    </>
  );
}
