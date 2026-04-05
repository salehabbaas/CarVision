import { useEffect, useMemo, useRef, useState } from 'react';
import { FlaskConical, Save, UploadCloud, Trash2, Ban, Boxes } from 'lucide-react';
import { request, apiPath, mediaPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { Link, useSearchParams } from 'react-router-dom';

const statusTabs = ['all', 'annotated', 'pending', 'negative', 'ignored'];

export default function TrainingDataPage() {
  const { token } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [samples, setSamples] = useState([]);
  const [counts, setCounts] = useState({});
  const [status, setStatus] = useState('all');
  const [q, setQ] = useState('');
  const [selectedId, setSelectedId] = useState(null);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState({
    plate_text: '',
    bbox_x: '',
    bbox_y: '',
    bbox_w: '',
    bbox_h: '',
    no_plate: false,
    notes: '',
  });
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [trainingStatus, setTrainingStatus] = useState({ status: 'idle', message: 'Idle' });
  const [trainingBusy, setTrainingBusy] = useState(false);
  const [debugPreview, setDebugPreview] = useState({ open: false, steps: [], index: 0 });
  const [drawBox, setDrawBox] = useState(null);
  const [drawStart, setDrawStart] = useState(null);
  const imageRef = useRef(null);
  const stageRef = useRef(null);
  const batchFilter = searchParams.get('batch') || '';

  useEffect(() => {
    const qSampleId = Number(searchParams.get('sample_id') || 0);
    if (qSampleId > 0) {
      setSelectedId(qSampleId);
    }
  }, [searchParams]);

  async function loadSamples() {
    const params = new URLSearchParams({ status, limit: '500' });
    if (q.trim()) params.set('q', q.trim());
    if (batchFilter) params.set('batch', batchFilter);
    const res = await request(`/api/v1/training/samples?${params.toString()}`, { token });
    setSamples(res.items || []);
    setCounts(res.counts || {});
    if (!selectedId && res.items?.length) {
      setSelectedId(res.items[0].id);
    } else if (selectedId && !res.items?.some((s) => s.id === selectedId)) {
      setSelectedId(res.items?.[0]?.id || null);
    }
  }

  async function loadDetail(sampleId) {
    if (!sampleId) {
      setDetail(null);
      return;
    }
    const res = await request(`/api/v1/training/samples/${sampleId}`, { token });
    setDetail(res || null);
  }

  useEffect(() => {
    loadSamples().catch((err) => setError(err.message || 'Failed to load samples'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, batchFilter]);

  useEffect(() => {
    if (!selectedId) return;
    loadDetail(selectedId).catch((err) => setError(err.message || 'Failed to load sample'));
  }, [selectedId, token]);

  useEffect(() => {
    let timer;
    let alive = true;
    const poll = async () => {
      try {
        const st = await request('/api/v1/training/status', { token });
        if (!alive) return;
        setTrainingStatus(st || { status: 'idle', message: 'Idle' });
      } catch {
        // ignore polling errors
      }
      timer = setTimeout(poll, 2500);
    };
    poll();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [token]);

  useEffect(() => {
    const item = detail?.item;
    if (!item) return;
    setForm({
      plate_text: item.plate_text || '',
      bbox_x: item.bbox?.x ?? '',
      bbox_y: item.bbox?.y ?? '',
      bbox_w: item.bbox?.w ?? '',
      bbox_h: item.bbox?.h ?? '',
      no_plate: Boolean(item.no_plate),
      notes: item.notes || '',
    });
    setDrawBox(null);
    setDrawStart(null);
  }, [detail]);

  const selected = detail?.item || null;
  const debugSteps = useMemo(() => detail?.debug_steps || [], [detail]);

  async function runUpload(files) {
    const fd = new FormData();
    [...files].forEach((f) => fd.append('files', f));
    const res = await fetch(apiPath('/api/v1/training/upload'), {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}` },
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data?.detail || 'Upload failed');
    setToast(`Uploaded ${data.created || 0} images.`);
    if (data.batch_id) {
      const next = new URLSearchParams(searchParams);
      next.set('batch', data.batch_id);
      setSearchParams(next, { replace: true });
    }
    await loadSamples();
    if (data.ids?.length) setSelectedId(data.ids[data.ids.length - 1]);
  }

  async function saveAnnotation(e) {
    e.preventDefault();
    if (!selectedId) return;
    const payload = {
      plate_text: form.plate_text || null,
      bbox_x: form.no_plate || form.bbox_x === '' ? null : Number(form.bbox_x),
      bbox_y: form.no_plate || form.bbox_y === '' ? null : Number(form.bbox_y),
      bbox_w: form.no_plate || form.bbox_w === '' ? null : Number(form.bbox_w),
      bbox_h: form.no_plate || form.bbox_h === '' ? null : Number(form.bbox_h),
      no_plate: Boolean(form.no_plate),
      notes: form.notes || null,
    };
    await request(`/api/v1/training/samples/${selectedId}/annotate`, {
      token,
      method: 'PATCH',
      body: payload,
    });
    setToast('Annotation saved.');
    await loadSamples();
    await loadDetail(selectedId);
  }

  async function toggleIgnore() {
    if (!selectedId) return;
    await request(`/api/v1/training/samples/${selectedId}/ignore`, {
      token,
      method: 'POST',
      body: {},
    });
    setToast('Ignore updated.');
    await loadSamples();
    await loadDetail(selectedId);
  }

  async function removeSample() {
    if (!selectedId) return;
    if (!window.confirm(`Delete sample ${selectedId}?`)) return;
    await request(`/api/v1/training/samples/${selectedId}`, {
      token,
      method: 'DELETE',
    });
    setToast('Sample deleted.');
    setSelectedId(null);
    setDetail(null);
    await loadSamples();
  }

  async function exportYolo() {
    const res = await request('/api/v1/training/export_yolo', { token });
    setToast(`Exported ${res?.counts?.exported || 0} samples to YOLO dataset.`);
  }

  async function startTraining() {
    setTrainingBusy(true);
    try {
      await request('/api/v1/training/start', { token, method: 'POST' });
      setToast('Training started.');
    } catch (err) {
      setError(err.message || 'Training start failed');
    } finally {
      setTrainingBusy(false);
    }
  }

  function getDrawPoint(ev) {
    const el = stageRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, ev.clientY - rect.top));
    return { x, y, w: rect.width, h: rect.height };
  }

  function beginDraw(ev) {
    if (form.no_plate) return;
    if (!stageRef.current) return;
    const pt = getDrawPoint(ev);
    if (!pt) return;
    setDrawStart(pt);
    setDrawBox({ x: pt.x, y: pt.y, w: 0, h: 0 });
  }

  function moveDraw(ev) {
    if (!drawStart) return;
    const pt = getDrawPoint(ev);
    if (!pt) return;
    const x = Math.min(drawStart.x, pt.x);
    const y = Math.min(drawStart.y, pt.y);
    const w = Math.abs(pt.x - drawStart.x);
    const h = Math.abs(pt.y - drawStart.y);
    setDrawBox({ x, y, w, h });
  }

  function endDraw() {
    if (!drawStart || !drawBox || !selected) {
      setDrawStart(null);
      return;
    }
    const img = imageRef.current;
    const stage = stageRef.current;
    if (!img || !stage) {
      setDrawStart(null);
      return;
    }
    const naturalW = img.naturalWidth || selected.image_width || 0;
    const naturalH = img.naturalHeight || selected.image_height || 0;
    const displayW = stage.clientWidth || 1;
    const displayH = stage.clientHeight || 1;
    const scaleX = naturalW / displayW;
    const scaleY = naturalH / displayH;

    const bx = Math.round(drawBox.x * scaleX);
    const by = Math.round(drawBox.y * scaleY);
    const bw = Math.round(drawBox.w * scaleX);
    const bh = Math.round(drawBox.h * scaleY);

    setForm((f) => ({
      ...f,
      no_plate: false,
      bbox_x: String(Math.max(0, bx)),
      bbox_y: String(Math.max(0, by)),
      bbox_w: String(Math.max(1, bw)),
      bbox_h: String(Math.max(1, bh)),
    }));
    setDrawStart(null);
  }

  const previewBox = useMemo(() => {
    if (!selected || form.no_plate) return null;
    const img = imageRef.current;
    const stage = stageRef.current;
    if (!img || !stage) return null;
    const naturalW = img.naturalWidth || selected.image_width || 0;
    const naturalH = img.naturalHeight || selected.image_height || 0;
    const displayW = stage.clientWidth || 1;
    const displayH = stage.clientHeight || 1;
    if (!naturalW || !naturalH) return drawBox;

    if (drawBox && drawStart) return drawBox;

    const bx = Number(form.bbox_x);
    const by = Number(form.bbox_y);
    const bw = Number(form.bbox_w);
    const bh = Number(form.bbox_h);
    if (!Number.isFinite(bx) || !Number.isFinite(by) || !Number.isFinite(bw) || !Number.isFinite(bh) || bw <= 0 || bh <= 0) {
      return null;
    }
    const x = (bx / naturalW) * displayW;
    const y = (by / naturalH) * displayH;
    const w = (bw / naturalW) * displayW;
    const h = (bh / naturalH) * displayH;
    return { x, y, w, h };
  }, [selected, form, drawBox, drawStart]);

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass toolbar between">
        <div className="row">
          <span className={`status-pill ${trainingStatus.status}`}>{trainingStatus.status}</span>
          <span className="muted">{trainingStatus.message}</span>
        </div>
        <div className="row">
          <button className="btn" onClick={exportYolo}><Boxes size={15} /> Export YOLO</button>
          <button className="btn primary" onClick={startTraining} disabled={trainingBusy}>
            <FlaskConical size={15} className={trainingBusy ? 'spin' : ''} /> {trainingBusy ? 'Starting...' : 'Start Training'}
          </button>
        </div>
      </div>

      <div className="panel glass toolbar between">
        <div className="row">
          {batchFilter ? (
            <>
              <span className="tag ok">Batch: {batchFilter}</span>
              <button
                className="btn ghost"
                onClick={() => {
                  const next = new URLSearchParams(searchParams);
                  next.delete('batch');
                  setSearchParams(next, { replace: true });
                }}
              >
                Clear Batch Filter
              </button>
            </>
          ) : (
            <span className="muted tiny">Showing all samples</span>
          )}
        </div>
      </div>

      <div className="panel glass toolbar between">
        <div className="row">
          {statusTabs.map((tab) => (
            <button key={tab} className={`btn ${status === tab ? 'primary' : ''}`} onClick={() => setStatus(tab)}>
              {tab} ({counts[tab === 'all' ? 'total' : tab] || 0})
            </button>
          ))}
        </div>
        <div className="row">
          <input placeholder="Search plate, file, notes" value={q} onChange={(e) => setQ(e.target.value)} style={{ minWidth: 250 }} />
          <button className="btn" onClick={() => loadSamples().catch((err) => setError(err.message))}>Search</button>
          <label className="btn">
            <UploadCloud size={15} /> Upload Images
            <input type="file" accept="image/*" multiple hidden onChange={(e) => {
              const files = e.target.files;
              if (!files?.length) return;
              runUpload(files).catch((err) => setError(err.message || 'Upload failed'));
              e.target.value = '';
            }} />
          </label>
          <Link className="btn ghost" to="/dataset-import">Dataset Import</Link>
        </div>
      </div>

      <div className="split two-col">
        <div className="panel glass">
          <div className="panel-head"><h3>Training Samples</h3></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Plate</th>
                  <th>Status</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s) => {
                  const st = s.ignored ? 'ignored' : s.no_plate ? 'negative' : s.bbox ? 'annotated' : 'pending';
                  return (
                    <tr key={s.id} className={selectedId === s.id ? 'selected-row' : ''} onClick={() => setSelectedId(s.id)}>
                      <td className="mono">{s.id}</td>
                      <td>{s.plate_text || '-'}</td>
                      <td><span className={`tag ${st === 'annotated' ? 'ok' : st === 'pending' ? 'muted' : st === 'negative' ? 'bad' : 'bad'}`}>{st}</span></td>
                      <td className="tiny">{s.updated_at ? new Date(s.updated_at).toLocaleString() : '-'}</td>
                    </tr>
                  );
                })}
                {!samples.length && <tr><td colSpan={4} className="empty">No samples.</td></tr>}
              </tbody>
            </table>
          </div>
        </div>

        <div className="panel glass">
          <div className="panel-head">
            <h3>Annotation</h3>
            <div className="row">
              <button className="btn" onClick={toggleIgnore} disabled={!selectedId}><Ban size={14} /> {selected?.ignored ? 'Unignore' : 'Ignore'}</button>
              <button className="btn ghost" onClick={removeSample} disabled={!selectedId}><Trash2 size={14} /> Delete</button>
            </div>
          </div>

          {!selected ? (
            <div className="muted">Select a sample.</div>
          ) : (
            <form className="stack" onSubmit={(e) => saveAnnotation(e).catch((err) => setError(err.message || 'Save failed'))}>
              <div className="row two">
                <div>
                  <div className="tiny muted">Sample #{selected.id}</div>
                  <div
                    className={`annotator-wrap ${form.no_plate ? 'disabled' : ''}`}
                    ref={stageRef}
                    onMouseDown={beginDraw}
                    onMouseMove={moveDraw}
                    onMouseUp={endDraw}
                    onMouseLeave={endDraw}
                  >
                    <img ref={imageRef} className="preview-image" src={mediaPath(selected.image_path)} alt={`sample-${selected.id}`} />
                    {previewBox ? (
                      <div
                        className="annotator-box"
                        style={{
                          left: `${previewBox.x}px`,
                          top: `${previewBox.y}px`,
                          width: `${previewBox.w}px`,
                          height: `${previewBox.h}px`,
                        }}
                      />
                    ) : null}
                  </div>
                  <div className="tiny muted">Tip: draw a box directly on image to fill bbox.</div>
                </div>
                <div className="stack">
                  <label>Plate text</label>
                  <input value={form.plate_text} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, plate_text: e.target.value }))} />
                  <label className="row tiny"><input type="checkbox" checked={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, no_plate: e.target.checked }))} /> No plate (negative)</label>
                  <div className="row two">
                    <input placeholder="x" type="number" value={form.bbox_x} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_x: e.target.value }))} />
                    <input placeholder="y" type="number" value={form.bbox_y} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_y: e.target.value }))} />
                    <input placeholder="w" type="number" value={form.bbox_w} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_w: e.target.value }))} />
                    <input placeholder="h" type="number" value={form.bbox_h} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_h: e.target.value }))} />
                  </div>
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={() => setForm((f) => ({ ...f, bbox_x: '', bbox_y: '', bbox_w: '', bbox_h: '' }))}
                    disabled={form.no_plate}
                  >
                    Clear BBox
                  </button>
                  <textarea placeholder="notes" value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
                  <button className="btn primary" type="submit"><Save size={14} /> Save Annotation</button>
                </div>
              </div>

              {!!debugSteps.length && (
                <div>
                  <div className="tiny muted">Debug steps</div>
                  <div className="row">
                    {debugSteps.map((s, idx) => (
                      <button
                        key={s.key}
                        type="button"
                        className="tiny-link btn-link"
                        onClick={() => setDebugPreview({ open: true, steps: debugSteps, index: idx })}
                      >
                        {s.label}
                      </button>
                    ))}
                  </div>
                </div>
              )}
            </form>
          )}
        </div>
      </div>

      {debugPreview.open && debugPreview.steps.length > 0 && (
        <div className="modal-backdrop" onClick={() => setDebugPreview((d) => ({ ...d, open: false }))}>
          <div className="modal glass feedback-modal" onClick={(e) => e.stopPropagation()}>
            <div className="panel-head">
              <h3>Training Debug Viewer</h3>
              <span className="tag ok">{debugPreview.steps[debugPreview.index]?.label || 'Step'}</span>
            </div>
            <img className="preview-image" src={mediaPath(debugPreview.steps[debugPreview.index]?.path)} alt="training-debug" />
            <div className="row">
              {debugPreview.steps.map((step, idx) => (
                <button
                  key={`train-step-${step.key}-${idx}`}
                  type="button"
                  className={`btn ${idx === debugPreview.index ? 'primary' : ''}`}
                  onClick={() => setDebugPreview((d) => ({ ...d, index: idx }))}
                >
                  {step.label}
                </button>
              ))}
            </div>
            <div className="row end">
              <button type="button" className="btn ghost" onClick={() => setDebugPreview((d) => ({ ...d, open: false }))}>
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
