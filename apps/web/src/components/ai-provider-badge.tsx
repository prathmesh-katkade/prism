"use client";

import { useEffect, useState } from "react";
import type { ReadinessResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";

type BadgeState = { kind: "loading" } | { kind: "error" } | { kind: "ready"; ollama: ReadinessResponse["providers"][number] | undefined };

/**
 * Local-first AI indicator for the topbar, next to AtlasStatusBadge. PRISM
 * has no cloud LLM integration to fall back to -- the desktop app's real
 * fallback tier is the deterministic, evidence-first path apps/api already
 * runs by default, so this never claims a "cloud" mode that doesn't exist.
 * It renders exactly what GET /api/v1/platform/ready reports for the
 * "ollama" provider entry (desktop-shell/src-tauri/src/ollama.rs sets
 * PRISM_AI_PROVIDER=ollama before launching the sidecar only if Ollama
 * actually answered its own API, re-checked on every launch) -- it must
 * never guess or claim local AI is active when the backend hasn't said so.
 */
export function AiProviderBadge() {
  const [state, setState] = useState<BadgeState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const response = await fetch(apiUrl("/api/v1/platform/ready"));
        if (!response.ok) throw new Error(`Readiness request failed: ${response.status}`);
        const body = (await response.json()) as ReadinessResponse;
        if (!cancelled) setState({ kind: "ready", ollama: body.providers.find((provider) => provider.name === "ollama") });
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
    return { label: "AI · CHECKING", tone: "legacy", detail: "Checking whether local AI (Ollama) is configured." };
  }
  if (state.kind === "error") {
    return { label: "AI · STATUS UNKNOWN", tone: "unavailable", detail: "Could not reach the platform readiness endpoint." };
  }
  if (state.ollama?.status === "configured") {
    return { label: "AI · LOCAL (OLLAMA)", tone: "native", detail: state.ollama.detail };
  }
  return {
    label: "AI · DETERMINISTIC",
    tone: "legacy",
    detail: state.ollama?.detail ?? "Ollama was not detected on this device; PRISM uses its built-in deterministic analysis, no cloud calls.",
  };
}
