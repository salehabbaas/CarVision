import { useEffect, useState } from 'react';
import { Plus, Save, Trash2 } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';

export default function AllowedPlatesPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState([]);
  const [newPlate, setNewPlate] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [pageLoading, setPageLoading] = useState(true);

  async function load() {
    const res = await request('/api/v1/allowed', { token });
    setRows((res.items || []).map((r) => ({ ...r, _dirty: false })));
  }

  useEffect(() => {
    load()
      .catch((err) => setError(err.message || 'Failed to load allowed plates'))
      .finally(() => setPageLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function createPlate() {
    if (!newPlate.trim()) return;
    await request('/api/v1/allowed', {
      token,
      method: 'POST',
      body: { plate_text: newPlate, label: newLabel || null, active: true },
    });
    setNewPlate('');
    setNewLabel('');
    setToast('Plate added.');
    await load();
  }

  async function saveRow(row) {
    await request(`/api/v1/allowed/${row.id}`, {
      token,
      method: 'PATCH',
      body: {
        plate_text: row.plate_text,
        label: row.label || null,
        active: Boolean(row.active),
      },
    });
    setToast(`Plate ${row.plate_text} saved.`);
    await load();
  }

  async function deleteRow(id) {
    if (!window.confirm('Delete this plate?')) return;
    await request(`/api/v1/allowed/${id}`, {
      token,
      method: 'DELETE',
    });
    setToast('Plate deleted.');
    await load();
  }

  if (pageLoading) return <LoadingState rows={3} message="Loading allowed plates…" />;
  if (error && rows.length === 0) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => { setPageLoading(true); load().catch(e => setError(e.message)).finally(() => setPageLoading(false)); }} />;

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass toolbar">
        <input
          title="Plate number to allow (for example ABC123)."
          placeholder="Plate"
          value={newPlate}
          onChange={(e) => setNewPlate(e.target.value)}
        />
        <input
          title="Optional label for this plate (owner, team, vehicle name)."
          placeholder="Label"
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
        />
        <button className="btn primary" onClick={() => createPlate().catch((err) => setError(err.message || 'Create failed'))}><Plus size={15} /> Add</button>
      </div>

      <div className="panel glass">
        <div className="panel-head"><h3>Allowed Plates</h3></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Plate</th>
                <th>Label</th>
                <th>Active</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id}>
                  <td className="mono">{r.id}</td>
                  <td><input title="Edit the allowed plate text." value={r.plate_text || ''} onChange={(e) => setRows((prev) => prev.map((x) => x.id === r.id ? { ...x, plate_text: e.target.value, _dirty: true } : x))} /></td>
                  <td><input title="Edit a descriptive label for this plate." value={r.label || ''} onChange={(e) => setRows((prev) => prev.map((x) => x.id === r.id ? { ...x, label: e.target.value, _dirty: true } : x))} /></td>
                  <td><input title="Enable or disable this plate without deleting it." type="checkbox" checked={Boolean(r.active)} onChange={(e) => setRows((prev) => prev.map((x) => x.id === r.id ? { ...x, active: e.target.checked, _dirty: true } : x))} /></td>
                  <td>
                    <div className="row">
                      <button className="btn" disabled={!r._dirty} onClick={() => saveRow(r).catch((err) => setError(err.message || 'Save failed'))}><Save size={14} /> Save</button>
                      <button className="btn ghost" onClick={() => deleteRow(r.id).catch((err) => setError(err.message || 'Delete failed'))}><Trash2 size={14} /> Delete</button>
                    </div>
                  </td>
                </tr>
              ))}
              {!rows.length && <tr><td colSpan={5} className="empty">No plates configured.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
