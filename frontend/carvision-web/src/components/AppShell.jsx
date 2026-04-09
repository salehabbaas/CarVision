import { useEffect, useRef, useState } from 'react';
import { Bell, BrainCircuit, CalendarClock, Camera, ChevronLeft, ChevronRight, FolderCheck, Gauge, ListChecks, LogOut, MonitorPlay, Network, Radar, ShieldCheck, Upload, Archive, Clapperboard, WifiOff, ServerCrash, RefreshCw } from 'lucide-react';
import { classifyError } from '../hooks/useApiQuery';
import { NavLink } from 'react-router-dom';
import { motion } from 'framer-motion';
import { useAuth } from '../context/AuthContext';
import { request } from '../lib/api';

const menu = [
  { to: '/', label: 'Dashboard', icon: Gauge },
  { to: '/live', label: 'Live DVR', icon: Radar },
  { to: '/detections', label: 'Detections', icon: ShieldCheck },
  { to: '/upload', label: 'Upload & Test', icon: Upload },
  { to: '/dataset-import', label: 'Dataset Import', icon: Archive },
  { to: '/trained-data', label: 'Trained Data', icon: Archive },
  { to: '/training-data', label: 'Training Data', icon: FolderCheck },
  { to: '/cameras', label: 'Cameras', icon: Camera },
  { to: '/allowed', label: 'Allowed Plates', icon: ListChecks },
  { to: '/discovery', label: 'Discovery', icon: Network },
  { to: '/training', label: 'Training', icon: BrainCircuit },
  { to: '/notifications', label: 'Notifications', icon: Bell },
  { to: '/clips', label: 'Clips', icon: Clapperboard },
];

export default function AppShell({ children }) {
  const { user, token, logout } = useAuth();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(true);
  const [now, setNow] = useState(() => new Date());
  const [onlineStreams, setOnlineStreams] = useState({ online: 0, total: 0 });
  const [notifOpen, setNotifOpen] = useState(false);
  const [notifItems, setNotifItems] = useState([]);
  const [notifUnread, setNotifUnread] = useState(0);
  const notifRef = useRef(null);
  // Network health tracking: count consecutive API failures
  const [apiError, setApiError] = useState(null);   // { type, message } | null
  const [apiFails, setApiFails] = useState(0);      // consecutive failure count
  const [apiBannerDismissed, setApiBannerDismissed] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    let alive = true;
    let timer;

    const load = async () => {
      try {
        const [cams, health] = await Promise.all([
          request('/api/v1/cameras', { token }),
          request('/api/v1/live/stream_health', { token }),
        ]);
        if (!alive) return;
        const liveCameras = (cams.items || []).filter((camera) => camera.enabled && camera.live_view);
        const healthItems = health.items || {};
        const online = liveCameras.filter((camera) => {
          const item = healthItems[camera.id];
          return item && typeof item.age === 'number' && item.age <= 5;
        }).length;
        setOnlineStreams({ online, total: liveCameras.length });
        // Clear network error on success
        setApiFails(0);
        setApiError(null);
        setApiBannerDismissed(false);
      } catch (err) {
        if (!alive) return;
        // Track consecutive failures — show banner after 2 in a row
        setApiFails((n) => {
          const next = n + 1;
          if (next >= 2) setApiError(classifyError(err));
          return next;
        });
      }
      timer = setTimeout(load, 5000);
    };

    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  useEffect(() => {
    let alive = true;
    let timer;

    const load = async () => {
      try {
        const res = await request('/api/v1/notifications?limit=8', { token });
        if (!alive) return;
        setNotifItems(res.items || []);
        setNotifUnread(res.unread || 0);
      } catch {
        // Notification polling is best-effort.
      }
      timer = setTimeout(load, 8000);
    };

    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  useEffect(() => {
    const onClick = (event) => {
      if (!notifRef.current || notifRef.current.contains(event.target)) return;
      setNotifOpen(false);
    };
    document.addEventListener('mousedown', onClick);
    return () => document.removeEventListener('mousedown', onClick);
  }, []);

  const timeLabel = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  const dateLabel = now.toLocaleDateString([], { weekday: 'short', year: 'numeric', month: 'short', day: 'numeric' });

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside className="sidebar glass" aria-label="Main navigation">
        <div className="brand">
          <span className="brand-dot" />
          <div className="brand-copy">
            <div className="brand-title">CarVision</div>
            <div className="brand-sub">by SpinelTech</div>
          </div>
          <button
            className="icon-btn sidebar-toggle"
            type="button"
            aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            onClick={() => setSidebarCollapsed((prev) => !prev)}
          >
            {sidebarCollapsed ? <ChevronRight size={14} /> : <ChevronLeft size={14} />}
          </button>
        </div>
        <nav className="menu">
          {menu.map((item) => {
            const Icon = item.icon;
            return (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `menu-item ${isActive ? 'active' : ''}`}
                end={item.to === '/'}
                title={item.label}
                aria-label={item.label}
              >
                <Icon size={16} />
                <span>{item.label}</span>
              </NavLink>
            );
          })}
        </nav>
      </aside>

      <main className="main-area">
        <header className="topbar glass">
          <motion.div
            initial={{ y: 6, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.25 }}
            className="topbar-title-wrap"
          >
            <h1>CarVision DVR</h1>
            <p className="muted">Realtime plate detection, feedback, and retraining.</p>
          </motion.div>
          <div className="topbar-right topbar-metrics">
            <div className="top-chip">
              <Gauge size={14} />
              <span>System</span>
              <strong>CarVision DVR</strong>
            </div>
            <div className="top-chip">
              <MonitorPlay size={14} />
              <span>Live Streams</span>
              <strong>{onlineStreams.online}/{onlineStreams.total}</strong>
            </div>
            <div className="top-chip">
              <CalendarClock size={14} />
              <span>{dateLabel}</span>
              <strong>{timeLabel}</strong>
            </div>
            <div className="top-chip">
              <Camera size={14} />
              <span>User</span>
              <strong>{user?.username || 'admin'}</strong>
            </div>
            <div className="notif-wrap" ref={notifRef}>
              <button
                className="btn ghost notif-btn"
                type="button"
                onClick={() => setNotifOpen((prev) => !prev)}
                aria-label="Open notifications"
              >
                <Bell size={15} />
                <span>Alerts</span>
                <span className={`tag ${notifUnread ? 'bad' : 'muted'}`}>{notifUnread}</span>
              </button>
              {notifOpen ? (
                <div className="notif-popover glass">
                  <div className="notif-popover-head">
                    <strong>Notifications</strong>
                    <NavLink to="/notifications" className="tiny-link" onClick={() => setNotifOpen(false)}>
                      Open center
                    </NavLink>
                  </div>
                  <div className="notif-popover-list">
                    {notifItems.map((item) => (
                      <div key={item.id} className={`notif-mini ${item.is_read ? 'read' : 'unread'}`}>
                        <strong>{item.title}</strong>
                        <p>{item.message}</p>
                      </div>
                    ))}
                    {!notifItems.length ? <div className="tiny muted">No notifications.</div> : null}
                  </div>
                </div>
              ) : null}
            </div>
            <button className="btn ghost" onClick={logout}>
              <LogOut size={15} /> Logout
            </button>
          </div>
        </header>
        {/* ── Global network connectivity banner ── */}
        {apiError && !apiBannerDismissed && apiFails >= 2 && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '8px 20px',
            background: apiError.type === 'network'
              ? 'rgba(255,94,126,0.15)' : 'rgba(255,191,71,0.13)',
            borderBottom: `1px solid ${apiError.type === 'network'
              ? 'rgba(255,94,126,0.35)' : 'rgba(255,191,71,0.35)'}`,
            zIndex: 200, flexShrink: 0,
            fontSize: 12,
          }}>
            {apiError.type === 'network'
              ? <WifiOff size={14} style={{ color: 'var(--bad)', flexShrink: 0 }} />
              : <ServerCrash size={14} style={{ color: 'var(--warn)', flexShrink: 0 }} />}
            <span style={{ fontWeight: 600, color: apiError.type === 'network' ? 'var(--bad)' : 'var(--warn)', flexShrink: 0 }}>
              {apiError.type === 'network' ? 'Server unreachable' : 'Server error'}
            </span>
            <span style={{ color: 'var(--muted)', flex: 1 }}>
              {apiFails >= 5
                ? 'CarVision backend has been unreachable for a while. Make sure Docker is running.'
                : `${apiError.message} — retrying every 5 s…`}
            </span>
            <div className="spinner-sm" style={{
              borderTopColor: apiError.type === 'network' ? 'var(--bad)' : 'var(--warn)',
              borderColor: apiError.type === 'network'
                ? 'rgba(255,94,126,0.2)' : 'rgba(255,191,71,0.2)',
            }} />
            <button
              type="button"
              className="btn ghost"
              style={{ height: 24, padding: '0 8px', fontSize: 10, flexShrink: 0 }}
              onClick={() => setApiBannerDismissed(true)}
            >
              ×
            </button>
          </div>
        )}
        <section className="page-content">{children}</section>
      </main>
    </div>
  );
}
