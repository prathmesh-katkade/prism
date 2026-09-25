"use client";
import { useEffect, useState } from "react";
import { apiUrl } from "../config/api";

export const ATLAS_REQUEST_TIMEOUT_MS = 10_000;

/** Keyed reads never expose another context's data, even before effect cleanup. */
export function useAtlasResource<T>(path: string | null, revision = 0) {
  const [result, setResult] = useState<{ key: string | null; data: T | null; loading: boolean; error: string | null }>({ key: null, data: null, loading: true, error: null });
  useEffect(() => {
    if (!path) return;
    const controller = new AbortController();
    let active = true;
    let timedOut = false;
    setResult((old) => ({ key: path, data: old.key === path ? old.data : null, loading: true, error: null }));
    const timeout = setTimeout(() => {
      timedOut = true;
      controller.abort();
      if (active) setResult((old) => ({ ...old, loading: false, error: "Request timed out. Retry to recover." }));
    }, ATLAS_REQUEST_TIMEOUT_MS);
    fetch(apiUrl(path), { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) throw new Error("Request failed. Retry to recover.");
        const data = await response.json() as T;
        if (active && !controller.signal.aborted) setResult({ key: path, data, loading: false, error: null });
      })
      .catch(() => {
        if (active && !timedOut) setResult((old) => ({ ...old, loading: false, error: "Request failed. Retry to recover." }));
      })
      .finally(() => clearTimeout(timeout));
    return () => { active = false; clearTimeout(timeout); controller.abort(); };
  }, [path, revision]);
  if (!path) return { data: null, loading: false, error: null, stale: false };
  if (result.key !== path) return { data: null, loading: true, error: null, stale: false };
  return { ...result, stale: Boolean(result.data && (result.loading || result.error)) };
}
