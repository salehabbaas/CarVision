export const DEFAULT_CLIP_MINUTES = 1;
export const DEFAULT_CLIP_SECONDS = DEFAULT_CLIP_MINUTES * 60;
export const CAMERA_DETECTOR_OPTIONS = [
  { value: 'inherit', label: 'inherit' },
  { value: 'auto', label: 'auto' },
  { value: 'contour', label: 'contour' },
  { value: 'yolo', label: 'yolo' },
  { value: 'ocr', label: 'ocr' },
];

export function secondsToMinutes(value) {
  const seconds = Math.max(0, Number(value) || 0);
  return seconds > 0 ? Number((seconds / 60).toFixed(2)) : 0;
}

export function minutesToSeconds(value) {
  const minutes = Math.max(0, Number(value) || 0);
  return Math.round(minutes * 60);
}

export function toCameraDraft(cam) {
  return {
    name: cam.name || '',
    type: cam.type || 'rtsp',
    source: cam.source || '',
    location: cam.location || '',
    enabled: !!cam.enabled,
    live_view: !!cam.live_view,
    live_order: Number(cam.live_order || 0),
    detector_mode: cam.detector_mode || 'inherit',
    scan_interval: Number(cam.scan_interval || 1),
    cooldown_seconds: Number(cam.cooldown_seconds || 10),
    save_clip: !!cam.save_clip,
    clip_seconds: Number(cam.clip_seconds || DEFAULT_CLIP_SECONDS),
    onvif_xaddr: cam.onvif_xaddr || '',
    onvif_username: cam.onvif_username || '',
    onvif_password: '',
    onvif_profile: cam.onvif_profile || '',
  };
}

export function buildCameraPatchPayload(draft) {
  const payload = {
    name: (draft?.name || '').trim(),
    type: draft?.type || 'rtsp',
    source: (draft?.type === 'browser' ? ((draft?.source || '').trim() || 'browser') : (draft?.source || '').trim()),
    location: (draft?.location || '').trim() || null,
    enabled: !!draft?.enabled,
    live_view: !!draft?.live_view,
    live_order: Number(draft?.live_order) || 0,
    detector_mode: draft?.detector_mode || 'inherit',
    scan_interval: Math.max(0.1, Number(draft?.scan_interval) || 1),
    cooldown_seconds: Math.max(0, Number(draft?.cooldown_seconds) || 0),
    save_clip: !!draft?.save_clip,
    clip_seconds: Math.max(0, Number(draft?.clip_seconds) || DEFAULT_CLIP_SECONDS),
    onvif_xaddr: (draft?.onvif_xaddr || '').trim() || null,
    onvif_username: (draft?.onvif_username || '').trim() || null,
    onvif_profile: (draft?.onvif_profile || '').trim() || null,
  };
  if ((draft?.onvif_password || '').trim()) {
    payload.onvif_password = (draft.onvif_password || '').trim();
  }
  return payload;
}
