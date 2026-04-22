import { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { CheckCircle2, ChevronLeft, ChevronRight, MessageSquareMore, RefreshCw, Search, Wrench, Trash2 } from 'lucide-react';
import { request, mediaPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';
import { Link, useSearchParams } from 'react-router-dom';
import Modal      from '../design-system/components/Modal';
import FormField  from '../design-system/components/FormField';
import Select     from '../design-system/components/Select';
import Input      from '../design-system/components/Input';
import Textarea   from '../design-system/components/Textarea';
import Button     from '../design-system/components/Button';
import FormModal  from '../design-system/components/FormModal';
import CollapsibleToolbar from '../components/admin/CollapsibleToolbar';
import SortableHeader from '../components/admin/SortableHeader';
import TablePagination from '../components/admin/TablePagination';
import { compareTableValues, useTableSorting } from '../hooks/useTableSorting';

function badgeClass(status) {
  if (status === 'allowed') return 'ok';
  if (status === 'denied') return 'bad';
  return 'muted';
}

function feedbackClass(row) {
  if (row?.sample?.ignored) return 'muted';
  if (row?.sample?.annotated) return 'ok';
  return 'bad';
}

function feedbackLabel(row) {
  if (row?.sample?.ignored) return 'Ignored';
  if (row?.sample?.annotated) return 'Annotated';
  return 'Pending';
}

const DEBUG_STEP_ORDER = [
  { key: 'color', label: 'Color Crop' },
  { key: 'bw', label: 'Threshold' },
  { key: 'gray', label: 'Gray' },
  { key: 'edged', label: 'Edges' },
  { key: 'mask', label: 'Mask' },
];

export default function DetectionsPage() {
  const { token } = useAuth();
  const [searchParams] = useSearchParams();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);  // true on mount — data hasn't arrived yet
  const [error, setError] = useState('');
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [feedback, setFeedback] = useState('');
  const [trained, setTrained] = useState('');
  const [cameraFilter, setCameraFilter] = useState('');
  const [selected, setSelected] = useState({});
  const [toast, setToast] = useState('');
  const [busyDebug, setBusyDebug] = useState({});
  const [busyReprocess, setBusyReprocess] = useState({});
  const [busyDelete, setBusyDelete] = useState({});
  const [bulkReprocessBusy, setBulkReprocessBusy] = useState(false);
  const [bulkDeleteBusy, setBulkDeleteBusy] = useState(false);
  const [debugPreview, setDebugPreview] = useState({ open: false, steps: [], index: 0, title: '' });

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkMode, setBulkMode] = useState('correct');
  const [bulkExpected, setBulkExpected] = useState('');
  const [bulkNotes, setBulkNotes] = useState('');

  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [feedbackRow, setFeedbackRow] = useState(null);
  const [feedbackMode, setFeedbackMode] = useState('correct');
  const [feedbackExpected, setFeedbackExpected] = useState('');
  const [feedbackNotes, setFeedbackNotes] = useState('');
  const [feedbackInitial, setFeedbackInitial] = useState({ mode: 'correct', expected: '', notes: '' });
  const [createdSampleId, setCreatedSampleId] = useState(null);
  const [focusedRowId, setFocusedRowId] = useState(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  const focusDetectionId = useMemo(() => {
    const raw = searchParams.get('detection_id');
    const num = Number(raw);
    return Number.isFinite(num) && num > 0 ? num : null;
  }, [searchParams]);

  async function load() {
    setLoading(true);
    setError('');
    try {
      const params = new URLSearchParams({ limit: '250' });
      if (q) params.set('q', q);
      if (status) params.set('status', status);
      if (feedback) params.set('feedback', feedback);
      if (trained) params.set('trained', trained);
      const res = await request(`/api/v1/detections?${params.toString()}`, { token });
      setItems(res.items || []);
    } catch (err) {
      setError(err.message || 'Failed to load detections');
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, feedback, trained]);

  useEffect(() => {
    if (!focusDetectionId) return;
    const exists = items.some((row) => row.id === focusDetectionId);
    if (!exists) return;
    setSelected((prev) => ({ ...prev, [focusDetectionId]: true }));
    setFocusedRowId(focusDetectionId);
    const node = document.getElementById(`detection-row-${focusDetectionId}`);
    if (node) {
      node.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
    const timer = setTimeout(() => setFocusedRowId(null), 5000);
    return () => clearTimeout(timer);
  }, [focusDetectionId, items]);

  const cameraOptions = useMemo(
    () => Array.from(new Set(items.map((row) => row.camera_name).filter(Boolean))).sort((a, b) => a.localeCompare(b)),
    [items]
  );
  const filteredItems = useMemo(
    () => items.filter((row) => !cameraFilter || row.camera_name === cameraFilter),
    [items, cameraFilter]
  );
  const { sortKey, sortDirection, sortedRows, requestSort } = useTableSorting(filteredItems, {
    initialKey: 'detected_at',
    initialDirection: 'desc',
    sorters: {
      id: (a, b) => compareTableValues(a.id, b.id),
      detected_at: (a, b) => compareTableValues(a.detected_at, b.detected_at),
      plate_text: (a, b) => compareTableValues(a.plate_text, b.plate_text),
      status: (a, b) => compareTableValues(a.status, b.status),
      confidence: (a, b) => compareTableValues(a.confidence, b.confidence),
      camera_name: (a, b) => compareTableValues(a.camera_name, b.camera_name),
    },
  });
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const pagedRows = useMemo(() => sortedRows.slice((page - 1) * pageSize, page * pageSize), [sortedRows, page, pageSize]);
  const visibleIds = useMemo(() => pagedRows.map((row) => row.id), [pagedRows]);
  const selectedIds = useMemo(
    () => Object.keys(selected).filter((id) => selected[id]).map((id) => Number(id)),
    [selected]
  );
  const targetIds = selectedIds.length ? selectedIds : visibleIds;
  const feedbackRowIndex = useMemo(
    () => (feedbackRow ? items.findIndex((row) => row.id === feedbackRow.id) : -1),
    [feedbackRow, items]
  );
  const feedbackHasPrev = feedbackRowIndex > 0;
  const feedbackHasNext = feedbackRowIndex >= 0 && feedbackRowIndex < items.length - 1;
  const feedbackDebugSteps = useMemo(() => {
    if (!feedbackRow?.debug_steps?.length) return [];
    return feedbackRow.debug_steps;
  }, [feedbackRow]);
  const feedbackDebugGrid = useMemo(() => {
    const byKey = new Map(feedbackDebugSteps.map((step) => [step.key, step]));
    return DEBUG_STEP_ORDER.map((entry) => ({ ...entry, step: byKey.get(entry.key) || null }));
  }, [feedbackDebugSteps]);
  const feedbackDirty =
    feedbackMode !== feedbackInitial.mode ||
    (feedbackExpected || '') !== (feedbackInitial.expected || '') ||
    (feedbackNotes || '') !== (feedbackInitial.notes || '');

  useEffect(() => {
    setPage(1);
  }, [cameraFilter, status, feedback, trained, items.length]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  function toggleAll(v) {
    const next = { ...selected };
    visibleIds.forEach((id) => {
      next[id] = v;
    });
    setSelected(next);
  }

  async function bulkReprocess() {
    if (!targetIds.length) return;
    if (!window.confirm(`Reprocess ${targetIds.length} detection(s)?`)) return;
    setBulkReprocessBusy(true);
    try {
      const res = await request('/api/v1/detections/bulk/reprocess', {
        token,
        method: 'POST',
        body: { detection_ids: targetIds },
      });
      setToast(`Reprocessed ${res.processed} events${res.failed ? `, failed ${res.failed}` : ''}.`);
      await load();
    } catch (err) {
      setError(err.message || 'Bulk reprocess failed');
    } finally {
      setBulkReprocessBusy(false);
    }
  }

  async function reprocessOne(id) {
    setBusyReprocess((prev) => ({ ...prev, [id]: true }));
    try {
      await request(`/api/v1/detections/${id}/reprocess`, {
        token,
        method: 'POST',
      });
      setToast(`Detection #${id} reprocessed.`);
      await load();
    } catch (err) {
      setError(err.message || 'Reprocess failed');
    } finally {
      setBusyReprocess((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function regenerateDebug(id) {
    setBusyDebug((prev) => ({ ...prev, [id]: true }));
    try {
      await request(`/api/v1/detections/${id}/debug/regenerate`, {
        token,
        method: 'POST',
      });
      setToast(`Debug steps regenerated for #${id}.`);
      await load();
    } catch (err) {
      setError(err.message || 'Debug regeneration failed');
    } finally {
      setBusyDebug((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function deleteOne(id) {
    if (!window.confirm(`Delete detection #${id}?`)) return;
    setBusyDelete((prev) => ({ ...prev, [id]: true }));
    try {
      await request(`/api/v1/detections/${id}`, {
        token,
        method: 'DELETE',
      });
      setToast(`Detection #${id} deleted.`);
      await load();
    } catch (err) {
      setError(err.message || 'Delete failed');
    } finally {
      setBusyDelete((prev) => ({ ...prev, [id]: false }));
    }
  }

  async function bulkDelete() {
    if (!targetIds.length) return;
    if (!window.confirm(`Delete ${targetIds.length} detection(s)?`)) return;
    setBulkDeleteBusy(true);
    try {
      const res = await request('/api/v1/detections/bulk/delete', {
        token,
        method: 'POST',
        body: { detection_ids: targetIds },
      });
      setToast(`Deleted ${res.deleted} events${res.failed ? `, failed ${res.failed}` : ''}.`);
      setSelected({});
      await load();
    } catch (err) {
      setError(err.message || 'Bulk delete failed');
    } finally {
      setBulkDeleteBusy(false);
    }
  }

  async function saveBulkFeedback(e) {
    e.preventDefault();
    if (!targetIds.length) return;
    try {
      const res = await request('/api/v1/detections/bulk/feedback', {
        token,
        method: 'POST',
        body: {
          detection_ids: targetIds,
          mode: bulkMode,
          expected_plate: bulkMode === 'corrected' ? bulkExpected : null,
          notes: bulkNotes,
        },
      });
      setToast(`Feedback saved for ${res.processed} events.`);
      setBulkOpen(false);
      setBulkNotes('');
      setBulkExpected('');
      await load();
    } catch (err) {
      setError(err.message || 'Bulk feedback failed');
    }
  }

  function openFeedback(row) {
    const mode = row.feedback_status || 'correct';
    const expected = row.plate_text || '';
    const notes = row.feedback_note || '';
    setFeedbackRow(row);
    setFeedbackMode(mode);
    setFeedbackExpected(expected);
    setFeedbackNotes(notes);
    setFeedbackInitial({ mode, expected, notes });
    setCreatedSampleId(null);
    setFeedbackOpen(true);
  }

  function navigateFeedback(delta) {
    if (!feedbackRow) return;
    const idx = items.findIndex((row) => row.id === feedbackRow.id);
    if (idx < 0) return;
    const nextIdx = idx + delta;
    if (nextIdx < 0 || nextIdx >= items.length) return;
    if (feedbackDirty) {
      const confirmed = window.confirm('You have unsaved feedback changes. Move to another detection anyway?');
      if (!confirmed) return;
    }
    openFeedback(items[nextIdx]);
  }

  async function saveFeedback(e) {
    e.preventDefault();
    if (!feedbackRow?.id) return;
    try {
      const res = await request(`/api/v1/detections/${feedbackRow.id}/feedback`, {
        token,
        method: 'POST',
        body: {
          mode: feedbackMode,
          expected_plate: feedbackMode === 'corrected' ? feedbackExpected : null,
          notes: feedbackNotes || null,
        },
      });
      setCreatedSampleId(res.sample_id || null);
      setToast(`Feedback saved for detection #${feedbackRow.id}.`);
      await load();
    } catch (err) {
      setError(err.message || 'Feedback save failed');
    }
  }

  useEffect(() => {
    if (!feedbackOpen || !feedbackRow) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
      const tag = String(event.target?.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
      event.preventDefault();
      navigateFeedback(event.key === 'ArrowRight' ? 1 : -1);
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [feedbackOpen, feedbackRow, items, feedbackDirty]);

  function openDebugPreview(row, startIndex = 0) {
    const steps = row?.debug_steps || [];
    if (!steps.length) return;
    setDebugPreview({
      open: true,
      steps,
      index: Math.max(0, Math.min(startIndex, steps.length - 1)),
      title: `Detection #${row.id}`,
    });
  }

  // Show loading skeleton on initial load (items empty + loading)
  if (loading && items.length === 0) return <LoadingState rows={5} message="Loading detections…" />;

  // Show full-page error only if we have no data at all
  if (error && items.length === 0) {
    return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={load} />;
  }

  return (
    <div className="stack">
      {error ? <div className="alert error">{error} <button className="btn ghost" style={{ marginLeft: 8 }} onClick={load}>Retry</button></div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <CollapsibleToolbar title="Detection Filters" summary="Search and filter controls are collapsed by default.">
        <div className="search-wrap">
          <Search size={16} />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search plate/camera/location"
            title="Search detections by plate text, camera name, or location."
          />
        </div>
        <select title="Filter detections by allow/deny decision status." value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All status</option>
          <option value="allowed">Allowed</option>
          <option value="denied">Denied</option>
        </select>
        <select title="Filter by feedback workflow state." value={feedback} onChange={(e) => setFeedback(e.target.value)}>
          <option value="">All feedback</option>
          <option value="annotated">Annotated</option>
          <option value="pending">Pending</option>
          <option value="ignored">Ignored</option>
        </select>
        <select title="Filter by whether detection sample has been used for training." value={trained} onChange={(e) => setTrained(e.target.value)}>
          <option value="">All training</option>
          <option value="trained">Trained</option>
          <option value="not_trained">Not trained</option>
        </select>
        <select title="Filter detections by camera name in the current result set." value={cameraFilter} onChange={(e) => setCameraFilter(e.target.value)}>
          <option value="">All cameras</option>
          {cameraOptions.map((camera) => (
            <option key={camera} value={camera}>{camera}</option>
          ))}
        </select>
        <button className="btn" onClick={load}>Filter</button>
      </CollapsibleToolbar>

      <div className="panel glass">
        <div className="panel-head">
          <h3>Detection Events</h3>
          <div className="row">
            <span className="tiny">
              Selected: {selectedIds.length} • Filtered: {sortedRows.length}
            </span>
            <button className="btn" onClick={() => setBulkOpen(true)} disabled={!targetIds.length}>
              <CheckCircle2 size={15} /> Bulk Feedback
            </button>
            <button className="btn" onClick={bulkReprocess} disabled={!targetIds.length || bulkReprocessBusy}>
              <RefreshCw size={15} className={bulkReprocessBusy ? 'spin' : ''} />
              {bulkReprocessBusy ? 'Reprocessing...' : 'Bulk Reprocess'}
            </button>
            <button className="btn ghost" onClick={bulkDelete} disabled={!targetIds.length || bulkDeleteBusy}>
              <Trash2 size={15} className={bulkDeleteBusy ? 'spin' : ''} />
              {bulkDeleteBusy ? 'Deleting...' : 'Bulk Delete'}
            </button>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><input title="Select or unselect all detections on the current page." type="checkbox" onChange={(e) => toggleAll(e.target.checked)} /></th>
                <th><SortableHeader label="ID" sortKey="id" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Snapshot</th>
                <th><SortableHeader label="Time" sortKey="detected_at" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Plate" sortKey="plate_text" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Status" sortKey="status" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Conf" sortKey="confidence" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Camera" sortKey="camera_name" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Debug</th>
                <th>Feedback</th>
                <th>Train</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((row) => (
                <motion.tr
                  key={row.id}
                  id={`detection-row-${row.id}`}
                  className={focusedRowId === row.id ? 'selected-row detection-row-focus' : ''}
                  initial={{ opacity: 0 }}
                  animate={{ opacity: 1 }}
                  onClick={(e) => {
                    const interactive = e.target.closest('button,a,input,textarea,select,label');
                    if (interactive) return;
                    setSelected((prev) => ({ ...prev, [row.id]: !prev[row.id] }));
                  }}
                >
                  <td>
                    <input
                      type="checkbox"
                      className="big-check"
                      title="Select this detection for bulk actions."
                      checked={Boolean(selected[row.id])}
                      onChange={(e) =>
                        setSelected((prev) => ({ ...prev, [row.id]: e.target.checked }))
                      }
                    />
                  </td>
                  <td className="mono">{row.id}</td>
                  <td>
                    {row.image_path ? (
                      <button type="button" className="unstyled-btn" onClick={() => openDebugPreview(row, 0)}>
                        <img className="tiny-thumb" src={mediaPath(row.image_path)} alt={`det-${row.id}`} />
                      </button>
                    ) : (
                      <span className="tiny muted">-</span>
                    )}
                  </td>
                  <td className="mono small">
                    {row.detected_at ? new Date(row.detected_at).toLocaleString() : '-'}
                  </td>
                  <td>{row.plate_text}</td>
                  <td>
                    <span className={`tag ${badgeClass(row.status)}`}>{row.status}</span>
                  </td>
                  <td>{Math.round((row.confidence || 0) * 100)}%</td>
                  <td>{row.camera_name}</td>
                  <td>
                    <div className="row">
                      {row.debug_steps?.map((step, idx) => (
                        <button
                          type="button"
                          key={`${row.id}-${step.key}`}
                          className="tiny-link btn-link"
                          onClick={() => openDebugPreview(row, idx)}
                        >
                          {step.label}
                        </button>
                      ))}
                      {!row.debug_steps?.length && <span className="tiny muted">No debug</span>}
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => regenerateDebug(row.id)}
                        disabled={Boolean(busyDebug[row.id])}
                      >
                        <Wrench size={13} /> {busyDebug[row.id] ? 'Building...' : 'Build Debug'}
                      </button>
                    </div>
                  </td>
                  <td>
                    <span className={`tag ${feedbackClass(row)}`}>{feedbackLabel(row)}</span>
                  </td>
                  <td>
                    {row.sample?.trained ? (
                      <span className="tag ok">Trained</span>
                    ) : (
                      <span className="tag muted">Not trained</span>
                    )}
                  </td>
                  <td>
                    <div className="row">
                      <button type="button" className="btn" onClick={() => openFeedback(row)}>
                        <MessageSquareMore size={14} /> Feedback
                      </button>
                      <button type="button" className="btn ghost" onClick={() => reprocessOne(row.id)} disabled={Boolean(busyReprocess[row.id])}>
                        <RefreshCw size={14} className={busyReprocess[row.id] ? 'spin' : ''} />
                        {busyReprocess[row.id] ? 'Reprocessing...' : 'Reprocess'}
                      </button>
                      <button type="button" className="btn ghost" onClick={() => deleteOne(row.id)} disabled={Boolean(busyDelete[row.id])}>
                        <Trash2 size={14} className={busyDelete[row.id] ? 'spin' : ''} />
                        {busyDelete[row.id] ? 'Deleting...' : 'Delete'}
                      </button>
                    </div>
                  </td>
                </motion.tr>
              ))}
              {!sortedRows.length && (
                <tr>
                  <td colSpan={12} className="empty">
                    {loading ? 'Loading...' : 'No detections match the current filters.'}
                  </td>
                </tr>
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
          itemLabel="detections"
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>

      <FormModal
        open={bulkOpen}
        onClose={() => setBulkOpen(false)}
        title="Bulk Feedback"
        subtitle={`Apply to ${targetIds.length} event(s) — ${selectedIds.length ? 'selected' : 'all filtered'}`}
        formId="bulk-feedback-form"
        submitLabel="Save Feedback"
      >
        <form
          id="bulk-feedback-form"
          onSubmit={saveBulkFeedback}
          style={{ display: 'flex', flexDirection: 'column', gap: 14 }}
        >
          <FormField label="Mode" hint="How to label the selected detections">
            <Select value={bulkMode} onChange={(e) => setBulkMode(e.target.value)}>
              <option value="correct">Correct — OCR was right</option>
              <option value="corrected">Corrected — provide the real plate</option>
              <option value="no_plate">No Plate — false positive</option>
            </Select>
          </FormField>

          {bulkMode === 'corrected' && (
            <FormField label="Expected plate" hint="The correct plate text (ground truth)">
              <Input
                value={bulkExpected}
                onChange={(e) => setBulkExpected(e.target.value)}
                placeholder="e.g. ABC1234"
              />
            </FormField>
          )}

          <FormField label="Notes" hint="Optional comment for audit trail">
            <Textarea
              value={bulkNotes}
              onChange={(e) => setBulkNotes(e.target.value)}
              placeholder="Why was this corrected?"
              rows={3}
            />
          </FormField>
        </form>
      </FormModal>

      <FormModal
        open={feedbackOpen && !!feedbackRow}
        onClose={() => setFeedbackOpen(false)}
        size="xl"
        title={`Detection #${feedbackRow?.id} — Feedback`}
        subtitle={feedbackRow ? `${feedbackRow.plate_text || '—'}  ·  ${feedbackRow.camera_name || '—'}` : ''}
        formId="feedback-form"
        submitLabel="Save Feedback"
        cancelLabel="Close"
        footerStart={
          <>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {createdSampleId && (
                <Link className="btn" to={`/training-data?sample_id=${createdSampleId}`}>
                  Open Sample #{createdSampleId}
                </Link>
              )}
              {feedbackRow?.feedback_sample_id && !createdSampleId && (
                <Link className="btn ghost" to={`/training-data?sample_id=${feedbackRow.feedback_sample_id}`}>
                  Existing Sample
                </Link>
              )}
            </div>
          </>
        }
        footerEnd={
          <>
            <Button
              variant="ghost"
              type="button"
              icon={<ChevronLeft size={14} />}
              onClick={() => navigateFeedback(-1)}
              disabled={!feedbackHasPrev}
            >
              Prev
            </Button>
            <Button
              variant="ghost"
              type="button"
              onClick={() => navigateFeedback(1)}
              disabled={!feedbackHasNext}
            >
              Next <ChevronRight size={14} />
            </Button>
          </>
        }
      >
        {feedbackRow && (
          <form
            id="feedback-form"
            onSubmit={saveFeedback}
            style={{ display: 'flex', flexDirection: 'column', gap: 18 }}
          >
            {/* Snapshot + meta */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
              <div>
                {feedbackRow.image_path ? (
                  <button type="button" className="unstyled-btn" onClick={() => openDebugPreview(feedbackRow, 0)}>
                    <img className="preview-image" src={mediaPath(feedbackRow.image_path)} alt={`det-${feedbackRow.id}`} />
                  </button>
                ) : (
                  <div className="muted" style={{ fontSize: '0.875rem' }}>No snapshot</div>
                )}
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  <span className="tiny muted">Detected plate</span>
                  <strong style={{ fontFamily: 'var(--font-mono, monospace)', fontSize: '1.1rem' }}>
                    {feedbackRow.plate_text || '—'}
                  </strong>
                </div>
                <div style={{ display: 'flex', gap: 8 }}>
                  <span className={`tag ${feedbackClass(feedbackRow)}`}>{feedbackLabel(feedbackRow)}</span>
                  <span className="tiny muted" style={{ alignSelf: 'center' }}>
                    {feedbackRowIndex >= 0 ? `${feedbackRowIndex + 1} / ${items.length}` : ''}
                  </span>
                </div>

                <FormField label="Mode">
                  <Select value={feedbackMode} onChange={(e) => setFeedbackMode(e.target.value)}>
                    <option value="correct">Correct — OCR was right</option>
                    <option value="corrected">Corrected — provide real plate</option>
                    <option value="no_plate">No Plate — false positive</option>
                  </Select>
                </FormField>

                {feedbackMode === 'corrected' && (
                  <FormField label="Expected plate" hint="The correct ground-truth plate">
                    <Input
                      value={feedbackExpected}
                      onChange={(e) => setFeedbackExpected(e.target.value)}
                      placeholder="e.g. ABC1234"
                    />
                  </FormField>
                )}

                <FormField label="Notes">
                  <Textarea
                    value={feedbackNotes}
                    onChange={(e) => setFeedbackNotes(e.target.value)}
                    placeholder="Optional correction note"
                    rows={3}
                  />
                </FormField>
              </div>
            </div>

            {/* Debug grid */}
            {feedbackDebugGrid?.length > 0 && (
              <div>
                <div className="tiny muted" style={{ marginBottom: 8 }}>Debug steps</div>
                <div className="feedback-debug-grid">
                  {feedbackDebugGrid.map((entry) => {
                    const idx = feedbackDebugSteps.findIndex((s) => s.key === entry.key);
                    return (
                      <button
                        type="button"
                        key={`modal-${feedbackRow.id}-${entry.key}`}
                        className={`feedback-debug-card ${entry.step?.path ? '' : 'is-missing'}`}
                        onClick={() => { if (idx >= 0) openDebugPreview(feedbackRow, idx); }}
                        disabled={idx < 0}
                      >
                        <div className="tiny">{entry.label}</div>
                        {entry.step?.path ? (
                          <img src={mediaPath(entry.step.path)} alt={`${entry.label}-${feedbackRow.id}`} />
                        ) : (
                          <div className="tiny muted">Not available</div>
                        )}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
          </form>
        )}
      </FormModal>

      <Modal
        open={debugPreview.open && debugPreview.steps.length > 0}
        onClose={() => setDebugPreview((d) => ({ ...d, open: false }))}
        size="lg"
        title={`${debugPreview.title} — Debug Viewer`}
        subtitle={debugPreview.steps[debugPreview.index]?.label || ''}
        footer={
          <>
            <div style={{ display: 'flex', gap: 6, flex: 1, flexWrap: 'wrap' }}>
              {debugPreview.steps.map((step, idx) => (
                <Button
                  key={`dbg-${step.key}-${idx}`}
                  variant={idx === debugPreview.index ? 'primary' : 'ghost'}
                  size="sm"
                  onClick={() => setDebugPreview((d) => ({ ...d, index: idx }))}
                >
                  {step.label}
                </Button>
              ))}
            </div>
            <Button variant="ghost" onClick={() => setDebugPreview((d) => ({ ...d, open: false }))}>
              Close
            </Button>
          </>
        }
      >
        <img
          className="preview-image"
          src={mediaPath(debugPreview.steps[debugPreview.index]?.path)}
          alt="debug-step"
          style={{ width: '100%', borderRadius: 8 }}
        />
      </Modal>
    </div>
  );
}
