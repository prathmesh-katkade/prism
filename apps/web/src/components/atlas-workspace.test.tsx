import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasWorkspace } from "./atlas-workspace";

const run = { run_id: "atlas_1", plan: { plan_id: "plan_1", objective: "Check quality", dataset_id: "ds_1", provider: "deterministic", state: "completed", created_at: "2026-09-04T00:00:00Z", steps: [{ step_id: "profile", title: "Profile the active dataset", kind: "profile_dataset", specialist: "scout", tool_name: "overview.profile", rationale: "Establish evidence.", state: "completed", attempts: 1, max_attempts: 3, evidence: [] }] }, answer: "Grounded answer", uncertainty: "Not a causal conclusion.", council: [{ specialist: "scout", conclusion: "Measured profile.", confidence: "high", objections: [], evidence: [{ evidence_id: "dataset:ds_1:r0", kind: "dataset_revision", summary: "Dataset revision", dataset_id: "ds_1", dataset_revision: 0, source_fingerprint: "a".repeat(64) }] }], evidence: [], events: [] };
const graph = { run_id: "atlas_1", generated_at: "2026-09-04T00:00:00Z", nodes: [{ node_id: "run:atlas_1", kind: "run", label: "Atlas run", state: "completed", source_id: "atlas_1" }, { node_id: "dataset:ds_1", kind: "dataset", label: "Dataset", state: "recorded", source_id: "ds_1" }], edges: [{ edge_id: "uses", source_node_id: "run:atlas_1", target_node_id: "dataset:ds_1", relation: "uses" }] };

describe("Atlas workspace", () => {
  afterEach(() => vi.restoreAllMocks());
  it("requires a durable dataset context", () => { render(<AtlasWorkspace datasetId={undefined} />); expect(screen.getByText("Load a dataset before opening an investigation.")).toBeInTheDocument(); });
  it("renders durable plan, council evidence, and real Cortex graph", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (init?.method === "POST" && path.endsWith("/runs")) return json(run, 202);
      if (path.endsWith("/events")) return new Response("event: atlas.run\ndata: {}\n\n", { headers: { "content-type": "text/event-stream" } });
      if (path.endsWith("/cortex")) return json(graph);
      return json(run);
    }));
    render(<AtlasWorkspace datasetId="ds_1" />); fireEvent.click(screen.getByRole("button", { name: "Run investigation" }));
    await waitFor(() => expect(screen.getByText("Grounded answer")).toBeInTheDocument());
    expect(screen.getByText("Measured profile.")).toBeInTheDocument(); expect(screen.getByLabelText("Cortex real-state graph")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Focus Atlas run" })); expect(screen.getByRole("button", { name: "Reset focus" })).not.toBeDisabled();
  });
});
function json(body: unknown, status = 200): Response { return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }); }
