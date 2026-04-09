import { useEffect, useMemo, useState } from 'react';
import { UploadCloud, LoaderCircle } from 'lucide-react';
import { apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';

export default function UploadPage() {
  const { token } = useAuth();
  const [file, setFile] = useState(null);
  const [sampleSeconds, setSampleSeconds] = useState(1.0);
  const [maxFrames, setMaxFrames] = useState(300);
  const [showDebug, setShowDebug] = useState(true);
  const [jobId, setJobId] = useState('');
  const [job, setJob] = useState(null);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!jobId) return;
    let timer;
    let alive = true;

    const poll = async () => {
      try {
        const res = await fetch(apiPath(`/api/v1/upload/status/${jobId}`), {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (!res.ok) throw new Error('Failed to fetch upload status');
        const data = await res.json();
        if (!alive) return;
        setJob(data.job || null);
        const st = data?.job?.status;
        if (st === 'complete' || st === 'failed') return;
      } catch (err) {
        if (!alive) return;
        setError(err.message || 'Upload status failed');
      }
      timer = setTimeout(poll, 1000);
    };

    poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [jobId, token]);

  async function startUpload(e) {
    e.preventDefault();
    if (!file) {
      setError('Select a file first.');
      return;
    }
    setError('');
    setJob(null);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('sample_seconds', String(sampleSeconds || 1.0));
    fd.append('max_frames', String(maxFrames || 300));
    fd.append('show_debug', showDebug ? 'true' : 'false');

    const res = await fetch(apiPath('/api/v1/upload/start'), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || !data?.job_id) {
      throw new Error(data?.detail || 'Failed to start upload job');
    }
    setJobId(data.job_id);
  }

  const items = useMemo(() => job?.result?.items || [], [job]);
  const debug = useMemo(() => job?.result?.debug || [], [job]);

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}

      <form
        className="panel glass"
        onSubmit={(e) => {
          startUpload(e).catch((err) => setError(err.message || 'Upload failed'));
        }}
      >
        <div className="panel-head"><h3><UploadCloud size={16} /> Upload & Test</h3></div>
        <div className="row two">
          <div>
            <label title="Choose a file to test detection on a single image or a video clip.">Image or Video</label>
            <input title="Supported: image or video files." type="file" accept="image/*,video/*" onChange={(e) => setFile(e.target.files?.[0] || null)} />
          </div>
          <div className="row">
            <div>
              <label title="How often to sample frames from the uploaded video.">Sample (sec)</label>
              <input title="Lower value scans more frames and increases load." type="number" step="0.1" min="0.1" value={sampleSeconds} onChange={(e) => setSampleSeconds(e.target.value)} />
            </div>
            <div>
              <label title="Maximum number of frames to process from the video.">Max frames</label>
              <input title="Caps processing work to keep jobs fast." type="number" min="1" max="2000" value={maxFrames} onChange={(e) => setMaxFrames(e.target.value)} />
            </div>
            <label className="row tiny" title="Attach intermediate processing outputs for troubleshooting OCR/detection quality."><input title="Enable debug images in upload result." type="checkbox" checked={showDebug} onChange={(e) => setShowDebug(e.target.checked)} /> Include debug steps</label>
          </div>
        </div>
        <div className="row end">
          <button className="btn primary" type="submit"><UploadCloud size={15} /> Start</button>
        </div>
      </form>

      <div className="panel glass">
        <div className="panel-head"><h3>Processing</h3></div>
        {!job ? (
          <div className="muted">No active job.</div>
        ) : (
          <>
            <div className="status-row">
              <span className={`status-pill ${job.status}`}>{job.status}</span>
              <span>{job.message}</span>
              {job.status === 'running' ? <LoaderCircle className="spin" size={16} /> : null}
            </div>
            <div className="progress-wrap"><div className="progress-bar" style={{ width: `${job.progress || 0}%` }} /></div>
            <div className="steps-list">
              {(job.steps || []).slice(-12).map((s, i) => <div key={i} className="tiny muted">{s}</div>)}
            </div>
          </>
        )}
      </div>

      {!!items.length && (
        <div className="panel glass">
          <div className="panel-head"><h3>Detections</h3></div>
          <div className="detect-grid">
            {items.map((it, idx) => (
              <div className="det-card" key={`${it.image_path || idx}-${idx}`}>
                {it.image_path ? <img src={apiPath(`/media/${it.image_path}`)} alt={it.plate_text} /> : null}
                <div className="row between"><strong>{it.plate_text}</strong><span className={`tag ${it.status === 'allowed' ? 'ok' : 'bad'}`}>{it.status}</span></div>
                <div className="tiny">Confidence: {Math.round((it.confidence || 0) * 100)}%</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {!!debug.length && (
        <div className="panel glass">
          <div className="panel-head"><h3>Debug Steps</h3></div>
          <div className="row">
            {debug.flatMap((d, idx) => {
              const out = [];
              ['debug_color', 'debug_bw', 'debug_gray', 'debug_edged', 'debug_mask'].forEach((k) => {
                if (d[k]) {
                  out.push(
                    <a key={`${idx}-${k}`} className="tiny-link" href={apiPath(`/media/${d[k]}`)} target="_blank" rel="noreferrer">
                      {d.plate_text || 'plate'} · {k.replace('debug_', '')}
                    </a>
                  );
                }
              });
              return out;
            })}
          </div>
        </div>
      )}
    </div>
  );
}
