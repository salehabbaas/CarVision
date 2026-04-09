/**
 * Reusable page-state components:
 *  <LoadingState />   – skeleton/spinner shown while data is loading
 *  <ErrorState />     – classified error with retry button
 *  <StaleBanner />    – small banner when polling fails but old data is visible
 *  <EmptyState />     – no results found
 */
import { AlertTriangle, RefreshCw, WifiOff, ShieldOff, ServerCrash, HelpCircle } from 'lucide-react';

// ── Skeleton row ──────────────────────────────────────────────────────────────
function SkeletonLine({ width = '100%', height = 14, style }) {
  return (
    <div
      className="skeleton"
      style={{ width, height, borderRadius: 6, ...style }}
    />
  );
}

function SkeletonCard() {
  return (
    <div className="panel glass" style={{ padding: 16, borderRadius: 12, display: 'flex', flexDirection: 'column', gap: 10 }}>
      <SkeletonLine width="45%" height={12} />
      <SkeletonLine width="90%" height={18} />
      <SkeletonLine width="65%" height={11} />
    </div>
  );
}

// ── LoadingState ──────────────────────────────────────────────────────────────
export function LoadingState({ rows = 3, message = 'Loading data…', inline = false }) {
  if (inline) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '20px 0', color: 'var(--muted)' }}>
        <div className="spinner-sm" />
        <span style={{ fontSize: 13 }}>{message}</span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
      {Array.from({ length: rows }).map((_, i) => (
        <SkeletonCard key={i} />
      ))}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 4px', color: 'var(--muted)' }}>
        <div className="spinner-sm" />
        <span style={{ fontSize: 12 }}>{message}</span>
      </div>
    </div>
  );
}

// ── Error icon by type ─────────────────────────────────────────────────────────
const ERROR_META = {
  network:    { Icon: WifiOff,      title: 'Cannot reach server',   hint: 'Check your network connection and that the CarVision backend is running.' },
  auth:       { Icon: ShieldOff,    title: 'Session expired',       hint: 'Your login session may have expired. Try refreshing the page.' },
  permission: { Icon: ShieldOff,    title: 'Access denied',         hint: 'You do not have permission to view this resource.' },
  server:     { Icon: ServerCrash,  title: 'Server error',          hint: 'The server encountered an internal error. Check the backend logs.' },
  unknown:    { Icon: HelpCircle,   title: 'Something went wrong',  hint: 'An unexpected error occurred.' },
};

// ── ErrorState (full page error) ──────────────────────────────────────────────
export function ErrorState({ error, onRetry, compact = false }) {
  const meta = ERROR_META[error?.type] || ERROR_META.unknown;
  const { Icon, title, hint } = meta;

  if (compact) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', gap: 10,
        padding: '12px 16px', borderRadius: 10,
        background: 'rgba(255,94,126,0.1)', border: '1px solid rgba(255,94,126,0.3)',
      }}>
        <Icon size={16} style={{ color: 'var(--bad)', flexShrink: 0 }} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--bad)' }}>{title}: </span>
          <span style={{ fontSize: 12, color: 'var(--muted)' }}>{error?.message}</span>
        </div>
        {onRetry && (
          <button type="button" className="btn ghost" style={{ flexShrink: 0, height: 28, fontSize: 11 }} onClick={onRetry}>
            <RefreshCw size={11} /> Retry
          </button>
        )}
      </div>
    );
  }

  return (
    <div style={{
      display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
      gap: 14, padding: '48px 24px', textAlign: 'center',
    }}>
      <div style={{
        width: 64, height: 64, borderRadius: '50%',
        background: 'rgba(255,94,126,0.12)', border: '1px solid rgba(255,94,126,0.3)',
        display: 'grid', placeItems: 'center',
      }}>
        <Icon size={28} style={{ color: 'var(--bad)' }} />
      </div>
      <div>
        <div style={{ fontWeight: 700, fontSize: 17, marginBottom: 6 }}>{title}</div>
        <div style={{ color: 'var(--muted)', fontSize: 13, maxWidth: 380 }}>{error?.message || hint}</div>
        <div style={{ color: 'var(--muted)', fontSize: 12, marginTop: 6, maxWidth: 380 }}>{hint}</div>
      </div>
      {onRetry && (
        <button type="button" className="btn" onClick={onRetry}>
          <RefreshCw size={14} /> Try Again
        </button>
      )}
    </div>
  );
}

// ── StaleBanner (shown when polling fails but old data is still displayed) ─────
export function StaleBanner({ error, onRetry }) {
  if (!error) return null;
  const meta = ERROR_META[error?.type] || ERROR_META.unknown;
  const { Icon, title } = meta;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 8,
      padding: '6px 12px', borderRadius: 8, marginBottom: 8,
      background: 'rgba(255,191,71,0.1)', border: '1px solid rgba(255,191,71,0.3)',
      fontSize: 12,
    }}>
      <Icon size={13} style={{ color: 'var(--warn)', flexShrink: 0 }} />
      <span style={{ color: 'var(--warn)', fontWeight: 600 }}>{title}:</span>
      <span style={{ color: 'var(--muted)', flex: 1 }}>{error.message} — showing last known data</span>
      {onRetry && (
        <button type="button" className="btn ghost" style={{ height: 22, padding: '0 8px', fontSize: 10 }} onClick={onRetry}>
          <RefreshCw size={10} /> Retry
        </button>
      )}
    </div>
  );
}

// ── EmptyState ────────────────────────────────────────────────────────────────
export function EmptyState({ message = 'No data found', sub }) {
  return (
    <div style={{ textAlign: 'center', color: 'var(--muted)', padding: '48px 24px' }}>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{message}</div>
      {sub && <div style={{ fontSize: 12 }}>{sub}</div>}
    </div>
  );
}

// ── NetworkBanner (shown in AppShell when API is unreachable) ─────────────────
export function NetworkBanner({ consecutive = 0, onDismiss }) {
  if (consecutive < 2) return null;

  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10,
      padding: '8px 16px',
      background: 'rgba(255,94,126,0.15)',
      borderBottom: '1px solid rgba(255,94,126,0.35)',
      zIndex: 200, flexShrink: 0,
    }}>
      <WifiOff size={14} style={{ color: 'var(--bad)', flexShrink: 0 }} />
      <span style={{ fontSize: 12, color: 'var(--bad)', fontWeight: 600 }}>Server unreachable</span>
      <span style={{ fontSize: 12, color: 'var(--muted)', flex: 1 }}>
        {consecutive >= 5
          ? 'Connection lost — the backend has been unreachable for a while. Check that CarVision is running.'
          : 'Cannot reach the backend — retrying automatically…'}
      </span>
      <div className="spinner-sm" style={{ borderTopColor: 'var(--bad)', borderColor: 'rgba(255,94,126,0.25)' }} />
    </div>
  );
}
