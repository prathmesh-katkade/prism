import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { MlLabWorkspace } from "./mllab-workspace";

const dataset = { dataset_id: "ds_1", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 40, column_count: 3 };
const profile = {
  dataset, provenance: { source_fingerprint: dataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" },
  quality: { n_rows: 40, n_cols: 3, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] },
  health: { completeness: 30, consistency: 25, uniqueness: 15, validity: 15, outlier_burden: 15, total: 100 },
  columns: [
    { name: "x1", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] },
    { name: "x2", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] },
    { name: "label", semantic_type: "categorical", missing_pct: 0, unique_count: 2, health: "good", issues: [], warnings: [], distribution: [] },
  ],
  correlations: [], suggestions: [],
};
const suggestions = { target_col: "label", suggestions: [{ kind: "scale", column: "x1", columns: null, method: "standard", reason: "Numeric feature — standardizing helps distance-based and linear models treat it fairly alongside other features." }] };
const baselineResult = {
  task_type: "classification", results: { Baseline: { accuracy: 0.8, f1: 0.79 }, "Random Forest": { accuracy: 0.85, f1: 0.84 } },
  confusion_matrix: [[15, 2], [1, 14]], confusion_labels: ["no", "yes"],
  feature_importances: [{ feature: "x1", importance: 0.6 }, { feature: "x2", importance: 0.4 }],
  n_train: 32, n_test: 8, smote_before_after: null,
  cv: { results: { Baseline: { accuracy: { mean: 0.78, std: 0.05 } }, "Random Forest": { accuracy: { mean: 0.82, std: 0.04 } } }, n_splits: 5 }, cv_error: null,
  verdict: "Random Forest wins on F1 score (0.840 vs 0.790, 6% higher than the other model). Top driver: x1.",
  leakage_note: "Preprocessing (imputation, scaling, one-hot encoding) is fit on the training split only, then applied unchanged to the test split — the test set never influences how features are transformed, so its score is not inflated by information the model would not have at prediction time.",
  provenance: profile.provenance,
};

afterEach(() => vi.restoreAllMocks());

describe("ML Lab workspace", () => {
  it("prompts to load a dataset first when none is active", () => {
    render(<MlLabWorkspace datasetId={undefined} onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
  });

  it("auto-selects a target, shows deterministic feature suggestions, and applies one", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.includes("/suggest-features")) return json(suggestions);
      if (path.includes("/detect-task")) return json({ target_col: "label", task_type: "classification", reason: "Non-numeric target." });
      if (path.includes("/apply-feature")) return json({ dataset: { ...dataset, revision: 1 }, description: "Standardized 'x1' (mean 0, std 1)", provenance: profile.provenance }, 201);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MlLabWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/Numeric feature — standardizing/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /scale: x1/i }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/apply-feature"), expect.objectContaining({ method: "POST" })));
  });

  it("runs the baseline models and shows the verdict, confusion matrix, and leakage-protection note", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.includes("/suggest-features")) return json(suggestions);
      if (path.includes("/detect-task")) return json({ target_col: "label", task_type: "classification", reason: "Non-numeric target." });
      if (path.includes("/imbalance")) return json({ target_col: "label", counts: { yes: 20, no: 20 }, proportions_pct: { yes: 50, no: 50 }, minority_pct: 50, is_imbalanced: false, explanation: "Balanced." });
      if (path.endsWith("/baseline")) return json(baselineResult);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<MlLabWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    await waitFor(() => expect(screen.getByText(/Numeric feature — standardizing/)).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Analysis"), { target: { value: "baseline" } });
    fireEvent.click(screen.getByRole("button", { name: "Run baseline models" }));

    await waitFor(() => expect(screen.getByText(baselineResult.verdict)).toBeInTheDocument());
    expect(screen.getByText("Leakage protection")).toBeInTheDocument();
    expect(screen.getByText(baselineResult.leakage_note)).toBeInTheDocument();
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
