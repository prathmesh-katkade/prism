import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { QueryStudio } from "./query-studio";

vi.mock("./query-editor", () => ({ QueryEditor: ({ value, onChange, onRun }: { value: string; onChange(value: string): void; onRun(): void }) => <textarea aria-label="PRISM Query Studio editor" value={value} onChange={(event) => onChange(event.target.value)} onKeyDown={(event) => { if (event.ctrlKey && event.key === "Enter") onRun(); }} /> }));

const connection = { connection_id: "local:ds_sales", label: "sales.csv · local dataset", source_type: "local_dataset", dialect: "duckdb", status: "ready", capabilities: [{ name: "query_execution", supported: true }], source_fingerprint: "a".repeat(64) };
const schema = { connection, tables: [{ name: "data", columns: [{ name: "revenue", data_type: "float64", nullable: true, sample_count: 2 }] }], schema_fingerprint: "b".repeat(64) };
const provenance = { connection_id: connection.connection_id, source_fingerprint: connection.source_fingerprint, schema_fingerprint: schema.schema_fingerprint, sql_fingerprint: "c".repeat(64), dialect: "duckdb", parameters: {}, service_version: "sql-lab-runtime/1.0", executed_at: "2026-08-28T00:00:00Z" };

afterEach(() => vi.restoreAllMocks());

describe("Query Studio", () => {
  it("loads schema metadata and runs a keyboard-first query into the result grid", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.endsWith("/snippets") ? []
        : path.includes("/schema") ? schema
        : path.endsWith("/history") ? []
        : path.includes("/promote") ? { run: { run_id: "run_1", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [{ name: "revenue", data_type: "float64" }], row_count: 2, returned_row_count: 2, truncated: false, duration_ms: 4, warnings: [], provenance: { ...provenance, downstream_objects: ["dataset:ds_result"] } }, dataset: { dataset_id: "ds_result", revision: 0, source_name: "SQL result run_1", source_fingerprint: "d".repeat(64), row_count: 2, column_count: 1 } }
        : path.endsWith("/runs") ? { run_id: "run_1", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [{ name: "revenue", data_type: "float64" }], row_count: 2, returned_row_count: 2, truncated: false, duration_ms: 4, warnings: [], provenance }
        : path.includes("/results") ? { run: { run_id: "run_1", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [{ name: "revenue", data_type: "float64" }], row_count: 2, returned_row_count: 2, truncated: false, duration_ms: 4, warnings: [], provenance }, offset: 0, limit: 100, rows: [{ revenue: 10 }, { revenue: 12 }] }
        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryStudio onSelectContext={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Write against evidence, not assumptions." })).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("revenue")).toBeInTheDocument());
    fireEvent.keyDown(screen.getByLabelText("PRISM Query Studio editor"), { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(screen.getByText("2 returned / 2 total rows")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Filter current result page"), { target: { value: "12" } });
    expect(screen.getByText("Rows 1–1")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("columnheader", { name: /revenue/ }));
    expect(screen.getByRole("columnheader", { name: /revenue/ })).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(screen.getByRole("button", { name: "Create dataset" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/promote"), expect.objectContaining({ method: "POST" })));
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/api/v1/sql-lab/runs"), expect.objectContaining({ method: "POST" }));
  });
});
