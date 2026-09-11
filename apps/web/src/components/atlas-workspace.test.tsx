import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasWorkspace } from "./atlas-workspace";

const run = { run_id: "atlas_1", plan: { plan_id: "plan_1", objective: "Check quality", dataset_id: "ds_1", provider: "deterministic", state: "completed", created_at: "2026-09-04T00:00:00Z", steps: [{ step_id: "profile", title: "Profile the active dataset", kind: "profile_dataset", specialist: "scout", tool_name: "overview.profile", rationale: "Establish evidence.", state: "completed", attempts: 1, max_attempts: 3, evidence: [] }] }, answer: "Grounded answer", uncertainty: "Not a causal conclusion.", council: [{ specialist: "scout", conclusion: "Measured profile.", confidence: "high", objections: [], evidence: [{ evidence_id: "dataset:ds_1:r0", kind: "dataset_revision", summary: "Dataset revision", dataset_id: "ds_1", dataset_revision: 0, source_fingerprint: "a".repeat(64) }] }], evidence: [], events: [{ event_id: "evt_1", run_id: "atlas_1", sequence: 1, type: "step_started", occurred_at: "2026-09-04T00:00:01Z", step_id: "profile", payload: { tool: "overview.profile" } }, { event_id: "evt_2", run_id: "atlas_1", sequence: 2, type: "step_completed", occurred_at: "2026-09-04T00:00:02Z", step_id: "profile", payload: { evidence_ids: ["dataset:ds_1:r0"] } }] };
const graph = { run_id: "atlas_1", generated_at: "2026-09-04T00:00:00Z", nodes: [{ node_id: "run:atlas_1", kind: "run", label: "Atlas run", state: "completed", source_id: "atlas_1" }, { node_id: "dataset:ds_1", kind: "dataset", label: "Dataset", state: "recorded", source_id: "ds_1" }], edges: [{ edge_id: "uses", source_node_id: "run:atlas_1", target_node_id: "dataset:ds_1", relation: "uses" }] };
const roster = [
  { specialist: "scout", display_name: "Scout", role: "Dataset reconnaissance and profiling", visible: true },
  { specialist: "curator", display_name: "Curator", role: "Data quality and cleaning readiness", visible: true },
  { specialist: "stat", display_name: "Stat", role: "Statistical methodology and experiment review", visible: true },
  { specialist: "auditor", display_name: "Auditor", role: "Independent evidence and methodology verifier", visible: true },
];

function mockAtlas(runBody: unknown) {
  return vi.fn(async (input: string | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/specialists")) return json(roster);
    if (init?.method === "POST" && path.endsWith("/runs")) return json(runBody, 202);
    if (path.endsWith("/events")) return new Response("event: atlas.run\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } });
    if (path.endsWith("/cortex")) return json(graph);
    return json(runBody);
  });
}

describe("Atlas workspace", () => {
  afterEach(() => vi.restoreAllMocks());
  it("requires a durable dataset context", () => { render(<AtlasWorkspace datasetId={undefined} />); expect(screen.getByText("Load a dataset before opening an investigation.")).toBeInTheDocument(); });
  it("renders durable plan, council evidence, real Cortex graph, specialist activity, tool timeline, and pipeline stage", async () => {
    vi.stubGlobal("fetch", mockAtlas(run));
    render(<AtlasWorkspace datasetId="ds_1" />); fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    await waitFor(() => expect(screen.getByText("Grounded answer")).toBeInTheDocument());
    expect(screen.getByText("Measured profile.")).toBeInTheDocument(); expect(screen.getByLabelText("Cortex real-state graph")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Focus Atlas run" })); expect(screen.getByRole("button", { name: "Reset focus" })).not.toBeDisabled();
    expect(screen.getByLabelText("Selected Cortex node")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Selected Cortex node")).getByText("run")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "dataset" })); // node-kind filter chip
    expect(screen.queryByLabelText("Atlas server guardrails")).not.toBeInTheDocument();

    // Specialist activity: the real roster, not an invented one -- Scout
    // actually ran (completed), Curator/Stat/Auditor were never assigned a
    // step in this run and are shown idle rather than hidden or animated.
    const specialists = screen.getByText("SPECIALISTS").closest("aside")!;
    expect(within(specialists).getByText("Scout")).toBeInTheDocument();
    expect(within(specialists).getByText("Curator")).toBeInTheDocument();
    expect(within(specialists).getAllByText("idle").length).toBeGreaterThan(0);

    // Tool execution timeline: real step_started/step_completed events, a
    // real tool name, and the evidence id the completed event actually
    // recorded -- never a fabricated "approved" state.
    const timeline = screen.getByLabelText("Atlas tool execution timeline");
    expect(within(timeline).getByText("overview.profile")).toBeInTheDocument();
    expect(within(timeline).getByText("COMPLETED")).toBeInTheDocument();
    expect(within(timeline).getByText(/evidence: dataset:ds_1:r0/)).toBeInTheDocument();

    // Command Core pipeline: a completed, answered run has reached Result.
    const pipeline = screen.getByLabelText("Atlas request pipeline");
    expect(within(pipeline).getByText("Result").closest("li")).toHaveClass("is-reached");

    // Evidence lineage: real record from council.evidence (the fixture's
    // top-level run.evidence is empty), attributed to the specialist that
    // actually cited it -- not a hardcoded freshness/verification claim
    // AtlasEvidenceReference doesn't carry.
    const evidence = screen.getByLabelText("Atlas evidence");
    expect(within(evidence).getByText(/1 RECORD/)).toBeInTheDocument();
    fireEvent.click(within(evidence).getByText("dataset:ds_1:r0"));
    expect(within(evidence).getByText("Dataset revision", { selector: ".migration-chip" })).toBeInTheDocument();
    expect(within(evidence).getByText(/ds_1 · revision 0/)).toBeInTheDocument();
    expect(within(evidence).getByText("scout")).toBeInTheDocument();
  });
  it("shows the real guardrail decision was checked clean, without inventing a pass when no decision is recorded", async () => {
    const checkedRun = { ...run, events: [{ type: "plan_created", payload: { guardrail_decision: { policy_version: "atlas-guardrails-v1", authority: "server", state: "checked", findings: [], decision_id: "dec_1" } } }] };
    vi.stubGlobal("fetch", mockAtlas(checkedRun));
    render(<AtlasWorkspace datasetId="ds_1" />); fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    await waitFor(() => expect(screen.getByLabelText("Atlas server guardrails")).toBeInTheDocument());
    expect(screen.getByText("checked")).toBeInTheDocument();
    expect(screen.getByText(/No findings -- the request cleared/)).toBeInTheDocument();
  });
  it("groups a blocked guardrail finding under its real category, with subject and reason on expand", async () => {
    const blockedRun = { ...run, events: [{ type: "plan_created", payload: { guardrail_decision: { policy_version: "atlas-guardrails-v1", authority: "server", state: "blocked", decision_id: "dec_2", findings: [{ category: "target", rule: "target_ancestry", subject: "dataset:ds_1", detail: "Feature is the target or derives transitively from target information.", state: "blocked" }] } } }] };
    vi.stubGlobal("fetch", mockAtlas(blockedRun));
    render(<AtlasWorkspace datasetId="ds_1" />); fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    await waitFor(() => expect(screen.getByLabelText("Atlas server guardrails")).toBeInTheDocument());
    const panel = screen.getByLabelText("Atlas server guardrails");
    expect(within(panel).getAllByText("blocked")).toHaveLength(2); // header state chip + finding-state chip
    expect(within(panel).getByText("Target Leakage")).toBeInTheDocument(); // real category "target", grouped honestly
    const summary = within(panel).getByText(/target ancestry/);
    expect(summary).toBeInTheDocument();
    fireEvent.click(summary);
    expect(within(panel).getByText("dataset:ds_1")).toBeInTheDocument();
    expect(within(panel).getByText("Feature is the target or derives transitively from target information.")).toBeInTheDocument();
  });
});
function json(body: unknown, status = 200): Response { return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }); }
