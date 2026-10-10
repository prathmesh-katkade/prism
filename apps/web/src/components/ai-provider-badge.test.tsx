import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AiProviderBadge } from "./ai-provider-badge";

describe("AI provider badge", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports status unknown honestly when the readiness endpoint cannot be reached", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network unavailable"); }));
    render(<AiProviderBadge />);
    await waitFor(() => expect(screen.getByText("AI · STATUS UNKNOWN")).toBeInTheDocument());
  });

  it("shows deterministic, not a fabricated cloud mode, when Ollama isn't configured", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => readinessResponse("not_configured", "PRISM_AI_PROVIDER is not set to 'ollama'; AI Analyst uses its deterministic path.")));
    render(<AiProviderBadge />);
    await waitFor(() => expect(screen.getByText("AI · DETERMINISTIC")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveAttribute("title", expect.stringContaining("deterministic path"));
  });

  it("shows local Ollama mode only when the backend itself reports it configured", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => readinessResponse("configured", "PRISM_AI_PROVIDER=ollama; AI Analyst probes reachability per-request.")));
    render(<AiProviderBadge />);
    await waitFor(() => expect(screen.getByText("AI · LOCAL (OLLAMA)")).toBeInTheDocument());
  });

  it("never guesses -- an unrecognized provider status still reads as deterministic, not a false positive", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => readinessResponse("unavailable", "unexpected state")));
    render(<AiProviderBadge />);
    await waitFor(() => expect(screen.getByText("AI · DETERMINISTIC")).toBeInTheDocument());
  });
});

function readinessResponse(ollamaStatus: string, ollamaDetail: string): Response {
  const body = {
    status: "ready",
    contract_version: "v1",
    generated_at: "2026-01-01T00:00:00Z",
    providers: [
      { name: "ollama", status: ollamaStatus, detail: ollamaDetail },
      { name: "analytical_history", status: "ready", detail: "Analytical-history persistence is reachable." },
    ],
  };
  return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
}
