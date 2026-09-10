import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasStatusBadge } from "./atlas-status-badge";

describe("Atlas status badge", () => {
  afterEach(() => vi.restoreAllMocks());

  it("reports an unknown status honestly when the endpoint cannot be reached, instead of guessing", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("network unavailable"); }));
    render(<AtlasStatusBadge />);
    await waitFor(() => expect(screen.getByText("ATLAS · STATUS UNKNOWN")).toBeInTheDocument());
  });

  it("shows no production model rather than fabricating one when none has ever been promoted", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => json({ production: null, candidate_kind: null, runtime_model: null })));
    render(<AtlasStatusBadge />);
    await waitFor(() => expect(screen.getByText("ATLAS · NO PRODUCTION MODEL")).toBeInTheDocument());
  });

  it("labels a legacy/bootstrap production pointer as legacy, never as verified", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          production: { event_id: "evt_1", candidate_id: "legacy", reason: "bootstrap", promoted_at: "2026-01-01T00:00:00Z" },
          candidate_kind: null,
          runtime_model: "legacy-model:latest",
        })
      )
    );
    render(<AtlasStatusBadge />);
    await waitFor(() => expect(screen.getByText("ATLAS · LEGACY · legacy-model:latest")).toBeInTheDocument());
  });

  it("labels a promoted candidate that has not passed trust verification as unverified", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          production: { event_id: "evt_2", candidate_id: "cand_1", reason: "test", promoted_at: "2026-01-01T00:00:00Z" },
          candidate_kind: "verified_base_model",
          runtime_model: "qwen3-test:latest",
          trust_verification_state: "pending",
        })
      )
    );
    render(<AtlasStatusBadge />);
    await waitFor(() => expect(screen.getByText("ATLAS · UNVERIFIED · qwen3-test:latest")).toBeInTheDocument());
  });

  it("only ever labels production verified when the API itself reports the verified trust state, and surfaces its real bench evidence", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        json({
          production: { event_id: "evt_3", candidate_id: "cand_2", reason: "final promotion", promoted_at: "2026-01-01T00:00:00Z" },
          candidate_kind: "verified_base_model",
          runtime_model: "qwen3-test:latest",
          trust_verification_state: "verified",
          latest_v1_run_id: "benchrun_1",
          latest_v1_total_passed: 90,
          latest_v1_total_tasks: 90,
          latest_operational_cert_run_id: "opcert_1",
          latest_operational_cert_total_passed: 23,
          latest_operational_cert_total_scenarios: 23,
          latest_operational_cert_critical_failures: 0,
        })
      )
    );
    render(<AtlasStatusBadge />);
    await waitFor(() => expect(screen.getByText("ATLAS · VERIFIED · qwen3-test:latest")).toBeInTheDocument());
    expect(screen.getByRole("status")).toHaveAttribute("title", expect.stringContaining("AtlasBench V1: 90/90"));
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
