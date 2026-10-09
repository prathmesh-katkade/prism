import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ReportsWorkspace } from "./reports-workspace";

const spec = { mark: "horizontal_bar", intent: "comparison", dimension: "region", measure: "revenue", aggregation: "sum", filters: {}, max_categories: 20, sort_by: "label_asc", axis_start: 0, currency: "USD" };
const result = { spec, data: [{ label: "Bengaluru", value: 14250 }, { label: "Chennai", value: 16500 }], truncated: false, warnings: [], provenance: { source_fingerprint: "a".repeat(64), dataset_revision: 1, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" } };
const chart = { chart_id: "chart_1", name: "revenue by region", dataset_id: "ds_1", dataset_revision: 1, source_fingerprint: "a".repeat(64), spec, rationale: "r", created_at: "2026-08-28T00:00:00Z", result };
const report = { report_id: "report_1", name: "Journey report", chart_refs: [{ chart_id: "chart_1", acknowledged_revision: 1, added_at: "2026-08-28T00:00:00Z" }], item_order: ["chart_1"], created_at: "2026-08-28T00:00:00Z", updated_at: "2026-08-28T00:00:00Z" };
const detail = { report, charts: [chart], freshness: [{ chart_id: "chart_1", needs_refresh: false }] };

afterEach(() => vi.restoreAllMocks());

function json(body: unknown): Response { return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }); }

describe("Reports workspace", () => {
  it("renders a saved chart in the report canvas with its persisted sort/axis/currency, not the renderer's bare defaults", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/reports/charts")) return json([chart]);
      if (path.endsWith("/reports") && !path.includes("report_1")) return json([report]);
      if (path.endsWith(`/reports/${report.report_id}`)) return json(detail);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<ReportsWorkspace datasetId={undefined} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Journey report" })).toBeInTheDocument());
    const chartSection = screen.getByRole("heading", { name: "revenue by region" }).closest("section")!;
    // Currency: the saved USD hint must reach the rendered value labels, not just sit unused on the spec.
    expect(chartSection.textContent).toMatch(/\$14,250|\$16,500/);
    // Axis starts at 0 (persisted): the tick row must show a real 0, not an auto-expanded negative/offset baseline.
    expect(chartSection.textContent).toContain("$0");
  });
});
