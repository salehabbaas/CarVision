import { useEffect, useMemo, useRef, useState } from 'react';
import { FlaskConical, Save, UploadCloud, Trash2, Ban, Boxes, RefreshCcw, Square, Play, Activity } from 'lucide-react';
import { request, apiPath, mediaPath } from '../lib/api';
import { useAuth } from '../context/AuthContext';
import { Link, useSearchParams } from 'react-router-dom';

const statusTabs = ['all', 'annotated', 'pending', 'negative', 'unclear', 'ignored'];
const MIN_ANNOTATION_ZOOM = 1;
const MAX_ANNOTATION_ZOOM = 4;
const DEBUG_STEP_ORDER = [
  { key: 'color', label: 'Color Crop' },
  { key: 'bw', label: 'Threshold' },
  { key: 'gray', label: 'Gray' },
  { key: 'edged', label: 'Edges' },
  { key: 'mask', label: 'Mask' },
];
const RESIZE_HANDLES = ['nw', 'ne', 'sw', 'se'];

export default function TrainingDataPage() {
  const { token } = useAuth();
  const [searchParams, setSearchParams] = useSearchParams();
  const [samples, setSamples] = useState([]);
  const [counts, setCounts] = useState({});
  const [status, setStatus] = useState('all');
  const [source, setSource] = useState(searchParams.get('source') || 'system');
  const [hasText, setHasText] = useState('all');
  const [processedFilter, setProcessedFilter] = useState('all');
  const [trainedFilter, setTrainedFilter] = useState('all');
  const [sortBy, setSortBy] = useState('created_at');
  const [sortDir, setSortDir] = useState('desc');
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(50);
  const [pagination, setPagination] = useState({ page: 1, page_size: 50, total_items: 0, total_pages: 1 });
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
    unclear_plate: false,
    notes: '',
  });
  const [toast, setToast] = useState('');
  const [error, setError] = useState('');
  const [trainingStatus, setTrainingStatus] = useState({ status: 'idle', message: 'Idle' });
  const [trainingBusy, setTrainingBusy] = useState('');
  const [reprocessBusy, setReprocessBusy] = useState(false);
  const [bulkBusy, setBulkBusy] = useState(false);
  const [selectedIds, setSelectedIds] = useState([]);
  const [debugPreview, setDebugPreview] = useState({ open: false, steps: [], index: 0 });
  const [draftBox, setDraftBox] = useState(null);
  const [dragState, setDragState] = useState(null);
  const [zoom, setZoom] = useState(1);
  const [imageMeta, setImageMeta] = useState({ naturalW: 0, naturalH: 0, baseW: 0, baseH: 0 });
  const imageRef = useRef(null);
  const viewportRef = useRef(null);
  const stageRef = useRef(null);
  const batchFilter = searchParams.get('batch') || '';
  const previousTrainingStatusRef = useRef('idle');

  useEffect(() => {
    const qSampleId = Number(searchParams.get('sample_id') || 0);
    if (qSampleId > 0) {
      setSelectedId(qSampleId);
    }
  }, [searchParams]);

  useEffect(() => {
    setPage(1);
  }, [status, source, hasText, processedFilter, trainedFilter, sortBy, sortDir, batchFilter]);

  async function loadSamples() {
    const params = new URLSearchParams({
      status,
      source: batchFilter ? 'all' : source,
      has_text: hasText,
      processed: processedFilter,
      trained: trainedFilter,
      sort_by: sortBy,
      sort_dir: sortDir,
      page: String(page),
      page_size: String(pageSize),
    });
    if (q.trim()) params.set('q', q.trim());
    if (batchFilter) params.set('batch', batchFilter);
    const res = await request(`/api/v1/training/samples?${params.toString()}`, { token });
    setSamples(res.items || []);
    setCounts(res.counts || {});
    setPagination(res.pagination || { page, page_size: pageSize, total_items: 0, total_pages: 1 });
    if (!selectedId && res.items?.length) {
      setSelectedId(res.items[0].id);
    } else if (selectedId && !res.items?.some((s) => s.id === selectedId)) {
      setSelectedId(res.items?.[0]?.id || null);
    }
  }

  function toggleSelectSample(id) {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  }

  function toggleSelectAllCurrentPage() {
    const ids = samples.map((s) => s.id);
    const allSelected = ids.length > 0 && ids.every((id) => selectedIds.includes(id));
    if (allSelected) {
      setSelectedIds((prev) => prev.filter((id) => !ids.includes(id)));
    } else {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...ids])));
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

  function goToSample(offset) {
    if (!samples.length || selectedIndex < 0) return;
    const nextIdx = Math.max(0, Math.min(samples.length - 1, selectedIndex + offset));
    const nextId = samples[nextIdx]?.id;
    if (!nextId || nextId === selectedId) return;
    setSelectedId(nextId);
  }

  function openDebugStep(stepKey) {
    const idx = orderedDebugSteps.findIndex((step) => step.key === stepKey);
    if (idx < 0) return;
    setDebugPreview({
      open: true,
      steps: orderedDebugSteps,
      index: idx,
    });
  }

  useEffect(() => {
    loadSamples().catch((err) => setError(err.message || 'Failed to load samples'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status, batchFilter, source, hasText, processedFilter, trainedFilter, sortBy, sortDir, page, pageSize]);

  useEffect(() => {
    if (!selectedId) return;
    loadDetail(selectedId).catch((err) => setError(err.message || 'Failed to load sample'));
  }, [selectedId, token]);

  useEffect(() => {
    let timer;
    let alive = true;
    const refreshTrainingStatus = async () => {
      const st = await request('/api/v1/training/status', { token });
      if (!alive) return;
      const next = st || { status: 'idle', message: 'Idle' };
      const prev = previousTrainingStatusRef.current;
      setTrainingStatus(next);
      previousTrainingStatusRef.current = next.status || 'idle';
      if (prev !== next.status && ['complete', 'failed', 'stopped'].includes(next.status || '')) {
        loadSamples().catch(() => {});
        if (selectedId) loadDetail(selectedId).catch(() => {});
      }
    };
    const poll = async () => {
      try {
        await refreshTrainingStatus();
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
  }, [token, selectedId]);

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
      unclear_plate: Boolean(item.unclear_plate),
      notes: item.notes || '',
    });
    setDraftBox(null);
    setDragState(null);
    setZoom(1);
    setImageMeta({ naturalW: 0, naturalH: 0, baseW: 0, baseH: 0 });
  }, [detail]);

  useEffect(() => {
    const onResize = () => recomputeImageMeta();
    window.addEventListener('resize', onResize);
    return () => window.removeEventListener('resize', onResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [detail?.item?.id]);

  const selected = detail?.item || null;
  const debugSteps = useMemo(() => detail?.debug_steps || [], [detail]);
  const selectedIndex = useMemo(
    () => samples.findIndex((s) => s.id === selectedId),
    [samples, selectedId]
  );
  const orderedDebugSteps = useMemo(() => {
    const byKey = new Map(debugSteps.map((step) => [step.key, step]));
    return DEBUG_STEP_ORDER.map((step) => ({
      key: step.key,
      label: step.label,
      path: byKey.get(step.key)?.path || null,
    }));
  }, [debugSteps]);

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
      unclear_plate: Boolean(form.unclear_plate),
      notes: form.notes || null,
    };
    const res = await request(`/api/v1/training/samples/${selectedId}/annotate`, {
      token,
      method: 'PATCH',
      body: payload,
    });
    setToast('Annotation saved.');
    if (res?.item) {
      setDetail({
        item: res.item,
        debug_steps: res.debug_steps || [],
      });
    }
    setDraftBox(null);
    setDragState(null);
    await loadSamples();
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
    setTrainingBusy('start');
    try {
      const res = await request('/api/v1/training/start', { token, method: 'POST' });
      if (res?.job) setTrainingStatus(res.job);
      setToast('Training started.');
    } catch (err) {
      setError(err.message || 'Training start failed');
    } finally {
      setTrainingBusy('');
    }
  }

  async function stopTraining() {
    setTrainingBusy('stop');
    try {
      const res = await request('/api/v1/training/stop', { token, method: 'POST' });
      if (res?.job) setTrainingStatus(res.job);
      setToast(res?.stopped ? 'Training stop requested.' : 'No active training job.');
    } catch (err) {
      setError(err.message || 'Training stop failed');
    } finally {
      setTrainingBusy('');
    }
  }

  async function resumeTraining() {
    setTrainingBusy('resume');
    try {
      const res = await request('/api/v1/training/resume', { token, method: 'POST' });
      if (res?.job) setTrainingStatus(res.job);
      setToast(res?.already_running ? 'Training is already running.' : 'Training resumed.');
    } catch (err) {
      setError(err.message || 'Training resume failed');
    } finally {
      setTrainingBusy('');
    }
  }

  async function reprocessSelected() {
    if (!selectedId) return;
    setReprocessBusy(true);
    try {
      const res = await request(`/api/v1/training/samples/${selectedId}/reprocess`, {
        token,
        method: 'POST',
      });
      setToast(`Reprocessed sample #${selectedId}. Plate: ${res.plate_text || '-'}`);
      if (res?.item) {
        setDetail({
          item: res.item,
          debug_steps: res.debug_steps || [],
        });
      }
      await loadSamples();
    } catch (err) {
      setError(err.message || 'Reprocess failed');
    } finally {
      setReprocessBusy(false);
    }
  }

  async function reprocessSelectedBulk() {
    if (!selectedIds.length) return;
    setBulkBusy(true);
    try {
      const res = await request('/api/v1/training/samples/reprocess', {
        token,
        method: 'POST',
        body: { sample_ids: selectedIds },
      });
      setToast(`Bulk reprocess done. Processed: ${res.processed || 0}, updated: ${res.updated || 0}, failed: ${res.failed || 0}.`);
      await loadSamples();
      if (selectedId) await loadDetail(selectedId);
    } catch (err) {
      setError(err.message || 'Bulk reprocess failed');
    } finally {
      setBulkBusy(false);
    }
  }

  function clampZoom(value) {
    return Math.min(MAX_ANNOTATION_ZOOM, Math.max(MIN_ANNOTATION_ZOOM, value));
  }

  function recomputeImageMeta() {
    const img = imageRef.current;
    const viewport = viewportRef.current;
    if (!img || !viewport) return;
    const naturalW = img.naturalWidth || selected?.image_width || 0;
    const naturalH = img.naturalHeight || selected?.image_height || 0;
    if (!naturalW || !naturalH) return;
    const viewportW = Math.max(260, viewport.clientWidth || 0);
    const baseW = Math.min(naturalW, viewportW);
    const baseH = (baseW / naturalW) * naturalH;
    setImageMeta({ naturalW, naturalH, baseW, baseH });
  }

  function getDisplayMetrics() {
    const img = imageRef.current;
    const stage = stageRef.current;
    if (!img || !stage || !selected) return null;
    const naturalW = img.naturalWidth || selected.image_width || 0;
    const naturalH = img.naturalHeight || selected.image_height || 0;
    const displayW = stage.clientWidth || 1;
    const displayH = stage.clientHeight || 1;
    if (!naturalW || !naturalH || !displayW || !displayH) return null;
    return { naturalW, naturalH, displayW, displayH };
  }

  function getDrawPoint(ev) {
    const el = stageRef.current;
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    const x = Math.max(0, Math.min(rect.width, ev.clientX - rect.left));
    const y = Math.max(0, Math.min(rect.height, ev.clientY - rect.top));
    return { x, y, w: rect.width, h: rect.height };
  }

  function pointInBox(pt, box) {
    return (
      pt.x >= box.x &&
      pt.x <= box.x + box.w &&
      pt.y >= box.y &&
      pt.y <= box.y + box.h
    );
  }

  function clampDisplayBox(box, boundsW, boundsH) {
    const minSize = 8;
    const w = Math.max(minSize, Math.min(boundsW, box.w));
    const h = Math.max(minSize, Math.min(boundsH, box.h));
    const x = Math.max(0, Math.min(boundsW - w, box.x));
    const y = Math.max(0, Math.min(boundsH - h, box.y));
    return { x, y, w, h };
  }

  function displayBoxFromForm() {
    if (!selected || form.no_plate) return null;
    const metrics = getDisplayMetrics();
    if (!metrics) return null;
    const { naturalW, naturalH, displayW, displayH } = metrics;
    const bx = Number(form.bbox_x);
    const by = Number(form.bbox_y);
    const bw = Number(form.bbox_w);
    const bh = Number(form.bbox_h);
    if (!Number.isFinite(bx) || !Number.isFinite(by) || !Number.isFinite(bw) || !Number.isFinite(bh) || bw <= 0 || bh <= 0) {
      return null;
    }
    return {
      x: (bx / naturalW) * displayW,
      y: (by / naturalH) * displayH,
      w: (bw / naturalW) * displayW,
      h: (bh / naturalH) * displayH,
    };
  }

  function commitDisplayBoxToForm(box, mode = 'draw') {
    const metrics = getDisplayMetrics();
    if (!metrics || !box) return;
    const { naturalW, naturalH, displayW, displayH } = metrics;
    const scaleX = naturalW / displayW;
    const scaleY = naturalH / displayH;
    const minTap = 8;

    let next = { ...box };
    if (mode === 'draw' && (next.w < minTap || next.h < minTap)) {
      const defaultW = Math.max(40, Math.round(naturalW * 0.22));
      const defaultH = Math.max(20, Math.round(naturalH * 0.09));
      const centerX = next.x;
      const centerY = next.y;
      next = clampDisplayBox(
        {
          x: centerX - defaultW / (2 * scaleX),
          y: centerY - defaultH / (2 * scaleY),
          w: defaultW / scaleX,
          h: defaultH / scaleY,
        },
        displayW,
        displayH
      );
    } else {
      next = clampDisplayBox(next, displayW, displayH);
    }

    let bx = Math.round(next.x * scaleX);
    let by = Math.round(next.y * scaleY);
    let bw = Math.round(next.w * scaleX);
    let bh = Math.round(next.h * scaleY);
    bx = Math.max(0, Math.min(naturalW - 1, bx));
    by = Math.max(0, Math.min(naturalH - 1, by));
    bw = Math.max(1, Math.min(naturalW - bx, bw));
    bh = Math.max(1, Math.min(naturalH - by, bh));

    setForm((f) => ({
      ...f,
      no_plate: false,
      bbox_x: String(bx),
      bbox_y: String(by),
      bbox_w: String(bw),
      bbox_h: String(bh),
    }));
  }

  function beginDraw(ev) {
    if (form.no_plate || !stageRef.current) return;
    if (ev.pointerType === 'mouse' && ev.button !== 0) return;
    const pt = getDrawPoint(ev);
    if (!pt) return;
    const currentBox = draftBox || displayBoxFromForm();
    const handle = ev.target?.dataset?.handle || '';
    let mode = 'draw';
    let initialBox = currentBox;
    if (handle && currentBox) {
      mode = 'resize';
    } else if (currentBox && pointInBox(pt, currentBox)) {
      mode = 'move';
    } else {
      initialBox = { x: pt.x, y: pt.y, w: 1, h: 1 };
    }
    setDragState({
      mode,
      handle,
      pointerId: ev.pointerId,
      startX: pt.x,
      startY: pt.y,
      stageW: pt.w,
      stageH: pt.h,
      initialBox,
    });
    setDraftBox(initialBox);
    stageRef.current.setPointerCapture?.(ev.pointerId);
    ev.preventDefault();
  }

  function moveDraw(ev) {
    if (!dragState) return;
    if (dragState.pointerId !== undefined && ev.pointerId !== dragState.pointerId) return;
    const pt = getDrawPoint(ev);
    if (!pt) return;
    const dx = pt.x - dragState.startX;
    const dy = pt.y - dragState.startY;
    const base = dragState.initialBox || { x: pt.x, y: pt.y, w: 1, h: 1 };
    let next = base;

    if (dragState.mode === 'draw') {
      next = {
        x: Math.min(dragState.startX, pt.x),
        y: Math.min(dragState.startY, pt.y),
        w: Math.abs(pt.x - dragState.startX),
        h: Math.abs(pt.y - dragState.startY),
      };
    } else if (dragState.mode === 'move') {
      next = {
        ...base,
        x: base.x + dx,
        y: base.y + dy,
      };
    } else if (dragState.mode === 'resize') {
      const right = base.x + base.w;
      const bottom = base.y + base.h;
      let x1 = base.x;
      let y1 = base.y;
      let x2 = right;
      let y2 = bottom;
      if (dragState.handle.includes('n')) y1 = base.y + dy;
      if (dragState.handle.includes('s')) y2 = bottom + dy;
      if (dragState.handle.includes('w')) x1 = base.x + dx;
      if (dragState.handle.includes('e')) x2 = right + dx;
      next = {
        x: Math.min(x1, x2),
        y: Math.min(y1, y2),
        w: Math.abs(x2 - x1),
        h: Math.abs(y2 - y1),
      };
    }

    setDraftBox(clampDisplayBox(next, dragState.stageW, dragState.stageH));
    ev.preventDefault();
  }

  function endDraw(ev) {
    if (!dragState) return;
    if (ev && dragState.pointerId !== undefined && ev.pointerId !== dragState.pointerId) return;
    const finalBox = draftBox || dragState.initialBox;
    if (finalBox) {
      commitDisplayBoxToForm(finalBox, dragState.mode);
    }
    if (ev && dragState.pointerId !== undefined) {
      stageRef.current?.releasePointerCapture?.(dragState.pointerId);
    }
    setDraftBox(null);
    setDragState(null);
  }

  const previewBox = useMemo(() => {
    if (!selected || form.no_plate) return null;
    if (draftBox) return draftBox;
    return displayBoxFromForm();
  }, [selected, form, draftBox, imageMeta]);

  const stageStyle = useMemo(() => {
    if (!imageMeta.baseW || !imageMeta.baseH) return {};
    return {
      width: `${Math.round(imageMeta.baseW * zoom)}px`,
      height: `${Math.round(imageMeta.baseH * zoom)}px`,
    };
  }, [imageMeta, zoom]);

  const currentStatus = useMemo(() => {
    if (!selected) return 'pending';
    if (selected.ignored) return 'ignored';
    if (selected.no_plate) return 'negative';
    if (selected.unclear_plate) return 'unclear';
    if (selected.bbox) return 'annotated';
    return 'pending';
  }, [selected]);

  const isAnnotationDirty = useMemo(() => {
    if (!selected) return false;
    return (
      (form.plate_text || '') !== (selected.plate_text || '') ||
      Number(form.bbox_x || 0) !== Number(selected.bbox?.x || 0) ||
      Number(form.bbox_y || 0) !== Number(selected.bbox?.y || 0) ||
      Number(form.bbox_w || 0) !== Number(selected.bbox?.w || 0) ||
      Number(form.bbox_h || 0) !== Number(selected.bbox?.h || 0) ||
      Boolean(form.no_plate) !== Boolean(selected.no_plate) ||
      Boolean(form.unclear_plate) !== Boolean(selected.unclear_plate) ||
      (form.notes || '') !== (selected.notes || '')
    );
  }, [selected, form]);

  const trainingLogs = useMemo(() => {
    const logs = trainingStatus?.details?.logs;
    return Array.isArray(logs) ? logs.slice().reverse().slice(0, 12) : [];
  }, [trainingStatus]);

  const backendState = trainingStatus?.details?.backend || {};
  const isTrainingActive = ['queued', 'running'].includes(trainingStatus?.status || '');
  const isStopping = (trainingStatus?.stage || '') === 'stopping' || (trainingStatus?.status || '') === 'stopping';
  const canStartTraining = !isTrainingActive && !isStopping;
  const canStopTraining = isTrainingActive || isStopping;
  const canResumeTraining = ['stopped', 'queued'].includes(trainingStatus?.status || '') && !isTrainingActive;
  const trainingProgress = Math.max(0, Math.min(100, Number(trainingStatus?.progress || 0)));
  const trainingElapsedSeconds = backendState?.elapsed_seconds || 0;
  const trainingMeta = [
    trainingStatus?.stage ? `Stage: ${trainingStatus.stage}` : null,
    trainingStatus?.chunk_total ? `Chunk ${trainingStatus.chunk_index || 0}/${trainingStatus.chunk_total}` : null,
    trainingStatus?.total_samples ? `Samples ${trainingStatus.trained_samples || 0}/${trainingStatus.total_samples}` : null,
    trainingStatus?.ocr_scanned ? `OCR scanned ${trainingStatus.ocr_scanned}` : null,
    trainingStatus?.ocr_updated ? `OCR updated ${trainingStatus.ocr_updated}` : null,
  ].filter(Boolean).join(' • ');

  function adjustBbox(deltaX = 0, deltaY = 0, deltaW = 0, deltaH = 0) {
    if (form.no_plate) return;
    setForm((prev) => {
      const nextX = Math.max(0, Number(prev.bbox_x || 0) + deltaX);
      const nextY = Math.max(0, Number(prev.bbox_y || 0) + deltaY);
      const nextW = Math.max(1, Number(prev.bbox_w || 1) + deltaW);
      const nextH = Math.max(1, Number(prev.bbox_h || 1) + deltaH);
      return {
        ...prev,
        bbox_x: String(nextX),
        bbox_y: String(nextY),
        bbox_w: String(nextW),
        bbox_h: String(nextH),
      };
    });
  }

  return (
    <div className="stack">
      {error ? <div className="alert error">{error}</div> : null}
      {toast ? <div className="alert success">{toast}</div> : null}

      <div className="panel glass training-hero">
        <div className="row between">
          <div className="stack" style={{ flex: 1 }}>
            <div className="row">
              <span className={`status-pill ${trainingStatus.status}`}>{trainingStatus.status}</span>
              <span className="tag muted">{trainingStatus.stage || 'idle'}</span>
              {trainingStatus?.id ? <span className="tag muted mono">job {trainingStatus.id}</span> : null}
            </div>
            <div className="muted">{trainingStatus.message}</div>
            <div className="training-progress">
              <div className={`training-progress-fill ${isTrainingActive ? 'running' : ''}`} style={{ width: `${trainingProgress}%` }} />
            </div>
            <div className="training-progress-label">
              <span>{trainingProgress}%</span>
              <span>{trainingMeta || 'Waiting for backend activity'}</span>
            </div>
          </div>
          <div className="row">
            <button className="btn" onClick={exportYolo}><Boxes size={15} /> Export YOLO</button>
            <button className="btn primary" onClick={startTraining} disabled={!canStartTraining || Boolean(trainingBusy)}>
              <FlaskConical size={15} className={trainingBusy === 'start' ? 'spin' : ''} /> {trainingBusy === 'start' ? 'Starting...' : 'Start Training'}
            </button>
            <button className="btn ghost" onClick={resumeTraining} disabled={!canResumeTraining || Boolean(trainingBusy)}>
              <Play size={15} className={trainingBusy === 'resume' ? 'spin' : ''} /> {trainingBusy === 'resume' ? 'Resuming...' : 'Resume'}
            </button>
            <button className="btn ghost" onClick={stopTraining} disabled={!canStopTraining || Boolean(trainingBusy)}>
              <Square size={15} className={trainingBusy === 'stop' ? 'spin' : ''} /> {trainingBusy === 'stop' || isStopping ? 'Stopping...' : 'Stop'}
            </button>
          </div>
        </div>
        <div className="training-kpis">
          <div className="kpi-card">
            <span className="tiny muted">Samples Trained</span>
            <strong>{trainingStatus?.trained_samples || 0}</strong>
          </div>
          <div className="kpi-card">
            <span className="tiny muted">Total Samples</span>
            <strong>{trainingStatus?.total_samples || 0}</strong>
          </div>
          <div className="kpi-card">
            <span className="tiny muted">Chunk Progress</span>
            <strong>{trainingStatus?.chunk_index || 0}/{trainingStatus?.chunk_total || 0}</strong>
          </div>
          <div className="kpi-card">
            <span className="tiny muted">Backend Activity</span>
            <strong>{backendState?.activity || trainingStatus?.stage || 'idle'}</strong>
          </div>
          <div className="kpi-card">
            <span className="tiny muted">Worker PID</span>
            <strong>{backendState?.pid || '-'}</strong>
          </div>
          <div className="kpi-card">
            <span className="tiny muted">Active For</span>
            <strong>{trainingElapsedSeconds ? `${trainingElapsedSeconds}s` : '-'}</strong>
          </div>
        </div>
        <div className="row wrap">
          <span className="tag muted"><Activity size={12} /> Backend: {backendState?.activity || 'waiting'}</span>
          {trainingStatus?.run_dir ? <span className="tag muted mono">run {trainingStatus.run_dir}</span> : null}
          {trainingStatus?.model_path ? <span className="tag muted mono">model {trainingStatus.model_path}</span> : null}
          {trainingStatus?.updated_at ? <span className="tag muted">Updated {new Date(trainingStatus.updated_at).toLocaleString()}</span> : null}
        </div>
        <div className="training-log">
          <div className="tiny muted">Recent backend activity</div>
          <div className="training-log-list">
            {trainingLogs.length ? trainingLogs.map((line, idx) => (
              <div key={`${line}-${idx}`} className="tiny mono">{line}</div>
            )) : (
              <div className="tiny muted">No backend activity logged yet.</div>
            )}
          </div>
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
            <div className="row">
              <span className="muted tiny">Source</span>
              <select
                value={source}
                onChange={(e) => setSource(e.target.value)}
                title="Default is system camera samples."
              >
                <option value="system">System Cameras (Default)</option>
                <option value="dataset">Imported Datasets</option>
                <option value="all">All</option>
              </select>
              <span className="muted tiny">Plate Text</span>
              <select value={hasText} onChange={(e) => setHasText(e.target.value)} title="Filter by extracted/annotated plate text.">
                <option value="all">All</option>
                <option value="yes">Has text</option>
                <option value="no">No text</option>
              </select>
              <span className="muted tiny">Processed</span>
              <select value={processedFilter} onChange={(e) => setProcessedFilter(e.target.value)}>
                <option value="all">All</option>
                <option value="yes">Processed</option>
                <option value="no">Not processed</option>
              </select>
              <span className="muted tiny">Trained</span>
              <select value={trainedFilter} onChange={(e) => setTrainedFilter(e.target.value)}>
                <option value="all">All</option>
                <option value="yes">Trained</option>
                <option value="no">Not trained</option>
              </select>
            </div>
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
          <input
            title="Search training samples by plate text, image path, or notes."
            placeholder="Search plate, file, notes"
            value={q}
            onChange={(e) => setQ(e.target.value)}
            style={{ minWidth: 250 }}
          />
          <button className="btn" onClick={() => loadSamples().catch((err) => setError(err.message))}>Search</button>
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)} title="Sort column">
            <option value="created_at">Sort: Created</option>
            <option value="updated_at">Sort: Updated</option>
            <option value="plate_text">Sort: Plate Text</option>
            <option value="processed_at">Sort: Processed</option>
            <option value="last_trained_at">Sort: Trained</option>
            <option value="id">Sort: ID</option>
          </select>
          <select value={sortDir} onChange={(e) => setSortDir(e.target.value)} title="Sort direction">
            <option value="desc">Desc</option>
            <option value="asc">Asc</option>
          </select>
          <select value={pageSize} onChange={(e) => setPageSize(Number(e.target.value) || 50)} title="Rows per page">
            <option value={25}>25 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
          <label className="btn">
            <UploadCloud size={15} /> Upload Images
            <input title="Upload one or more images to create new training samples." type="file" accept="image/*" multiple hidden onChange={(e) => {
              const files = e.target.files;
              if (!files?.length) return;
              runUpload(files).catch((err) => setError(err.message || 'Upload failed'));
              e.target.value = '';
            }} />
          </label>
          <Link className="btn ghost" to="/dataset-import">Dataset Import</Link>
          <button className="btn ghost" onClick={reprocessSelectedBulk} disabled={!selectedIds.length || bulkBusy}>
            <RefreshCcw size={14} /> {bulkBusy ? 'Bulk Reprocessing...' : `Bulk Reprocess (${selectedIds.length})`}
          </button>
        </div>
      </div>

      <div className="split two-col">
        <div className="panel glass">
          <div className="panel-head"><h3>Training Samples</h3></div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>
                    <input
                      type="checkbox"
                      checked={samples.length > 0 && samples.every((s) => selectedIds.includes(s.id))}
                      onChange={toggleSelectAllCurrentPage}
                      title="Select all on current page"
                    />
                  </th>
                  <th>ID</th>
                  <th>Plate</th>
                  <th>Status</th>
                  <th>Processed</th>
                  <th>Trained</th>
                  <th>Updated</th>
                </tr>
              </thead>
              <tbody>
                {samples.map((s) => {
                  const st = s.ignored ? 'ignored' : s.no_plate ? 'negative' : s.unclear_plate ? 'unclear' : s.bbox ? 'annotated' : 'pending';
                  return (
                    <tr key={s.id} className={selectedId === s.id ? 'selected-row' : ''} onClick={() => setSelectedId(s.id)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input
                          type="checkbox"
                          checked={selectedIds.includes(s.id)}
                          onChange={() => toggleSelectSample(s.id)}
                        />
                      </td>
                      <td className="mono">{s.id}</td>
                      <td>{s.plate_text || '-'}</td>
                      <td><span className={`tag ${st === 'annotated' ? 'ok' : st === 'pending' ? 'muted' : st === 'unclear' ? 'bad' : st === 'negative' ? 'bad' : 'bad'}`}>{st}</span></td>
                      <td>{s.processed ? <span className="tag ok">processed</span> : <span className="tag muted">no</span>}</td>
                      <td>{s.trained ? <span className="tag ok">trained</span> : <span className="tag muted">no</span>}</td>
                      <td className="tiny">{s.updated_at ? new Date(s.updated_at).toLocaleString() : '-'}</td>
                    </tr>
                  );
                })}
                {!samples.length && <tr><td colSpan={7} className="empty">No samples.</td></tr>}
              </tbody>
            </table>
          </div>
          <div className="row between" style={{ marginTop: 8 }}>
            <div className="tiny muted">
              Page {pagination.page || 1} / {pagination.total_pages || 1} · Total {pagination.total_items || 0}
            </div>
            <div className="row">
              <button className="btn ghost" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={(pagination.page || 1) <= 1}>
                Previous
              </button>
              <button
                className="btn ghost"
                onClick={() => setPage((p) => Math.min((pagination.total_pages || 1), p + 1))}
                disabled={(pagination.page || 1) >= (pagination.total_pages || 1)}
              >
                Next
              </button>
            </div>
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
                  <div className="row between">
                    <div className="tiny muted">Sample #{selected.id}</div>
                    <div className="row">
                      <button type="button" className="btn ghost" onClick={() => goToSample(-1)} disabled={selectedIndex <= 0}>Previous</button>
                      <button
                        type="button"
                        className="btn ghost"
                        onClick={() => goToSample(1)}
                        disabled={selectedIndex < 0 || selectedIndex >= samples.length - 1}
                      >
                        Next
                      </button>
                    </div>
                  </div>
                  <div className="annotator-toolbar">
                    <div className="row">
                      <button type="button" className="btn ghost" onClick={() => setZoom((z) => clampZoom(z - 0.25))}>-</button>
                      <input
                        className="annotator-zoom"
                        type="range"
                        min={MIN_ANNOTATION_ZOOM}
                        max={MAX_ANNOTATION_ZOOM}
                        step="0.25"
                        value={zoom}
                        title="Zoom image for precise annotation drawing."
                        onChange={(e) => setZoom(clampZoom(Number(e.target.value)))}
                      />
                      <button type="button" className="btn ghost" onClick={() => setZoom((z) => clampZoom(z + 0.25))}>+</button>
                    </div>
                    <div className="row">
                      <span className="tiny muted">{Math.round(zoom * 100)}%</span>
                      <button type="button" className="btn ghost" onClick={() => setZoom(1)}>Fit</button>
                    </div>
                  </div>
                  <div
                    className="annotator-viewport"
                    ref={viewportRef}
                    onWheel={(ev) => {
                      if (!ev.ctrlKey) return;
                      ev.preventDefault();
                      const delta = ev.deltaY > 0 ? -0.1 : 0.1;
                      setZoom((z) => clampZoom(z + delta));
                    }}
                  >
                    <div
                      className={`annotator-wrap ${form.no_plate ? 'disabled' : ''} ${dragState ? 'dragging' : ''}`}
                      ref={stageRef}
                      style={stageStyle}
                      onPointerDown={beginDraw}
                      onPointerMove={moveDraw}
                      onPointerUp={endDraw}
                      onPointerLeave={endDraw}
                      onPointerCancel={endDraw}
                    >
                      <img
                        ref={imageRef}
                        className="preview-image"
                        src={mediaPath(selected.image_path)}
                        alt={`sample-${selected.id}`}
                        onLoad={recomputeImageMeta}
                      />
                      {previewBox ? (
                        <div
                          className="annotator-box"
                          style={{
                            left: `${previewBox.x}px`,
                            top: `${previewBox.y}px`,
                            width: `${previewBox.w}px`,
                            height: `${previewBox.h}px`,
                          }}
                        >
                          {RESIZE_HANDLES.map((handle) => (
                            <button
                              key={handle}
                              type="button"
                              className={`annotator-handle annotator-handle-${handle}`}
                              data-handle={handle}
                              tabIndex={-1}
                              title={`Resize from ${handle.toUpperCase()} corner`}
                            />
                          ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                  <div className="tiny muted">
                    Tip: draw to create a plate box, drag inside box to move, drag corner handles to resize, or quick-tap to place a default box.
                  </div>
                  <div className="annotator-meta">
                    <span className={`tag ${currentStatus === 'annotated' ? 'ok' : currentStatus === 'pending' ? 'muted' : 'bad'}`}>{currentStatus}</span>
                    <span className={`tag ${isAnnotationDirty ? 'bad' : 'ok'}`}>{isAnnotationDirty ? 'unsaved changes' : 'saved'}</span>
                    {selected.bbox ? (
                      <span className="tiny muted mono">
                        saved bbox: x={selected.bbox.x}, y={selected.bbox.y}, w={selected.bbox.w}, h={selected.bbox.h}
                      </span>
                    ) : (
                      <span className="tiny muted">No saved bbox yet.</span>
                    )}
                  </div>
                </div>
                <div className="stack">
                  <label title="Ground-truth plate string for this sample.">Plate text</label>
                  <input
                    title="Enter the true plate value to train OCR correctly."
                    value={form.plate_text}
                    disabled={form.no_plate || form.unclear_plate}
                    onChange={(e) => setForm((f) => ({ ...f, plate_text: e.target.value }))}
                  />
                  <label className="row tiny" title="Use this when the sample should be treated as negative (no valid plate).">
                    <input
                      title="Mark this sample as no-plate negative."
                      type="checkbox"
                      checked={form.no_plate}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          no_plate: e.target.checked,
                          unclear_plate: e.target.checked ? false : f.unclear_plate,
                          plate_text: e.target.checked ? '' : f.plate_text,
                        }))
                      }
                    /> No plate (negative)
                  </label>
                  <label className="row tiny" title="Plate is present but unreadable/unclear. Keeps bbox and excludes this sample from text supervision.">
                    <input
                      title="Mark this sample as unclear plate."
                      type="checkbox"
                      checked={form.unclear_plate}
                      disabled={form.no_plate}
                      onChange={(e) =>
                        setForm((f) => ({
                          ...f,
                          unclear_plate: e.target.checked,
                          plate_text: e.target.checked ? '' : f.plate_text,
                        }))
                      }
                    /> Plate present but unclear
                  </label>
                  <div className="row two">
                    <input title="Bounding box X position (left)." placeholder="x" type="number" value={form.bbox_x} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_x: e.target.value }))} />
                    <input title="Bounding box Y position (top)." placeholder="y" type="number" value={form.bbox_y} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_y: e.target.value }))} />
                    <input title="Bounding box width in pixels." placeholder="w" type="number" value={form.bbox_w} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_w: e.target.value }))} />
                    <input title="Bounding box height in pixels." placeholder="h" type="number" value={form.bbox_h} disabled={form.no_plate} onChange={(e) => setForm((f) => ({ ...f, bbox_h: e.target.value }))} />
                  </div>
                  <div className="row">
                    <button type="button" className="btn ghost" disabled={form.no_plate} onClick={() => adjustBbox(-2, 0, 0, 0)}>x-</button>
                    <button type="button" className="btn ghost" disabled={form.no_plate} onClick={() => adjustBbox(2, 0, 0, 0)}>x+</button>
                    <button type="button" className="btn ghost" disabled={form.no_plate} onClick={() => adjustBbox(0, -2, 0, 0)}>y-</button>
                    <button type="button" className="btn ghost" disabled={form.no_plate} onClick={() => adjustBbox(0, 2, 0, 0)}>y+</button>
                    <button type="button" className="btn ghost" disabled={form.no_plate} onClick={() => adjustBbox(0, 0, -2, -2)}>size-</button>
                    <button type="button" className="btn ghost" disabled={form.no_plate} onClick={() => adjustBbox(0, 0, 2, 2)}>size+</button>
                  </div>
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={() => setForm((f) => ({ ...f, bbox_x: '', bbox_y: '', bbox_w: '', bbox_h: '' }))}
                    disabled={form.no_plate}
                  >
                    Clear BBox
                  </button>
                  <textarea title="Optional operator notes about visibility, occlusion, or annotation decisions." placeholder="notes" value={form.notes} onChange={(e) => setForm((f) => ({ ...f, notes: e.target.value }))} />
                  <button
                    type="button"
                    className="btn ghost"
                    onClick={reprocessSelected}
                    disabled={!selectedId || form.no_plate || reprocessBusy}
                    title="Run OCR on this exact image+bbox and update the same sample (no new sample created)."
                  >
                    <RefreshCcw size={14} /> {reprocessBusy ? 'Reprocessing...' : 'Reprocess This Image'}
                  </button>
                  <button className="btn primary" type="submit"><Save size={14} /> Save Annotation</button>
                </div>
              </div>

              <div>
                <div className="tiny muted">Debug steps</div>
                <div className="feedback-debug-grid">
                  {orderedDebugSteps.map((step) => (
                    <button
                      key={`train-debug-${step.key}`}
                      type="button"
                      className={`feedback-debug-card ${step.path ? '' : 'is-missing'}`}
                      onClick={() => step.path && openDebugStep(step.key)}
                      disabled={!step.path}
                    >
                      {step.path ? (
                        <img src={mediaPath(step.path)} alt={step.label} />
                      ) : (
                        <div className="preview-image" style={{ height: 86, display: 'grid', placeItems: 'center' }}>
                          <span className="tiny muted">Not generated</span>
                        </div>
                      )}
                      <strong className="small">{step.label}</strong>
                      <span className="tiny muted">{step.path ? 'Ready' : 'Missing'}</span>
                    </button>
                  ))}
                </div>
              </div>
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
            {debugPreview.steps[debugPreview.index]?.path ? (
              <img className="preview-image" src={mediaPath(debugPreview.steps[debugPreview.index]?.path)} alt="training-debug" />
            ) : (
              <div className="panel glass">
                <div className="muted tiny">This debug image is not generated yet for the current annotation.</div>
              </div>
            )}
            <div className="row">
              {debugPreview.steps.map((step, idx) => (
                <button
                  key={`train-step-${step.key}-${idx}`}
                  type="button"
                  className={`btn ${idx === debugPreview.index ? 'primary' : ''}`}
                  onClick={() => setDebugPreview((d) => ({ ...d, index: idx }))}
                  disabled={!step.path}
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
