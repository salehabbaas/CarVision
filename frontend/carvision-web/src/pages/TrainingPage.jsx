import { useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  Download,
  FlaskConical,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  Settings2,
  ShieldCheck,
  Square,
  XCircle,
  Zap,
} from 'lucide-react';
import { apiPath, request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

// ── helpers ──────────────────────────────────────────────────────────────────
const DEFAULTS = {
  train_model: 'yolov8n.pt',
  train_epochs: 50,
  train_imgsz: 640,
  train_batch: -1,
  train_device: 'auto',
  train_patience: 15,
  train_chunk_size: 1000,
  train_chunk_epochs: 8,
  train_new_only_default: true,
  train_nightly_enabled: true,
  train_nightly_hour: 0,
  train_nightly_minute: 0,
  train_schedule_tz: 'America/Toronto',
  plate_region: 'generic',
  plate_min_length: 5,
  plate_max_length: 8,
  plate_charset: 'alnum',
  plate_pattern_regex: '',
  plate_shape_hint: 'standard',
  plate_reference_date: '',
  allowed_stationary_enabled: true,
  allowed_stationary_motion_threshold: 7.0,
  allowed_stationary_hold_seconds: 0.0,
};

function asBool(v, fb = false) {
  if (v === undefined || v === null) return fb;
  if (typeof v === 'boolean') return v;
  return ['1', 'true', 'yes', 'on'].includes(String(v).toLowerCase());
}

function fmtDuration(seconds) {
  const t = Number(seconds || 0);
  if (!Number.isFinite(t) || t <= 0) return '—';
  const h = Math.floor(t / 3600);
  const m = Math.floor((t % 3600) / 60);
  const s = Math.floor(t % 60);
  if (h > 0) return `${h}h ${m}m ${s}s`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function fmtDate(iso) {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString();
}

function StatBar({ label, value, total, color = 'var(--accent)' }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div style={{ marginBottom: 6 }}>
      <div className="row between" style={{ marginBottom: 2 }}>
        <span className="tiny muted">{label}</span>
        <span className="tiny mono">{value.toLocaleString()} <span className="muted">({pct}%)</span></span>
      </div>
      <div style={{ background: 'rgba(255,255,255,.08)', borderRadius: 4, height: 6, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 4, transition: 'width .4s' }} />
      </div>
    </div>
  );
}

function KpiCard({ label, value, sub, accent }) {
  return (
    <div className="kpi-card" style={accent ? { borderTop: `2px solid ${accent}` } : {}}>
      <span className="tiny muted">{label}</span>
      <strong style={accent ? { color: accent } : {}}>{value}</strong>
      {sub && <span className="tiny muted">{sub}</span>}
    </div>
  );
}

// ── DatasetStats panel ────────────────────────────────────────────────────────
function DatasetStats({ token }) {
  const [stats, setStats] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  async function load() {
    setBusy(true);
    setErr('');
    try {
      const res = await request('/api/v1/training/dataset_stats', { token });
      setStats(res);
    } catch (e) {
      setErr(e.message || 'Failed to load stats');
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => { load(); }, []);

  if (busy && !stats) {
    return (
      <div className="panel glass" style={{ padding: 20, textAlign: 'center' }}>
        <LoaderCircle size={20} className="spin" /> Loading dataset stats…
      </div>
    );
  }

  if (err) return <div className="alert error">{err}</div>;
  if (!stats) return null;

  const t = stats.total || 0;

  return (
    <div className="panel glass stack">
      <div className="panel-head">
        <h3>Dataset Overview</h3>
        <button className="btn ghost" onClick={load} disabled={busy} title="Refresh stats">
          <RefreshCw size={14} className={busy ? 'spin' : ''} />
        </button>
      </div>

      <div className="training-kpis" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(120px,1fr))' }}>
        <KpiCard label="Total Images" value={t.toLocaleString()} />
        <KpiCard label="Annotated" value={stats.annotated.toLocaleString()} accent="var(--ok)" sub={`${stats.annotation_rate}%`} />
        <KpiCard label="With Plate Text" value={stats.with_text.toLocaleString()} />
        <KpiCard label="Negative (no plate)" value={stats.negative.toLocaleString()} />
        <KpiCard label="Pending Review" value={stats.pending.toLocaleString()} accent={stats.pending > 0 ? 'var(--warn)' : undefined} />
        <KpiCard label="Trained" value={stats.trained.toLocaleString()} accent="var(--accent)" sub={`${stats.trained_rate}%`} />
        <KpiCard label="Testable" value={stats.testable.toLocaleString()} accent="#a78bfa" sub="annotated + text" />
        <KpiCard label="Ignored" value={stats.ignored.toLocaleString()} />
      </div>

      <div className="row two" style={{ gap: 20 }}>
        <div>
          <div className="tiny muted" style={{ marginBottom: 6 }}>Annotation breakdown</div>
          <StatBar label="Annotated" value={stats.annotated} total={t} color="var(--ok)" />
          <StatBar label="Pending" value={stats.pending} total={t} color="var(--warn)" />
          <StatBar label="Negative" value={stats.negative} total={t} color="#64748b" />
          <StatBar label="Ignored" value={stats.ignored} total={t} color="#374151" />
        </div>
        <div>
          <div className="tiny muted" style={{ marginBottom: 6 }}>Training progress</div>
          <StatBar label="Trained" value={stats.trained} total={t} color="var(--accent)" />
          <StatBar label="Untrained" value={stats.untrained} total={t} color="#1e3a5f" />
          <div style={{ marginTop: 10 }}>
            <div className="tiny muted" style={{ marginBottom: 6 }}>Source</div>
            <StatBar label="From cameras" value={stats.from_system} total={t} color="#0ea5e9" />
            <StatBar label="From imports" value={stats.from_dataset} total={t} color="#8b5cf6" />
          </div>
        </div>
      </div>
    </div>
  );
}

// ── ModelTestPanel ────────────────────────────────────────────────────────────
function ModelTestPanel({ token }) {
  const [limit, setLimit] = useState(50);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [err, setErr] = useState('');
  const [expanded, setExpanded] = useState(false);

  async function runTest() {
    setBusy(true);
    setErr('');
    setResult(null);
    try {
      const res = await request('/api/v1/training/test_model', {
        token, method: 'POST', body: { limit: Number(limit) },
      });
      if (!res.ok) throw new Error(res.error || 'Test failed');
      setResult(res);
      setExpanded(true);
    } catch (e) {
      setErr(e.message || 'Model test failed');
    } finally {
      setBusy(false);
    }
  }

  const summary = result?.summary || {};
  const rows = result?.results || [];

  return (
    <div className="panel glass stack">
      <div className="panel-head">
        <h3><FlaskConical size={15} /> Model Accuracy Test</h3>
      </div>
      <p className="tiny muted">
        Runs the live model against manually annotated samples that have both a bounding box and a plate text label.
        Compares model output to the ground truth and reports exact match and similarity scores.
      </p>

      <div className="row" style={{ gap: 10, alignItems: 'center' }}>
        <label className="tiny muted">Max samples to test</label>
        <input type="number" min={1} max={500} value={limit} style={{ width: 80 }}
          onChange={(e) => setLimit(Number(e.target.value) || 50)} />
        <button className="btn primary" onClick={runTest} disabled={busy}>
          {busy
            ? <><LoaderCircle size={14} className="spin" /> Running…</>
            : <><Play size={14} /> Run Test</>}
        </button>
      </div>

      {err && <div className="alert error">{err}</div>}

      {result && (
        <>
          {/* Summary KPIs */}
          <div className="training-kpis" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(130px,1fr))' }}>
            <KpiCard label="Tested" value={summary.total_tested} />
            <KpiCard
              label="Exact Match"
              value={`${summary.exact_accuracy}%`}
              sub={`${summary.exact_matches} / ${summary.total_tested}`}
              accent={summary.exact_accuracy >= 80 ? 'var(--ok)' : summary.exact_accuracy >= 50 ? 'var(--warn)' : 'var(--bad)'}
            />
            <KpiCard
              label="Fuzzy Match"
              value={`${summary.fuzzy_accuracy}%`}
              sub={`avg similarity ${(summary.avg_similarity * 100).toFixed(1)}%`}
              accent="#a78bfa"
            />
            <KpiCard
              label="Detection Rate"
              value={`${summary.detection_rate}%`}
              sub={`${summary.detected} detected`}
              accent={summary.detection_rate >= 80 ? 'var(--ok)' : 'var(--warn)'}
            />
            <KpiCard
              label="No Detection"
              value={summary.no_detection}
              accent={summary.no_detection > 0 ? 'var(--bad)' : undefined}
            />
            <KpiCard
              label="Avg Confidence"
              value={summary.avg_confidence != null ? `${(summary.avg_confidence * 100).toFixed(1)}%` : '—'}
            />
          </div>

          {/* Score bar */}
          <div>
            <div className="tiny muted" style={{ marginBottom: 4 }}>Exact accuracy</div>
            <div style={{ background: 'rgba(255,255,255,.08)', borderRadius: 6, height: 10, overflow: 'hidden' }}>
              <div style={{
                width: `${summary.exact_accuracy}%`,
                height: '100%',
                borderRadius: 6,
                background: summary.exact_accuracy >= 80 ? 'var(--ok)' : summary.exact_accuracy >= 50 ? 'var(--warn)' : 'var(--bad)',
                transition: 'width .5s',
              }} />
            </div>
          </div>

          {/* Per-sample results table */}
          <div>
            <button className="btn ghost" style={{ alignSelf: 'flex-start', marginBottom: 8 }}
              onClick={() => setExpanded((s) => !s)}>
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {expanded ? 'Hide' : 'Show'} per-sample results ({rows.length})
            </button>
            {expanded && (
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>ID</th>
                      <th>Expected</th>
                      <th>Predicted</th>
                      <th>Match</th>
                      <th>Similarity</th>
                      <th>Confidence</th>
                      <th>Detector</th>
                      <th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.sample_id} style={r.exact_match ? {} : { opacity: 0.85 }}>
                        <td className="mono tiny">{r.sample_id}</td>
                        <td className="mono">{r.expected}</td>
                        <td className="mono">{r.predicted ?? <span className="muted">—</span>}</td>
                        <td>
                          {r.exact_match
                            ? <span className="tag ok"><CheckCircle size={11} /> exact</span>
                            : r.predicted
                              ? <span className="tag warn">partial</span>
                              : <span className="tag bad"><XCircle size={11} /> none</span>}
                        </td>
                        <td className="mono">{r.similarity != null ? `${(r.similarity * 100).toFixed(0)}%` : '—'}</td>
                        <td className="mono">{r.confidence != null ? `${(r.confidence * 100).toFixed(1)}%` : '—'}</td>
                        <td className="tiny">{r.detector ?? '—'}</td>
                        <td className="tiny muted">{r.error ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function TrainingPage() {
  const { token } = useAuth();
  const [status, setStatus] = useState({ status: 'idle', stage: 'idle', message: 'Idle', progress: 0, details: {} });
  const [settings, setSettings] = useState(DEFAULTS);
  const [startMode, setStartMode] = useState('new_only');
  const [runOcrPrefill, setRunOcrPrefill] = useState(true);
  const [runOcrLearn, setRunOcrLearn] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [saving, setSaving] = useState(false);
  const [startBusy, setStartBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [learnBusy, setLearnBusy] = useState(false);
  const [ocrJob, setOcrJob] = useState(null);
  const [jobs, setJobs] = useState([]);
  const [jobsMeta, setJobsMeta] = useState({ total: 0, page: 1, pages: 1, limit: 20, status: 'all' });
  const [jobsFilter, setJobsFilter] = useState('all');
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsBusy, setJobsBusy] = useState(false);
  const [showSettings, setShowSettings] = useState(false);

  const isRunning = ['queued', 'running'].includes(String(status.status || '').toLowerCase());

  function showToast(msg) {
    setToast(msg);
    setTimeout(() => setToast(''), 5000);
  }

  async function loadSettings() {
    const cfg = await request('/api/v1/training/settings', { token });
    setSettings({
      train_model: cfg.train_model || DEFAULTS.train_model,
      train_epochs: Number(cfg.train_epochs ?? DEFAULTS.train_epochs),
      train_imgsz: Number(cfg.train_imgsz ?? DEFAULTS.train_imgsz),
      train_batch: Number(cfg.train_batch ?? DEFAULTS.train_batch),
      train_device: cfg.train_device || DEFAULTS.train_device,
      train_patience: Number(cfg.train_patience ?? DEFAULTS.train_patience),
      train_chunk_size: Number(cfg.train_chunk_size ?? DEFAULTS.train_chunk_size),
      train_chunk_epochs: Number(cfg.train_chunk_epochs ?? DEFAULTS.train_chunk_epochs),
      train_new_only_default: asBool(cfg.train_new_only_default, DEFAULTS.train_new_only_default),
      train_nightly_enabled: asBool(cfg.train_nightly_enabled, DEFAULTS.train_nightly_enabled),
      train_nightly_hour: Number(cfg.train_nightly_hour ?? DEFAULTS.train_nightly_hour),
      train_nightly_minute: Number(cfg.train_nightly_minute ?? DEFAULTS.train_nightly_minute),
      train_schedule_tz: cfg.train_schedule_tz || DEFAULTS.train_schedule_tz,
      plate_region: cfg.plate_region || DEFAULTS.plate_region,
      plate_min_length: Number(cfg.plate_min_length ?? DEFAULTS.plate_min_length),
      plate_max_length: Number(cfg.plate_max_length ?? DEFAULTS.plate_max_length),
      plate_charset: cfg.plate_charset || DEFAULTS.plate_charset,
      plate_pattern_regex: cfg.plate_pattern_regex || DEFAULTS.plate_pattern_regex,
      plate_shape_hint: cfg.plate_shape_hint || DEFAULTS.plate_shape_hint,
      plate_reference_date: cfg.plate_reference_date || DEFAULTS.plate_reference_date,
      allowed_stationary_enabled: asBool(cfg.allowed_stationary_enabled, DEFAULTS.allowed_stationary_enabled),
      allowed_stationary_motion_threshold: Number(cfg.allowed_stationary_motion_threshold ?? DEFAULTS.allowed_stationary_motion_threshold),
      allowed_stationary_hold_seconds: Number(cfg.allowed_stationary_hold_seconds ?? DEFAULTS.allowed_stationary_hold_seconds),
    });
    setStartMode(asBool(cfg.train_new_only_default, true) ? 'new_only' : 'all');
  }

  async function loadJobs({ page = jobsPage, status: st = jobsFilter, silent = false } = {}) {
    if (!silent) setJobsBusy(true);
    try {
      const query = new URLSearchParams({ page: String(page), limit: '20', status: String(st || 'all') });
      const res = await request(`/api/v1/training/jobs?${query.toString()}`, { token });
      setJobs(Array.isArray(res.items) ? res.items : []);
      setJobsMeta({ total: Number(res.total || 0), page: Number(res.page || 1), pages: Number(res.pages || 1), limit: Number(res.limit || 20), status: res.status || 'all' });
    } catch (err) {
      setError(err.message || 'Failed to load training history');
    } finally {
      if (!silent) setJobsBusy(false);
    }
  }

  // Status polling
  useEffect(() => {
    let timer; let alive = true;
    const loop = async () => {
      try {
        const st = await request('/api/v1/training/status', { token });
        if (!alive) return;
        setStatus({ ...st, details: st.details || {}, progress: Number(st.progress || 0), status: st.status || 'idle', stage: st.stage || 'idle', message: st.message || 'Idle' });
      } catch {}
      timer = setTimeout(loop, 2500);
    };
    loop();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [token]);

  useEffect(() => { loadJobs({ page: jobsPage, status: jobsFilter }).catch(() => {}); }, [token, jobsPage, jobsFilter]);

  useEffect(() => {
    let timer; let alive = true;
    const tick = async () => {
      if (!alive) return;
      if (isRunning) await loadJobs({ page: jobsPage, status: jobsFilter, silent: true });
      timer = setTimeout(tick, isRunning ? 4000 : 15000);
    };
    tick();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [isRunning, jobsPage, jobsFilter]);

  useEffect(() => { loadSettings().catch((e) => setError(e.message || 'Failed to load settings')); }, [token]);

  // OCR job polling
  useEffect(() => {
    if (!ocrJob?.id) return undefined;
    let timer; let alive = true;
    const poll = async () => {
      try {
        const res = await request(`/api/v1/training/ocr/prefill/${ocrJob.id}`, { token });
        if (!alive) return;
        const job = res?.job || {};
        setOcrJob({ id: ocrJob.id, status: job.status || 'running', progress: Number(job.progress || 0), message: job.message || '', result: job.result || null, error: job.error || null });
        if (job.status === 'complete') {
          const rr = job.result || {};
          showToast(`OCR prefill done. Updated: ${rr.updated || 0}, skipped: ${rr.skipped || 0}, total: ${rr.total || rr.scanned || 0}.`);
          return;
        }
        if (job.status === 'failed') { setError(job.error || job.message || 'OCR prefill failed'); return; }
      } catch (e) { if (!alive) return; setError(e.message || 'OCR prefill status failed'); return; }
      timer = setTimeout(poll, 1300);
    };
    poll();
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [ocrJob?.id, token]);

  async function startTraining() {
    setError(''); setToast(''); setStartBusy(true);
    try {
      const res = await request('/api/v1/training/start', { token, method: 'POST', body: { mode: startMode, chunk_size: Number(settings.train_chunk_size), chunk_epochs: Number(settings.train_chunk_epochs), run_ocr_prefill: Boolean(runOcrPrefill), run_ocr_learn: Boolean(runOcrLearn) } });
      showToast(res?.job?.id ? `Training job started: ${res.job.id}` : 'Training started');
      const st = await request('/api/v1/training/status', { token });
      setStatus({ ...st, details: st.details || {}, progress: Number(st.progress || 0), status: st.status || 'idle', stage: st.stage || 'idle', message: st.message || 'Idle' });
    } catch (e) {
      if (String(e.message || '').toLowerCase().includes('already running')) {
        showToast('A training job is already running. Monitoring active job.');
      } else {
        setError(e.message || 'Failed to start training');
      }
    } finally { setStartBusy(false); }
  }

  async function stopTraining() {
    setError(''); setToast(''); setStopBusy(true);
    try {
      await request('/api/v1/training/stop', { token, method: 'POST' });
      showToast('Stop requested. Current chunk will stop safely.');
    } catch (e) { setError(e.message || 'Failed to stop training'); }
    finally { setStopBusy(false); }
  }

  async function downloadModel(jobId) {
    setError(''); setToast(''); setDownloadBusy(true);
    try {
      const url = jobId
        ? apiPath(`/api/v1/training/model/download?job_id=${encodeURIComponent(jobId)}`)
        : apiPath('/api/v1/training/model/download');
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error((await res.text()) || `Download failed (${res.status})`);
      const blob = await res.blob();
      const href = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = href;
      a.download = `carvision_plate_${jobId || new Date().toISOString().replaceAll(':', '-')}.pt`;
      document.body.appendChild(a); a.click(); a.remove();
      URL.revokeObjectURL(href);
      showToast('Model downloaded.');
    } catch (e) { setError(e.message || 'Failed to download model'); }
    finally { setDownloadBusy(false); }
  }

  async function prefillOcrTexts() {
    setError(''); setToast(''); setOcrBusy(true);
    try {
      const res = await request('/api/v1/training/ocr/prefill', { token, method: 'POST' });
      if (res?.job_id) setOcrJob({ id: res.job_id, status: 'running', progress: 0, result: null, message: 'Queued' });
      else showToast('OCR prefill started.');
    } catch (e) { setError(e.message || 'OCR prefill failed'); }
    finally { setOcrBusy(false); }
  }

  async function learnOcrCorrections() {
    setError(''); setToast(''); setLearnBusy(true);
    try {
      const res = await request('/api/v1/training/ocr/learn', { token, method: 'POST' });
      showToast(`OCR correction map updated. Pairs: ${res.pairs || 0}, replacements: ${res.replacements || 0}.`);
    } catch (e) { setError(e.message || 'OCR learning failed'); }
    finally { setLearnBusy(false); }
  }

  async function saveSettings() {
    setError(''); setToast(''); setSaving(true);
    try {
      await request('/api/v1/training/settings', { token, method: 'POST', body: { ...settings, train_epochs: Number(settings.train_epochs), train_imgsz: Number(settings.train_imgsz), train_batch: Number(settings.train_batch), train_patience: Number(settings.train_patience), train_chunk_size: Number(settings.train_chunk_size), train_chunk_epochs: Number(settings.train_chunk_epochs), train_new_only_default: Boolean(settings.train_new_only_default), train_nightly_enabled: Boolean(settings.train_nightly_enabled), train_nightly_hour: Number(settings.train_nightly_hour), train_nightly_minute: Number(settings.train_nightly_minute), plate_min_length: Number(settings.plate_min_length), plate_max_length: Number(settings.plate_max_length), allowed_stationary_enabled: Boolean(settings.allowed_stationary_enabled), allowed_stationary_motion_threshold: Number(settings.allowed_stationary_motion_threshold), allowed_stationary_hold_seconds: Number(settings.allowed_stationary_hold_seconds) } });
      showToast('Settings saved.');
      await loadSettings();
    } catch (e) { setError(e.message || 'Failed to save settings'); }
    finally { setSaving(false); }
  }

  const logs = useMemo(() => (Array.isArray(status?.details?.logs) ? status.details.logs : []), [status?.details?.logs]);
  const progress = Math.max(0, Math.min(100, Number(status.progress || 0)));

  return (
    <div className="stack">
      {error ? <div className="alert error" onClick={() => setError('')}>{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      {/* ── Dataset Stats ─────────────────────────────────────────────────── */}
      <DatasetStats token={token} />

      {/* ── Pipeline Control ──────────────────────────────────────────────── */}
      <div className="panel glass training-hero stack">
        <div className="panel-head">
          <div>
            <h3>Training Pipeline</h3>
            <span className={`status-pill ${status.status}`} style={{ marginTop: 2 }}>{status.status || 'idle'}</span>
            {' '}
            <span className="status-pill">{status.stage || 'idle'}</span>
            {' '}
            <span className="tiny muted">{status.message}</span>
          </div>
          <div className="row" style={{ gap: 8 }}>
            <select value={startMode} onChange={(e) => setStartMode(e.target.value)} title="Training scope">
              <option value="new_only">New / Updated Only</option>
              <option value="all">All Annotated</option>
            </select>
            <button className="btn primary" onClick={startTraining} disabled={startBusy || isRunning}>
              {startBusy ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
              {startBusy ? 'Starting…' : 'Start'}
            </button>
            <button className="btn ghost" onClick={stopTraining} disabled={stopBusy || !isRunning}>
              {stopBusy ? <LoaderCircle size={14} className="spin" /> : <Square size={14} />} Stop
            </button>
            <button className="btn" onClick={() => downloadModel()} disabled={downloadBusy}>
              {downloadBusy ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />} Model
            </button>
          </div>
        </div>

        {/* Progress bar */}
        <div className="progress-wrap">
          <div className="progress-bar" style={{ width: `${progress}%` }} />
        </div>

        {/* Runtime KPIs */}
        <div className="training-kpis">
          <KpiCard label="Selected" value={status.total_samples || 0} />
          <KpiCard label="Trained" value={status.trained_samples || 0} />
          <KpiCard label="Chunk" value={`${status.chunk_index || 0}/${status.chunk_total || 0}`} />
          <KpiCard label="OCR Updated" value={status.ocr_updated || 0} />
        </div>

        <div className="row two">
          <div>
            <div className="tiny muted">Run directory</div>
            <div className="mono tiny">{status.run_dir || status.last_run_dir || '—'}</div>
          </div>
          <div>
            <div className="tiny muted">Model output</div>
            <div className="mono tiny">{status.model_path || status.last_model_path || '—'}</div>
          </div>
        </div>

        <div className="row" style={{ gap: 12 }}>
          <label className="row tiny">
            <input type="checkbox" checked={runOcrPrefill} onChange={(e) => setRunOcrPrefill(e.target.checked)} />
            Run OCR Prefill
          </label>
          <label className="row tiny">
            <input type="checkbox" checked={runOcrLearn} onChange={(e) => setRunOcrLearn(e.target.checked)} />
            Run OCR Learn
          </label>
        </div>

        {/* Job log */}
        <div className="training-log">
          <div className="tiny muted">Job Log</div>
          <div className="training-log-list">
            {(logs.length ? logs.slice(-10).reverse() : ['No logs yet.']).map((line, i) => (
              <div key={`${line}-${i}`} className="tiny mono">{line}</div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Model Accuracy Test ───────────────────────────────────────────── */}
      <ModelTestPanel token={token} />

      {/* ── OCR Tools ─────────────────────────────────────────────────────── */}
      <div className="panel glass stack">
        <div className="panel-head">
          <h3><Zap size={15} /> OCR Tools</h3>
        </div>
        <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
          <button className="btn ghost" onClick={prefillOcrTexts} disabled={ocrBusy}>
            {ocrBusy ? <LoaderCircle size={13} className="spin" /> : null}
            {ocrBusy ? 'Running…' : '1) Auto Fill Plate Text From Boxes'}
          </button>
          <button className="btn ghost" onClick={learnOcrCorrections} disabled={learnBusy}>
            {learnBusy ? 'Running…' : '2) Learn OCR Corrections'}
          </button>
        </div>
        {ocrJob?.id && (
          <div style={{ marginTop: 8 }}>
            <div className="tiny muted">OCR Job: {ocrJob.status} {ocrJob.progress ?? 0}%</div>
            <div className="progress-wrap">
              <div className="progress-bar" style={{ width: `${Math.max(0, Math.min(100, Number(ocrJob.progress || 0)))}%` }} />
            </div>
            <div className="tiny muted">
              {ocrJob.message}
              {ocrJob.result ? ` | updated ${ocrJob.result.updated || 0}, skipped ${ocrJob.result.skipped || 0}` : ''}
            </div>
          </div>
        )}
      </div>

      {/* ── Settings (collapsible) ─────────────────────────────────────────── */}
      <div className="panel glass stack">
        <button
          className="btn ghost"
          style={{ alignSelf: 'flex-start', display: 'flex', alignItems: 'center', gap: 6 }}
          onClick={() => setShowSettings((s) => !s)}
        >
          <Settings2 size={15} />
          Training Settings
          {showSettings ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
        </button>

        {showSettings && (
          <>
            <div className="panel-head" style={{ marginTop: 8 }}>
              <h3>Model & Training Hyperparameters</h3>
              <button className="btn primary" onClick={saveSettings} disabled={saving}>
                <Save size={14} /> {saving ? 'Saving…' : 'Save'}
              </button>
            </div>

            <div className="param-grid">
              {[
                { label: 'Base Model', key: 'train_model', type: 'text' },
                { label: 'Chunk Size', key: 'train_chunk_size', type: 'number', min: 100, max: 5000 },
                { label: 'Chunk Epochs', key: 'train_chunk_epochs', type: 'number', min: 1, max: 50 },
                { label: 'Image Size', key: 'train_imgsz', type: 'number', min: 160, max: 1920 },
                { label: 'Batch', key: 'train_batch', type: 'number', min: -1, max: 256 },
                { label: 'Device', key: 'train_device', type: 'text' },
                { label: 'Patience', key: 'train_patience', type: 'number', min: 1, max: 200 },
              ].map(({ label, key, type, min, max }) => (
                <div className="param-item" key={key}>
                  <span className="tiny">{label}</span>
                  <input type={type} min={min} max={max} value={settings[key]}
                    onChange={(e) => setSettings((s) => ({ ...s, [key]: type === 'number' ? e.target.value : e.target.value }))} />
                </div>
              ))}
              <div className="param-item">
                <span className="tiny">Default Mode</span>
                <label className="row tiny">
                  <input type="checkbox" checked={!!settings.train_new_only_default}
                    onChange={(e) => setSettings((s) => ({ ...s, train_new_only_default: e.target.checked }))} />
                  Train New/Updated by default
                </label>
              </div>
            </div>

            <div className="panel glass" style={{ marginTop: 12 }}>
              <div className="panel-head">
                <h3><ShieldCheck size={15} /> Nightly Schedule</h3>
              </div>
              <div className="param-grid">
                <div className="param-item">
                  <span className="tiny">Enabled</span>
                  <label className="row tiny">
                    <input type="checkbox" checked={!!settings.train_nightly_enabled}
                      onChange={(e) => setSettings((s) => ({ ...s, train_nightly_enabled: e.target.checked }))} />
                    Run every night
                  </label>
                </div>
                <div className="param-item">
                  <span className="tiny">Hour</span>
                  <input type="number" min={0} max={23} value={settings.train_nightly_hour}
                    onChange={(e) => setSettings((s) => ({ ...s, train_nightly_hour: e.target.value }))} />
                </div>
                <div className="param-item">
                  <span className="tiny">Minute</span>
                  <input type="number" min={0} max={59} value={settings.train_nightly_minute}
                    onChange={(e) => setSettings((s) => ({ ...s, train_nightly_minute: e.target.value }))} />
                </div>
                <div className="param-item">
                  <span className="tiny">Timezone</span>
                  <input value={settings.train_schedule_tz}
                    onChange={(e) => setSettings((s) => ({ ...s, train_schedule_tz: e.target.value }))} />
                </div>
              </div>
            </div>

            <div className="panel glass" style={{ marginTop: 12 }}>
              <div className="panel-head"><h3>Plate Profile (OCR Guidance)</h3></div>
              <div className="param-grid">
                <div className="param-item">
                  <span className="tiny">Region</span>
                  <input value={settings.plate_region}
                    onChange={(e) => setSettings((s) => ({ ...s, plate_region: e.target.value }))} />
                </div>
                <div className="param-item">
                  <span className="tiny">Min Length</span>
                  <input type="number" min={1} max={12} value={settings.plate_min_length}
                    onChange={(e) => setSettings((s) => ({ ...s, plate_min_length: e.target.value }))} />
                </div>
                <div className="param-item">
                  <span className="tiny">Max Length</span>
                  <input type="number" min={1} max={16} value={settings.plate_max_length}
                    onChange={(e) => setSettings((s) => ({ ...s, plate_max_length: e.target.value }))} />
                </div>
                <div className="param-item">
                  <span className="tiny">Charset</span>
                  <select value={settings.plate_charset}
                    onChange={(e) => setSettings((s) => ({ ...s, plate_charset: e.target.value }))}>
                    <option value="alnum">Letters + Digits</option>
                    <option value="digits">Digits Only</option>
                    <option value="letters">Letters Only</option>
                  </select>
                </div>
                <div className="param-item">
                  <span className="tiny">Plate Shape</span>
                  <select value={settings.plate_shape_hint}
                    onChange={(e) => setSettings((s) => ({ ...s, plate_shape_hint: e.target.value }))}>
                    <option value="standard">Standard</option>
                    <option value="long">Long Rectangle</option>
                    <option value="square">Square</option>
                    <option value="motorcycle">Motorcycle</option>
                  </select>
                </div>
                <div className="param-item">
                  <span className="tiny">Reference Date</span>
                  <input placeholder="2026-04" value={settings.plate_reference_date}
                    onChange={(e) => setSettings((s) => ({ ...s, plate_reference_date: e.target.value }))} />
                </div>
              </div>
              <div className="param-item" style={{ marginTop: 10 }}>
                <span className="tiny">Regex Pattern</span>
                <input placeholder="^[A-Z]{3}[0-9]{3}$" value={settings.plate_pattern_regex}
                  onChange={(e) => setSettings((s) => ({ ...s, plate_pattern_regex: e.target.value }))} />
              </div>
            </div>
          </>
        )}
      </div>

      {/* ── Training History ──────────────────────────────────────────────── */}
      <div className="panel glass stack">
        <div className="panel-head">
          <h3>Training History</h3>
          <div className="row" style={{ gap: 8 }}>
            <select value={jobsFilter} onChange={(e) => { setJobsFilter(e.target.value); setJobsPage(1); }}>
              <option value="all">All</option>
              <option value="queued">Queued</option>
              <option value="running">Running</option>
              <option value="stopped">Stopped</option>
              <option value="complete">Complete</option>
              <option value="failed">Failed</option>
            </select>
            <button className="btn ghost" onClick={() => loadJobs({ page: jobsPage, status: jobsFilter })} disabled={jobsBusy}>
              {jobsBusy ? <LoaderCircle size={14} className="spin" /> : <RefreshCw size={14} />}
            </button>
          </div>
        </div>

        <div className="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Job ID</th>
                <th>Status</th>
                <th>Mode</th>
                <th>Progress</th>
                <th>Trained / Total</th>
                <th>Duration</th>
                <th>Started</th>
                <th>Finished</th>
                <th>Model</th>
              </tr>
            </thead>
            <tbody>
              {jobs.length ? jobs.map((job) => (
                <tr key={job.id}>
                  <td className="mono tiny" title={job.id}>{job.id.slice(0, 8)}…</td>
                  <td><span className={`status-pill ${job.status || 'idle'}`}>{job.status || 'idle'}</span></td>
                  <td className="tiny">{job.mode || '—'}</td>
                  <td>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <div style={{ flex: 1, background: 'rgba(255,255,255,.08)', borderRadius: 4, height: 5, minWidth: 60 }}>
                        <div style={{ width: `${Math.round(Number(job.progress || 0))}%`, height: '100%', background: 'var(--accent)', borderRadius: 4 }} />
                      </div>
                      <span className="tiny mono">{Math.round(Number(job.progress || 0))}%</span>
                    </div>
                  </td>
                  <td className="tiny mono">{Number(job.trained_samples || 0)}/{Number(job.total_samples || 0)}</td>
                  <td className="tiny">{fmtDuration(job.duration_seconds)}</td>
                  <td className="tiny">{fmtDate(job.started_at || job.run_started_at)}</td>
                  <td className="tiny">{fmtDate(job.finished_at)}</td>
                  <td>
                    <button className="btn ghost" onClick={() => downloadModel(job.id)}
                      disabled={!job.model_path} title={job.model_path || 'No model artifact'}>
                      <Download size={13} />
                    </button>
                  </td>
                </tr>
              )) : (
                <tr><td colSpan={9} className="empty">No training jobs found.</td></tr>
              )}
            </tbody>
          </table>
        </div>

        <div className="row between" style={{ marginTop: 8 }}>
          <span className="tiny muted">Total: {jobsMeta.total}</span>
          <div className="row" style={{ gap: 6 }}>
            <button className="btn ghost" onClick={() => setJobsPage((p) => Math.max(1, p - 1))} disabled={jobsMeta.page <= 1}>Prev</button>
            <span className="tiny muted">Page {jobsMeta.page} / {jobsMeta.pages}</span>
            <button className="btn ghost" onClick={() => setJobsPage((p) => Math.min(Number(jobsMeta.pages || 1), p + 1))} disabled={jobsMeta.page >= jobsMeta.pages}>Next</button>
          </div>
        </div>
      </div>
    </div>
  );
}
