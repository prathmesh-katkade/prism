import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChartCanvas, VisualizeWorkspace } from "./visualize-workspace";

const dataset = { dataset_id: "ds_1", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 6, column_count: 2 };
const profile = {
  dataset, provenance: { source_fingerprint: dataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" },
  quality: { n_rows: 6, n_cols: 2, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] },
  health: { completeness: 30, consistency: 25, uniqueness: 15, validity: 15, outlier_burden: 15, total: 100 },
  columns: [
    { name: "segment", semantic_type: "categorical", missing_pct: 0, unique_count: 2, health: "good", issues: [], warnings: [], distribution: [] },
    { name: "revenue", semantic_type: "numeric", missing_pct: 0, unique_count: 6, health: "good", issues: [], warnings: [], distribution: [] },
  ],
  correlations: [], suggestions: [],
};
const suggestion = { spec: { mark: "bar", intent: "comparison", dimension: "segment", measure: "revenue", aggregation: "sum", filters: {}, max_categories: 20 }, rationale: "Comparison question → bar chart of revenue by segment.", alternatives: ["line"] };
const rendered = { spec: suggestion.spec, data: [{ label: "a", value: 30 }, { label: "b", value: 12 }], truncated: false, warnings: [], provenance: profile.provenance };

afterEach(() => vi.restoreAllMocks());

describe("Visualize workspace", () => {
  it("prompts to load a dataset first when none is active", () => {
    render(<VisualizeWorkspace datasetId={undefined} onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
  });

  it("suggests a deterministic chart, renders server-aggregated data, and explains it through Atlas", async () => {
    const fetchMock = vi.fn(async (input: string | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.includes("/suggest")) return json(suggestion);
      if (path.includes("/render")) return json(rendered);
      if (path.includes("/atlas")) return json({ action: "explain_chart", summary: "This bar chart answers a comparison question using sum of revenue by segment.", uncertainty: "This explains what the chart shows; it does not establish why.", evidence: [] });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<VisualizeWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("img", { name: /Bar chart with 2 categories/ })).toBeInTheDocument());
    expect(screen.getByText(suggestion.rationale)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Explain this chart" }));
    await waitFor(() => expect(screen.getByText(/answers a comparison question/)).toBeInTheDocument());
  });

  it("resolves a clicked bar to its real contributing rows via a server-resolved filter, disclosing truncation", async () => {
    const drilldownResponse = { total_matching_rows: 5, rows: [{ segment: "a", revenue: 15 }, { segment: "a", revenue: 15 }], offset: 0, limit: 2, truncated: true, filters_applied: { segment: "a" } };
    const fetchMock = vi.fn(async (input: string | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.includes("/suggest")) return json(suggestion);
      if (path.includes("/render")) return json(rendered);
      if (path.includes("/drilldown")) return json(drilldownResponse);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSelectContext = vi.fn();
    render(<VisualizeWorkspace datasetId="ds_1" onSelectContext={onSelectContext} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("img", { name: /Bar chart with 2 categories/ })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Inspect a" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/drilldown"), expect.objectContaining({ method: "POST" })));
    const [, callInit] = fetchMock.mock.calls.find(([, requestInit]) => String((requestInit as RequestInit | undefined)?.body ?? "").includes("dimension_value"))!;
    expect(JSON.parse(String((callInit as RequestInit).body))).toMatchObject({ dimension_value: "a" });

    await waitFor(() => expect(screen.getByText("5", { selector: "strong" })).toBeInTheDocument()); // total_matching_rows disclosed
    expect(screen.getByText(/truncated, not downloaded in full/)).toBeInTheDocument();
    expect(screen.getByText(/segment = a/)).toBeInTheDocument(); // active filter disclosed
    expect(onSelectContext).toHaveBeenCalledWith(expect.objectContaining({ metadata: expect.arrayContaining([expect.stringContaining("5 matching row(s)")]) }));
  });

  it("shows the error state with a retry control, never an indefinite loading spinner, when the initial load fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<VisualizeWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Visualize could not suggest a chart.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("Choosing a chart for this data")).not.toBeInTheDocument();
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}

describe("ChartCanvas", () => {
  it("positions scatter points by their numeric x value, not by array index", () => {
    // Irregularly spaced x values: an index-based x (the original bug) would space
    // these evenly regardless of these numbers, which is exactly what this catches.
    const data = [
      { label: "p0", value: 10, x: 0 },
      { label: "p1", value: 10, x: 1 },
      { label: "p2", value: 10, x: 100 },
    ];
    const { container } = render(<ChartCanvas mark="scatter" data={data} />);
    const circles = container.querySelectorAll("circle");
    expect(circles).toHaveLength(3);
    const [cx0, cx1, cx2] = Array.from(circles).map((c) => Number(c.getAttribute("cx")));
    // p0 and p1 (x=0 and x=1) must sit far closer together than p1 and p2 (x=1 and x=100).
    expect(Math.abs(cx1! - cx0!)).toBeLessThan(Math.abs(cx2! - cx1!) / 10);
  });

  it("draws real box-plot geometry (quartile box, whiskers, outliers) instead of falling back to bars", () => {
    const data = [
      { label: "group-a", value: 50, box: { q1: 25, median: 50, q3: 75, whisker_low: 10, whisker_high: 90, outliers: [120] } },
    ];
    const { container } = render(<ChartCanvas mark="box" data={data} />);
    expect(container.querySelector("rect")).not.toBeNull(); // the quartile box
    expect(container.querySelectorAll("line").length).toBeGreaterThanOrEqual(3); // two whiskers + median line
    expect(container.querySelector("circle.viz-box-outlier")).not.toBeNull();
  });

  it("renders a line chart left-to-right in the given data order without resorting by value", () => {
    // Values are intentionally non-monotonic; if anything resorted by value the
    // polyline's point order would change and no longer match this input order.
    const data = [
      { label: "jan", value: 5 },
      { label: "feb", value: 50 },
      { label: "mar", value: 1 },
    ];
    const { container } = render(<ChartCanvas mark="line" data={data} />);
    const polyline = container.querySelector("polyline");
    expect(polyline).not.toBeNull();
    const xs = (polyline!.getAttribute("points") ?? "").trim().split(/\s+/).map((pair) => Number(pair.split(",")[0]));
    expect(xs).toEqual([...xs].sort((a, b) => a - b)); // left-to-right in input order
  });
});
