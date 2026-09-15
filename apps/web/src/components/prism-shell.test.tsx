import React from "react";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PrismShell } from "./prism-shell";

describe("PRISM shell", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    window.history.pushState({}, "", "/");
  });

  it("opens the universal command surface with the keyboard", async () => {
    render(<PrismShell />);
    fireEvent.keyDown(window, { key: "k", ctrlKey: true });
    expect(screen.getByRole("dialog", { name: "PRISM command surface" })).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("textbox", { name: "Search commands" })).toHaveFocus());
  });

  it("opens native Overview and SQL Lab", () => {
    render(<PrismShell />);
    fireEvent.click(screen.getAllByRole("button", { name: /Overview native/i })[0]!);
    expect(screen.getByText("Start with the dataset, then follow the evidence.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /SQL Lab native/i })[0]!);
    expect(screen.getByText("Preparing Query Studio")).toBeInTheDocument();
  });

  // Phase 7C's ML Lab was the last workflow to move off the migration bridge — every
  // navigation entry now opens a native workspace (some still `shadow`, not yet
  // `enabled`, but reachable and fully interactive either way).
  it("opens native Clean, Visualize, Stats, Forecasting, and ML Lab, prompting for a dataset before an object is loaded", () => {
    render(<PrismShell />);
    fireEvent.click(screen.getAllByRole("button", { name: /Clean native/i })[0]!);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Visualize native/i })[0]!);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Stats/i })[0]!);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /Forecasting/i })[0]!);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
    fireEvent.click(screen.getAllByRole("button", { name: /ML/i })[0]!);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
  });

  it("keeps the inspector available as contextual shell state", () => {
    const { container } = render(<PrismShell />);
    const shell = container.querySelector<HTMLElement>(".prism-shell")!;
    expect(screen.getByRole("complementary", { name: "Contextual inspector" })).toBeInTheDocument();
    expect(shell.style.getPropertyValue("--inspector-size")).toBe("292px");
    fireEvent.click(screen.getByRole("button", { name: "Hide inspector" }));
    expect(screen.getByRole("button", { name: "Show inspector" })).toBeInTheDocument();
    expect(shell.style.getPropertyValue("--inspector-size")).toBe("0px");
  });

  it("keeps the native Overview upload action available to keyboard users", () => {
    render(<PrismShell />);
    fireEvent.click(screen.getAllByRole("button", { name: /Overview native/i })[0]!);
    const upload = screen.getByLabelText("Choose dataset");
    upload.focus();
    expect(upload).toHaveFocus();
  });

  it("remembers the active dataset in Overview across a tab switch instead of resetting to the upload prompt", async () => {
    const dataset = { dataset_id: "ds_1", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 3, column_count: 2 };
    const provenance = { source_fingerprint: dataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" };
    const profile = { dataset, provenance, quality: { n_rows: 3, n_cols: 2, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] }, health: { completeness: 30, consistency: 25, uniqueness: 15, validity: 15, outlier_burden: 15, total: 100 }, columns: [], correlations: [], suggestions: [] };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/overview/datasets") && !path.includes("/rows") && !path.endsWith("/datasets")) return json(profile);
      if (path.endsWith("/datasets")) return json(dataset, 201);
      if (path.includes("/rows")) return json({ dataset, offset: 0, limit: 20, total_rows: 3, rows: [], provenance });
      if (path.includes("/sql-lab/connections")) return json([]);
      if (path.includes("/sql-lab/snippets")) return json([]);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<PrismShell />);
    fireEvent.click(screen.getAllByRole("button", { name: /Overview native/i })[0]!);
    const file = new File(["segment,revenue\na,1\n"], "sales.csv", { type: "text/csv" });
    fireEvent.change(screen.getByLabelText("Choose dataset"), { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("heading", { name: "sales.csv" })).toBeInTheDocument());

    fireEvent.click(screen.getAllByRole("button", { name: /SQL Lab native/i })[0]!);
    expect(screen.queryByRole("heading", { name: "sales.csv" })).not.toBeInTheDocument();

    fireEvent.click(screen.getAllByRole("button", { name: /Overview native/i })[0]!);
    await waitFor(() => expect(screen.getByRole("heading", { name: "sales.csv" })).toBeInTheDocument());
    expect(screen.queryByText("Start with the dataset, then follow the evidence.")).not.toBeInTheDocument();
  });

  // Phase 11C: `atlas_panel=history` is the new, explicit, additive query
  // key -- see `atlas-history-link.ts`. A plain `dataset_id`/`run_id` link
  // (every existing link) is covered by the dataset-restore tests above and
  // must keep requiring a manual click into Atlas; only this new key lands
  // directly on the Atlas tab with its Command Center already open.
  it("lands directly on the Atlas tab with the Command Center open when the URL carries a history deep link", async () => {
    window.history.pushState({}, "", "/?atlas_panel=history&run_id=atlas_hist_1");
    const historicalRun = {
      run_id: "atlas_hist_1",
      plan: { plan_id: "plan_hist_1", objective: "Investigate churn drivers", dataset_id: "ds_hist", provider: "deterministic", state: "completed", created_at: "2026-01-03T00:00:00Z", steps: [] },
      answer: "Churn correlates with support-ticket volume.",
      council: [],
      evidence: [],
      events: [],
      created_at: "2026-01-03T00:00:00Z",
    };
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/promotion/current-status")) return json({ production: null, candidate_kind: null, runtime_model: null });
      if (path.includes("/specialists") || path.includes("/atlas/runs?limit=8")) return json([]);
      if (path.endsWith("/atlas/runs/atlas_hist_1/cortex")) return json({ run_id: "atlas_hist_1", generated_at: "2026-01-03T00:00:00Z", nodes: [], edges: [] });
      if (path.endsWith("/atlas/runs/atlas_hist_1")) return json(historicalRun);
      if (path.includes("/feedback/runs/") || path.includes("/feedback/recent") || path.includes("/promotion/history") || path.includes("/memories")) return json([]);
      if (path.includes("/retrieval/capability")) return json({ provider: "lexical", model: "none", revision: "v1", available: false, detail: "not configured" });
      if (path.includes("/foundry/")) return json([]);
      if (path.includes("training-datasets:combined-summary")) return json(null, 404);
      return json({});
    }));

    render(<PrismShell />);

    // No manual "Atlas" nav click, and no manual "System status" click --
    // the deep link alone puts the operator on the Cortex with the Command
    // Center's Run activity already showing the linked run expanded.
    await waitFor(() => expect(screen.getByText("Immersive Cortex")).toBeInTheDocument());
    const systemToggle = screen.getByRole("button", { name: /System status|Hide system status/ });
    expect(systemToggle).toHaveAttribute("aria-expanded", "true");
    const commandCenter = screen.getByLabelText("Atlas command center");
    await within(commandCenter).findByText("Investigate churn drivers");
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
