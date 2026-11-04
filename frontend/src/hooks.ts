import { useCallback, useEffect, useRef, useState } from "react";
import type { Alert, BlockRow } from "./api";

export interface Async<T> {
  data: T | undefined;
  error: Error | undefined;
  loading: boolean;
  reload: () => void;
}

/** Fetch on mount and whenever `deps` change; optionally refresh every `refreshMs`. */
export function useApi<T>(fn: () => Promise<T>, deps: unknown[], refreshMs?: number): Async<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<Error>();
  const [loading, setLoading] = useState(true);
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fn()
      .then((d) => alive && (setData(d), setError(undefined)))
      .catch((e: Error) => alive && setError(e))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick]);

  useEffect(() => {
    if (!refreshMs) return;
    const id = setInterval(reload, refreshMs);
    return () => clearInterval(id);
  }, [refreshMs, reload]);

  return { data, error, loading, reload };
}

/** Minimal hash router: "#/blocks/123" -> ["blocks", "123"]. */
export function useRoute(): string[] {
  const parse = () => window.location.hash.replace(/^#\/?/, "").split("/").filter(Boolean);
  const [route, setRoute] = useState(parse);
  useEffect(() => {
    const on = () => {
      setRoute(parse());
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);
  return route;
}

export interface LiveState {
  connected: boolean;
  lastBlock: BlockRow | undefined;
  alerts: Alert[];
  blockCount: number;
}

/** Subscribe to the backend's Server-Sent-Events stream (/api/stream). */
export function useLiveStream(maxAlerts = 30): LiveState {
  const [state, setState] = useState<LiveState>({ connected: false, lastBlock: undefined, alerts: [], blockCount: 0 });
  const ref = useRef<EventSource>();

  useEffect(() => {
    const es = new EventSource("/api/stream");
    ref.current = es;
    es.onopen = () => setState((s) => ({ ...s, connected: true }));
    es.onerror = () => setState((s) => ({ ...s, connected: false }));
    es.addEventListener("block", (e) => {
      const b = JSON.parse((e as MessageEvent).data) as BlockRow;
      setState((s) => ({ ...s, lastBlock: b, blockCount: s.blockCount + 1 }));
    });
    es.addEventListener("alert", (e) => {
      const a = JSON.parse((e as MessageEvent).data) as Alert;
      setState((s) => ({ ...s, alerts: [a, ...s.alerts].slice(0, maxAlerts) }));
    });
    return () => es.close();
  }, [maxAlerts]);

  return state;
}

/** Persist a small per-viewer preference; storage failures fall back to memory. */
export function usePref<T>(key: string, initial: T): [T, (v: T) => void] {
  const [v, setV] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? initial : (JSON.parse(raw) as T);
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T) => {
      setV(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        /* private mode etc. */
      }
    },
    [key],
  );
  return [v, set];
}
