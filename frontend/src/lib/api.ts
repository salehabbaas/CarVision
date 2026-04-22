const LOCAL_HOSTS = new Set(["localhost", "127.0.0.1", "::1"]);
const CLIENT_BUILD_ID = "2026-04-14-ui-refresh-1";

interface RequestOptions {
  token?: string;
  method?: string;
  body?: unknown;
  headers?: Record<string, string>;
  signal?: AbortSignal;
}

function resolveApiBase() {
  const raw = String(import.meta.env.VITE_API_URL || "").trim();
  if (!raw) return "";
  if (typeof window === "undefined") return raw.replace(/\/$/, "");

  try {
    const pageUrl = new URL(window.location.href);
    const apiUrl = new URL(raw, window.location.origin);

    if (LOCAL_HOSTS.has(apiUrl.hostname) && !LOCAL_HOSTS.has(pageUrl.hostname)) {
      return "";
    }

    if (pageUrl.protocol === "https:" && apiUrl.protocol === "http:") {
      return "";
    }

    return apiUrl.href.replace(/\/$/, "");
  } catch {
    return "";
  }
}

const API_BASE = resolveApiBase();

export function apiPath(path: string) {
  if (/^https?:\/\//i.test(path)) return path;
  if (!path.startsWith("/")) return API_BASE ? `${API_BASE}/${path}` : `/${path}`;
  return API_BASE ? `${API_BASE}${path}` : path;
}

export function mediaPath(path?: string | null) {
  if (!path) return "";
  if (/^https?:\/\//i.test(path)) return path;
  if (path.startsWith("/media/")) return apiPath(path);
  if (path.startsWith("media/")) return apiPath(`/${path}`);
  return apiPath(`/media/${path.replace(/^\//, "")}`);
}

export async function request<T = any>(
  path: string,
  { token, method = "GET", body, headers = {}, signal }: RequestOptions = {}
): Promise<T> {
  const requestInit: RequestInit = {
    method,
    headers: {
      "Content-Type": "application/json",
      "X-CarVision-Client-Build": CLIENT_BUILD_ID,
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body !== undefined ? JSON.stringify(body) : undefined,
    signal,
  };

  let response: Response;
  try {
    response = await fetch(apiPath(path), requestInit);
  } catch (error) {
    if (API_BASE && typeof window !== "undefined" && !/^https?:\/\//i.test(path)) {
      const fallbackPath = path.startsWith("/") ? path : `/${path}`;
      response = await fetch(fallbackPath, requestInit);
    } else {
      throw error;
    }
  }

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const message =
      typeof data === "object" && data && "detail" in data
        ? String((data as { detail?: string }).detail)
        : `Request failed (${response.status})`;
    throw new Error(message);
  }

  return data as T;
}
