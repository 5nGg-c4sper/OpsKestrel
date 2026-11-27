import { useCallback, useEffect, useRef, useState } from "react";

interface PollingResult<T> {
  data: T | null;
  error: Error | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

export function usePolling<T>(
  loader: () => Promise<T>,
  intervalMs: number,
  cacheKey = ""
): PollingResult<T> {
  const loaderRef = useRef(loader);
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);
  const activeRef = useRef(true);

  useEffect(() => {
    loaderRef.current = loader;
  }, [loader]);

  const refresh = useCallback(async () => {
    try {
      const next = await loaderRef.current();
      if (activeRef.current) {
        setData(next);
        setError(null);
      }
    } catch (caught) {
      if (activeRef.current) {
        setError(caught instanceof Error ? caught : new Error(String(caught)));
      }
    } finally {
      if (activeRef.current) {
        setLoading(false);
      }
    }
  }, []);

  useEffect(() => {
    activeRef.current = true;
    setLoading(true);
    void refresh();
    const timer = window.setInterval(() => {
      void refresh();
    }, intervalMs);
    return () => {
      activeRef.current = false;
      window.clearInterval(timer);
    };
  }, [cacheKey, intervalMs, refresh]);

  return { data, error, loading, refresh };
}
