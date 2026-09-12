import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { AtlasRunResponse, CortexNode } from "@prism/api-contracts";
import { AtlasWorkspace, connectedStepIdForNode } from "./atlas-workspace";

const run = { run_id: "atlas_1", plan: { plan_id: "plan_1", objective: "Check quality", dataset_id: "ds_1", provider: "deterministic", state: "completed", created_at: "2026-09-04T00:00:00Z", steps: [{ step_id: "profile", title: "Profile the active dataset", kind: "profile_dataset", specialist: "scout", tool_name: "overview.profile", rationale: "Establish evidence.", state: "completed", attempts: 1, max_attempts: 3, evidence: [] }] }, answer: "Grounded answer", uncertainty: "Not a causal conclusion.", council: [{ specialist: "scout", conclusion: "Measured profile.", confidence: "high", objections: [], evidence: [{ evidence_id: "dataset:ds_1:r0", kind: "dataset_revision", summary: "Dataset revision", dataset_id: "ds_1", dataset_revision: 0, source_fingerprint: "a".repeat(64) }] }], evidence: [], events: [{ event_id: "evt_1", run_id: "atlas_1", sequence: 1, type: "step_started", occurred_at: "2026-09-04T00:00:01Z", step_id: "profile", payload: { tool: "overview.profile" } }, { event_id: "evt_2", run_id: "atlas_1", sequence: 2, type: "step_completed", occurred_at: "2026-09-04T00:00:02Z", step_id: "profile", payload: { evidence_ids: ["dataset:ds_1:r0"] } }] };
const graph = { run_id: "atlas_1", generated_at: "2026-09-04T00:00:00Z", nodes: [{ node_id: "run:atlas_1", kind: "run", label: "Atlas run", state: "completed", source_id: "atlas_1" }, { node_id: "dataset:ds_1", kind: "dataset", label: "Dataset", state: "recorded", source_id: "ds_1" }, { node_id: "step:profile", kind: "plan_step", label: "Profile the active dataset", state: "completed", source_id: "profile" }, { node_id: "specialist:scout", kind: "specialist", label: "Scout", state: "visible", source_id: "scout" }, { node_id: "tool:overview.profile", kind: "tool", label: "overview.profile", state: "executed", source_id: "overview.profile" }], edges: [{ edge_id: "uses", source_node_id: "run:atlas_1", target_node_id: "dataset:ds_1", relation: "uses" }, { edge_id: "contains", source_node_id: "run:atlas_1", target_node_id: "step:profile", relation: "contains" }, { edge_id: "executor", source_node_id: "step:profile", target_node_id: "specialist:scout", relation: "executed_by" }, { edge_id: "tool", source_node_id: "step:profile", target_node_id: "tool:overview.profile", relation: "uses" }] };
const roster = [
  { specialist: "scout", display_name: "Scout", role: "Dataset reconnaissance and profiling", visible: true },
  { specialist: "curator", display_name: "Curator", role: "Data quality and cleaning readiness", visible: true },
  { specialist: "stat", display_name: "Stat", role: "Statistical methodology and experiment review", visible: true },
  { specialist: "auditor", display_name: "Auditor", role: "Independent evidence and methodology verifier", visible: true },
];

function notFound(): Response {
  return new Response(JSON.stringify({ detail: "not found" }), { status: 404, headers: { "content-type": "application/json" } });
}

function mockAtlas(runBody: unknown, options: { memories?: unknown[]; feedback?: unknown[] } = {}) {
  return vi.fn(async (input: string | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/specialists")) return json(roster);
    if (init?.method === "POST" && path.endsWith("/runs")) return json(runBody, 202);
    if (path.endsWith("/events")) return new Response("event: atlas.run\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } });
    if (path.endsWith("/cortex")) return json(graph);
    if (path.includes("/memories")) return json(options.memories ?? []);
    if (path.includes("/feedback/runs/")) return json(options.feedback ?? []);
    if (path.endsWith(`/runs/${(runBody as { run_id: string }).run_id}`)) return json(runBody);
    return notFound();
  });
}

describe("Atlas workspace", () => {
  afterEach(() => vi.restoreAllMocks());
  it("requires a durable dataset context", () => { render(<AtlasWorkspace datasetId={undefined} />); expect(screen.getByText("Load a dataset before opening an investigation.")).toBeInTheDocument(); });
  it("maps only real Cortex step, specialist, and tool records back to a declared plan step", () => {
    const typedRun = run as AtlasRunResponse;
    expect(connectedStepIdForNode(graph.nodes[2]! as CortexNode, typedRun)).toBe("profile");
    expect(connectedStepIdForNode(graph.nodes[3]! as CortexNode, typedRun)).toBe("profile");
    expect(connectedStepIdForNode(graph.nodes[4]! as CortexNode, typedRun)).toBe("profile");
    expect(connectedStepIdForNode(graph.nodes[0]! as CortexNode, typedRun)).toBeNull();
  });
  it("renders durable plan, council evidence, real Cortex graph, specialist activity, tool timeline, pipeline stage, and memory trace", async () => {
    const linkedMemory = { memory_id: "memory_1", scope: "session", knowledge_class: "user_memory", content: "The user asked to focus on North region revenue.", source: "operator note", source_ref: "atlas_1", confidence: "medium", timestamp: "2026-09-04T00:00:00Z", sensitivity: "internal", created_at: "2026-09-04T00:00:00Z" };
    const privateMemory = { memory_id: "memory_2", scope: "global", knowledge_class: "model_knowledge", content: "SECRET RAW CONTENT SHOULD NEVER RENDER", source: "internal", source_ref: "atlas_1", confidence: "low", timestamp: "2026-09-04T00:00:00Z", sensitivity: "private", created_at: "2026-09-04T00:00:00Z" };
    const unrelatedMemory = { memory_id: "memory_3", scope: "global", knowledge_class: "web_research", content: "Not linked to this run.", source: "web", source_ref: "atlas_other_run", confidence: "low", timestamp: "2026-09-04T00:00:00Z", sensitivity: "public", created_at: "2026-09-04T00:00:00Z" };
    const correction = { feedback_id: "atlasfeedback_1", run_id: "atlas_1", kind: "corrected", answer: "SELECT * FROM sales", correction: "SELECT id, region FROM sales", created_at: "2026-09-04T00:01:00Z" };
    vi.stubGlobal("fetch", mockAtlas(run, { memories: [linkedMemory, privateMemory, unrelatedMemory], feedback: [correction] }));
    render(<AtlasWorkspace datasetId="ds_1" />); fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    await waitFor(() => expect(screen.getByText("Grounded answer")).toBeInTheDocument());
    const journey = screen.getByLabelText("Atlas active investigation journey");
    await waitFor(() => expect(within(journey).getByRole("button", { name: /Profile the active dataset/ })).toHaveAttribute("aria-pressed", "true"));
    expect(screen.getByText("Measured profile.")).toBeInTheDocument(); expect(screen.getByLabelText("Cortex real-state graph")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Focus Atlas run" })); expect(screen.getByRole("button", { name: "Reset focus" })).not.toBeDisabled();
    expect(screen.getByLabelText("Selected Cortex node")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Selected Cortex node")).getByText("run")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Focus Scout" }));
    expect(within(journey).getByRole("button", { name: /Profile the active dataset/ })).toHaveAttribute("aria-pressed", "true");
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

    // Memory trace: only the memory actually linked to this run (real
    // source_ref === run_id) appears, never the one from another run.
    // Private content is never put in the DOM at all, even collapsed.
    const memoryTrace = await screen.findByLabelText("Atlas memory used by this run");
    expect(within(memoryTrace).getByText("operator note")).toBeInTheDocument();
    expect(within(memoryTrace).queryByText("web")).not.toBeInTheDocument(); // unrelated-run memory excluded
    expect(within(memoryTrace).queryByText("SECRET RAW CONTENT SHOULD NEVER RENDER")).not.toBeInTheDocument();
    expect(within(memoryTrace).getByText(/hidden -- sensitivity: private/)).toBeInTheDocument();
    fireEvent.click(within(memoryTrace).getByText("operator note"));
    expect(within(memoryTrace).getByText("The user asked to focus on North region revenue.")).toBeInTheDocument();

    // Corrections: the real feedback event for this run, from the
    // dedicated GET /feedback/runs/{id} route.
    expect(within(memoryTrace).getByText("Corrected")).toBeInTheDocument();
    fireEvent.click(within(memoryTrace).getByText("atlas_1", { selector: "strong" }));
    expect(within(memoryTrace).getByText("SELECT * FROM sales")).toBeInTheDocument();
    expect(within(memoryTrace).getByText("SELECT id, region FROM sales")).toBeInTheDocument();
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
