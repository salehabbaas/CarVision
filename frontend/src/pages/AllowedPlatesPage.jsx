import { useEffect, useState } from 'react';
import { Plus, Save, Trash2 } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';
import SortableHeader from '../components/admin/SortableHeader';
import CollapsibleToolbar from '../components/admin/CollapsibleToolbar';
import TablePagination from '../components/admin/TablePagination';
import { compareTableValues, useTableSorting } from '../hooks/useTableSorting';

export default function AllowedPlatesPage() {
  const { token } = useAuth();
  const [rows, setRows] = useState([]);
  const [newPlate, setNewPlate] = useState('');
  const [newLabel, setNewLabel] = useState('');
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [pageLoading, setPageLoading] = useState(true);
  const [tableSearch, setTableSearch] = useState('');
  const [activeFilter, setActiveFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

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

  const filteredRows = rows.filter((row) => {
    const query = tableSearch.trim().toLowerCase();
    const matchesSearch = !query || [row.plate_text, row.label].filter(Boolean).some((value) => String(value).toLowerCase().includes(query));
    const matchesActive =
      activeFilter === 'all' ||
      (activeFilter === 'active' && row.active) ||
      (activeFilter === 'inactive' && !row.active);
    return matchesSearch && matchesActive;
  });

  const { sortKey, sortDirection, sortedRows, requestSort } = useTableSorting(filteredRows, {
    initialKey: 'id',
    sorters: {
      id: (a, b) => compareTableValues(a.id, b.id),
      plate_text: (a, b) => compareTableValues(a.plate_text, b.plate_text),
      label: (a, b) => compareTableValues(a.label, b.label),
      active: (a, b) => compareTableValues(a.active, b.active),
    },
  });
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const pagedRows = sortedRows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [tableSearch, activeFilter]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  if (pageLoading) return <LoadingState rows={3} message="Loading allowed plates…" />;
  if (error && rows.length === 0) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => { setPageLoading(true); load().catch(e => setError(e.message)).finally(() => setPageLoading(false)); }} />;

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <CollapsibleToolbar title="Plate Filters & Add" summary="Filters and create controls are collapsed by default.">
        <input
          title="Filter allowed plates by plate text or label."
          placeholder="Filter plates or labels"
          value={tableSearch}
          onChange={(e) => setTableSearch(e.target.value)}
        />
        <select
          title="Filter allowed plates by active state."
          value={activeFilter}
          onChange={(e) => setActiveFilter(e.target.value)}
        >
          <option value="all">All states</option>
          <option value="active">Active only</option>
          <option value="inactive">Inactive only</option>
        </select>
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
      </CollapsibleToolbar>

      <div className="panel glass">
        <div className="panel-head"><h3>Allowed Plates</h3><span className="tiny muted">{sortedRows.length} shown</span></div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><SortableHeader label="ID" sortKey="id" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Plate" sortKey="plate_text" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Label" sortKey="label" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Active" sortKey="active" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((r) => (
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
              {!sortedRows.length && <tr><td colSpan={5} className="empty">No plates match the current filters.</td></tr>}
            </tbody>
          </table>
        </div>
        <TablePagination
          page={page}
          totalPages={totalPages}
          totalItems={sortedRows.length}
          pageSize={pageSize}
          currentCount={pagedRows.length}
          itemLabel="plates"
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>
    </div>
  );
}
