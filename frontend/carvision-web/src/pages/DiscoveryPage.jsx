import { useState } from 'react';
import { Radar, Search, Plus } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function DiscoveryPage() {
  const { token } = useAuth();
  const [timeout, setTimeoutVal] = useState(3);
  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [creds, setCreds] = useState({});

  async function runDiscovery() {
    const res = await request(`/api/v1/discovery/run?timeout=${Number(timeout) || 3}`, { token });
    setResult(res || { devices: [] });
  }

  async function resolveProfiles(xaddr) {
    const c = creds[xaddr] || {};
    if (!c.username || !c.password) {
      setError('Provide username/password before resolve.');
      return;
    }
    const out = await request('/api/v1/discovery/resolve', {
      token,
      method: 'POST',
      body: {
        xaddr,
        username: c.username,
        password: c.password,
      },
    });
    setResult((prev) => {
      const next = { ...(prev || { devices: [] }) };
      next.devices = (next.devices || []).map((d) => {
        if (!(d.xaddrs || []).includes(xaddr)) return d;
        return { ...d, rtsp_profiles: out.rtsp_profiles || [] };
      });
      return next;
    });
  }

  async function addCamera(profile, device) {
    const c = creds[(device.xaddrs || [])[0] || ''] || {};
    const name = device.name || `ONVIF ${new Date().toLocaleTimeString()}`;
    await request('/api/v1/cameras', {
      token,
      method: 'POST',
      body: {
        name,
        type: 'rtsp',
        source: profile.uri,
        location: device.location || null,
        enabled: true,
        live_view: true,
        detector_mode: 'inherit',
        onvif_xaddr: (device.xaddrs || [])[0] || null,
        onvif_username: c.username || null,
        onvif_password: c.password || null,
        onvif_profile: profile.token || null,
      },
    });
    setToast(`Camera added from profile ${profile.name || profile.token || 'stream'}.`);
  }

  const devices = result?.devices || [];

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass toolbar between">
        <div className="row">
          <Radar size={16} />
          <strong>ONVIF Discovery</strong>
        </div>
        <div className="row">
          <input type="number" min="1" max="15" value={timeout} onChange={(e) => setTimeoutVal(e.target.value)} style={{ width: 90 }} />
          <button className="btn primary" onClick={() => runDiscovery().catch((err) => setError(err.message || 'Discovery failed'))}><Search size={14} /> Scan</button>
        </div>
      </div>

      <div className="panel glass">
        <div className="panel-head"><h3>Devices ({devices.length})</h3></div>
        {!devices.length ? (
          <div className="muted">No devices discovered yet.</div>
        ) : (
          <div className="stack">
            {devices.map((dev, idx) => {
              const xaddr = (dev.xaddrs || [])[0] || '';
              const c = creds[xaddr] || { username: '', password: '' };
              return (
                <div className="device-card" key={`${xaddr}-${idx}`}>
                  <div className="row between">
                    <div>
                      <strong>{dev.name || `Device ${idx + 1}`}</strong>
                      <div className="tiny muted">{dev.location || '-'}</div>
                    </div>
                    <span className="tiny mono">{xaddr || 'No xaddr'}</span>
                  </div>
                  <div className="row">
                    <input placeholder="ONVIF user" value={c.username} onChange={(e) => setCreds((prev) => ({ ...prev, [xaddr]: { ...c, username: e.target.value } }))} />
                    <input placeholder="ONVIF password" type="password" value={c.password} onChange={(e) => setCreds((prev) => ({ ...prev, [xaddr]: { ...c, password: e.target.value } }))} />
                    <button className="btn" onClick={() => resolveProfiles(xaddr).catch((err) => setError(err.message || 'Resolve failed'))}>Resolve RTSP</button>
                  </div>
                  {!!dev.rtsp_profiles?.length && (
                    <div className="stack">
                      {dev.rtsp_profiles.map((p, pIdx) => (
                        <div className="row between" key={`${p.token || p.uri}-${pIdx}`}>
                          <div>
                            <strong>{p.name || 'Profile'}</strong>
                            <div className="tiny mono">{p.resolution || '-'} · {p.uri}</div>
                          </div>
                          <button className="btn primary" onClick={() => addCamera(p, dev).catch((err) => setError(err.message || 'Add camera failed'))}><Plus size={14} /> Add Camera</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
