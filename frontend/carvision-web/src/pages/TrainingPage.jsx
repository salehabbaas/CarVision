import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  Activity,
  AlertTriangle,
  BrainCircuit,
  CheckCircle,
  ChevronDown,
  ChevronUp,
  ClipboardList,
  Download,
  FlaskConical,
  Gauge,
  History,
  LoaderCircle,
  Play,
  RefreshCw,
  Save,
  ScanLine,
  Settings2,
  ShieldCheck,
  Square,
  TriangleAlert,
  XCircle,
  Zap,
} from 'lucide-react';
import { apiPath, request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

// ── constants ─────────────────────────────────────────────────────────────────
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

const PIPELINE_MODES = [
  { value: 'extract_only', label: 'Extract Text Only', desc: 'Run OCR to auto-fill plate text from annotated boxes (no training)' },
  { value: 'train_only', label: 'Train Only', desc: 'Train YOLO on already-annotated+extracted data (skip OCR prefill/learn)' },
  { value: 'full', label: 'Full Pipeline', desc: 'Extract text → learn corrections → train model' },
];

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

/**
 * Compute ETA string from progress (0-100) and start timestamp (epoch seconds).
 * Returns something like "~2m 14s remaining" or null if not enough data.
 */
function calcEta(progressPct, startedTs) {
  const pct = Number(progressPct || 0);
  if (pct <= 1 || !startedTs) return null;
  const elapsed = Date.now() / 1000 - Number(startedTs);
  if (elapsed <= 0) return null;
  const rate = pct / elapsed;          // % per second
  const remaining = (100 - pct) / rate; // seconds left
  if (!Number.isFinite(remaining) || remaining <= 0) return null;
  return `~${fmtDuration(remaining)} remaining`;
}

// ── Toast system ─────────────────────────────────────────────────────────────
let _toastId = 0;
function ToastContainer({ toasts, onDismiss }) {
  return (
    <div style={{
      position: 'fixed', top: 18, right: 18, zIndex: 9999,
      display: 'flex', flexDirection: 'column', gap: 10, pointerEvents: 'none',
    }}>
      {toasts.map((t) => (
        <div key={t.id} onClick={() => onDismiss(t.id)} style={{
          pointerEvents: 'all',
          display: 'flex', alignItems: 'flex-start', gap: 10,
          background: t.type === 'error' ? 'rgba(255,40,80,.18)' : t.type === 'warn' ? 'rgba(255,191,71,.14)' : 'rgba(28,217,164,.14)',
          border: `1px solid ${t.type === 'error' ? 'rgba(255,94,126,.45)' : t.type === 'warn' ? 'rgba(255,191,71,.4)' : 'rgba(28,217,164,.4)'}`,
          borderRadius: 12, padding: '12px 16px',
          backdropFilter: 'blur(16px)',
          boxShadow: '0 8px 32px rgba(0,0,0,.35)',
          maxWidth: 380, cursor: 'pointer',
          animation: 'slideIn .22s ease',
          color: 'var(--text)', fontSize: 13,
        }}>
          {t.type === 'error' ? <XCircle size={16} style={{ color: 'var(--bad)', flexShrink: 0, marginTop: 1 }} />
            : t.type === 'warn' ? <TriangleAlert size={16} style={{ color: 'var(--warn)', flexShrink: 0, marginTop: 1 }} />
              : <CheckCircle size={16} style={{ color: 'var(--ok)', flexShrink: 0, marginTop: 1 }} />}
          <span style={{ lineHeight: 1.45 }}>{t.msg}</span>
        </div>
      ))}
    </div>
  );
}

function useToasts() {
  const [toasts, setToasts] = useState([]);
  const push = useCallback((msg, type = 'success', ms = 5000) => {
    const id = ++_toastId;
    setToasts((p) => [...p, { id, msg, type }]);
    if (ms > 0) setTimeout(() => setToasts((p) => p.filter((t) => t.id !== id)), ms);
  }, []);
  const dismiss = useCallback((id) => setToasts((p) => p.filter((t) => t.id !== id)), []);
  return { toasts, push, dismiss };
}

// ── StatBar ───────────────────────────────────────────────────────────────────
function StatBar({ label, value, total, color = 'var(--accent)' }) {
  const pct = total > 0 ? Math.round((value / total) * 100) : 0;
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span className="tiny muted">{label}</span>
        <span className="tiny mono">{(value || 0).toLocaleString()} <span className="muted">({pct}%)</span></span>
      </div>
      <div style={{ background: 'rgba(255,255,255,.07)', borderRadius: 6, height: 7, overflow: 'hidden' }}>
        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 6, transition: 'width .5s ease' }} />
      </div>
    </div>
  );
}

// ── KpiCard ───────────────────────────────────────────────────────────────────
function KpiCard({ label, value, sub, accent, pulse }) {
  return (
    <div style={{
      background: 'rgba(255,255,255,.04)',
      border: `1px solid ${accent ? accent + '44' : 'rgba(255,255,255,.08)'}`,
      borderTop: `2px solid ${accent || 'rgba(255,255,255,.12)'}`,
      borderRadius: 10, padding: '12px 14px',
      display: 'flex', flexDirection: 'column', gap: 4,
      position: 'relative', overflow: 'hidden',
    }}>
      {pulse && (
        <span style={{
          position: 'absolute', top: 8, right: 8,
          width: 8, height: 8, borderRadius: '50%',
          background: accent || 'var(--accent)',
          boxShadow: `0 0 8px ${accent || 'var(--accent)'}`,
          animation: 'pulseDot 1.4s infinite',
        }} />
      )}
      <span className="tiny muted" style={{ fontSize: 11 }}>{label}</span>
      <strong style={{ fontSize: 18, color: accent || 'var(--text)', lineHeight: 1 }}>{value ?? '—'}</strong>
      {sub && <span className="tiny muted" style={{ fontSize: 11 }}>{sub}</span>}
    </div>
  );
}

// ── Section header ────────────────────────────────────────────────────────────
function SectionHead({ icon: Icon, title, badge, action }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      paddingBottom: 12, borderBottom: '1px solid rgba(255,255,255,.07)', marginBottom: 16,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
        {Icon && <Icon size={17} style={{ color: 'var(--accent)' }} />}
        <span style={{ fontWeight: 600, fontSize: 15 }}>{title}</span>
        {badge && (
          <span style={{
            fontSize: 11, padding: '2px 8px', borderRadius: 99,
            background: 'rgba(53,162,255,.18)', color: 'var(--accent)', fontWeight: 600,
          }}>{badge}</span>
        )}
      </div>
      {action}
    </div>
  );
}

// ── Panel wrapper ─────────────────────────────────────────────────────────────
function Panel({ children, style }) {
  return (
    <div className="glass" style={{
      borderRadius: 16, padding: 20,
      display: 'flex', flexDirection: 'column', gap: 0,
      ...style,
    }}>
      {children}
    </div>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────
function StatusBadge({ status }) {
  const s = String(status || 'idle').toLowerCase();
  const map = {
    running: { bg: 'rgba(53,162,255,.2)', color: 'var(--accent)', border: 'rgba(53,162,255,.4)', pulse: true },
    queued: { bg: 'rgba(255,191,71,.15)', color: 'var(--warn)', border: 'rgba(255,191,71,.35)', pulse: true },
    complete: { bg: 'rgba(28,217,164,.15)', color: 'var(--ok)', border: 'rgba(28,217,164,.35)' },
    stopped: { bg: 'rgba(100,116,139,.2)', color: '#94a3b8', border: 'rgba(100,116,139,.35)' },
    failed: { bg: 'rgba(255,94,126,.15)', color: 'var(--bad)', border: 'rgba(255,94,126,.35)' },
    idle: { bg: 'rgba(255,255,255,.06)', color: 'var(--muted)', border: 'rgba(255,255,255,.12)' },
  };
  const theme = map[s] || map.idle;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '3px 10px', borderRadius: 99, fontSize: 12, fontWeight: 600,
      background: theme.bg, color: theme.color, border: `1px solid ${theme.border}`,
    }}>
      {theme.pulse && <span style={{ width: 6, height: 6, borderRadius: '50%', background: theme.color, animation: 'pulseDot 1.4s infinite', flexShrink: 0 }} />}
      {s}
    </span>
  );
}

// ── Progress bar ──────────────────────────────────────────────────────────────
function ProgressBar({ value, color = 'var(--accent)', animated }) {
  const pct = Math.max(0, Math.min(100, Number(value || 0)));
  return (
    <div style={{ background: 'rgba(255,255,255,.07)', borderRadius: 8, height: 8, overflow: 'hidden' }}>
      <div style={{
        width: `${pct}%`, height: '100%',
        background: `linear-gradient(90deg, ${color}, ${color}cc)`,
        borderRadius: 8, transition: 'width .5s ease',
        backgroundSize: animated ? '200% 100%' : undefined,
        animation: animated ? 'shimmer 1.5s infinite linear' : undefined,
      }} />
    </div>
  );
}

// ── Dataset Stats ─────────────────────────────────────────────────────────────
function DatasetStats({ token }) {
  const [stats, setStats] = useState(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState('');

  const load = useCallback(async () => {
    setBusy(true); setErr('');
    try {
      const res = await request('/api/v1/training/dataset_stats', { token });
      setStats(res);
    } catch (e) { setErr(e.message || 'Failed to load stats'); }
    finally { setBusy(false); }
  }, [token]);

  useEffect(() => { load(); }, [load]);

  if (err) return (
    <Panel>
      <SectionHead icon={Activity} title="Dataset Overview" action={
        <button className="btn ghost" onClick={load}><RefreshCw size={13} /></button>
      } />
      <div style={{ color: 'var(--bad)', fontSize: 13 }}>{err}</div>
    </Panel>
  );

  if (!stats && busy) return (
    <Panel>
      <SectionHead icon={Activity} title="Dataset Overview" />
      <div style={{ textAlign: 'center', padding: 24, color: 'var(--muted)' }}>
        <LoaderCircle size={20} className="spin" style={{ marginBottom: 8 }} />
        <div className="tiny">Loading dataset statistics…</div>
      </div>
    </Panel>
  );

  if (!stats) return null;

  const t = stats.total || 0;
  return (
    <Panel>
      <SectionHead icon={Activity} title="Dataset Overview"
        badge={t > 0 ? `${t.toLocaleString()} images` : undefined}
        action={
          <button className="btn ghost" onClick={load} disabled={busy} title="Refresh stats">
            <RefreshCw size={13} className={busy ? 'spin' : ''} />
          </button>
        }
      />

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px, 1fr))', gap: 10, marginBottom: 20 }}>
        <KpiCard label="Total Images" value={t.toLocaleString()} />
        <KpiCard label="Annotated" value={(stats.annotated || 0).toLocaleString()} accent="var(--ok)" sub={`${stats.annotation_rate || 0}%`} />
        <KpiCard label="With Plate Text" value={(stats.with_text || 0).toLocaleString()} accent="#60a5fa" />
        <KpiCard label="Negative (no plate)" value={(stats.negative || 0).toLocaleString()} />
        <KpiCard label="Pending Review" value={(stats.pending || 0).toLocaleString()} accent={stats.pending > 0 ? 'var(--warn)' : undefined} />
        <KpiCard label="Trained" value={(stats.trained || 0).toLocaleString()} accent="var(--accent)" sub={`${stats.trained_rate || 0}%`} />
        <KpiCard label="Testable" value={(stats.testable || 0).toLocaleString()} accent="#a78bfa" sub="annotated + text" />
        <KpiCard label="Ignored" value={(stats.ignored || 0).toLocaleString()} />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 20 }}>
        <div>
          <div className="tiny muted" style={{ marginBottom: 10, fontWeight: 600 }}>Annotation breakdown</div>
          <StatBar label="Annotated" value={stats.annotated} total={t} color="var(--ok)" />
          <StatBar label="Pending" value={stats.pending} total={t} color="var(--warn)" />
          <StatBar label="Negative" value={stats.negative} total={t} color="#64748b" />
          <StatBar label="Ignored" value={stats.ignored} total={t} color="#374151" />
        </div>
        <div>
          <div className="tiny muted" style={{ marginBottom: 10, fontWeight: 600 }}>Training progress</div>
          <StatBar label="Trained" value={stats.trained} total={t} color="var(--accent)" />
          <StatBar label="Untrained" value={stats.untrained} total={t} color="#1e3a5f" />
          <div style={{ marginTop: 14 }}>
            <div className="tiny muted" style={{ marginBottom: 10, fontWeight: 600 }}>Source</div>
            <StatBar label="From cameras" value={stats.from_system} total={t} color="#0ea5e9" />
            <StatBar label="From imports" value={stats.from_dataset} total={t} color="#8b5cf6" />
          </div>
        </div>
      </div>
    </Panel>
  );
}

// ── Model Accuracy Test ───────────────────────────────────────────────────────
function ModelTestPanel({ token, pushToast }) {
  const [limit, setLimit] = useState(50);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState(null);
  const [expanded, setExpanded] = useState(false);

  async function runTest() {
    setBusy(true); setResult(null);
    try {
      const res = await request('/api/v1/training/test_model', {
        token, method: 'POST', body: { limit: Number(limit) },
      });
      if (!res.ok) throw new Error(res.error || 'Test failed');
      setResult(res);
      setExpanded(true);
      const s = res.summary || {};
      pushToast(`Model test complete — ${s.exact_accuracy}% exact match on ${s.total_tested} samples`);
    } catch (e) {
      pushToast(e.message || 'Model test failed', 'error');
    } finally { setBusy(false); }
  }

  const summary = result?.summary || {};
  const rows = result?.results || [];

  return (
    <Panel>
      <SectionHead icon={FlaskConical} title="Model Accuracy Test" />
      <p className="tiny muted" style={{ marginBottom: 16, lineHeight: 1.6 }}>
        Runs the live model against manually annotated samples that have both a bounding box and plate text. Compares output to ground truth.
      </p>

      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <span className="tiny muted">Max samples</span>
        <input type="number" min={1} max={500} value={limit}
          style={{ width: 80, padding: '6px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)' }}
          onChange={(e) => setLimit(Number(e.target.value) || 50)} />
        <button className="btn primary" onClick={runTest} disabled={busy} style={{ gap: 6 }}>
          {busy ? <><LoaderCircle size={14} className="spin" /> Running…</> : <><Play size={14} /> Run Test</>}
        </button>
      </div>

      {result && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(130px,1fr))', gap: 10 }}>
            <KpiCard label="Tested" value={summary.total_tested} />
            <KpiCard label="Exact Match" value={`${summary.exact_accuracy}%`}
              sub={`${summary.exact_matches} / ${summary.total_tested}`}
              accent={summary.exact_accuracy >= 80 ? 'var(--ok)' : summary.exact_accuracy >= 50 ? 'var(--warn)' : 'var(--bad)'} />
            <KpiCard label="Fuzzy Match" value={`${summary.fuzzy_accuracy}%`}
              sub={`avg sim ${(summary.avg_similarity * 100).toFixed(1)}%`} accent="#a78bfa" />
            <KpiCard label="Detection Rate" value={`${summary.detection_rate}%`}
              sub={`${summary.detected} detected`}
              accent={summary.detection_rate >= 80 ? 'var(--ok)' : 'var(--warn)'} />
            <KpiCard label="No Detection" value={summary.no_detection}
              accent={summary.no_detection > 0 ? 'var(--bad)' : undefined} />
            <KpiCard label="Avg Confidence"
              value={summary.avg_confidence != null ? `${(summary.avg_confidence * 100).toFixed(1)}%` : '—'} />
          </div>

          <div>
            <div className="tiny muted" style={{ marginBottom: 6 }}>Exact accuracy</div>
            <ProgressBar value={summary.exact_accuracy}
              color={summary.exact_accuracy >= 80 ? 'var(--ok)' : summary.exact_accuracy >= 50 ? 'var(--warn)' : 'var(--bad)'} />
          </div>

          <div>
            <button className="btn ghost" style={{ fontSize: 12, gap: 6 }} onClick={() => setExpanded((s) => !s)}>
              {expanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
              {expanded ? 'Hide' : 'Show'} per-sample results ({rows.length})
            </button>
            {expanded && (
              <div className="table-wrap" style={{ marginTop: 8 }}>
                <table>
                  <thead>
                    <tr>
                      <th>ID</th><th>Expected</th><th>Predicted</th><th>Match</th>
                      <th>Similarity</th><th>Confidence</th><th>Detector</th><th>Note</th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr key={r.sample_id} style={r.exact_match ? {} : { opacity: 0.8 }}>
                        <td className="mono tiny">{r.sample_id}</td>
                        <td className="mono">{r.expected}</td>
                        <td className="mono">{r.predicted ?? <span className="muted">—</span>}</td>
                        <td>
                          {r.exact_match
                            ? <span className="tag ok" style={{ gap: 4 }}><CheckCircle size={10} /> exact</span>
                            : r.predicted
                              ? <span className="tag warn">partial</span>
                              : <span className="tag bad" style={{ gap: 4 }}><XCircle size={10} /> none</span>}
                        </td>
                        <td className="mono tiny">{r.similarity != null ? `${(r.similarity * 100).toFixed(0)}%` : '—'}</td>
                        <td className="mono tiny">{r.confidence != null ? `${(r.confidence * 100).toFixed(1)}%` : '—'}</td>
                        <td className="tiny">{r.detector ?? '—'}</td>
                        <td className="tiny muted">{r.error ?? ''}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      )}
    </Panel>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function TrainingPage() {
  const { token } = useAuth();
  const { toasts, push: pushToast, dismiss: dismissToast } = useToasts();

  // Training status (polled)
  const [status, setStatus] = useState({
    status: 'idle', stage: 'idle', message: 'Idle', progress: 0, details: {},
  });

  // Settings
  const [settings, setSettings] = useState(DEFAULTS);
  const [showSettings, setShowSettings] = useState(false);
  const [saving, setSaving] = useState(false);

  // Pipeline mode (new unified control)
  const [pipelineMode, setPipelineMode] = useState('full'); // 'extract_only' | 'train_only' | 'full'
  const [trainScope, setTrainScope] = useState('new_only'); // 'new_only' | 'all'

  // Button states
  const [startBusy, setStartBusy] = useState(false);
  const [stopBusy, setStopBusy] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);

  // Track when training started (for ETA); reset when a new job begins
  const [trainStartedTs, setTrainStartedTs] = useState(null);

  // Standalone OCR prefill job (independent of training)
  // ocrJob shape: { id, status, progress, message, result, error, startedTs }
  const [ocrJob, setOcrJob] = useState(null);
  const [ocrBusy, setOcrBusy] = useState(false);
  const [learnBusy, setLearnBusy] = useState(false);

  // Live ETA ticker (re-renders every second while a job is active)
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(id);
  }, []);

  // Training history
  const [jobs, setJobs] = useState([]);
  const [jobsMeta, setJobsMeta] = useState({ total: 0, page: 1, pages: 1, limit: 20 });
  const [jobsFilter, setJobsFilter] = useState('all');
  const [jobsPage, setJobsPage] = useState(1);
  const [jobsBusy, setJobsBusy] = useState(false);
  const [showHistory, setShowHistory] = useState(false);

  const isRunning = ['queued', 'running'].includes(String(status.status || '').toLowerCase());
  const isOcrRunning = ocrJob?.status === 'running' || ocrJob?.status === 'queued';

  // ── Loaders ──────────────────────────────────────────────────────────────
  const loadSettings = useCallback(async () => {
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
    setTrainScope(asBool(cfg.train_new_only_default, true) ? 'new_only' : 'all');
  }, [token]);

  const loadJobs = useCallback(async ({ page = jobsPage, status: st = jobsFilter, silent = false } = {}) => {
    if (!silent) setJobsBusy(true);
    try {
      const q = new URLSearchParams({ page: String(page), limit: '20', status: String(st || 'all') });
      const res = await request(`/api/v1/training/jobs?${q}`, { token });
      setJobs(Array.isArray(res.items) ? res.items : []);
      setJobsMeta({ total: Number(res.total || 0), page: Number(res.page || 1), pages: Number(res.pages || 1), limit: Number(res.limit || 20) });
    } catch { /* silent */ }
    finally { if (!silent) setJobsBusy(false); }
  }, [token, jobsPage, jobsFilter]);

  // ── Status polling (always on) ──────────────────────────────────────────
  useEffect(() => {
    let timer; let alive = true;
    let lastWasRunning = false;
    const loop = async () => {
      try {
        const st = await request('/api/v1/training/status', { token });
        if (!alive) return;
        const nowRunning = ['queued', 'running'].includes(String(st.status || '').toLowerCase());
        // Record the moment training transitions to running so we can compute ETA
        if (nowRunning && !lastWasRunning) {
          setTrainStartedTs(Date.now() / 1000);
        }
        if (!nowRunning && lastWasRunning) {
          // Job finished — keep startedTs for final ETA display but stop updating
        }
        lastWasRunning = nowRunning;
        setStatus({
          ...st,
          details: st.details || {},
          progress: Number(st.progress || 0),
          status: st.status || 'idle',
          stage: st.stage || 'idle',
          message: st.message || 'Idle',
        });
      } catch { /* ignore */ }
      if (alive) timer = setTimeout(loop, 2500);
    };
    loop();
    return () => { alive = false; clearTimeout(timer); };
  }, [token]);

  // ── Jobs polling ────────────────────────────────────────────────────────
  useEffect(() => { loadJobs({ page: jobsPage, status: jobsFilter }); }, [token, jobsPage, jobsFilter]);

  useEffect(() => {
    let timer; let alive = true;
    const tick = async () => {
      if (!alive) return;
      if (isRunning) await loadJobs({ page: jobsPage, status: jobsFilter, silent: true });
      if (alive) timer = setTimeout(tick, isRunning ? 4000 : 20000);
    };
    tick();
    return () => { alive = false; clearTimeout(timer); };
  }, [isRunning, jobsPage, jobsFilter]);

  useEffect(() => { loadSettings().catch(() => {}); }, [loadSettings]);

  // ── OCR job polling — survives page refresh by checking server state ────
  const ocrPollRef = useRef(null);

  const startOcrPolling = useCallback((jobId, knownStartedTs = null) => {
    if (ocrPollRef.current) clearTimeout(ocrPollRef.current);
    let alive = true;
    const poll = async () => {
      try {
        const res = await request(`/api/v1/training/ocr/prefill/${jobId}`, { token });
        if (!alive) return;
        const job = res?.job || {};
        // started_ts comes from backend (epoch seconds); fall back to now on first poll
        const startedTs = job.started_ts ?? knownStartedTs ?? (Date.now() / 1000);
        setOcrJob({
          id: jobId,
          status: job.status || 'running',
          progress: Number(job.progress || 0),
          message: job.message || '',
          result: job.result || null,
          error: job.error || null,
          startedTs,
        });
        if (job.status === 'complete') {
          const rr = job.result || {};
          pushToast(`OCR prefill done — updated ${rr.updated || 0}, skipped ${rr.skipped || 0} of ${rr.total || rr.scanned || 0} samples`);
          alive = false; return;
        }
        if (job.status === 'failed') {
          pushToast(job.error || job.message || 'OCR prefill failed', 'error');
          alive = false; return;
        }
      } catch { if (!alive) return; }
      if (alive) ocrPollRef.current = setTimeout(poll, 1300);
    };
    poll();
    return () => { alive = false; clearTimeout(ocrPollRef.current); };
  }, [token, pushToast]);

  // On mount: recover any in-progress OCR job from the server (survives page refresh)
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await request('/api/v1/training/ocr/prefill/latest', { token });
        if (cancelled) return;
        const job = res?.job;
        if (!job || !job.id) return;
        // Only reconnect if the job is still actively running
        if (job.status === 'running' || job.status === 'queued') {
          const startedTs = job.started_ts ?? (Date.now() / 1000);
          setOcrJob({
            id: job.id,
            status: job.status,
            progress: Number(job.progress || 0),
            message: job.message || '',
            result: job.result || null,
            error: job.error || null,
            startedTs,
          });
          startOcrPolling(job.id, startedTs);
        } else if (job.status === 'complete' || job.status === 'failed') {
          // Show final state but don't start polling
          setOcrJob({
            id: job.id,
            status: job.status,
            progress: Number(job.progress || 0),
            message: job.message || '',
            result: job.result || null,
            error: job.error || null,
            startedTs: job.started_ts ?? null,
          });
        }
      } catch { /* ignore — server may not have a latest job */ }
    })();
    return () => { cancelled = true; };
  }, [token]); // intentionally omit startOcrPolling to run only once on mount

  // ── Actions ─────────────────────────────────────────────────────────────
  async function startPipeline() {
    setStartBusy(true);
    try {
      const runOcrPrefill = pipelineMode !== 'train_only';
      const runOcrLearn = pipelineMode !== 'train_only';
      const doTrain = pipelineMode !== 'extract_only';

      if (pipelineMode === 'extract_only') {
        // Just run OCR prefill standalone
        await prefillOcrTexts();
        return;
      }

      const res = await request('/api/v1/training/start', {
        token, method: 'POST',
        body: {
          mode: trainScope,
          chunk_size: Number(settings.train_chunk_size),
          chunk_epochs: Number(settings.train_chunk_epochs),
          run_ocr_prefill: runOcrPrefill,
          run_ocr_learn: runOcrLearn,
        },
      });
      pushToast(res?.job?.id ? `Training job queued: ${res.job.id.slice(0, 8)}…` : 'Training started');
      const st = await request('/api/v1/training/status', { token });
      setStatus({ ...st, details: st.details || {}, progress: Number(st.progress || 0), status: st.status || 'idle', stage: st.stage || 'idle', message: st.message || 'Idle' });
    } catch (e) {
      if (String(e.message || '').toLowerCase().includes('already running')) {
        pushToast('A training job is already running — monitoring it now.', 'warn');
      } else {
        pushToast(e.message || 'Failed to start pipeline', 'error');
      }
    } finally { setStartBusy(false); }
  }

  async function stopPipeline() {
    setStopBusy(true);
    try {
      await request('/api/v1/training/stop', { token, method: 'POST' });
      pushToast('Stop signal sent — current chunk will finish safely.', 'warn');
    } catch (e) { pushToast(e.message || 'Failed to stop', 'error'); }
    finally { setStopBusy(false); }
  }

  async function downloadModel(jobId) {
    setDownloadBusy(true);
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
      pushToast('Model downloaded successfully.');
    } catch (e) { pushToast(e.message || 'Download failed', 'error'); }
    finally { setDownloadBusy(false); }
  }

  async function prefillOcrTexts() {
    setOcrBusy(true);
    try {
      const startedTs = Date.now() / 1000;
      const res = await request('/api/v1/training/ocr/prefill', { token, method: 'POST' });
      if (res?.job_id) {
        setOcrJob({ id: res.job_id, status: 'running', progress: 0, result: null, message: 'Queued…', startedTs });
        startOcrPolling(res.job_id, startedTs);
        pushToast('OCR prefill started — scanning all unfilled samples…');
      } else {
        pushToast('OCR prefill started.');
      }
    } catch (e) { pushToast(e.message || 'OCR prefill failed', 'error'); }
    finally { setOcrBusy(false); }
  }

  async function learnOcrCorrections() {
    setLearnBusy(true);
    try {
      const res = await request('/api/v1/training/ocr/learn', { token, method: 'POST' });
      pushToast(`OCR correction map updated — ${res.pairs || 0} pairs, ${res.replacements || 0} replacements`);
    } catch (e) { pushToast(e.message || 'OCR learning failed', 'error'); }
    finally { setLearnBusy(false); }
  }

  async function saveSettings() {
    setSaving(true);
    try {
      await request('/api/v1/training/settings', {
        token, method: 'POST',
        body: {
          ...settings,
          train_epochs: Number(settings.train_epochs),
          train_imgsz: Number(settings.train_imgsz),
          train_batch: Number(settings.train_batch),
          train_patience: Number(settings.train_patience),
          train_chunk_size: Number(settings.train_chunk_size),
          train_chunk_epochs: Number(settings.train_chunk_epochs),
          train_new_only_default: Boolean(settings.train_new_only_default),
          train_nightly_enabled: Boolean(settings.train_nightly_enabled),
          train_nightly_hour: Number(settings.train_nightly_hour),
          train_nightly_minute: Number(settings.train_nightly_minute),
          plate_min_length: Number(settings.plate_min_length),
          plate_max_length: Number(settings.plate_max_length),
          allowed_stationary_enabled: Boolean(settings.allowed_stationary_enabled),
          allowed_stationary_motion_threshold: Number(settings.allowed_stationary_motion_threshold),
          allowed_stationary_hold_seconds: Number(settings.allowed_stationary_hold_seconds),
        },
      });
      pushToast('Settings saved successfully.');
      await loadSettings();
    } catch (e) { pushToast(e.message || 'Failed to save settings', 'error'); }
    finally { setSaving(false); }
  }

  const logs = useMemo(() => (Array.isArray(status?.details?.logs) ? status.details.logs : []), [status?.details?.logs]);
  const progress = Math.max(0, Math.min(100, Number(status.progress || 0)));
  const ocrProgress = Math.max(0, Math.min(100, Number(ocrJob?.progress || 0)));

  return (
    <>
      {/* Toast layer */}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* Keyframe animations injected once */}
      <style>{`
        @keyframes slideIn { from { opacity:0; transform:translateX(20px); } to { opacity:1; transform:translateX(0); } }
        @keyframes pulseDot { 0%,100% { opacity:1; transform:scale(1); } 50% { opacity:.5; transform:scale(.7); } }
        @keyframes shimmer { 0% { background-position:200% 0; } 100% { background-position:-200% 0; } }
        @keyframes spin { to { transform:rotate(360deg); } }
        .spin { animation: spin 1s linear infinite; }
      `}</style>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 20, paddingBottom: 40 }}>

        {/* ── Dataset Stats ─────────────────────────────────────────────── */}
        <DatasetStats token={token} />

        {/* ── Pipeline Control ──────────────────────────────────────────── */}
        <Panel>
          <SectionHead icon={BrainCircuit} title="Training Pipeline" badge={
            <StatusBadge status={status.status} />
          } action={
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="tiny muted">{status.stage !== 'idle' ? status.stage : ''}</span>
            </div>
          } />

          {/* Mode selector */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10, marginBottom: 20 }}>
            {PIPELINE_MODES.map((m) => (
              <button key={m.value} onClick={() => setPipelineMode(m.value)}
                disabled={isRunning}
                style={{
                  padding: '12px 14px', borderRadius: 12, cursor: isRunning ? 'not-allowed' : 'pointer',
                  background: pipelineMode === m.value ? 'rgba(53,162,255,.18)' : 'rgba(255,255,255,.04)',
                  border: `1px solid ${pipelineMode === m.value ? 'rgba(53,162,255,.5)' : 'rgba(255,255,255,.1)'}`,
                  color: 'var(--text)', textAlign: 'left', transition: 'all .2s',
                }}>
                <div style={{ fontWeight: 600, fontSize: 13, marginBottom: 4, color: pipelineMode === m.value ? 'var(--accent)' : 'var(--text)' }}>{m.label}</div>
                <div style={{ fontSize: 11, color: 'var(--muted)', lineHeight: 1.45 }}>{m.desc}</div>
              </button>
            ))}
          </div>

          {/* Training scope (only relevant when training is included) */}
          {pipelineMode !== 'extract_only' && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 18 }}>
              <span className="tiny muted">Training scope:</span>
              <div style={{ display: 'flex', gap: 6 }}>
                {[
                  { value: 'new_only', label: 'New / Updated Only' },
                  { value: 'all', label: 'All Annotated' },
                ].map((opt) => (
                  <button key={opt.value} onClick={() => setTrainScope(opt.value)}
                    disabled={isRunning}
                    className={trainScope === opt.value ? 'btn primary' : 'btn ghost'}
                    style={{ fontSize: 12, padding: '5px 12px' }}>
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>
          )}

          {/* Action buttons */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20 }}>
            <button className="btn primary" onClick={startPipeline}
              disabled={startBusy || isRunning}
              style={{ gap: 7, minWidth: 130 }}>
              {startBusy ? <LoaderCircle size={15} className="spin" /> : <Play size={15} />}
              {startBusy ? 'Starting…' : isRunning ? 'Running…' : pipelineMode === 'extract_only' ? 'Run OCR Extract' : 'Start Pipeline'}
            </button>

            {isRunning && (
              <button className="btn" onClick={stopPipeline} disabled={stopBusy}
                style={{ gap: 7, background: 'rgba(255,94,126,.15)', border: '1px solid rgba(255,94,126,.4)', color: 'var(--bad)' }}>
                {stopBusy ? <LoaderCircle size={15} className="spin" /> : <Square size={15} />}
                {stopBusy ? 'Stopping…' : 'Stop'}
              </button>
            )}

            <button className="btn ghost" onClick={() => downloadModel()} disabled={downloadBusy} style={{ gap: 7, marginLeft: 'auto' }}>
              {downloadBusy ? <LoaderCircle size={14} className="spin" /> : <Download size={14} />}
              {downloadBusy ? 'Downloading…' : 'Download Model'}
            </button>
          </div>

          {/* Progress */}
          {(isRunning || progress > 0) && (
            <div style={{ marginBottom: 18 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6, flexWrap: 'wrap', gap: 4 }}>
                <span className="tiny muted">{status.message}</span>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {isRunning && trainStartedTs && (() => {
                    const eta = calcEta(progress, trainStartedTs);
                    return eta ? (
                      <span className="tiny" style={{ color: 'var(--warn)', fontWeight: 500 }}>⏱ {eta}</span>
                    ) : null;
                  })()}
                  <span className="tiny mono" style={{ color: 'var(--accent)' }}>{progress}%</span>
                </div>
              </div>
              <ProgressBar value={progress} animated={isRunning} />
            </div>
          )}

          {/* Runtime KPIs */}
          {(isRunning || status.total_samples > 0) && (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10, marginBottom: 20 }}>
              <KpiCard label="Selected" value={status.total_samples || 0} pulse={isRunning} />
              <KpiCard label="Trained" value={status.trained_samples || 0} accent={isRunning ? 'var(--accent)' : undefined} pulse={isRunning} />
              <KpiCard label="Chunk" value={`${status.chunk_index || 0} / ${status.chunk_total || 0}`} />
              <KpiCard label="OCR Updated" value={status.ocr_updated || 0} />
            </div>
          )}

          {/* Run info */}
          {(status.run_dir || status.last_run_dir) && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12, marginBottom: 16 }}>
              <div>
                <div className="tiny muted" style={{ marginBottom: 3 }}>Run directory</div>
                <div className="mono tiny" style={{ wordBreak: 'break-all', color: 'var(--muted)' }}>{status.run_dir || status.last_run_dir || '—'}</div>
              </div>
              <div>
                <div className="tiny muted" style={{ marginBottom: 3 }}>Model output</div>
                <div className="mono tiny" style={{ wordBreak: 'break-all', color: 'var(--muted)' }}>{status.model_path || status.last_model_path || '—'}</div>
              </div>
            </div>
          )}

          {/* Job log */}
          <div>
            <div className="tiny muted" style={{ marginBottom: 8 }}>Job log</div>
            <div style={{
              background: 'rgba(0,0,0,.3)', borderRadius: 10, padding: '12px 14px',
              border: '1px solid rgba(255,255,255,.07)',
              maxHeight: 160, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: 3,
            }}>
              {(logs.length ? logs.slice(-15).reverse() : ['No logs yet.']).map((line, i) => (
                <div key={`${line}-${i}`} className="tiny mono" style={{ color: 'var(--muted)', lineHeight: 1.5 }}>{line}</div>
              ))}
            </div>
          </div>
        </Panel>

        {/* ── Standalone OCR Tools ──────────────────────────────────────── */}
        <Panel>
          <SectionHead icon={ScanLine} title="OCR Tools" badge="Standalone" />

          <p className="tiny muted" style={{ marginBottom: 16, lineHeight: 1.6 }}>
            Run these independently from training. <strong style={{ color: 'var(--text)' }}>Auto Fill</strong> scans all annotated samples that have no plate text yet and applies OCR.
            <strong style={{ color: 'var(--text)' }}> Learn Corrections</strong> improves accuracy by studying manual edits in your dataset.
          </p>

          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
            <button className="btn ghost" onClick={prefillOcrTexts} disabled={ocrBusy || isOcrRunning}
              style={{ gap: 7, position: 'relative' }}>
              {(ocrBusy || isOcrRunning) ? <LoaderCircle size={14} className="spin" /> : <ScanLine size={14} />}
              {isOcrRunning ? `Scanning… ${ocrProgress}%` : ocrBusy ? 'Starting…' : 'Auto Fill Plate Text From Boxes'}
            </button>

            <button className="btn ghost" onClick={learnOcrCorrections} disabled={learnBusy} style={{ gap: 7 }}>
              {learnBusy ? <LoaderCircle size={14} className="spin" /> : <Zap size={14} />}
              {learnBusy ? 'Learning…' : 'Learn OCR Corrections'}
            </button>
          </div>

          {/* OCR job progress — persists across page refresh */}
          {ocrJob?.id && (
            <div style={{ marginTop: 16, padding: '16px 18px', borderRadius: 12, background: 'rgba(255,255,255,.04)', border: '1px solid rgba(255,255,255,.08)' }}>
              {/* Header row */}
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10, alignItems: 'center', flexWrap: 'wrap', gap: 8 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <StatusBadge status={ocrJob.status} />
                  <span className="tiny muted" style={{ maxWidth: 300, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{ocrJob.message}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                  {isOcrRunning && ocrJob.startedTs && (() => {
                    const eta = calcEta(ocrProgress, ocrJob.startedTs);
                    return eta ? (
                      <span className="tiny" style={{ color: 'var(--warn)', fontWeight: 500 }}>⏱ {eta}</span>
                    ) : null;
                  })()}
                  <span className="tiny mono" style={{ color: 'var(--ok)', fontWeight: 600 }}>{ocrProgress}%</span>
                </div>
              </div>

              {/* Progress bar */}
              <ProgressBar value={ocrProgress} animated={isOcrRunning} color="var(--ok)" />

              {/* Stats row — shown as the job runs (from result partial updates) */}
              {ocrJob.result && (
                <div style={{ marginTop: 10, display: 'flex', gap: 20, flexWrap: 'wrap' }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="tiny muted">Updated</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--ok)' }}>{(ocrJob.result.updated || 0).toLocaleString()}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="tiny muted">Skipped</span>
                    <span style={{ fontSize: 16, fontWeight: 700, color: 'var(--muted)' }}>{(ocrJob.result.skipped || 0).toLocaleString()}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span className="tiny muted">Scanned / Total</span>
                    <span style={{ fontSize: 16, fontWeight: 700 }}>
                      {(ocrJob.result.scanned || 0).toLocaleString()} / {(ocrJob.result.total || ocrJob.result.scanned || 0).toLocaleString()}
                    </span>
                  </div>
                </div>
              )}

              {/* Elapsed time */}
              {ocrJob.startedTs && (
                <div style={{ marginTop: 8 }}>
                  <span className="tiny muted">
                    Elapsed: {fmtDuration(Date.now() / 1000 - ocrJob.startedTs)}
                    {ocrJob.status === 'complete' ? ' (finished)' : ''}
                  </span>
                </div>
              )}
            </div>
          )}
        </Panel>

        {/* ── Model Accuracy Test ───────────────────────────────────────── */}
        <ModelTestPanel token={token} pushToast={pushToast} />

        {/* ── Training Settings ─────────────────────────────────────────── */}
        <Panel>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <button className="btn ghost" onClick={() => setShowSettings((s) => !s)}
              style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
              <Settings2 size={16} style={{ color: 'var(--accent)' }} />
              Training Settings
              {showSettings ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {showSettings && (
              <button className="btn primary" onClick={saveSettings} disabled={saving} style={{ gap: 7 }}>
                <Save size={14} />{saving ? 'Saving…' : 'Save Settings'}
              </button>
            )}
          </div>

          {showSettings && (
            <div style={{ marginTop: 20, display: 'flex', flexDirection: 'column', gap: 20 }}>
              {/* Model hyperparameters */}
              <div>
                <div className="tiny muted" style={{ marginBottom: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.04em', fontSize: 11 }}>Model & Hyperparameters</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}>
                  {[
                    { label: 'Base Model', key: 'train_model', type: 'text' },
                    { label: 'Chunk Size', key: 'train_chunk_size', type: 'number', min: 100, max: 5000 },
                    { label: 'Chunk Epochs', key: 'train_chunk_epochs', type: 'number', min: 1, max: 50 },
                    { label: 'Image Size', key: 'train_imgsz', type: 'number', min: 160, max: 1920 },
                    { label: 'Batch Size', key: 'train_batch', type: 'number', min: -1, max: 256 },
                    { label: 'Device', key: 'train_device', type: 'text' },
                    { label: 'Early Stop Patience', key: 'train_patience', type: 'number', min: 1, max: 200 },
                  ].map(({ label, key, type, min, max }) => (
                    <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      <label className="tiny muted">{label}</label>
                      <input type={type} min={min} max={max} value={settings[key]}
                        style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                        onChange={(e) => setSettings((s) => ({ ...s, [key]: type === 'number' ? e.target.value : e.target.value }))} />
                    </div>
                  ))}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <label className="tiny muted">Default Mode</label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                      <input type="checkbox" checked={!!settings.train_new_only_default}
                        onChange={(e) => setSettings((s) => ({ ...s, train_new_only_default: e.target.checked }))} />
                      Train New/Updated by default
                    </label>
                  </div>
                </div>
              </div>

              {/* Nightly schedule */}
              <div style={{ borderTop: '1px solid rgba(255,255,255,.07)', paddingTop: 20 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                  <ShieldCheck size={14} style={{ color: 'var(--accent)' }} />
                  <div className="tiny muted" style={{ fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.04em', fontSize: 11 }}>Nightly Schedule</div>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <label className="tiny muted">Enabled</label>
                    <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 13, cursor: 'pointer' }}>
                      <input type="checkbox" checked={!!settings.train_nightly_enabled}
                        onChange={(e) => setSettings((s) => ({ ...s, train_nightly_enabled: e.target.checked }))} />
                      Run every night
                    </label>
                  </div>
                  {[
                    { label: 'Hour (0–23)', key: 'train_nightly_hour', min: 0, max: 23 },
                    { label: 'Minute (0–59)', key: 'train_nightly_minute', min: 0, max: 59 },
                  ].map(({ label, key, min, max }) => (
                    <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      <label className="tiny muted">{label}</label>
                      <input type="number" min={min} max={max} value={settings[key]}
                        style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                        onChange={(e) => setSettings((s) => ({ ...s, [key]: e.target.value }))} />
                    </div>
                  ))}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <label className="tiny muted">Timezone</label>
                    <input value={settings.train_schedule_tz}
                      style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                      onChange={(e) => setSettings((s) => ({ ...s, train_schedule_tz: e.target.value }))} />
                  </div>
                </div>
              </div>

              {/* Plate profile */}
              <div style={{ borderTop: '1px solid rgba(255,255,255,.07)', paddingTop: 20 }}>
                <div className="tiny muted" style={{ marginBottom: 12, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.04em', fontSize: 11 }}>Plate Profile (OCR Guidance)</div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 14 }}>
                  {[
                    { label: 'Region', key: 'plate_region', type: 'text' },
                    { label: 'Min Length', key: 'plate_min_length', type: 'number', min: 1, max: 12 },
                    { label: 'Max Length', key: 'plate_max_length', type: 'number', min: 1, max: 16 },
                  ].map(({ label, key, type, min, max }) => (
                    <div key={key} style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                      <label className="tiny muted">{label}</label>
                      <input type={type} min={min} max={max} value={settings[key]}
                        style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                        onChange={(e) => setSettings((s) => ({ ...s, [key]: e.target.value }))} />
                    </div>
                  ))}
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <label className="tiny muted">Charset</label>
                    <select value={settings.plate_charset}
                      style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(20,30,50,1)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                      onChange={(e) => setSettings((s) => ({ ...s, plate_charset: e.target.value }))}>
                      <option value="alnum">Letters + Digits</option>
                      <option value="digits">Digits Only</option>
                      <option value="letters">Letters Only</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <label className="tiny muted">Plate Shape</label>
                    <select value={settings.plate_shape_hint}
                      style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(20,30,50,1)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                      onChange={(e) => setSettings((s) => ({ ...s, plate_shape_hint: e.target.value }))}>
                      <option value="standard">Standard</option>
                      <option value="long">Long Rectangle</option>
                      <option value="square">Square</option>
                      <option value="motorcycle">Motorcycle</option>
                    </select>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
                    <label className="tiny muted">Reference Date</label>
                    <input placeholder="2026-04" value={settings.plate_reference_date}
                      style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13 }}
                      onChange={(e) => setSettings((s) => ({ ...s, plate_reference_date: e.target.value }))} />
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 5, gridColumn: '1 / -1' }}>
                    <label className="tiny muted">Regex Pattern (optional)</label>
                    <input placeholder="^[A-Z]{3}[0-9]{3}$" value={settings.plate_pattern_regex}
                      style={{ padding: '7px 10px', borderRadius: 8, background: 'rgba(255,255,255,.06)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 13, fontFamily: 'monospace' }}
                      onChange={(e) => setSettings((s) => ({ ...s, plate_pattern_regex: e.target.value }))} />
                  </div>
                </div>
              </div>
            </div>
          )}
        </Panel>

        {/* ── Training History ──────────────────────────────────────────── */}
        <Panel>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: showHistory ? 12 : 0, borderBottom: showHistory ? '1px solid rgba(255,255,255,.07)' : 'none', marginBottom: showHistory ? 16 : 0 }}>
            <button className="btn ghost" onClick={() => { setShowHistory((s) => !s); if (!showHistory) loadJobs({ page: 1, status: jobsFilter }); }}
              style={{ display: 'flex', alignItems: 'center', gap: 8, fontWeight: 600 }}>
              <History size={16} style={{ color: 'var(--accent)' }} />
              Training History
              {jobsMeta.total > 0 && <span style={{ fontSize: 11, padding: '2px 7px', borderRadius: 99, background: 'rgba(255,255,255,.1)', color: 'var(--muted)' }}>{jobsMeta.total}</span>}
              {showHistory ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
            </button>
            {showHistory && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <select value={jobsFilter}
                  style={{ padding: '5px 10px', borderRadius: 8, background: 'rgba(20,30,50,1)', border: '1px solid rgba(255,255,255,.12)', color: 'var(--text)', fontSize: 12 }}
                  onChange={(e) => { setJobsFilter(e.target.value); setJobsPage(1); }}>
                  <option value="all">All</option>
                  <option value="queued">Queued</option>
                  <option value="running">Running</option>
                  <option value="stopped">Stopped</option>
                  <option value="complete">Complete</option>
                  <option value="failed">Failed</option>
                </select>
                <button className="btn ghost" onClick={() => loadJobs({ page: jobsPage, status: jobsFilter })} disabled={jobsBusy}>
                  <RefreshCw size={13} className={jobsBusy ? 'spin' : ''} />
                </button>
              </div>
            )}
          </div>

          {showHistory && (
            <>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Job ID</th><th>Status</th><th>Mode</th><th>Progress</th>
                      <th>Trained / Total</th><th>Duration</th><th>Started</th><th>Finished</th><th>Model</th>
                    </tr>
                  </thead>
                  <tbody>
                    {jobs.length ? jobs.map((job) => (
                      <tr key={job.id}>
                        <td className="mono tiny" title={job.id}>{job.id.slice(0, 10)}…</td>
                        <td><StatusBadge status={job.status} /></td>
                        <td className="tiny">{job.mode || '—'}</td>
                        <td>
                          <div style={{ display: 'flex', alignItems: 'center', gap: 6, minWidth: 80 }}>
                            <div style={{ flex: 1, background: 'rgba(255,255,255,.07)', borderRadius: 4, height: 5 }}>
                              <div style={{ width: `${Math.round(Number(job.progress || 0))}%`, height: '100%', background: 'var(--accent)', borderRadius: 4 }} />
                            </div>
                            <span className="tiny mono">{Math.round(Number(job.progress || 0))}%</span>
                          </div>
                        </td>
                        <td className="tiny mono">{Number(job.trained_samples || 0).toLocaleString()} / {Number(job.total_samples || 0).toLocaleString()}</td>
                        <td className="tiny">{fmtDuration(job.duration_seconds)}</td>
                        <td className="tiny">{fmtDate(job.started_at || job.run_started_at)}</td>
                        <td className="tiny">{fmtDate(job.finished_at)}</td>
                        <td>
                          <button className="btn ghost" onClick={() => downloadModel(job.id)}
                            disabled={!job.model_path || downloadBusy} title={job.model_path || 'No model artifact'}
                            style={{ padding: '4px 8px' }}>
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

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginTop: 12 }}>
                <span className="tiny muted">Total: {jobsMeta.total.toLocaleString()}</span>
                <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                  <button className="btn ghost" style={{ fontSize: 12, padding: '4px 10px' }}
                    onClick={() => setJobsPage((p) => Math.max(1, p - 1))} disabled={jobsMeta.page <= 1}>Prev</button>
                  <span className="tiny muted">Page {jobsMeta.page} / {jobsMeta.pages}</span>
                  <button className="btn ghost" style={{ fontSize: 12, padding: '4px 10px' }}
                    onClick={() => setJobsPage((p) => Math.min(Number(jobsMeta.pages || 1), p + 1))} disabled={jobsMeta.page >= jobsMeta.pages}>Next</button>
                </div>
              </div>
            </>
          )}
        </Panel>

      </div>
    </>
  );
}
