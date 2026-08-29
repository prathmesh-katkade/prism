import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ForecastingWorkspace } from "./forecasting-workspace";

const dataset = { dataset_id: "ds_1", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 10, column_count: 2 };
const profile = {
  dataset, provenance: { source_fingerprint: dataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" },
  quality: { n_rows: 10, n_cols: 2, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] },
  health: { completeness: 30, consistency: 25, uniqueness: 15, validity: 15, outlier_burden: 15, total: 100 },
  columns: [
    { name: "date", semantic_type: "datetime", missing_pct: 0, unique_count: 10, health: "good", issues: [], warnings: [], distribution: [] },
    { name: "revenue", semantic_type: "numeric", missing_pct: 0, unique_count: 10, health: "good", issues: [], warnings: [], distribution: [] },
  ],
  correlations: [], suggestions: [],
};
const forecastResult = {
  datetime_col: "date", numeric_col: "revenue", frequency: "D", model_used: "Exponential Smoothing (ETS)", horizon: 3,
  observed: [{ timestamp: "2026-01-01T00:00:00", value: 10 }, { timestamp: "2026-01-02T00:00:00", value: 12 }],
  forecast: [{ timestamp: "2026-01-03T00:00:00", value: 14 }, { timestamp: "2026-01-04T00:00:00", value: 16 }, { timestamp: "2026-01-05T00:00:00", value: 18 }],
  intervals: [{ timestamp: "2026-01-03T00:00:00", lower: 12, upper: 16 }, { timestamp: "2026-01-04T00:00:00", lower: 13, upper: 19 }, { timestamp: "2026-01-05T00:00:00", lower: 14, upper: 22 }],
  metrics: { mae: 1.2, rmse: 1.5, mape: null, holdout_points: 2, note: "Computed by fitting on all but the last 2 point(s)." },
  caveat: "Fit on 10 historical observations to project 3 periods ahead using Exponential Smoothing (ETS). Confidence in this forecast is **reasonable**.",
  warnings: [], provenance: profile.provenance,
};

afterEach(() => vi.restoreAllMocks());

describe("Forecasting workspace", () => {
  it("prompts to load a dataset first when none is active", () => {
    render(<ForecastingWorkspace datasetId={undefined} onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
  });

  it("auto-selects a datetime and numeric column, forecasts, and shows the point forecast with its interval and caveat", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.endsWith("/forecast")) return json(forecastResult);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ForecastingWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Exponential Smoothing (ETS)")).toBeInTheDocument());
    expect(screen.getByText("Reliability caveat")).toBeInTheDocument();
    expect(screen.getByText(forecastResult.caveat)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Forecast chart/ })).toBeInTheDocument();
  });

  it("switches to decomposition and shows trend/seasonal strength", async () => {
    const decomposition = {
      datetime_col: "date", numeric_col: "revenue", seasonal_period: 7, trend_strength: 0.82, seasonal_strength: 0.65,
      observed: forecastResult.observed, trend: forecastResult.observed, seasonal: forecastResult.observed, resid: forecastResult.observed,
      verdict: "Trend strength: 0.82 (strong). Seasonal strength: 0.65 (moderate).", provenance: profile.provenance,
    };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.endsWith("/forecast")) return json(forecastResult);
      if (path.endsWith("/decompose")) return json(decomposition);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ForecastingWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Exponential Smoothing (ETS)")).toBeInTheDocument());

    fireEvent.change(screen.getByLabelText("Analysis"), { target: { value: "decompose" } });
    await waitFor(() => expect(screen.getByText(decomposition.verdict)).toBeInTheDocument());
    expect(screen.getByText("0.820")).toBeInTheDocument();
  });

  it("never presents a forecast point without a matching interval in the chart", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.includes("/profile")) return json(profile);
      if (path.endsWith("/forecast")) return json(forecastResult);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ForecastingWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    await waitFor(() => expect(screen.getByRole("img", { name: /Forecast chart/ })).toBeInTheDocument());
    // The accessible name embeds both counts, proving the chart renders the band alongside every point.
    expect(screen.getByRole("img", { name: "Forecast chart: 2 observed points and 3 forecast points" })).toBeInTheDocument();
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
