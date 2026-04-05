import { useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import { Activity, BadgeCheck, Camera, ShieldAlert, Bell } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

const cards = [
  { key: 'detections', label: 'Detections', icon: Activity },
  { key: 'active_cameras', label: 'Active Cameras', icon: Camera },
  { key: 'allowed', label: 'Allowed', icon: BadgeCheck },
  { key: 'denied', label: 'Denied', icon: ShieldAlert },
  { key: 'unread_notifications', label: 'Unread Alerts', icon: Bell },
];

export default function DashboardPage() {
  const { token } = useAuth();
  const [data, setData] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let timer;
    let alive = true;

    const load = async () => {
      try {
        const res = await request('/api/v1/dashboard/summary', { token });
        if (!alive) return;
        setData(res);
      } catch (err) {
        if (!alive) return;
        setError(err.message || 'Failed to load summary');
      }
      timer = setTimeout(load, 5000);
    };

    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  const totals = data?.totals || {};
  const status = data?.training || {};

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      <div className="card-grid">
        {cards.map((card, idx) => {
          const Icon = card.icon;
          return (
            <motion.div
              key={card.key}
              className="metric-card glass"
              initial={{ y: 14, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ duration: 0.25, delay: idx * 0.04 }}
            >
              <div className="metric-label">{card.label}</div>
              <div className="metric-value">{totals[card.key] ?? '-'}</div>
              <Icon className="metric-icon" size={20} />
            </motion.div>
          );
        })}
      </div>

      <motion.div className="panel glass" initial={{ opacity: 0 }} animate={{ opacity: 1 }}>
        <div className="panel-head">
          <h3>Training Process</h3>
          <span className={`status-pill ${status.status || 'idle'}`}>{status.status || 'idle'}</span>
        </div>
        <p className="muted">{status.message || 'No training job yet.'}</p>
        <div className="row two">
          <div>
            <div className="tiny">Last run dir</div>
            <div className="mono">{status.last_run_dir || '-'}</div>
          </div>
          <div>
            <div className="tiny">Model path</div>
            <div className="mono">{status.last_model_path || '-'}</div>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
