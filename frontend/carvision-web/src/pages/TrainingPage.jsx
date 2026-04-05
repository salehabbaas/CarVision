import { useEffect, useState } from 'react';
import { Play, Zap } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function TrainingPage() {
  const { token } = useAuth();
  const [status, setStatus] = useState({ status: 'idle', message: 'Idle' });
  const [settings, setSettings] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let timer;
    let alive = true;
    const load = async () => {
      try {
        const [st, cfg] = await Promise.all([
          request('/api/v1/training/status', { token }),
          request('/api/v1/training/settings', { token }),
        ]);
        if (!alive) return;
        setStatus(st);
        setSettings(cfg);
      } catch (err) {
        if (!alive) return;
        setError(err.message || 'Failed to load training status');
      }
      timer = setTimeout(load, 3000);
    };
    load();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  async function startTraining() {
    setError('');
    try {
      await request('/api/v1/training/start', {
        token,
        method: 'POST',
      });
    } catch (err) {
      setError(err.message || 'Failed to start training');
    }
  }

  const progress = status.status === 'running' ? 70 : status.status === 'complete' ? 100 : status.status === 'failed' ? 100 : 0;

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}

      <div className="panel glass">
        <div className="panel-head">
          <h3>Training Runner</h3>
          <button className="btn primary" onClick={startTraining} disabled={status.status === 'running'}>
            <Play size={15} /> Start Training
          </button>
        </div>
        <div className="status-row">
          <span className={`status-pill ${status.status}`}>{status.status}</span>
          <span className="muted">{status.message}</span>
        </div>
        <div className="progress-wrap">
          <div className="progress-bar" style={{ width: `${progress}%` }} />
        </div>
        <div className="row two">
          <div>
            <div className="tiny">Run directory</div>
            <div className="mono">{status.last_run_dir || '-'}</div>
          </div>
          <div>
            <div className="tiny">Model output</div>
            <div className="mono">{status.last_model_path || '-'}</div>
          </div>
        </div>
      </div>

      <div className="panel glass">
        <div className="panel-head"><h3><Zap size={15} /> Parameters</h3></div>
        {!settings ? (
          <div className="muted">Loading…</div>
        ) : (
          <div className="param-grid">
            {Object.entries(settings).map(([k, v]) => (
              <div key={k} className="param-item">
                <span className="tiny">{k}</span>
                <strong>{String(v)}</strong>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
