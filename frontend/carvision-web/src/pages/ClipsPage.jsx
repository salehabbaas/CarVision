import { useEffect, useMemo, useState } from 'react';
import { RefreshCw, Square, Trash2, ExternalLink } from 'lucide-react';
import { request, mediaPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';
import CollapsibleToolbar from '../components/admin/CollapsibleToolbar';
import SortableHeader from '../components/admin/SortableHeader';
import TablePagination from '../components/admin/TablePagination';
import { compareTableValues, useTableSorting } from '../hooks/useTableSorting';

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
  const [tableSearch, setTableSearch] = useState('');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const queryCameraId = useMemo(() => (cameraId === 'all' ? null : Number(cameraId)), [cameraId]);
  const queryKind = useMemo(() => (kind === 'all' ? '' : kind), [kind]);

  const filteredClips = clips.filter((clip) => {
    const query = tableSearch.trim().toLowerCase();
    if (!query) return true;
    return [
      clip.id,
      clip.camera_name,
      clip.camera_id,
      clip.kind,
      clip.file_path,
    ].some((value) => String(value ?? '').toLowerCase().includes(query));
  });

  const { sortKey, sortDirection, sortedRows, requestSort } = useTableSorting(filteredClips, {
    initialKey: 'started_at',
    initialDirection: 'desc',
    sorters: {
      id: (a, b) => compareTableValues(a.id, b.id),
      camera_name: (a, b) => compareTableValues(a.camera_name || a.camera_id, b.camera_name || b.camera_id),
      kind: (a, b) => compareTableValues(a.kind, b.kind),
      started_at: (a, b) => compareTableValues(a.started_at, b.started_at),
      duration_seconds: (a, b) => compareTableValues(a.duration_seconds, b.duration_seconds),
      detection_count: (a, b) => compareTableValues(a.detection_count, b.detection_count),
      size_bytes: (a, b) => compareTableValues(a.size_bytes, b.size_bytes),
    },
  });
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const pagedRows = sortedRows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [tableSearch, cameraId, kind]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

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
    const ids = pagedRows.map((clip) => clip.id);
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

      <CollapsibleToolbar title="Clip Filters" summary="Filter and bulk clip actions are collapsed by default.">
        <div className="row">
          <input
            title="Filter clips by camera, ID, kind, or file path."
            placeholder="Filter clips"
            value={tableSearch}
            onChange={(e) => setTableSearch(e.target.value)}
          />
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
      </CollapsibleToolbar>

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
          <span className="tiny muted">{sortedRows.length} shown</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>
                  <input
                    type="checkbox"
                    checked={pagedRows.length > 0 && pagedRows.every((clip) => selectedIds.includes(clip.id))}
                    onChange={toggleSelectAllShown}
                    title="Select all shown clips"
                  />
                </th>
                <th><SortableHeader label="ID" sortKey="id" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Camera" sortKey="camera_name" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Type" sortKey="kind" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Preview</th>
                <th><SortableHeader label="Started" sortKey="started_at" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Duration" sortKey="duration_seconds" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Detections" sortKey="detection_count" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Size" sortKey="size_bytes" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((clip) => (
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
              {!sortedRows.length ? <tr><td colSpan={10} className="empty">No clips match the current filters.</td></tr> : null}
            </tbody>
          </table>
        </div>
        <TablePagination
          page={page}
          totalPages={totalPages}
          totalItems={sortedRows.length}
          pageSize={pageSize}
          currentCount={pagedRows.length}
          itemLabel="clips"
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>
    </div>
  );
}
