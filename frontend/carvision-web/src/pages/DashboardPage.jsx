import { useMemo } from 'react';
import { motion } from 'framer-motion';
import { Activity, BadgeCheck, Camera, ShieldAlert, Bell, Users, ClipboardCheck } from 'lucide-react';
import { useApiQuery } from '../hooks/useApiQuery';
import { LoadingState, ErrorState, StaleBanner } from '../components/PageState';
import {
  Chart as ChartJS,
  ArcElement,
  CategoryScale,
  Filler,
  Legend,
  LineElement,
  BarElement,
  LinearScale,
  PointElement,
  Tooltip,
} from 'chart.js';
import { Bar, Doughnut, Line } from 'react-chartjs-2';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';


ChartJS.register(
  ArcElement,
  CategoryScale,
  Filler,
  Legend,
  LineElement,
  BarElement,
  LinearScale,
  PointElement,
  Tooltip
);

const cards = [
  { key: 'detections', label: 'Detections', icon: Activity },
  { key: 'active_cameras', label: 'Active Cameras', icon: Camera },
  { key: 'allowed', label: 'Allowed', icon: BadgeCheck },
  { key: 'denied', label: 'Denied', icon: ShieldAlert },
  { key: 'unread_notifications', label: 'Unread Alerts', icon: Bell },
  { key: 'users_active', label: 'Active Users (Upcoming)', icon: Users, futureKey: 'users.active' },
  { key: 'actions_pending', label: 'Pending Actions (Upcoming)', icon: ClipboardCheck, futureKey: 'actions.pending' },
];

function getNestedValue(obj, path) {
  if (!path) return undefined;
  return path.split('.').reduce((acc, key) => (acc ? acc[key] : undefined), obj);
}

function chartOptions(legend = true) {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: legend, labels: { color: '#c9dbf7' } },
      tooltip: { enabled: true },
    },
    scales: {
      x: { ticks: { color: '#9bb2d1' }, grid: { color: 'rgba(143, 173, 204, 0.12)' } },
      y: {
        ticks: { color: '#9bb2d1' },
        grid: { color: 'rgba(143, 173, 204, 0.12)' },
        beginAtZero: true,
      },
    },
  };
}

export default function DashboardPage() {
  const { token } = useAuth();

  const { data, loading, error, refetch, lastUpdated } = useApiQuery(
    () => request('/api/v1/dashboard/summary', { token }),
    { pollInterval: 5000, deps: [token], keepOnError: true },
  );

  const totals = data?.totals || {};
  const details = data?.details || {};
  const charts = data?.charts || {};
  const training = data?.training || {};
  const future = data?.future_metrics || {};
  const events = data?.recent_events || [];

  const lineData = useMemo(
    () => ({
      labels: charts.hourly_activity?.labels || [],
      datasets: [
        {
          label: 'Detections',
          data: charts.hourly_activity?.detections || [],
          borderColor: '#35a2ff',
          backgroundColor: 'rgba(53, 162, 255, 0.24)',
          fill: true,
          tension: 0.32,
          pointRadius: 2,
        },
        {
          label: 'Allowed',
          data: charts.hourly_activity?.allowed || [],
          borderColor: '#1cd9a4',
          backgroundColor: 'rgba(28, 217, 164, 0.15)',
          fill: false,
          tension: 0.32,
          pointRadius: 2,
        },
        {
          label: 'Denied',
          data: charts.hourly_activity?.denied || [],
          borderColor: '#ff5e7e',
          backgroundColor: 'rgba(255, 94, 126, 0.15)',
          fill: false,
          tension: 0.32,
          pointRadius: 2,
        },
      ],
    }),
    [charts]
  );

  const statusData = useMemo(
    () => ({
      labels: charts.status_breakdown?.labels || [],
      datasets: [
        {
          data: charts.status_breakdown?.values || [],
          backgroundColor: ['#1cd9a4', '#ff5e7e', '#5a6d8a'],
          borderColor: 'rgba(7, 13, 22, 0.6)',
          borderWidth: 2,
        },
      ],
    }),
    [charts]
  );

  const cameraData = useMemo(
    () => ({
      labels: charts.top_cameras?.labels || [],
      datasets: [
        {
          label: 'Detections (24h)',
          data: charts.top_cameras?.values || [],
          backgroundColor: 'rgba(53, 162, 255, 0.7)',
          borderRadius: 8,
          borderSkipped: false,
        },
      ],
    }),
    [charts]
  );

  const usersActionsData = useMemo(
    () => ({
      labels: charts.future_users_actions?.labels || [],
      datasets: [
        {
          label: 'Users',
          data: charts.future_users_actions?.users || [],
          borderColor: '#a77dff',
          backgroundColor: 'rgba(167, 125, 255, 0.2)',
          fill: true,
          tension: 0.34,
          pointRadius: 2,
        },
        {
          label: 'Actions',
          data: charts.future_users_actions?.actions || [],
          borderColor: '#ffbf47',
          backgroundColor: 'rgba(255, 191, 71, 0.2)',
          fill: true,
          tension: 0.34,
          pointRadius: 2,
        },
      ],
    }),
    [charts]
  );

  // First load — show skeleton
  if (loading && !data) return <LoadingState rows={4} message="Loading dashboard…" />;

  // Permanent failure on first load — no stale data to show
  if (error && !data) return <ErrorState error={error} onRetry={refetch} />;

  return (
    <div className="stack">
      {/* Stale data banner — shown when polling fails but old data is visible */}
      <StaleBanner error={error} onRetry={refetch} />

      <div className="panel glass toolbar between">
        <div className="row">
          <span className={`status-pill ${training.status || 'idle'}`}>{training.status || 'idle'}</span>
          <span className="muted">{training.message || 'No training job yet.'}</span>
        </div>
        <div className="tiny muted">
          Last update: {lastUpdated ? lastUpdated.toLocaleTimeString() : '--'}
        </div>
      </div>

      <div className="card-grid">
        {cards.map((card, idx) => {
          const Icon = card.icon;
          const value = card.futureKey ? getNestedValue(future, card.futureKey) : totals[card.key];
          return (
            <motion.div
              key={card.key}
              className="metric-card glass"
              initial={{ y: 14, opacity: 0 }}
              animate={{ y: 0, opacity: 1 }}
              transition={{ duration: 0.25, delay: idx * 0.03 }}
            >
              <div className="metric-label">{card.label}</div>
              <div className="metric-value">{value ?? 0}</div>
              <Icon className="metric-icon" size={20} />
            </motion.div>
          );
        })}
      </div>

      <div className="dashboard-grid">
        <div className="panel glass chart-panel">
          <div className="panel-head">
            <h3>Detection Activity (24h)</h3>
            <span className="tiny muted">{details.recent_24h_total || 0} events</span>
          </div>
          <div className="chart-wrap">
            <Line data={lineData} options={chartOptions(true)} />
          </div>
        </div>

        <div className="panel glass chart-panel">
          <div className="panel-head">
            <h3>Status Distribution</h3>
            <span className="tiny muted">
              allow {details.allowed_rate_24h ?? 0}% / deny {details.denied_rate_24h ?? 0}%
            </span>
          </div>
          <div className="chart-wrap">
            <Doughnut
              data={statusData}
              options={{
                ...chartOptions(true),
                scales: undefined,
              }}
            />
          </div>
        </div>

        <div className="panel glass chart-panel">
          <div className="panel-head">
            <h3>Top Cameras (24h)</h3>
            <span className="tiny muted">Live ranking</span>
          </div>
          <div className="chart-wrap">
            <Bar data={cameraData} options={chartOptions(false)} />
          </div>
        </div>

        <div className="panel glass chart-panel">
          <div className="panel-head">
            <h3>Users & Actions (Upcoming)</h3>
            <span className="tiny muted">Future-ready chart</span>
          </div>
          <div className="chart-wrap">
            <Line data={usersActionsData} options={chartOptions(true)} />
          </div>
        </div>
      </div>

      <div className="split two-col">
        <div className="panel glass">
          <div className="panel-head">
            <h3>Recent Detection Events</h3>
            <span className="tiny muted">Last 8</span>
          </div>
          <div className="events-list">
            {events.map((event) => (
              <div className="event-item" key={event.id}>
                <div>
                  <div className="row">
                    <strong className="mono">{event.plate_text || `#${event.id}`}</strong>
                    <span className={`tag ${event.status === 'allowed' ? 'ok' : 'bad'}`}>{event.status || 'unknown'}</span>
                  </div>
                  <div className="tiny muted">{event.camera_name || 'Unknown camera'}</div>
                </div>
                <div className="tiny muted">{event.detected_at ? new Date(event.detected_at).toLocaleTimeString() : '--'}</div>
              </div>
            ))}
            {!events.length ? <div className="empty">No detection events yet.</div> : null}
          </div>
        </div>

        <div className="panel glass">
          <div className="panel-head">
            <h3>System Details</h3>
          </div>
          <div className="param-grid">
            <div className="param-item">
              <span className="tiny muted">Last run dir</span>
              <span className="mono tiny">{training.last_run_dir || '-'}</span>
            </div>
            <div className="param-item">
              <span className="tiny muted">Model path</span>
              <span className="mono tiny">{training.last_model_path || '-'}</span>
            </div>
            <div className="param-item">
              <span className="tiny muted">Last detection</span>
              <span className="mono tiny">{details.last_detection_at ? new Date(details.last_detection_at).toLocaleString() : '-'}</span>
            </div>
            <div className="param-item">
              <span className="tiny muted">Top plate today</span>
              <span className="mono tiny">{charts.top_plates?.labels?.[0] || '-'}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
