const envBase = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '');
const fallbackBase =
  typeof window !== 'undefined'
    ? `${window.location.protocol}//${window.location.hostname}:8000`
    : '';
const API_BASE = (envBase || fallbackBase).replace(/\/$/, '');

export function apiPath(path) {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith('/')) return `${API_BASE}/${path}`;
  return `${API_BASE}${path}`;
}

export function mediaPath(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/media/')) return apiPath(path);
  if (path.startsWith('media/')) return apiPath(`/${path}`);
  return apiPath(`/media/${path.replace(/^\//, '')}`);
}

export async function request(path, { token, method = 'GET', body, headers = {} } = {}) {
  const res = await fetch(apiPath(path), {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
  });

  let data;
  const contentType = res.headers.get('content-type') || '';
  if (contentType.includes('application/json')) {
    data = await res.json();
  } else {
    data = await res.text();
  }

  if (!res.ok) {
    const message = typeof data === 'object' && data?.detail ? data.detail : `Request failed (${res.status})`;
    throw new Error(message);
  }

  return data;
}
