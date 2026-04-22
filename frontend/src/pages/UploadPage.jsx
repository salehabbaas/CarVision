import { useEffect, useMemo, useState } from 'react';
import { UploadCloud, LoaderCircle, Play } from 'lucide-react';
import { apiPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import FormField    from '../design-system/components/FormField';
import Input        from '../design-system/components/Input';
import Checkbox     from '../design-system/components/Checkbox';
import Button       from '../design-system/components/Button';
import FileDropZone from '../design-system/components/FileDropZone';
import Alert        from '../design-system/components/Alert';
import FormSection  from '../design-system/components/FormSection';
import FormModal    from '../design-system/components/FormModal';

export default function UploadPage() {
  const { token } = useAuth();
  const [file, setFile]                 = useState(null);
  const [sampleSeconds, setSampleSeconds] = useState(1.0);
  const [maxFrames, setMaxFrames]       = useState(300);
  const [showDebug, setShowDebug]       = useState(true);
  const [jobId, setJobId]               = useState('');
  const [job, setJob]                   = useState(null);
  const [error, setError]               = useState('');
  const [formOpen, setFormOpen]         = useState(false);

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
    return () => { alive = false; if (timer) clearTimeout(timer); };
  }, [jobId, token]);

  async function startUpload(e) {
    e.preventDefault();
    if (!file) { setError('Select a file first.'); return; }
    setError('');
    setJob(null);
    const fd = new FormData();
    fd.append('file', file);
    fd.append('sample_seconds', String(sampleSeconds || 1.0));
    fd.append('max_frames', String(maxFrames || 300));
    fd.append('show_debug', showDebug ? 'true' : 'false');
    try {
      const res = await fetch(apiPath('/api/v1/upload/start'), {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: fd,
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || !data?.job_id) throw new Error(data?.detail || 'Failed to start upload job');
      setJobId(data.job_id);
      setFormOpen(false);
    } catch (err) {
      setError(err.message || 'Upload failed');
    }
  }

  const items = useMemo(() => job?.result?.items || [], [job]);
  const debug = useMemo(() => job?.result?.debug  || [], [job]);

  return (
    <div className="stack">
      {error && <Alert variant="error" onDismiss={() => setError('')}>{error}</Alert>}

      <div className="panel glass" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, flexWrap: 'wrap' }}>
        <div>
          <h3 style={{ margin: '0 0 4px' }}>Upload & Test Detection</h3>
          <span className="muted tiny">Run detection on a single image or video clip.</span>
        </div>
        <Button type="button" variant="primary" icon={<UploadCloud size={14} />} onClick={() => setFormOpen(true)}>
          New Upload Test
        </Button>
      </div>

      <FormModal
        open={formOpen}
        onClose={() => setFormOpen(false)}
        title="Upload & Test Detection"
        subtitle="Run detection on a single image or video clip"
        formId="upload-test-form"
        submitLabel="Start Detection"
        submitDisabled={!file}
      >
        <form id="upload-test-form" onSubmit={startUpload} style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
          <FormSection title="File">
            <FileDropZone
              accept="image/*,video/*"
              value={file}
              onChange={setFile}
              icon={<UploadCloud size={22} />}
              label="Drop an image or video here, or click to browse"
              hint="Supported: JPEG, PNG, MP4, AVI, MOV…"
            />
          </FormSection>

          <FormSection title="Options">
            <div className="ds-grid-2">
              <FormField
                label="Sample interval (sec)"
                hint="How often frames are extracted from video"
              >
                <Input
                  type="number"
                  step="0.1"
                  min="0.1"
                  value={sampleSeconds}
                  onChange={(e) => setSampleSeconds(e.target.value)}
                />
              </FormField>

              <FormField
                label="Max frames"
                hint="Cap on total frames processed"
              >
                <Input
                  type="number"
                  min="1"
                  max="2000"
                  value={maxFrames}
                  onChange={(e) => setMaxFrames(e.target.value)}
                />
              </FormField>
            </div>

            <Checkbox
              checked={showDebug}
              onChange={(e) => setShowDebug(e.target.checked)}
              label="Include debug steps"
              hint="Attaches intermediate detection images for troubleshooting"
            />
          </FormSection>
        </form>
      </FormModal>

      {/* ── Job progress ───────────────────────────────────────────────── */}
      <div className="panel glass">
        <div className="panel-head"><h3 style={{ margin: 0 }}>Processing</h3></div>
        {!job ? (
          <div className="muted" style={{ fontSize: '0.875rem' }}>No active job — upload a file to begin.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div className="status-row">
              <span className={`status-pill ${job.status}`}>{job.status}</span>
              <span style={{ fontSize: '0.875rem' }}>{job.message}</span>
              {job.status === 'running' && <LoaderCircle className="spin" size={15} />}
            </div>
            <div className="progress-wrap">
              <div className="progress-bar" style={{ width: `${job.progress || 0}%` }} />
            </div>
            <div className="steps-list">
              {(job.steps || []).slice(-12).map((s, i) => (
                <div key={i} className="tiny muted">{s}</div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* ── Detections result ──────────────────────────────────────────── */}
      {!!items.length && (
        <div className="panel glass">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Detections</h3></div>
          <div className="detect-grid">
            {items.map((it, idx) => (
              <div className="det-card" key={`${it.image_path || idx}-${idx}`}>
                {it.image_path && <img src={apiPath(`/media/${it.image_path}`)} alt={it.plate_text} />}
                <div className="row between">
                  <strong>{it.plate_text}</strong>
                  <span className={`tag ${it.status === 'allowed' ? 'ok' : 'bad'}`}>{it.status}</span>
                </div>
                <div className="tiny">Confidence: {Math.round((it.confidence || 0) * 100)}%</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Debug steps ────────────────────────────────────────────────── */}
      {!!debug.length && (
        <div className="panel glass">
          <div className="panel-head"><h3 style={{ margin: 0 }}>Debug Steps</h3></div>
          <div className="row" style={{ flexWrap: 'wrap', gap: 8 }}>
            {debug.flatMap((d, idx) =>
              ['debug_color', 'debug_bw', 'debug_gray', 'debug_edged', 'debug_mask']
                .filter((k) => d[k])
                .map((k) => (
                  <a
                    key={`${idx}-${k}`}
                    className="tiny-link"
                    href={apiPath(`/media/${d[k]}`)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {d.plate_text || 'plate'} · {k.replace('debug_', '')}
                  </a>
                ))
            )}
          </div>
        </div>
      )}
    </div>
  );
}
