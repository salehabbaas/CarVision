import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';
import CollapsibleToolbar from '../components/admin/CollapsibleToolbar';
import SortableHeader from '../components/admin/SortableHeader';
import TablePagination from '../components/admin/TablePagination';
import { compareTableValues, useTableSorting } from '../hooks/useTableSorting';

function fmtDuration(seconds) {
  const val = Number(seconds || 0);
  if (!Number.isFinite(val) || val <= 0) return '-';
  const h = Math.floor(val / 3600);
  const m = Math.floor((val % 3600) / 60);
  const s = Math.floor(val % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function fmtAgo(iso) {
  if (!iso) return '-';
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return '-';
  const sec = Math.max(0, Math.floor((Date.now() - dt.getTime()) / 1000));
  return fmtDuration(sec);
}

export default function TrainedDataPage() {
  const { token } = useAuth();
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [deletingBatch, setDeletingBatch] = useState('');
  const [startingBatch, setStartingBatch] = useState('');
  const [controlBatch, setControlBatch] = useState('');
  const [error, setError] = useState('');
  const [tableSearch, setTableSearch] = useState('');
  const [jobFilter, setJobFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);

  async function loadBatches(signal) {
    setLoading(true);
    setError('');
    try {
      const res = await request('/api/v1/training/import_batches?limit=500', { token, signal });
      setItems(res.items || []);
    } catch (err) {
      if (signal?.aborted) return;
      setError(err.message || 'Failed to load imported batches');
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    loadBatches(controller.signal);
    return () => {
      controller.abort();
    };
  }, [token]);

  useEffect(() => {
    const hasRunning = items.some((row) => ['running', 'stopping'].includes(String(row.ocr_job?.status || '').toLowerCase()));
    if (!hasRunning) return;
    const timer = setInterval(() => {
      loadBatches().catch(() => {});
    }, 3000);
    return () => clearInterval(timer);
  }, [items]);

  async function deleteBatch(batch) {
    if (!batch || deletingBatch) return;
    const ok = window.confirm(`Delete imported batch "${batch}"?\nThis will remove its training samples.`);
    if (!ok) return;
    setDeletingBatch(batch);
    setError('');
    try {
      await request(`/api/v1/training/import_batches/${encodeURIComponent(batch)}`, { token, method: 'DELETE' });
      setItems((prev) => prev.filter((row) => row.batch !== batch));
    } catch (err) {
      setError(err.message || 'Failed to delete batch');
    } finally {
      setDeletingBatch('');
    }
  }

  async function startBatchReprocess(batch) {
    if (!batch || startingBatch) return;
    setStartingBatch(batch);
    setError('');
    try {
      await request(`/api/v1/training/import_batches/${encodeURIComponent(batch)}/ocr/reprocess?chunk_size=1000`, {
        token,
        method: 'POST',
      });
      await loadBatches();
    } catch (err) {
      setError(err.message || 'Failed to start OCR reprocess');
    } finally {
      setStartingBatch('');
    }
  }

  async function controlBatchJob(batch, action) {
    if (!batch || !action || controlBatch) return;
    setControlBatch(batch);
    setError('');
    try {
      await request(
        `/api/v1/training/import_batches/${encodeURIComponent(batch)}/ocr/control?action=${encodeURIComponent(action)}&chunk_size=1000`,
        { token, method: 'POST' }
      );
      await loadBatches();
    } catch (err) {
      setError(err.message || `Failed to ${action} OCR job`);
    } finally {
      setControlBatch('');
    }
  }

  const filteredItems = items.filter((row) => {
    const query = tableSearch.trim().toLowerCase();
    const status = String(row.ocr_job?.status || 'not_started').toLowerCase();
    const matchesSearch =
      !query ||
      [row.batch, row.ocr_job?.message, row.ocr_job?.error].filter(Boolean).some((value) => String(value).toLowerCase().includes(query));
    const matchesJob = jobFilter === 'all' || status === jobFilter;
    return matchesSearch && matchesJob;
  });

  const { sortKey, sortDirection, sortedRows, requestSort } = useTableSorting(filteredItems, {
    initialKey: 'updated_at',
    initialDirection: 'desc',
    sorters: {
      batch: (a, b) => compareTableValues(a.batch, b.batch),
      total: (a, b) => compareTableValues(a.total, b.total),
      annotated: (a, b) => compareTableValues(a.annotated, b.annotated),
      negatives: (a, b) => compareTableValues(a.negatives, b.negatives),
      pending: (a, b) => compareTableValues(a.pending, b.pending),
      updated_at: (a, b) => compareTableValues(a.updated_at, b.updated_at),
    },
  });
  const totalPages = Math.max(1, Math.ceil(sortedRows.length / pageSize));
  const pagedRows = sortedRows.slice((page - 1) * pageSize, page * pageSize);

  useEffect(() => {
    setPage(1);
  }, [tableSearch, jobFilter]);

  useEffect(() => {
    setPage((current) => Math.min(current, totalPages));
  }, [totalPages]);

  if (loading && items.length === 0) return <LoadingState rows={4} message="Loading imported batches…" />;
  if (error && items.length === 0) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => { setLoading(true); loadBatches().catch(e => setError(e.message)).finally(() => setLoading(false)); }} />;

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      <CollapsibleToolbar title="Batch Filters" summary="Top filters are collapsed by default.">
        <div className="row">
          <input
            title="Filter imported batches by batch id or OCR job text."
            placeholder="Filter batches"
            value={tableSearch}
            onChange={(e) => setTableSearch(e.target.value)}
          />
          <select
            title="Filter imported batches by OCR job status."
            value={jobFilter}
            onChange={(e) => setJobFilter(e.target.value)}
          >
            <option value="all">All job states</option>
            <option value="not_started">Not started</option>
            <option value="running">Running</option>
            <option value="stopping">Stopping</option>
            <option value="stopped">Stopped</option>
            <option value="failed">Failed</option>
            <option value="complete">Complete</option>
          </select>
        </div>
      </CollapsibleToolbar>
      <div className="panel glass">
        <div className="panel-head">
          <h3>Trained Data (Imported Batches)</h3>
          <span className="tiny muted">{sortedRows.length} batches</span>
        </div>
        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th><SortableHeader label="Batch" sortKey="batch" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Total" sortKey="total" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Annotated" sortKey="annotated" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Negatives" sortKey="negatives" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th><SortableHeader label="Pending" sortKey="pending" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>OCR Job</th>
                <th><SortableHeader label="Updated" sortKey="updated_at" activeKey={sortKey} direction={sortDirection} onSort={requestSort} /></th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((row) => (
                <tr key={row.batch}>
                  {(() => {
                    const ocrStatus = String(row.ocr_job?.status || '').toLowerCase();
                    const runningLike = ['running', 'stopping'].includes(ocrStatus);
                    const heartbeat = fmtAgo(row.ocr_job?.heartbeat_at || row.ocr_job?.updated_at);
                    return (
                      <>
                  <td className="mono">{row.batch}</td>
                  <td>{row.total}</td>
                  <td>{row.annotated}</td>
                  <td>{row.negatives}</td>
                  <td>{row.pending}</td>
                  <td>
                    {row.ocr_job ? (
                      <div className="stack" style={{ minWidth: 220 }}>
                        <div className="row">
                          <span className={`status-pill ${row.ocr_job.status || 'idle'}`}>{row.ocr_job.status || 'idle'}</span>
                          <span className="tiny muted">
                            {Number(row.ocr_job.processed || 0)}/{Number(row.ocr_job.total || 0)}
                          </span>
                        </div>
                        <div className="progress-wrap">
                          <div className="progress-bar" style={{ width: `${Math.max(0, Math.min(100, Number(row.ocr_job.progress || 0)))}%` }} />
                        </div>
                        <div className="tiny muted">{row.ocr_job.message || ''}</div>
                        <div className="tiny muted">
                          Updated: {Number(row.ocr_job.updated || 0)} | Skipped: {Number(row.ocr_job.skipped || 0)}
                        </div>
                        <div className="tiny muted">
                          Chunk: {Number(row.ocr_job.chunk_index || 0)}/{Number(row.ocr_job.chunk_total || 0)} | Cursor: {Number(row.ocr_job.last_id || 0)}
                        </div>
                        <div className="tiny muted">
                          Speed: {Number(row.ocr_job.speed_sps || 0).toFixed(2)}/s | ETA: {fmtDuration(row.ocr_job.eta_seconds || 0)} | Heartbeat: {heartbeat === '-' ? 'n/a' : `${heartbeat} ago`}
                        </div>
                        {row.ocr_job.error ? <div className="tiny" style={{ color: '#ff8aa2' }}>{row.ocr_job.error}</div> : null}
                      </div>
                    ) : (
                      <span className="tiny muted">Not started</span>
                    )}
                  </td>
                  <td className="tiny">{row.updated_at ? new Date(row.updated_at).toLocaleString() : '-'}</td>
                  <td>
                    <Link className="btn ghost" to={`/training-data?batch=${encodeURIComponent(row.batch)}`}>
                      Open
                    </Link>
                    <button
                      className="btn"
                      type="button"
                      onClick={() => startBatchReprocess(row.batch)}
                      disabled={startingBatch === row.batch || runningLike}
                      style={{ marginInlineStart: 8 }}
                      title="Extract plate text for all annotated samples in this imported batch (processed in chunks of 1000)."
                    >
                      {startingBatch === row.batch ? 'Starting...' : (ocrStatus === 'running' ? 'Running...' : 'Reprocess OCR')}
                    </button>
                    <button
                      className="btn ghost"
                      type="button"
                      onClick={() => controlBatchJob(row.batch, 'stop')}
                      disabled={controlBatch === row.batch || !runningLike}
                      style={{ marginInlineStart: 8 }}
                      title="Request safe stop for the current OCR batch job."
                    >
                      {controlBatch === row.batch ? '...' : 'Stop'}
                    </button>
                    <button
                      className="btn ghost"
                      type="button"
                      onClick={() => controlBatchJob(row.batch, 'resume')}
                      disabled={controlBatch === row.batch || ocrStatus === 'running'}
                      style={{ marginInlineStart: 8 }}
                      title="Resume OCR from the last processed cursor."
                    >
                      {controlBatch === row.batch ? '...' : 'Resume'}
                    </button>
                    <button
                      className="btn ghost"
                      type="button"
                      onClick={() => controlBatchJob(row.batch, 'restart')}
                      disabled={controlBatch === row.batch}
                      style={{ marginInlineStart: 8 }}
                      title="Restart OCR for this batch from the beginning."
                    >
                      {controlBatch === row.batch ? '...' : 'Restart'}
                    </button>
                    <button
                      className="btn ghost"
                      type="button"
                      onClick={() => controlBatchJob(row.batch, 'clear')}
                      disabled={controlBatch === row.batch || !row.ocr_job}
                      style={{ marginInlineStart: 8 }}
                      title="Clear stored OCR job state for this batch."
                    >
                      {controlBatch === row.batch ? '...' : 'Clear'}
                    </button>
                    <button
                      className="btn danger"
                      type="button"
                      onClick={() => deleteBatch(row.batch)}
                      disabled={deletingBatch === row.batch}
                      style={{ marginInlineStart: 8 }}
                    >
                      {deletingBatch === row.batch ? 'Deleting...' : 'Delete'}
                    </button>
                  </td>
                      </>
                    );
                  })()}
                </tr>
              ))}
              {!sortedRows.length && !loading ? (
                <tr>
                  <td colSpan={8} className="empty">No imported batches match the current filters.</td>
                </tr>
              ) : null}
            </tbody>
          </table>
        </div>
        <TablePagination
          page={page}
          totalPages={totalPages}
          totalItems={sortedRows.length}
          pageSize={pageSize}
          currentCount={pagedRows.length}
          itemLabel="batches"
          onPageChange={setPage}
          onPageSizeChange={setPageSize}
        />
      </div>
    </div>
  );
}
