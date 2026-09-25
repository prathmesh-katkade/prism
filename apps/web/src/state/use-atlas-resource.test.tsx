import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useAtlasResource, ATLAS_REQUEST_TIMEOUT_MS } from "./use-atlas-resource";

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

it("aborts old context and rejects its late response", async () => {
  let oldResolve!: (response: Response) => void;
  let oldSignal: AbortSignal | undefined;
  vi.stubGlobal("fetch", vi.fn((path: string, options: RequestInit) => {
    if (path.endsWith("/old")) { oldSignal = options.signal as AbortSignal; return new Promise<Response>((resolve) => { oldResolve = resolve; }); }
    return Promise.resolve(new Response(JSON.stringify({ id: "new" })));
  }));
  const hook = renderHook(({ path }) => useAtlasResource<{ id: string }>(path), { initialProps: { path: "/old" } });
  hook.rerender({ path: "/new" });
  await waitFor(() => expect(hook.result.current.data?.id).toBe("new"));
  expect(oldSignal?.aborted).toBe(true);
  await act(async () => oldResolve(new Response(JSON.stringify({ id: "old" }))));
  expect(hook.result.current.data?.id).toBe("new");
});

it("bounds hung requests and recovers on retry", async () => {
  vi.useFakeTimers();
  const fetcher = vi.fn().mockImplementationOnce(() => new Promise(() => {})).mockResolvedValue(new Response(JSON.stringify({ ok: true })));
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(({ revision }) => useAtlasResource("/summary", revision), { initialProps: { revision: 0 } });
  await act(async () => vi.advanceTimersByTime(ATLAS_REQUEST_TIMEOUT_MS));
  expect(hook.result.current.error).toContain("timed out");
  await act(async () => hook.rerender({ revision: 1 }));
  expect(hook.result.current.data).toEqual({ ok: true });
});

it("marks retained same-context content stale while refreshing and on failure", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(new Response(JSON.stringify({ ok: true }))).mockRejectedValue(new Error("offline"));
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(({ revision }) => useAtlasResource("/summary", revision), { initialProps: { revision: 0 } });
  await waitFor(() => expect(hook.result.current.data).toEqual({ ok: true }));
  hook.rerender({ revision: 1 });
  await waitFor(() => expect(hook.result.current.error).toBeTruthy());
  expect(hook.result.current.stale).toBe(true);
  expect(hook.result.current.data).toEqual({ ok: true });
});
