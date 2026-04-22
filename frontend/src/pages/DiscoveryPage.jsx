import { useEffect, useMemo, useState } from 'react';
import { LoaderCircle, Plus, Radar, Search, ShieldCheck } from 'lucide-react';
import { request } from '../lib/api';
import { useAuth } from '../context/AuthContext';

function parseSubnetsCsv(raw) {
  return Array.from(
    new Set(
      String(raw || '')
        .split(',')
        .map((item) => item.trim())
        .filter(Boolean)
    )
  );
}

function hostSubnetHint(host) {
  if (!/^\d+\.\d+\.\d+\.\d+$/.test(String(host || ''))) return null;
  const [a, b, c] = host.split('.');
  return `${a}.${b}.${c}.0/24`;
}

export default function DiscoveryPage() {
  const { token } = useAuth();
  const [timeout, setTimeoutVal] = useState(3);
  const [subnetsInput, setSubnetsInput] = useState('');
  const [probePorts, setProbePorts] = useState(false);
  const [query, setQuery] = useState('');
  const [sortBy, setSortBy] = useState('name');
  const [onlyResolved, setOnlyResolved] = useState(false);

  const [result, setResult] = useState(null);
  const [error, setError] = useState('');
  const [toast, setToast] = useState('');
  const [creds, setCreds] = useState({});
  const [scanning, setScanning] = useState(false);
  const [scanStartedAt, setScanStartedAt] = useState(null);
  const [elapsedSec, setElapsedSec] = useState(0);
  const [resolvingByXaddr, setResolvingByXaddr] = useState({});
  const [addingByProfile, setAddingByProfile] = useState({});
  const [resolvingAll, setResolvingAll] = useState(false);

  useEffect(() => {
    if (!scanning || !scanStartedAt) return undefined;
    const timer = setInterval(() => {
      const elapsed = Math.max(0, Math.round((Date.now() - scanStartedAt) / 1000));
      setElapsedSec(elapsed);
    }, 250);
    return () => clearInterval(timer);
  }, [scanning, scanStartedAt]);

  async function runDiscovery() {
    setError('');
    setToast('');
    setScanning(true);
    setScanStartedAt(Date.now());
    setElapsedSec(0);
    try {
      const params = new URLSearchParams();
      params.set('timeout', String(Number(timeout) || 3));
      if (subnetsInput.trim()) params.set('subnets', subnetsInput.trim());
      if (probePorts) params.set('probe_ports', '1');
      const res = await request(`/api/v1/discovery/run?${params.toString()}`, { token });
      setResult(res || { devices: [] });
      const invalid = res?.filters?.invalid_subnets || [];
      if (invalid.length) {
        setError(`Invalid subnets ignored: ${invalid.join(', ')}`);
      }
      setToast(`Scan finished. Found ${res?.total_after_filter ?? 0} devices.`);
    } finally {
      setScanning(false);
    }
  }

  async function resolveProfiles(xaddr) {
    const c = creds[xaddr] || {};
    if (!c.username || !c.password) {
      setError('Provide username/password before resolve.');
      return;
    }
    setResolvingByXaddr((prev) => ({ ...prev, [xaddr]: true }));
    setError('');
    try {
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
    } catch (err) {
      setError(err.message || 'Resolve failed');
    } finally {
      setResolvingByXaddr((prev) => ({ ...prev, [xaddr]: false }));
    }
  }

  async function resolveAllProfiles() {
    const devices = result?.devices || [];
    const queue = devices
      .map((dev) => (dev.xaddrs || [])[0] || '')
      .filter((xaddr) => {
        const c = creds[xaddr] || {};
        return xaddr && c.username && c.password;
      });
    if (!queue.length) {
      setError('Add credentials first, then use Resolve All.');
      return;
    }
    setResolvingAll(true);
    setError('');
    for (const xaddr of queue) {
      // eslint-disable-next-line no-await-in-loop
      await resolveProfiles(xaddr);
    }
    setResolvingAll(false);
    setToast('Resolve all finished.');
  }

  async function addCamera(profile, device) {
    const xaddr = (device.xaddrs || [])[0] || '';
    const c = creds[xaddr] || {};
    const name = device.name || `ONVIF ${new Date().toLocaleTimeString()}`;
    const profileKey = `${xaddr}-${profile.token || profile.uri}`;
    setAddingByProfile((prev) => ({ ...prev, [profileKey]: true }));
    try {
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
          onvif_xaddr: xaddr || null,
          onvif_username: c.username || null,
          onvif_password: c.password || null,
          onvif_profile: profile.token || null,
        },
      });
      setToast(`Camera added from profile ${profile.name || profile.token || 'stream'}.`);
    } catch (err) {
      setError(err.message || 'Add camera failed');
    } finally {
      setAddingByProfile((prev) => ({ ...prev, [profileKey]: false }));
    }
  }

  function toggleSubnetHint(subnet) {
    const current = parseSubnetsCsv(subnetsInput);
    const next = current.includes(subnet)
      ? current.filter((item) => item !== subnet)
      : [...current, subnet];
    setSubnetsInput(next.join(', '));
  }

  const devices = result?.devices || [];
  const subnetHints = useMemo(() => {
    const found = new Set();
    devices.forEach((dev) => {
      const hint = hostSubnetHint(dev.host);
      if (hint) found.add(hint);
    });
    return Array.from(found).sort();
  }, [devices]);

  const summary = useMemo(() => {
    const withProfiles = devices.filter((d) => (d.rtsp_profiles || []).length > 0).length;
    const withOpenRtsp = devices.filter((d) => d.port_probe?.['554']).length;
    return {
      totalFound: result?.total_found ?? devices.length,
      afterFilter: result?.total_after_filter ?? devices.length,
      withProfiles,
      withOpenRtsp,
    };
  }, [devices, result]);

  const filteredDevices = useMemo(() => {
    const q = query.trim().toLowerCase();
    let rows = devices.filter((dev) => {
      if (onlyResolved && !(dev.rtsp_profiles || []).length) return false;
      if (!q) return true;
      const text = [
        dev.name || '',
        dev.location || '',
        dev.host || '',
        ...(dev.xaddrs || []),
      ]
        .join(' ')
        .toLowerCase();
      return text.includes(q);
    });

    rows = [...rows].sort((a, b) => {
      if (sortBy === 'host') return String(a.host || '').localeCompare(String(b.host || ''));
      if (sortBy === 'location') return String(a.location || '').localeCompare(String(b.location || ''));
      if (sortBy === 'profiles') return (b.rtsp_profiles || []).length - (a.rtsp_profiles || []).length;
      return String(a.name || '').localeCompare(String(b.name || ''));
    });
    return rows;
  }, [devices, onlyResolved, query, sortBy]);

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass stack">
        <div className="toolbar between">
          <div className="row">
            <Radar size={16} />
            <strong>ONVIF Discovery Control Center</strong>
          </div>
          <div className="row">
            <button className="btn ghost" onClick={() => setResult(null)} disabled={scanning}>
              Clear Results
            </button>
            <button className="btn primary" onClick={() => runDiscovery().catch((err) => setError(err.message || 'Discovery failed'))} disabled={scanning}>
              {scanning ? <LoaderCircle className="spin" size={14} /> : <Search size={14} />}
              {scanning ? `Scanning... ${elapsedSec}s` : 'Scan'}
            </button>
          </div>
        </div>

        <div className="discovery-controls">
          <div>
            <label title="How long the backend waits for ONVIF WS-Discovery responses.">Timeout (sec)</label>
            <input
              title="Longer timeout can discover slower cameras but increases scan duration."
              type="number"
              min="1"
              max="15"
              value={timeout}
              onChange={(e) => setTimeoutVal(e.target.value)}
            />
          </div>
          <div>
            <label title="Comma-separated subnets to include in results (example: 192.168.1.0/24,10.0.0.0/24).">Subnet Filter</label>
            <input
              title="Only devices with hosts inside these subnets will be shown."
              placeholder="192.168.1.0/24,10.0.0.0/24"
              value={subnetsInput}
              onChange={(e) => setSubnetsInput(e.target.value)}
            />
          </div>
          <div>
            <label title="Optional network probing and local filtering controls.">Extra Controls</label>
            <div className="row">
              <label className="tiny row" title="Probe common camera TCP ports (80/443/554) on discovered hosts.">
                <input title="Enable live TCP port probe." type="checkbox" checked={probePorts} onChange={(e) => setProbePorts(e.target.checked)} />
                Probe Ports
              </label>
              <label className="tiny row" title="Show only devices that already have resolved RTSP profiles.">
                <input title="Hide unresolved devices." type="checkbox" checked={onlyResolved} onChange={(e) => setOnlyResolved(e.target.checked)} />
                Resolved Only
              </label>
            </div>
          </div>
          <div>
            <label title="Search discovered devices by name, location, host, or xaddr.">Result Search</label>
            <input title="Filter current discovery results." placeholder="Search result devices..." value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div>
            <label title="Sort order for device result cards.">Sort</label>
            <select title="Choose how result cards are sorted." value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
              <option value="name">Name</option>
              <option value="host">Host</option>
              <option value="profiles">Profile Count</option>
              <option value="location">Location</option>
            </select>
          </div>
          <div>
            <label title="Resolve all devices where credentials are already filled in.">Batch Resolve</label>
            <button className="btn" onClick={() => resolveAllProfiles().catch((err) => setError(err.message || 'Resolve all failed'))} disabled={resolvingAll || scanning}>
              {resolvingAll ? <LoaderCircle className="spin" size={14} /> : <ShieldCheck size={14} />}
              {resolvingAll ? 'Resolving...' : 'Resolve All With Credentials'}
            </button>
          </div>
        </div>

        {!!subnetHints.length && (
          <div className="row">
            <span className="tiny muted">Quick subnet picks:</span>
            {subnetHints.map((subnet) => {
              const selected = parseSubnetsCsv(subnetsInput).includes(subnet);
              return (
                <button
                  key={subnet}
                  className={`btn ${selected ? 'primary' : 'ghost'}`}
                  onClick={() => toggleSubnetHint(subnet)}
                  type="button"
                  title="Toggle this detected subnet in filter list."
                >
                  {subnet}
                </button>
              );
            })}
          </div>
        )}
      </div>

      <div className="card-grid">
        <div className="panel glass metric-card">
          <div className="metric-label">Found (raw)</div>
          <div className="metric-value">{summary.totalFound}</div>
        </div>
        <div className="panel glass metric-card">
          <div className="metric-label">After Filter</div>
          <div className="metric-value">{summary.afterFilter}</div>
        </div>
        <div className="panel glass metric-card">
          <div className="metric-label">Resolved Profiles</div>
          <div className="metric-value">{summary.withProfiles}</div>
        </div>
        <div className="panel glass metric-card">
          <div className="metric-label">Hosts With RTSP Port Open</div>
          <div className="metric-value">{summary.withOpenRtsp}</div>
        </div>
      </div>

      <div className="panel glass">
        <div className="panel-head">
          <h3>Devices ({filteredDevices.length})</h3>
          <span className="tiny muted">Detected {summary.totalFound} total devices</span>
        </div>
        {!filteredDevices.length ? (
          <div className="muted">No devices discovered yet. Run scan, or adjust filters.</div>
        ) : (
          <div className="stack">
            {filteredDevices.map((dev, idx) => {
              const xaddr = (dev.xaddrs || [])[0] || '';
              const c = creds[xaddr] || { username: '', password: '' };
              const profiles = dev.rtsp_profiles || [];
              const probing = resolvingByXaddr[xaddr];
              return (
                <div className="device-card" key={`${xaddr || dev.host || 'device'}-${idx}`}>
                  <div className="row between">
                    <div>
                      <strong>{dev.name || `Device ${idx + 1}`}</strong>
                      <div className="tiny muted">{dev.location || 'No location metadata'}</div>
                    </div>
                    <div className="row">
                      {dev.host ? <span className="tag muted">{dev.host}</span> : null}
                      {dev.xaddr_ports?.map((port) => <span key={`${dev.host}-${port}`} className="tag muted">ONVIF:{port}</span>)}
                      <span className={`tag ${profiles.length ? 'ok' : 'muted'}`}>{profiles.length} profiles</span>
                    </div>
                  </div>

                  {!!Object.keys(dev.port_probe || {}).length && (
                    <div className="row">
                      <span className="tiny muted">Port Probe:</span>
                      {Object.entries(dev.port_probe).map(([port, open]) => (
                        <span key={`${dev.host}-${port}`} className={`tag ${open ? 'ok' : 'bad'}`}>
                          {port} {open ? 'open' : 'closed'}
                        </span>
                      ))}
                    </div>
                  )}

                  <div className="row">
                    <input
                      title="ONVIF username used to query RTSP profiles for this device."
                      placeholder="ONVIF user"
                      value={c.username}
                      onChange={(e) => setCreds((prev) => ({ ...prev, [xaddr]: { ...c, username: e.target.value } }))}
                    />
                    <input
                      title="ONVIF password for the username above."
                      placeholder="ONVIF password"
                      type="password"
                      value={c.password}
                      onChange={(e) => setCreds((prev) => ({ ...prev, [xaddr]: { ...c, password: e.target.value } }))}
                    />
                    <button
                      className="btn"
                      onClick={() => resolveProfiles(xaddr).catch((err) => setError(err.message || 'Resolve failed'))}
                      disabled={!xaddr || probing}
                      title="Resolve RTSP stream profiles from this camera's ONVIF endpoint."
                    >
                      {probing ? <LoaderCircle className="spin" size={14} /> : null}
                      {probing ? 'Resolving...' : 'Resolve RTSP'}
                    </button>
                  </div>

                  {!!profiles.length && (
                    <div className="profile-list">
                      {profiles.map((p, pIdx) => {
                        const profileKey = `${xaddr}-${p.token || p.uri}`;
                        const adding = addingByProfile[profileKey];
                        return (
                          <div className="profile-item" key={`${p.token || p.uri}-${pIdx}`}>
                            <div>
                              <strong>{p.name || 'Profile'}</strong>
                              <div className="tiny mono">{p.resolution || '-'} · {p.uri}</div>
                            </div>
                            <button
                              className="btn primary"
                              onClick={() => addCamera(p, dev).catch((err) => setError(err.message || 'Add camera failed'))}
                              disabled={adding}
                              title="Create a camera entry from this RTSP profile."
                            >
                              {adding ? <LoaderCircle className="spin" size={14} /> : <Plus size={14} />}
                              {adding ? 'Adding...' : 'Add Camera'}
                            </button>
                          </div>
                        );
                      })}
                    </div>
                  )}

                  <details>
                    <summary className="tiny muted">Show endpoint details</summary>
                    <div className="tiny mono">
                      {(dev.xaddrs || []).map((line, i) => (
                        <div key={`${line}-${i}`}>{line}</div>
                      ))}
                    </div>
                  </details>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
