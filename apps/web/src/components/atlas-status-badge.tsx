"use client";

import { useEffect, useState } from "react";
import type { AtlasProductionTrustStatus } from "@prism/api-contracts";
import { apiUrl } from "../config/api";

type BadgeState = { kind: "loading" } | { kind: "error" } | { kind: "status"; status: AtlasProductionTrustStatus };

/**
 * Always-visible ATLAS model/trust indicator for the topbar. This never
 * decides or fabricates anything -- it renders exactly what
 * GET /api/v1/atlas/promotion/current-status reports, including the honest
 * "no production model yet" and "legacy (unverified)" states. It must never
 * hardcode a model name or a "verified" claim: those come only from the API
 * response.
 */
export function AtlasStatusBadge() {
  const [state, setState] = useState<BadgeState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(apiUrl("/api/v1/atlas/promotion/current-status"));
        if (!response.ok) throw new Error(`Atlas status request failed: ${response.status}`);
        const status = (await response.json()) as AtlasProductionTrustStatus;
        if (!cancelled) setState({ kind: "status", status });
      } catch {
        if (!cancelled) setState({ kind: "error" });
      }
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, []);

  const presentation = presentationFor(state);
  return (
    <span className={`atlas-status-badge migration-chip ${presentation.tone}`} role="status" aria-live="polite" title={presentation.detail}>
      <span className="status-dot" />
      <span>{presentation.label}</span>
    </span>
  );
}

function presentationFor(state: BadgeState): { label: string; tone: string; detail: string } {
  if (state.kind === "loading") {
    return { label: "ATLAS · CHECKING", tone: "legacy", detail: "Loading Atlas production trust status." };
  }
  if (state.kind === "error") {
    return { label: "ATLAS · STATUS UNKNOWN", tone: "unavailable", detail: "Could not reach the Atlas promotion status endpoint." };
  }
  const { status } = state;
  if (!status.production) {
    return { label: "ATLAS · NO PRODUCTION MODEL", tone: "unavailable", detail: "No candidate has ever been promoted to production." };
  }
  if (!status.candidate_kind) {
    return {
      label: `ATLAS · LEGACY${status.runtime_model ? ` · ${status.runtime_model}` : ""}`,
      tone: "legacy",
      detail: "Production is a legacy/bootstrap pointer that predates the trust registries -- neither verified nor rejected.",
    };
  }
  if (status.trust_verification_state !== "verified") {
    return {
      label: `ATLAS · UNVERIFIED${status.runtime_model ? ` · ${status.runtime_model}` : ""}`,
      tone: "bridged",
      detail: `Trust verification state: ${status.trust_verification_state ?? "unknown"}.`,
    };
  }
  return {
    label: `ATLAS · VERIFIED${status.runtime_model ? ` · ${status.runtime_model}` : ""}`,
    tone: "native",
    detail: benchDetail(status),
  };
}

function benchDetail(status: AtlasProductionTrustStatus): string {
  const parts: string[] = [];
  if (status.latest_v1_run_id) {
    parts.push(`AtlasBench V1: ${status.latest_v1_total_passed ?? "?"}/${status.latest_v1_total_tasks ?? "?"}`);
  }
  if (status.latest_operational_cert_run_id) {
    parts.push(
      `Operational cert: ${status.latest_operational_cert_total_passed ?? "?"}/${status.latest_operational_cert_total_scenarios ?? "?"} · ${status.latest_operational_cert_critical_failures ?? 0} critical failures`
    );
  }
  return parts.length ? parts.join(" · ") : "Verified production candidate; no recorded bench or operational cert run yet.";
}
