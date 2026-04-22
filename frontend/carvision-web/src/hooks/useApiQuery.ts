import { useCallback, useEffect, useRef, useState } from "react";

export interface ClassifiedError {
  message: string;
  type: "network" | "auth" | "permission" | "server" | "unknown";
}

export function classifyError(err: unknown): ClassifiedError {
  if (!err) return { message: "Unknown error", type: "unknown" };
  const message = err instanceof Error ? err.message : String(err);
  const lower = message.toLowerCase();

  const type =
    err instanceof TypeError ||
    lower.includes("failed to fetch") ||
    lower.includes("load failed") ||
    lower.includes("networkerror") ||
    lower.includes("network request") ||
    lower.includes("net::err")
      ? "network"
      : lower.includes("401") || lower.includes("unauthorized")
        ? "auth"
        : lower.includes("403") || lower.includes("forbidden")
          ? "permission"
          : /5\d\d/.test(lower) ||
              lower.includes("internal server") ||
              lower.includes("bad gateway") ||
              lower.includes("service unavailable")
            ? "server"
            : "unknown";

  return { message, type };
}

interface UseApiQueryOptions {
  pollInterval?: number;
  deps?: ReadonlyArray<unknown>;
  keepOnError?: boolean;
  enabled?: boolean;
}

export function useApiQuery<T>(
  fetchFn: () => Promise<T>,
  { pollInterval = 0, deps = [], keepOnError = true, enabled = true }: UseApiQueryOptions = {}
) {
  const [data, setData] = useState<T | undefined>(undefined);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<ClassifiedError | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const fnRef = useRef(fetchFn);
  const hasDataRef = useRef(false);
  fnRef.current = fetchFn;

  const doFetch = useCallback(async () => {
    if (!hasDataRef.current) setLoading(true);
    try {
      const result = await fnRef.current();
      hasDataRef.current = true;
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(classifyError(err));
      if (!keepOnError) {
        hasDataRef.current = false;
        setData(undefined);
      }
    } finally {
      setLoading(false);
    }
  }, [keepOnError]);

  useEffect(() => {
    if (!enabled) {
      setLoading(false);
      return;
    }

    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;

    hasDataRef.current = false;
    setLoading(true);
    setError(null);

    const run = async () => {
      if (!alive) return;
      await doFetch();
      if (!alive || pollInterval <= 0) return;
      timer = setTimeout(run, pollInterval);
    };

    void run();

    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
    };
  }, [doFetch, enabled, pollInterval, ...deps]);

  const refetch = useCallback(() => {
    hasDataRef.current = false;
    void doFetch();
  }, [doFetch]);

  return { data, loading, error, refetch, lastUpdated };
}
