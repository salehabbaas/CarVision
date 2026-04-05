import { useEffect, useState } from 'react';
import { BellRing, CheckCheck } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function NotificationsPage() {
  const { token } = useAuth();
  const [items, setItems] = useState([]);
  const [unread, setUnread] = useState(0);

  async function load() {
    const res = await request('/api/v1/notifications?limit=150', { token });
    setItems(res.items || []);
    setUnread(res.unread || 0);
  }

  useEffect(() => {
    load().catch(() => null);
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

  return (
    <div className="stack">
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
