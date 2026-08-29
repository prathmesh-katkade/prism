import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { PrismShell } from "./prism-shell";

describe("PRISM shell", () => {
  afterEach(() => vi.restoreAllMocks());

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
    render(<PrismShell />);
    expect(screen.getByRole("complementary", { name: "Contextual inspector" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Hide inspector" }));
    expect(screen.getByRole("button", { name: "Show inspector" })).toBeInTheDocument();
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
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
