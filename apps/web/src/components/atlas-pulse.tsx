"use client";

import { useEffect, useState } from "react";
import type { AtlasResourceSnapshot } from "@prism/api-contracts";
import { apiUrl } from "../config/api";

type PulseState = { kind: "loading" } | { kind: "error" } | { kind: "ready"; snapshot: AtlasResourceSnapshot };

const POLL_MS = 20_000;

/**
 * Polls Atlas's real resource governor (GET /api/v1/atlas/resources/snapshot)
 * so the ambient Atlas presence chip reflects genuine machine/workload state
 * rather than a permanently static "watching" label. `active_leases` only
 * appear when something -- today, Foundry training -- actually acquired one
 * (see apps/api/src/prism_api/atlas_resources.py), so "N active" is a real
 * signal, never invented activity. Polling pauses while the tab is hidden so
 * an always-open workspace doesn't poll forever in a background tab.
 */
export function useAtlasResourceSnapshot(): PulseState {
  const [state, setState] = useState<PulseState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(apiUrl("/api/v1/atlas/resources/snapshot"));
        if (!response.ok) throw new Error(`Resource snapshot request failed: ${response.status}`);
        const snapshot = (await response.json()) as AtlasResourceSnapshot;
        if (!cancelled) setState({ kind: "ready", snapshot });
      } catch {
        if (!cancelled) setState({ kind: "error" });
      }
    }
    void load();
    const interval = window.setInterval(() => {
      if (document.visibilityState === "visible") void load();
    }, POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  return state;
}

export function activeLeaseCount(state: PulseState): number {
  if (state.kind !== "ready") return 0;
  return (state.snapshot.active_leases ?? []).filter((lease) => lease.state === "active").length;
}

/** The subtitle shown on the collapsed ambient chip -- real workload count when Atlas is doing something, otherwise the existing idle copy. */
export function pulseSubtitle(state: PulseState, expanded: boolean): string {
  if (expanded) return "Context workspace ready";
  const active = activeLeaseCount(state);
  if (active > 0) return `${active} workload${active === 1 ? "" : "s"} active`;
  return "Watching workspace context";
}

export function AtlasSystemPanel({ state }: { state: PulseState }) {
  if (state.kind === "loading") {
    return (
      <section className="atlas-system-panel" aria-label="Atlas system resources">
        <span className="eyebrow">SYSTEM</span>
        <p className="quiet-note">Checking machine resources…</p>
      </section>
    );
  }
  if (state.kind === "error") {
    return (
      <section className="atlas-system-panel" aria-label="Atlas system resources">
        <span className="eyebrow">SYSTEM</span>
        <p className="quiet-note">Could not reach the resource governor.</p>
      </section>
    );
  }
  const { snapshot } = state;
  const ramUsedPct =
    snapshot.memory_total_mb && snapshot.memory_available_mb != null
      ? Math.round(((snapshot.memory_total_mb - snapshot.memory_available_mb) / snapshot.memory_total_mb) * 100)
      : null;
  const active = (snapshot.active_leases ?? []).filter((lease) => lease.state === "active");
  const queued = (snapshot.active_leases ?? []).filter((lease) => lease.state === "queued");
  return (
    <section className="atlas-system-panel" aria-label="Atlas system resources">
      <span className="eyebrow">SYSTEM</span>
      <dl>
        <div>
          <dt>CPU</dt>
          <dd>{snapshot.cpu_count} core{snapshot.cpu_count === 1 ? "" : "s"}</dd>
        </div>
        <div>
          <dt>RAM</dt>
          <dd>
            {ramUsedPct != null
              ? `${ramUsedPct}% used · ${Math.round((snapshot.memory_total_mb! - snapshot.memory_available_mb!) / 1024)} / ${Math.round(snapshot.memory_total_mb! / 1024)} GB`
              : "Unavailable"}
          </dd>
        </div>
        <div>
          <dt>Storage</dt>
          <dd>{snapshot.storage_free_mb != null ? `${Math.round(snapshot.storage_free_mb / 1024)} GB free` : "Unavailable"}</dd>
        </div>
        <div>
          <dt>GPU</dt>
          <dd title={snapshot.gpu_telemetry_detail}>
            {snapshot.gpu_available
              ? `${snapshot.gpu_name ?? "Detected"}${snapshot.vram_total_mb ? ` · ${Math.round(snapshot.vram_total_mb / 1024)} GB VRAM` : ""}`
              : "Not detected"}
          </dd>
        </div>
      </dl>
      {active.length || queued.length ? (
        <ul className="atlas-workload-list">
          {active.map((lease) => (
            <li key={lease.lease_id} data-state="active">
              <strong>{lease.workload.description}</strong>
              <small>active</small>
            </li>
          ))}
          {queued.map((lease) => (
            <li key={lease.lease_id} data-state="queued">
              <strong>{lease.workload.description}</strong>
              <small>queued</small>
            </li>
          ))}
        </ul>
      ) : (
        <p className="quiet-note">No Atlas workloads are currently using resources.</p>
      )}
    </section>
  );
}
