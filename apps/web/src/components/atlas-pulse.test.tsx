import React from "react";
import { render, renderHook, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { activeLeaseCount, AtlasSystemPanel, pulseSubtitle, useAtlasResourceSnapshot } from "./atlas-pulse";
import type { AtlasResourceLease, AtlasResourceSnapshot } from "@prism/api-contracts";

describe("Atlas resource pulse", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports zero active leases and the idle subtitle when the governor is unreachable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network unavailable"); }));
    const { result } = renderHook(() => useAtlasResourceSnapshot());
    await waitFor(() => expect(result.current.kind).toBe("error"));
    expect(activeLeaseCount(result.current)).toBe(0);
    expect(pulseSubtitle(result.current, false)).toBe("Watching workspace context");
  });

  it("counts only active leases, not queued or released ones, and reflects that in the subtitle", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => snapshotResponse(withLeases([
      { lease_id: "l1", state: "active", workload: { workload_id: "w1", priority: 2, description: "Training candidate 3" }, reason: "Capacity admitted the workload." },
      { lease_id: "l2", state: "queued", workload: { workload_id: "w2", priority: 3, description: "Baseline sweep" }, reason: "Waiting for capacity." },
    ]))));
    const { result } = renderHook(() => useAtlasResourceSnapshot());
    await waitFor(() => expect(result.current.kind).toBe("ready"));
    expect(activeLeaseCount(result.current)).toBe(1);
    expect(pulseSubtitle(result.current, false)).toBe("1 workload active");
  });

  it("never invents a GPU when the backend reports none detected", async () => {
    render(<AtlasSystemPanel state={{ kind: "ready", snapshot: withLeases([]) }} />);
    await waitFor(() => expect(screen.getByText("Not detected")).toBeInTheDocument());
    expect(screen.getByText("No Atlas workloads are currently using resources.")).toBeInTheDocument();
  });

  it("shows real GPU and workload detail without fabricating a utilization percentage", () => {
    const snapshot = withLeases([
      { lease_id: "l1", state: "active", workload: { workload_id: "w1", priority: 1, description: "Training candidate 3" }, reason: "Capacity admitted the workload." },
    ]);
    render(<AtlasSystemPanel state={{ kind: "ready", snapshot: { ...snapshot, gpu_available: true, gpu_name: "RTX 4090", vram_total_mb: 24576, gpu_telemetry_detail: "NVIDIA telemetry available through nvidia-smi." } }} />);
    expect(screen.getByText("RTX 4090 · 24 GB VRAM")).toBeInTheDocument();
    expect(screen.getByText("Training candidate 3")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });
});

function withLeases(leases: AtlasResourceLease[]): AtlasResourceSnapshot {
  return {
    cpu_count: 8,
    memory_total_mb: 16384,
    memory_available_mb: 8192,
    storage_free_mb: 102400,
    gpu_available: false,
    gpu_telemetry_detail: "GPU telemetry is unavailable; Atlas will not assume a GPU or VRAM budget.",
    active_leases: leases,
  };
}

function snapshotResponse(snapshot: AtlasResourceSnapshot): Response {
  return new Response(JSON.stringify(snapshot), { status: 200, headers: { "content-type": "application/json" } });
}
