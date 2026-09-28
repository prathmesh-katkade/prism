import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AtlasInvestigation } from "./atlas-investigation";

const recorded = {
  run_id: "atlas-recorded", plan: { plan_id: "plan-recorded", objective: "Can we attribute the change?", dataset_id: "dataset-1", provider: "deterministic", state: "completed", created_at: "2026-09-27T00:00:00Z", steps: [
    { step_id: "profile", title: "Profile dataset", kind: "profile_dataset", specialist: "scout", tool_name: "overview.profile", state: "completed", attempts: 1, evidence: [], dependencies: [] },
    { step_id: "sql", title: "Compare groups", kind: "sql_question", specialist: "query", tool_name: "sql.execute", state: "blocked", error: "A reviewed query is required; SQL was not executed.", attempts: 1, evidence: [], dependencies: ["profile"] },
  ] }, answer: "Profile completed.", uncertainty: "Causal claim unresolved.", evidence: [], council: [], events: [
    { event_id: "e2", run_id: "atlas-recorded", sequence: 2, type: "step_completed", step_id: "profile", occurred_at: "2026-09-27T00:00:02Z", payload: {} },
    { event_id: "e1", run_id: "atlas-recorded", sequence: 1, type: "step_started", step_id: "profile", occurred_at: "2026-09-27T00:00:01Z", payload: { tool: "overview.profile" } },
  ],
};

afterEach(() => vi.unstubAllGlobals());

describe("Atlas investigation", () => {
  it("keeps a sample refusal visible after collapsing and labels the source", () => {
    render(<AtlasInvestigation datasetId={undefined} onSelectContext={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Open sample investigation" }));
    fireEvent.click(screen.getByRole("button", { name: "Collapse details" }));
    expect(screen.getByText("Assignment provenance is missing. Causal attribution remains unresolved.")).toBeInTheDocument();
    expect(screen.getByText("Sample · no execution")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    expect(screen.getByRole("button", { name: /Open exact query in SQL Lab/ })).toBeDisabled();
  });

  it("keeps a 200-task sample readable in declared dependency order", () => {
    render(<AtlasInvestigation datasetId={undefined} onSelectContext={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Open 200-task sample" }));
    const map = screen.getByRole("heading", { name: "Work map" }).closest("section")!;
    expect(within(map).getAllByRole("listitem")).toHaveLength(200);
    expect(screen.getByText("Large illustrative investigation · 200 tasks")).toBeInTheDocument();
    expect(screen.getByText("After large-sample-199")).toBeInTheDocument();
  });

  it("shows ordered recorded events without reconstructing historical state", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => new Response(
      JSON.stringify(String(input).endsWith("/interventions") ? [] : recorded),
      { status: 200, headers: { "content-type": "application/json" } },
    )));
    render(<AtlasInvestigation datasetId="dataset-1" initialRunId="atlas-recorded" onSelectContext={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Can we attribute the change?")).toBeInTheDocument());
    expect(screen.getByText("Supporting evidence not linked.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Activity" }));
    const log = screen.getByRole("list", { name: "" });
    const events = within(log).getAllByRole("button");
    expect(events[0]).toHaveTextContent("step started");
    expect(events[1]).toHaveTextContent("step completed");
    fireEvent.click(screen.getByRole("button", { name: "Next event" }));
    expect(screen.getByText("Event 2 of 2")).toBeInTheDocument();
    expect(screen.getByText("Historical state reconstruction is unavailable.", { exact: false })).toBeInTheDocument();
  });

  it("retains an unknown waiting cause instead of inventing a dependency", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => new Response(
      JSON.stringify(String(input).endsWith("/interventions") ? [] : recorded), { status: 200 },
    )));
    render(<AtlasInvestigation datasetId="dataset-1" initialRunId="atlas-recorded" onSelectContext={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Can we attribute the change?")).toBeInTheDocument());
    expect(screen.getByText("No dependency recorded")).toBeInTheDocument();
    expect(screen.getByText("A reviewed query is required; SQL was not executed.")).toBeInTheDocument();
  });

  it("hands the exact recorded SQL and parameters to SQL Lab after evidence selection", async () => {
    const onSqlDraft = vi.fn();
    const sql = 'SELECT COUNT(*) AS result_value FROM "data" WHERE "region" = $filter_value LIMIT 100';
    const withSql = { ...recorded, evidence: [{ evidence_id: "sql:run-1", kind: "tool_output", summary: "Counted rows", dataset_id: "dataset-1", dataset_revision: 0, source_fingerprint: "a".repeat(64) }], events: [
      ...recorded.events,
      { event_id: "e3", run_id: "atlas-recorded", sequence: 3, type: "step_completed", step_id: "sql", occurred_at: "2026-09-27T00:00:03Z", payload: { output: { sql_run_id: "run-1", sql, parameters: { filter_value: "west" }, connection_id: "local:dataset-1", rows: [{ result_value: 2 }] } } },
    ] };
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => new Response(
      JSON.stringify(String(input).endsWith("/interventions") ? [] : withSql), { status: 200 },
    )));
    render(<AtlasInvestigation datasetId="dataset-1" initialRunId="atlas-recorded" onSelectContext={vi.fn()} onSqlDraft={onSqlDraft} />);
    await waitFor(() => expect(screen.getByText("Can we attribute the change?")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Evidence" }));
    fireEvent.click(screen.getByRole("button", { name: /Counted rows/ }));
    fireEvent.click(screen.getByRole("button", { name: "Open exact query in SQL Lab" }));
    expect(onSqlDraft).toHaveBeenCalledWith(sql, { filter_value: "west" }, "local:dataset-1");
    expect(screen.getByText("Recorded original; edits in SQL Lab create a draft.")).toBeInTheDocument();
  });

  it("shows a persisted statistical question and sends the declared method and design", async () => {
    const waiting = { ...recorded, plan: { ...recorded.plan, state: "waiting" }, clarifications: [{
      question_id: "clarify:atlas-recorded:statistical_analysis", step_id: "statistical_analysis", state: "open",
      prompt: "Which columns and design?", created_at: "2026-09-27T00:00:00Z",
    }] };
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/overview/datasets/")) return new Response(JSON.stringify({ columns: [{ name: "outcome" }, { name: "group" }] }), { status: 200 });
      if (path.endsWith("/interventions")) return new Response("[]", { status: 200 });
      if (init?.method === "POST") return new Response(JSON.stringify({ ...waiting, plan: { ...waiting.plan, state: "running" }, clarifications: [{ ...waiting.clarifications[0], state: "answered" }] }), { status: 200 });
      return new Response(JSON.stringify(waiting), { status: 200 });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AtlasInvestigation datasetId="dataset-1" initialRunId="atlas-recorded" onSelectContext={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Which columns and design?")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Statistical method"), { target: { value: "ttest" } });
    fireEvent.change(screen.getByLabelText("Outcome or first comparison column"), { target: { value: "outcome" } });
    fireEvent.change(screen.getByLabelText("Group or second comparison column"), { target: { value: "group" } });
    fireEvent.change(screen.getByLabelText("Study design"), { target: { value: "independent_groups" } });
    fireEvent.click(screen.getByRole("button", { name: "Save answer and resume" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/clarifications/"), expect.objectContaining({
      method: "POST", body: JSON.stringify({ test: "ttest", col_a: "outcome", col_b: "group", design: "independent_groups" }),
    })));
  });
});
