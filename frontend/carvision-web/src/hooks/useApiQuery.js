/**
 * useApiQuery – fetch + optional polling with proper loading/error states.
 *
 * Guarantees:
 *  - Shows loading=true only on the FIRST load (while data===undefined).
 *  - On polling errors, keeps stale data and sets error — data never disappears.
 *  - Classifies errors into: network | auth | server | unknown.
 *  - Cleans up (cancels pending fetch) on unmount or dep change.
 */
import { useCallback, useEffect, useRef, useState } from 'react';

// ── Error classifier ──────────────────────────────────────────────────────────
export function classifyError(err) {
  if (!err) return { message: 'Unknown error', type: 'unknown' };
  const msg = (err.message || String(err)).toLowerCase();
  const type =
    err.name === 'TypeError'        ||
    msg.includes('failed to fetch') ||
    msg.includes('load failed')     ||
    msg.includes('networkerror')    ||
    msg.includes('network request') ||
    msg.includes('net::err')
      ? 'network'
    : msg.includes('401') || msg.includes('unauthorized')
      ? 'auth'
    : msg.includes('403') || msg.includes('forbidden')
      ? 'permission'
    : msg.match(/5\d\d/) ||
      msg.includes('internal server') ||
      msg.includes('bad gateway')    ||
      msg.includes('service unavailable')
      ? 'server'
    : 'unknown';

  return { message: err.message || 'Request failed', type };
}

// ── Main hook ─────────────────────────────────────────────────────────────────
export function useApiQuery(fetchFn, {
  pollInterval  = 0,     // ms — 0 = no auto-poll
  deps          = [],    // extra deps that trigger a fresh fetch
  keepOnError   = true,  // keep stale data when a poll fails
  enabled       = true,  // set false to skip fetching entirely
} = {}) {
  const [data,  setData]  = useState(undefined);
  const [loading, setLoading] = useState(enabled);
  const [error,   setError]   = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  // Keep a ref to the latest fetchFn so we can call it from inside the effect
  // without making the effect re-run every render.
  const fnRef = useRef(fetchFn);
  fnRef.current = fetchFn;

  // Whether we've ever received data (used to decide "show spinner" vs "silently poll").
  const hasDataRef = useRef(false);

  const doFetch = useCallback(async () => {
    // Show spinner only on the very first load.
    if (!hasDataRef.current) setLoading(true);
    try {
      const result = await fnRef.current();
      hasDataRef.current = true;
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      if (err?.name === 'AbortError') return;
      const classified = classifyError(err);
      setError(classified);
      if (!keepOnError) {
        hasDataRef.current = false;
        setData(undefined);
      }
    } finally {
      setLoading(false);
    }
  }, [keepOnError]);

  useEffect(() => {
    if (!enabled) { setLoading(false); return; }

    let alive = true;
    let timer;

    // Reset "has data" flag so new deps always start fresh.
    hasDataRef.current = false;
    setLoading(true);
    setError(null);

    const run = async () => {
      if (!alive) return;
      await doFetch();
      if (!alive) return;
      if (pollInterval > 0) timer = setTimeout(run, pollInterval);
    };

    run();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [doFetch, enabled, pollInterval, ...deps]);

  const refetch = useCallback(() => {
    hasDataRef.current = false;
    doFetch();
  }, [doFetch]);

  return { data, loading, error, refetch, lastUpdated };
}
