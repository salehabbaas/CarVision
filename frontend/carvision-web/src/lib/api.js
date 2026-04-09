const LOCAL_HOSTS = new Set(['localhost', '127.0.0.1', '::1']);
const CLIENT_BUILD_ID = '2026-04-09-api-fix-1';

function resolveApiBase() {
  const raw = String(import.meta.env.VITE_API_URL || '').trim();
  if (!raw) return '';
  if (typeof window === 'undefined') return raw.replace(/\/$/, '');

  try {
    const pageUrl = new URL(window.location.href);
    const apiUrl = new URL(raw, window.location.origin);

    // If the app is opened on another device (phone/tablet), a localhost API
    // URL points to that device itself, not the CarVision server.
    if (LOCAL_HOSTS.has(apiUrl.hostname) && !LOCAL_HOSTS.has(pageUrl.hostname)) {
      return '';
    }

    // Browsers block https pages from calling http APIs (mixed content).
    // Fall back to same-origin proxy path in this case.
    if (pageUrl.protocol === 'https:' && apiUrl.protocol === 'http:') {
      return '';
    }

    return apiUrl.href.replace(/\/$/, '');
  } catch {
    return '';
  }
}

const API_BASE = resolveApiBase();

export function apiPath(path) {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith('/')) return API_BASE ? `${API_BASE}/${path}` : `/${path}`;
  return API_BASE ? `${API_BASE}${path}` : path;
}

export function mediaPath(path) {
  if (!path) return '';
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith('/media/')) return apiPath(path);
  if (path.startsWith('media/')) return apiPath(`/${path}`);
  return apiPath(`/media/${path.replace(/^\//, '')}`);
}

export async function request(path, {
  token,
  method = 'GET',
  body,
  headers = {},
  signal,
} = {}) {
  const reqInit = {
    method,
    headers: {
      'Content-Type': 'application/json',
      'X-CarVision-Client-Build': CLIENT_BUILD_ID,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body ? JSON.stringify(body) : undefined,
    signal,
  };
  let res;
  try {
    res = await fetch(apiPath(path), reqInit);
  } catch (err) {
    // Runtime safety net for stale/cached builds with bad absolute API URL.
    if (API_BASE && typeof window !== 'undefined' && !/^https?:\/\//i.test(path)) {
      const fallbackPath = path.startsWith('/') ? path : `/${path}`;
      res = await fetch(fallbackPath, reqInit);
    } else {
      throw err;
    }
  }

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
