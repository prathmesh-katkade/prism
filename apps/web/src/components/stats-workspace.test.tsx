import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { StatsWorkspace } from "./stats-workspace";

const dataset = { dataset_id: "ds_1", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 40, column_count: 2 };
const profile = {
  dataset, provenance: { source_fingerprint: dataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" },
  quality: { n_rows: 40, n_cols: 2, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] },
  health: { completeness: 30, consistency: 25, uniqueness: 15, validity: 15, outlier_burden: 15, total: 100 },
  columns: [
    { name: "x", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] },
    { name: "y", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] },
  ],
  correlations: [], suggestions: [],
};
const suggestion = { col_a: "x", col_b: "y", test: "pearson", reason: "Both 'x' and 'y' are numeric — testing whether they're linearly correlated.", numeric_col: null, cat_col: null, error: null };
const result = {
  test: "pearson", statistic: 0.87, p_value: 0.0001, effect_size: 0.87, effect_size_name: "Pearson r", effect_size_label: "large",
  groups: {}, means: {}, dof: null, n: 40, low_expected_pct: null, normality: [], significant: true,
  interpretation: "Significant correlation detected (p<0.0001, large effect, Pearson r=0.87).",
  evidence_statement: "This test found statistically significant evidence of a correlation in this sample. Statistical significance is not the same as practical importance or causation.",
  warnings: [], provenance: profile.provenance,
};

afterEach(() => vi.restoreAllMocks());

describe("Stats workspace", () => {
  it("prompts to load a dataset first when none is active", () => {
    render(<StatsWorkspace datasetId={undefined} onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
  });

  it("suggests a deterministic test, runs it, shows the evidence statement, and explains it through Atlas", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.includes("/suggest")) return json(suggestion);
      if (path.includes("/run")) return json(result);
      if (path.includes("/atlas")) return json({ action: "explain_test", summary: suggestion.reason, uncertainty: "This explanation describes a deterministic statistical result; it does not establish causation.", evidence: [{ label: "Selected test", value: "pearson" }] });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<StatsWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(suggestion.reason)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));

    await waitFor(() => expect(screen.getByText(result.interpretation)).toBeInTheDocument());
    expect(screen.getByText(result.evidence_statement)).toBeInTheDocument();
    expect(screen.getByText("Evidence found")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "explain test" }));
    await waitFor(() => expect(screen.getByText(/deterministic statistical result/)).toBeInTheDocument());
  });

  it("never claims 'no relationship' when a test finds insufficient evidence", async () => {
    const notSignificant = { ...result, significant: false, evidence_statement: "The available analysis did not find sufficient evidence of a correlation at the 0.05 threshold. This does not establish that no correlation exists — only that this test, on this sample, did not detect one." };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.includes("/suggest")) return json(suggestion);
      if (path.includes("/run")) return json(notSignificant);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<StatsWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(suggestion.reason)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Run test" }));

    await waitFor(() => expect(screen.getByText("Insufficient evidence")).toBeInTheDocument());
    expect(screen.getByText(/does not establish that no correlation exists/)).toBeInTheDocument();
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
