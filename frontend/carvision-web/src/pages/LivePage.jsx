import { useEffect, useMemo, useState } from 'react';
import { Maximize2, Pin, PinOff } from 'lucide-react';
import { request, apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';

const layouts = [4, 8, 16];

export default function LivePage() {
  const { token } = useAuth();
  const [cameras, setCameras] = useState([]);
  const [gridSize, setGridSize] = useState(8);
  const [pinnedId, setPinnedId] = useState(null);
  const [health, setHealth] = useState({});

  useEffect(() => {
    let timer;
    let alive = true;
    const load = async () => {
      try {
        const [camRes, healthRes] = await Promise.all([
          request('/api/v1/cameras', { token }),
          request('/api/v1/live/stream_health', { token }),
        ]);
        if (!alive) return;
        setCameras((camRes.items || []).filter((c) => c.enabled && c.live_view));
        setHealth(healthRes.items || {});
      } catch {
        // keep silent in UI for polling errors
      }
      timer = setTimeout(load, 4000);
    };

    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  const visible = useMemo(() => {
    if (pinnedId) {
      const pinned = cameras.find((c) => c.id === pinnedId);
      return pinned ? [pinned] : cameras.slice(0, gridSize);
    }
    return cameras.slice(0, gridSize);
  }, [cameras, gridSize, pinnedId]);

  return (
    <div className="stack">
      <div className="panel glass toolbar between">
        <div className="row">
          {layouts.map((n) => (
            <button key={n} className={`btn ${gridSize === n ? 'primary' : ''}`} onClick={() => setGridSize(n)}>{n} View</button>
          ))}
        </div>
        <div className="row">
          <button className="btn ghost" onClick={() => setPinnedId(null)}><PinOff size={15} /> Clear pin</button>
        </div>
      </div>

      <div className={`live-grid cols-${pinnedId ? 1 : Math.min(4, Math.ceil(Math.sqrt(gridSize)))}`}>
        {visible.map((cam) => {
          const itemHealth = health[cam.id] || {};
          const age = itemHealth.age;
          const stale = typeof age === 'number' && age > 5;
          const streamSrc = apiPath(`/stream/${cam.id}?overlay=1&token=${encodeURIComponent(token)}`);
          return (
            <div key={cam.id} className="camera-card glass">
              <div className="camera-head">
                <div>
                  <strong>{cam.name}</strong>
                  <div className="tiny muted">{cam.location || 'No location'}</div>
                </div>
                <div className="row">
                  <span className={`tag ${stale ? 'bad' : 'ok'}`}>{stale ? 'stale' : 'live'}</span>
                  <button className="icon-btn" onClick={() => setPinnedId((prev) => (prev === cam.id ? null : cam.id))}>
                    <Pin size={14} />
                  </button>
                  <a className="icon-btn" href={streamSrc} target="_blank" rel="noreferrer"><Maximize2 size={14} /></a>
                </div>
              </div>
              <div className="camera-feed">
                <img src={streamSrc} alt={cam.name} loading="lazy" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
