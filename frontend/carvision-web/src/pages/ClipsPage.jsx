import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Square, Trash2, ExternalLink } from 'lucide-react';
import { request, mediaPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';

export default function ClipsPage() {
  const { token } = useAuth();
  const [clips, setClips] = useState([]);
  const [active, setActive] = useState([]);
  const [cameras, setCameras] = useState([]);
  const [cameraId, setCameraId] = useState('all');
  const [kind, setKind] = useState('all');
  const [busy, setBusy] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [pageLoading, setPageLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');

  const queryCameraId = useMemo(() => (cameraId === 'all' ? null : Number(cameraId)), [cameraId]);
  const queryKind = useMemo(() => (kind === 'all' ? '' : kind), [kind]);

  async function load() {
    setBusy(true);
    try {
      const params = new URLSearchParams();
      params.set('limit', '200');
      if (queryCameraId) params.set('camera_id', String(queryCameraId));
      if (queryKind) params.set('kind', queryKind);
      const [clipsRes, activeRes, camsRes] = await Promise.all([
        request(`/api/v1/clips?${params.toString()}`, { token }),
        request('/api/v1/clips/active', { token }),
        request('/api/v1/cameras', { token }),
      ]);
      setClips(clipsRes.items || []);
      setActive(activeRes.items || []);
      setCameras(camsRes.items || []);
      setSelectedIds((prev) => prev.filter((id) => (clipsRes.items || []).some((clip) => clip.id === id)));
      setError('');
    } catch (err) {
      setError(err.message || 'Failed to load clips');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    load().catch((err) => setError(err.message || 'Failed to load clips')).finally(() => setPageLoading(false));
    const timer = setInterval(load, 4000);
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, queryCameraId, queryKind]);

  async function stopActive(camera_id) {
    setBusy(true);
    try {
      const res = await request('/api/v1/clips/stop', {
        token,
        method: 'POST',
        body: { camera_id },
      });
      setToast(`Clip saved for ${res?.item?.camera_name || `Camera ${camera_id}`}.`);
      await load();
    } catch (err) {
      setError(err.message || 'Failed to stop recording');
    } finally {
      setBusy(false);
    }
  }

  async function removeClip(clipId) {
    if (!window.confirm(`Delete clip #${clipId}?`)) return;
    setBusy(true);
    try {
      await request(`/api/v1/clips/${clipId}`, { token, method: 'DELETE' });
      setToast(`Clip #${clipId} deleted.`);
      await load();
    } catch (err) {
      setError(err.message || 'Failed to delete clip');
    } finally {
      setBusy(false);
    }
  }

  function toggleSelectClip(clipId) {
    setSelectedIds((prev) => (prev.includes(clipId) ? prev.filter((id) => id !== clipId) : [...prev, clipId]));
  }

  function toggleSelectAllShown() {
    const ids = clips.map((clip) => clip.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedIds.includes(id));
    if (allSelected) {
      setSelectedIds((prev) => prev.filter((id) => !ids.includes(id)));
    } else {
      setSelectedIds(ids);
    }
  }

  async function removeSelectedClips() {
    if (!selectedIds.length) return;
    if (!window.confirm(`Delete ${selectedIds.length} selected clip(s)?`)) return;
    setBusy(true);
    try {
      const res = await request('/api/v1/clips/bulk/delete', {
        token,
        method: 'POST',
        body: { detection_ids: selectedIds },
      });
      setToast(`Deleted ${res.deleted || 0} clip(s)${res.failed ? `, failed ${res.failed}` : ''}.`);
      setSelectedIds([]);
      await load();
    } catch (err) {
      setError(err.message || 'Failed to delete selected clips');
    } finally {
      setBusy(false);
    }
  }

  function formatTime(value) {
    if (!value) return '--';
    const dt = new Date(value);
    if (Number.isNaN(dt.getTime())) return '--';
    return dt.toLocaleString();
  }

  if (pageLoading) return <LoadingState rows={3} message="Loading clips…" />;
  if (error && !clips.length && !active.length) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => { setPageLoading(true); load().catch(e => setError(e.message)).finally(() => setPageLoading(false)); }} />;

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass toolbar between">
        <div className="row">
          <select title="Filter clips by camera." value={cameraId} onChange={(e) => setCameraId(e.target.value)}>
            <option value="all">All cameras</option>
            {cameras.map((cam) => (
              <option key={cam.id} value={cam.id}>{cam.name}</option>
            ))}
          </select>
          <select title="Filter clips by source type." value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="all">All types</option>
            <option value="manual">Manual</option>
            <option value="detection">Detection</option>
          </select>
        </div>
        <div className="row">
          <button className="btn ghost" type="button" disabled={busy || !selectedIds.length} onClick={removeSelectedClips}>
            <Trash2 size={14} /> Delete Selected ({selectedIds.length})
          </button>
          <button className="btn" type="button" disabled={busy} onClick={() => load()}>
            <RefreshCw size={14} /> Refresh
          </button>
        </div>
      </div>

      <div className="panel glass">
        <div className="panel-head">
          <h3>Active Recordings</h3>
          <span className="tag ok">{active.length}</span>
        </div>
        {active.length ? (
          <div className="clip-active-list">
            {active.map((item) => (
              <div key={item.camera_id} className="clip-active-item">
                <div>
                  <strong>{item.camera_name || `Camera ${item.camera_id}`}</strong>
                  <div className="tiny muted">Started: {formatTime(item.started_at)}</div>
                  <div className="tiny muted mono">{item.file_path}</div>
                </div>
                <button className="btn danger" type="button" disabled={busy} onClick={() => stopActive(item.camera_id)}>
                  <Square size={14} /> Stop & Save
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="empty">No active manual recordings.</div>
        )}
      </div>

      <div className="panel glass">
        <div className="panel-head">
          <h3>Saved Clips</h3>
          <span className="tiny muted">{clips.length} shown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    checked={clips.length > 0 && clips.every((clip) => selectedIds.includes(clip.id))}
                    onChange={toggleSelectAllShown}
                    title="Select all shown clips"
                  />
                </th>
                <th>ID</th>
                <th>Camera</th>
                <th>Type</th>
                <th>Preview</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Detections</th>
                <th>Size</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {clips.map((clip) => (
                <tr key={clip.id}>
                  <td>
                    <input
                      type="checkbox"
                      checked={selectedIds.includes(clip.id)}
                      onChange={() => toggleSelectClip(clip.id)}
                      title={`Select clip #${clip.id}`}
                    />
                  </td>
                  <td className="mono">{clip.id}</td>
                  <td>{clip.camera_name || `Camera ${clip.camera_id}`}</td>
                  <td><span className={`tag ${clip.kind === 'manual' ? 'ok' : 'muted'}`}>{clip.kind}</span></td>
                  <td>
                    <video className="clip-preview" src={mediaPath(clip.file_path)} controls preload="metadata" />
                  </td>
                  <td className="tiny">{formatTime(clip.started_at)}</td>
                  <td className="tiny">{Number(clip.duration_seconds || 0).toFixed(1)}s</td>
                  <td className="tiny">{clip.detection_count || 0}</td>
                  <td className="tiny">{Math.round(Number(clip.size_bytes || 0) / 1024)} KB</td>
                  <td>
                    <div className="row">
                      <a className="btn" href={mediaPath(clip.file_path)} target="_blank" rel="noreferrer">
                        <ExternalLink size={14} /> Open
                      </a>
                      <button className="btn ghost" type="button" disabled={busy} onClick={() => removeClip(clip.id)}>
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {!clips.length ? <tr><td colSpan={10} className="empty">No clips found.</td></tr> : null}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
