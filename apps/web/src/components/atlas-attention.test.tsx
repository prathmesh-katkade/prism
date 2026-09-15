import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AtlasProductionTrustStatus, AtlasRunEvent, AtlasRunResponse } from "@prism/api-contracts";
import { AttentionPanel, buildAttentionQueue } from "./atlas-attention";

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

describe("Attention queue", () => {
  it("stays empty when every guardrail decision is the real passing 'checked' state, never the nonexistent 'allowed'", () => {
    const cleanRun = run({
      events: [{ event_id: "e1", run_id: "atlas_run_1", sequence: 1, type: "plan_created", occurred_at: "2026-01-03T00:00:01Z", payload: { guardrail_decision: { state: "checked", policy_version: "v1", authority: "server", decision_id: "d1", findings: [] } } }] as AtlasRunEvent[],
    });
    expect(buildAttentionQueue(null, [cleanRun])).toEqual([]);
  });

  it("surfaces a blocked guardrail as critical and a verification_required one as a warning", () => {
    const blockedRun = run({
      run_id: "run_blocked",
      events: [{ event_id: "e1", run_id: "run_blocked", sequence: 1, type: "plan_created", occurred_at: "2026-01-03T00:00:01Z", payload: { guardrail_decision: { state: "blocked", policy_version: "v1", authority: "server", decision_id: "d1", findings: [{ category: "python", rule: "no_exec", subject: "code", detail: "disallowed call", state: "blocked" }] } } }] as AtlasRunEvent[],
    });
    const verificationRun = run({
      run_id: "run_verify",
      events: [{ event_id: "e2", run_id: "run_verify", sequence: 1, type: "plan_created", occurred_at: "2026-01-03T00:00:01Z", payload: { guardrail_decision: { state: "verification_required", policy_version: "v1", authority: "server", decision_id: "d2", findings: [] } } }] as AtlasRunEvent[],
    });
    const queue = buildAttentionQueue(null, [blockedRun, verificationRun]);
    expect(queue).toHaveLength(2);
    expect(queue.find((item) => item.runId === "run_blocked")).toMatchObject({ severity: "critical" });
    expect(queue.find((item) => item.runId === "run_verify")).toMatchObject({ severity: "warning" });
  });

  it("uses the run_failed event's real detail for a failed run", () => {
    const failedRun = run({
      run_id: "run_failed_1",
      events: [{ event_id: "e1", run_id: "run_failed_1", sequence: 1, type: "run_failed", occurred_at: "2026-01-03T00:00:02Z", payload: { detail: "Dataset revision no longer exists." } }] as AtlasRunEvent[],
    });
    const queue = buildAttentionQueue(null, [failedRun]);
    expect(queue).toEqual([{ id: "e1", severity: "critical", summary: 'Run failed: "Investigate churn drivers"', detail: "Dataset revision no longer exists.", runId: "run_failed_1" }]);
  });

  it("surfaces real operational-certification critical failures ranked ahead of warnings", () => {
    const status = { latest_operational_cert_critical_failures: 2, operational_cert_min_pass_rate: 0.95 } as AtlasProductionTrustStatus;
    const verificationRun = run({
      run_id: "run_verify",
      events: [{ event_id: "e1", run_id: "run_verify", sequence: 1, type: "plan_created", occurred_at: "2026-01-03T00:00:01Z", payload: { guardrail_decision: { state: "verification_required", policy_version: "v1", authority: "server", decision_id: "d1", findings: [] } } }] as AtlasRunEvent[],
    });
    const queue = buildAttentionQueue(status, [verificationRun]);
    expect(queue[0]).toMatchObject({ id: "opcert_critical", severity: "critical" });
    expect(queue[1]).toMatchObject({ severity: "warning" });
  });
});

describe("Attention panel", () => {
  it("says plainly that nothing needs attention rather than manufacturing an item", () => {
    render(<AttentionPanel status={null} statusFailed={false} runs={[]} runsFailed={false} />);
    expect(screen.getByText("Nothing needs attention right now.")).toBeInTheDocument();
  });

  it("renders nothing when both underlying sources already failed elsewhere, instead of a third redundant error card", () => {
    const { container } = render(<AttentionPanel status={null} statusFailed={true} runs={[]} runsFailed={true} />);
    expect(container).toBeEmptyDOMElement();
  });
});
