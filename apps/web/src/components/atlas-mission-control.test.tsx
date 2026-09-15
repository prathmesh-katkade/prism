import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AtlasRunResponse } from "@prism/api-contracts";
import { filterActiveMissions, MissionControlPanel } from "./atlas-mission-control";

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

describe("Active mission filtering", () => {
  it("only counts draft or running plans as active, never a terminal state", () => {
    const draft = run({ run_id: "r1", plan: { ...run({}).plan, state: "draft" } });
    const running = run({ run_id: "r2", plan: { ...run({}).plan, state: "running" } });
    const completed = run({ run_id: "r3", plan: { ...run({}).plan, state: "completed" } });
    const failed = run({ run_id: "r4", plan: { ...run({}).plan, state: "failed" } });
    const cancelled = run({ run_id: "r5", plan: { ...run({}).plan, state: "cancelled" } });
    const missions = filterActiveMissions([draft, running, completed, failed, cancelled]);
    expect(missions.map((mission) => mission.run.run_id)).toEqual(["r1", "r2"]);
    expect(missions.map((mission) => mission.state)).toEqual(["draft", "running"]);
  });
});

describe("Mission Control panel", () => {
  it("renders nothing at all when no mission is active -- no permanent '0 active' chrome", () => {
    const { container } = render(<MissionControlPanel runs={[run({ plan: { ...run({}).plan, state: "completed" } })]} failed={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when the underlying run fetch failed, deferring to Run activity's own error card", () => {
    const { container } = render(<MissionControlPanel runs={[]} failed={true} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("lists each real active mission with its real objective and state", () => {
    const running = run({ run_id: "r1", plan: { ...run({}).plan, state: "running", objective: "Explain regional revenue" } });
    render(<MissionControlPanel runs={[running]} failed={false} />);
    expect(screen.getByText("ATLAS · 1 ACTIVE MISSION")).toBeInTheDocument();
    expect(screen.getByText("Explain regional revenue")).toBeInTheDocument();
    expect(screen.getByText("running")).toBeInTheDocument();
  });
});
