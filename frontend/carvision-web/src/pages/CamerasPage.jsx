import { useEffect, useState } from 'react';
import { Save, Plus, Trash2, ExternalLink } from 'lucide-react';
import { request, apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';

const defaultNewCamera = {
  name: '',
  type: 'rtsp',
  source: '',
  location: '',
  enabled: true,
  live_view: true,
  detector_mode: 'inherit',
};

export default function CamerasPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState([]);
  const [health, setHealth] = useState({});
  const [saving, setSaving] = useState({});
  const [layout, setLayout] = useState(16);
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [newCamera, setNewCamera] = useState(defaultNewCamera);

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
    load().catch((err) => setError(err.message || 'Failed to load cameras'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function patchCamera(id, patch) {
    setSaving((s) => ({ ...s, [id]: true }));
    try {
      await request(`/api/v1/cameras/${id}`, {
        token,
        method: 'PATCH',
        body: patch,
      });
      setToast(`Camera ${id} updated.`);
      await load();
    } finally {
      setSaving((s) => ({ ...s, [id]: false }));
    }
  }

  async function removeCamera(id) {
    if (!window.confirm(`Delete camera ${id}?`)) return;
    await request(`/api/v1/cameras/${id}`, {
      token,
      method: 'DELETE',
    });
    setToast('Camera deleted.');
    await load();
  }

  async function createCamera() {
    if (!newCamera.name.trim() || !newCamera.source.trim()) {
      setError('Camera name and source are required.');
      return;
    }
    await request('/api/v1/cameras', {
      token,
      method: 'POST',
      body: {
        ...newCamera,
        location: newCamera.location || null,
      },
    });
    setToast('Camera added.');
    setNewCamera(defaultNewCamera);
    await load();
  }

  async function saveLayout() {
    await request('/api/v1/cameras/layout', {
      token,
      method: 'POST',
      body: { max_live_cameras: Number(layout) || 16 },
    });
    setToast('Live layout setting saved.');
  }

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass toolbar between">
        <div>
          <h3>Global Live Limit</h3>
          <p className="tiny muted">How many cameras can be rendered at once in live view.</p>
        </div>
        <div className="row">
          <input type="number" min={1} max={64} value={layout} onChange={(e) => setLayout(e.target.value)} style={{ width: 90 }} />
          <button className="btn primary" onClick={() => saveLayout().catch((err) => setError(err.message || 'Save failed'))}><Save size={15} /> Save</button>
        </div>
      </div>

      <div className="panel glass">
        <div className="panel-head"><h3>Add Camera</h3></div>
        <div className="row two">
          <input placeholder="Name" value={newCamera.name} onChange={(e) => setNewCamera((c) => ({ ...c, name: e.target.value }))} />
          <select value={newCamera.type} onChange={(e) => setNewCamera((c) => ({ ...c, type: e.target.value }))}>
            <option value="rtsp">rtsp</option>
            <option value="http_mjpeg">http_mjpeg</option>
            <option value="webcam">webcam</option>
            <option value="browser">browser</option>
            <option value="upload">upload</option>
          </select>
          <input placeholder="Source (rtsp/http url/index/browser)" value={newCamera.source} onChange={(e) => setNewCamera((c) => ({ ...c, source: e.target.value }))} />
          <input placeholder="Location" value={newCamera.location} onChange={(e) => setNewCamera((c) => ({ ...c, location: e.target.value }))} />
          <select value={newCamera.detector_mode} onChange={(e) => setNewCamera((c) => ({ ...c, detector_mode: e.target.value }))}>
            <option value="inherit">inherit</option>
            <option value="auto">auto</option>
            <option value="contour">contour</option>
            <option value="yolo">yolo</option>
          </select>
          <div className="row">
            <label className="tiny row"><input type="checkbox" checked={newCamera.enabled} onChange={(e) => setNewCamera((c) => ({ ...c, enabled: e.target.checked }))} /> enabled</label>
            <label className="tiny row"><input type="checkbox" checked={newCamera.live_view} onChange={(e) => setNewCamera((c) => ({ ...c, live_view: e.target.checked }))} /> live view</label>
            <button className="btn primary" onClick={() => createCamera().catch((err) => setError(err.message || 'Create camera failed'))}><Plus size={15} /> Add Camera</button>
          </div>
        </div>
      </div>

      <div className="panel glass">
        <div className="panel-head"><h3>Camera Control</h3></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Name</th>
                <th>Type</th>
                <th>Enabled</th>
                <th>Live</th>
                <th>Detector</th>
                <th>Online</th>
                <th>Preview</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((cam) => (
                <tr key={cam.id}>
                  <td className="mono">{cam.id}</td>
                  <td>{cam.name}</td>
                  <td>{cam.type}</td>
                  <td><input type="checkbox" checked={cam.enabled} disabled={saving[cam.id]} onChange={(e) => patchCamera(cam.id, { enabled: e.target.checked }).catch((err) => setError(err.message || 'Update failed'))} /></td>
                  <td><input type="checkbox" checked={cam.live_view} disabled={saving[cam.id]} onChange={(e) => patchCamera(cam.id, { live_view: e.target.checked }).catch((err) => setError(err.message || 'Update failed'))} /></td>
                  <td>
                    <select value={cam.detector_mode} disabled={saving[cam.id]} onChange={(e) => patchCamera(cam.id, { detector_mode: e.target.value }).catch((err) => setError(err.message || 'Update failed'))}>
                      <option value="inherit">inherit</option>
                      <option value="auto">auto</option>
                      <option value="contour">contour</option>
                      <option value="yolo">yolo</option>
                    </select>
                  </td>
                  <td>
                    {cam.browser_online == null ? '-' : <span className={`tag ${cam.browser_online ? 'ok' : 'bad'}`}>{cam.browser_online ? 'online' : 'offline'}</span>}
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
                        <div className="tiny muted">
                          {typeof health?.[cam.id]?.age === 'number'
                            ? health[cam.id].age <= 5
                              ? 'live'
                              : `stale ${Math.round(health[cam.id].age)}s`
                            : 'no signal'}
                        </div>
                      </div>
                    ) : (
                      <span className="tiny muted">disabled</span>
                    )}
                  </td>
                  <td>
                    <div className="row">
                      <a className="btn" href={apiPath(`${cam.stream_url}${cam.stream_url.includes('?') ? '&' : '?'}token=${encodeURIComponent(token)}`)} target="_blank" rel="noreferrer"><ExternalLink size={14} /> Stream</a>
                      {cam.capture_url ? <a className="btn" href={apiPath(cam.capture_url)} target="_blank" rel="noreferrer">Run Camera</a> : null}
                      <button className="btn ghost" onClick={() => removeCamera(cam.id).catch((err) => setError(err.message || 'Delete failed'))}><Trash2 size={14} /></button>
                    </div>
                  </td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={9} className="empty">No cameras.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
