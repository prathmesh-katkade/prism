import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AtlasProductionPointer, AtlasRunEvent, AtlasRunResponse } from "@prism/api-contracts";
import { AccountabilityPanel, buildAccountabilityLedger } from "./atlas-accountability";

function run(overrides: Partial<AtlasRunResponse>): AtlasRunResponse {
  return {
    run_id: "atlas_run_1",
    plan: { plan_id: "plan_1", objective: "Investigate churn drivers", dataset_id: "ds_1", provider: "deterministic", state: "completed", created_at: "2026-01-03T00:00:00Z", steps: [] },
    answer: "Churn correlates with support-ticket volume.",
    council: [],
    evidence: [],
    events: [],
    created_at: "2026-01-03T00:00:00Z",
    ...overrides,
  } as AtlasRunResponse;
}

describe("Accountability ledger", () => {
  it("orders a run's own lifecycle -- started, guardrail, completed -- by real timestamp, newest first", () => {
    const completedRun = run({
      run_id: "atlas_run_1",
      events: [
        { event_id: "e1", run_id: "atlas_run_1", sequence: 1, type: "run_created", occurred_at: "2026-01-03T00:00:00Z", payload: {} },
        { event_id: "e2", run_id: "atlas_run_1", sequence: 2, type: "plan_created", occurred_at: "2026-01-03T00:00:01Z", payload: { guardrail_decision: { state: "checked", policy_version: "v3", authority: "server", decision_id: "dec_1", findings: [] } } },
        { event_id: "e3", run_id: "atlas_run_1", sequence: 3, type: "run_completed", occurred_at: "2026-01-03T00:00:05Z", payload: { answer_grounded: true } },
      ] as AtlasRunEvent[],
    });
    const entries = buildAccountabilityLedger([completedRun], []);
    expect(entries.map((entry) => entry.kind)).toEqual(["run_completed", "guardrail", "run_started"]);
    expect(entries[0]).toMatchObject({ kind: "run_completed", runId: "atlas_run_1", summary: "Churn correlates with support-ticket volume." });
    expect(entries[1]).toMatchObject({ kind: "guardrail", state: "checked", policyVersion: "v3" });
  });

  it("uses the run_failed event's real detail, never a generic guess, when one is recorded", () => {
    const failedRun = run({
      run_id: "atlas_run_2",
      events: [
        { event_id: "e1", run_id: "atlas_run_2", sequence: 1, type: "run_created", occurred_at: "2026-01-03T00:00:00Z", payload: {} },
        { event_id: "e2", run_id: "atlas_run_2", sequence: 2, type: "run_failed", occurred_at: "2026-01-03T00:00:02Z", payload: { detail: "Dataset revision no longer exists." } },
      ] as AtlasRunEvent[],
    });
    const entries = buildAccountabilityLedger([failedRun], []);
    const failure = entries.find((entry) => entry.kind === "run_failed");
    expect(failure).toMatchObject({ summary: "Dataset revision no longer exists." });
  });

  it("never invents a guardrail entry for a run that never recorded a guardrail decision", () => {
    const bareRun = run({ run_id: "atlas_run_3", events: [{ event_id: "e1", run_id: "atlas_run_3", sequence: 1, type: "run_created", occurred_at: "2026-01-03T00:00:00Z", payload: {} }] as AtlasRunEvent[] });
    const entries = buildAccountabilityLedger([bareRun], []);
    expect(entries.some((entry) => entry.kind === "guardrail")).toBe(false);
  });

  it("merges promotion/rollback history alongside run events in one real timeline", () => {
    const pointer: AtlasProductionPointer = { event_id: "promo_1", candidate_id: "atlas-ds-v1.9", previous_candidate_id: "atlas-ds-v1.8", decision_id: "dec_promo", is_rollback: false, reason: "Promotion confidence 98.7%.", promoted_at: "2026-01-04T00:00:00Z" };
    const entries = buildAccountabilityLedger([], [pointer]);
    expect(entries).toEqual([{ id: "promo_1", at: "2026-01-04T00:00:00Z", kind: "promotion", candidateId: "atlas-ds-v1.9", reason: "Promotion confidence 98.7%." }]);
  });
});

describe("Accountability panel", () => {
  it("shows an honest empty state rather than a fabricated ledger when nothing has happened yet", () => {
    render(<AccountabilityPanel runs={[]} failed={false} promotions={[]} />);
    expect(screen.getByText("No recorded runs or promotions yet.")).toBeInTheDocument();
  });

  it("reports the endpoint failure honestly instead of silently showing an empty ledger", () => {
    render(<AccountabilityPanel runs={[]} failed={true} promotions={[]} />);
    expect(screen.getByText(/Could not build an accountability ledger/)).toBeInTheDocument();
  });
});
