import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VisualizeWorkspace } from "./visualize-workspace";

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
    const fetchMock = vi.fn(async (input: string | URL) => {
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
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
