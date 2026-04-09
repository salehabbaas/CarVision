import { useEffect, useState } from 'react';
import { BellRing, CheckCheck } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { LoadingState, ErrorState } from '../components/PageState';

export default function NotificationsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);
  const [pageLoading, setPageLoading] = useState(true);
  const [error, setError] = useState('');

  async function load() {
    const res = await request('/api/v1/notifications?limit=150', { token });
    setItems(res.items || []);
    setUnread(res.unread || 0);
    setError('');
  }

  useEffect(() => {
    load().catch((err) => setError(err.message || 'Failed to load notifications')).finally(() => setPageLoading(false));
    const t = setInterval(() => load().catch(() => null), 4000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function markRead(id) {
    await request(`/api/v1/notifications/${id}/read`, { token, method: 'POST' });
    load();
  }

  async function markAll() {
    await request('/api/v1/notifications/read_all', { token, method: 'POST' });
    load();
  }

  if (pageLoading) return <LoadingState rows={4} message="Loading notifications…" />;
  if (error && !items.length) return <ErrorState error={{ message: error, type: 'unknown' }} onRetry={() => { setPageLoading(true); load().catch(e => setError(e.message)).finally(() => setPageLoading(false)); }} />;

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      <div className="panel glass toolbar between">
        <div className="row"><BellRing size={16} /> <strong>Notification Center</strong> <span className="tag bad">Unread {unread}</span></div>
        <button className="btn" onClick={markAll}><CheckCheck size={15} /> Mark all read</button>
      </div>

      <div className="notif-list">
        {items.map((n) => (
          <div key={n.id} className={`notif card ${n.is_read ? 'read' : 'unread'}`}>
            <div>
              <strong>{n.title}</strong>
              <p>{n.message}</p>
              <span className="tiny muted">{n.created_at ? new Date(n.created_at).toLocaleString() : '-'}</span>
            </div>
            {!n.is_read && <button className="btn ghost" onClick={() => markRead(n.id)}>Read</button>}
          </div>
        ))}
        {!items.length && <div className="panel glass empty">No notifications yet.</div>}
      </div>
    </div>
  );
}
