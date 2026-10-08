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
  it("resolves an explicit handoff source even when discovery lists a different latest dataset", async () => {
    const requested = { ...connection, connection_id: "local:ds_requested" };
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.includes("/schema") ? { ...schema, connection: requested } : [];
      return new Response(JSON.stringify(body), { status: 200 });
    }));
    render(<QueryStudio onSelectContext={vi.fn()} initialConnectionId={requested.connection_id} />);
    await waitFor(() => expect(screen.getByRole("combobox", { name: "Source" })).toHaveValue(requested.connection_id));
  });

  it("fails closed when the requested handoff source cannot be resolved", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: string | URL) => {
      const path = String(input);
      return path.includes("/schema")
        ? new Response(JSON.stringify({ detail: "Requested dataset is unavailable" }), { status: 404 })
        : new Response(JSON.stringify(path.endsWith("/connections") ? [connection] : []), { status: 200 });
    }));
    render(<QueryStudio onSelectContext={vi.fn()} initialConnectionId="local:missing" />);
    await waitFor(() => expect(screen.getByRole("heading", { name: "Query Studio could not establish its source." })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /Run query/ })).not.toBeInTheDocument();
  });

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

    await waitFor(() => expect(screen.getByRole("heading", { name: "Untitled query" })).toBeInTheDocument());
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

  it("restores both the SQL and the saved parameters when a snippet is picked, not just the SQL", async () => {
    const snippet = { snippet_id: "snip_1", name: "Top segments", sql: "SELECT * FROM data WHERE segment = :segment", dialect: "duckdb", parameters: { segment: "b" }, created_at: "2026-08-28T00:00:00Z" };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.endsWith("/snippets") ? [snippet]
        : path.includes("/schema") ? schema
        : path.endsWith("/history") ? []
        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryStudio onSelectContext={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("button", { name: "Top segments" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Top segments" }));

    await waitFor(() => expect(screen.getByLabelText("PRISM Query Studio editor")).toHaveValue(snippet.sql));
    expect(screen.getByLabelText("Query parameters JSON")).toHaveValue(JSON.stringify(snippet.parameters, null, 2));
  });

  it("inspects joins and shows real cardinality, unmatched-key, and multiplication-risk results", async () => {
    const diagnostics = {
      connection_id: connection.connection_id, sql_fingerprint: "f".repeat(64),
      joins: [{
        join_index: 0, join_kind: "inner",
        left: { table: "data", column: "customer_id", total_rows: 4, distinct_keys: 3, null_keys: 0, duplicate_key_rows: 1 },
        right: { table: "joined", column: "customer_id", total_rows: 4, distinct_keys: 3, null_keys: 0, duplicate_key_rows: 1 },
        unmatched_left_rows: 1, unmatched_right_rows: 1, row_multiplication_risk: true,
      }],
      unsupported_notes: [],
    };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.endsWith("/snippets") ? []
        : path.includes("/schema") ? schema
        : path.endsWith("/history") ? []
        : path.endsWith("/joins/diagnose") ? diagnostics
        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryStudio onSelectContext={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Untitled query" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Inspect joins" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/joins/diagnose"), expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(screen.getByText("row-multiplication risk")).toBeInTheDocument());
    expect(screen.getByText(/1 data row\(s\) have no match in joined/)).toBeInTheDocument();
  });

  it("finds a query's CTEs and materializes one into the editor for standalone inspection", async () => {
    const materialized = "WITH recent AS (SELECT * FROM data WHERE revenue > 10) SELECT * FROM recent";
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.endsWith("/snippets") ? []
        : path.includes("/schema") ? schema
        : path.endsWith("/history") ? []
        : path.endsWith("/ctes/list") ? { ctes: ["recent", "totals"] }
        : path.endsWith("/ctes/materialize") ? { cte_name: "recent", materialized_sql: materialized }
        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryStudio onSelectContext={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Untitled query" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Find CTEs" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "Inspect recent" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Inspect totals" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inspect recent" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/ctes/materialize"), expect.objectContaining({ method: "POST", body: JSON.stringify({ connection_id: connection.connection_id, sql: "SELECT *\nFROM data\nLIMIT 100;", cte_name: "recent" }) })));
    await waitFor(() => expect(screen.getByLabelText("PRISM Query Studio editor")).toHaveValue(materialized));
  });

  it("picks a base and compare run from history, declares a key column, and shows the real diff counts", async () => {
    const historyEntries = [
      { run_id: "run_a", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [], row_count: 3, returned_row_count: 3, truncated: false, duration_ms: 5, warnings: [], provenance },
      { run_id: "run_b", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [], row_count: 3, returned_row_count: 3, truncated: false, duration_ms: 5, warnings: [], provenance },
    ];
    const comparisonResult = { base_run_id: "run_a", compare_run_id: "run_b", key_columns: ["id"], base_row_count: 3, compare_row_count: 3, duplicate_key_count_base: 0, duplicate_key_count_compare: 0, added_count: 1, removed_count: 1, changed_count: 1, unchanged_count: 1, sample_diffs: [], warnings: [] };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.endsWith("/snippets") ? []
        : path.includes("/schema") ? schema
        : path.endsWith("/history") ? historyEntries
        : path.includes("/results") ? { run: { run_id: "run_a", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [], row_count: 3, returned_row_count: 3, truncated: false, duration_ms: 5, warnings: [], provenance }, offset: 0, limit: 100, rows: [] }
        : path.endsWith("/runs") ? { run_id: "run_a", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [], row_count: 3, returned_row_count: 3, truncated: false, duration_ms: 5, warnings: [], provenance }
        : path.endsWith("/runs/compare") ? comparisonResult
        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<QueryStudio onSelectContext={vi.fn()} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Untitled query" })).toBeInTheDocument());
    fireEvent.keyDown(screen.getByLabelText("PRISM Query Studio editor"), { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Create dataset" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("tab", { name: "history" }));
    await waitFor(() => expect(screen.getAllByRole("button", { name: "Base" })).toHaveLength(2));

    const [baseButtons, compareButtons] = [screen.getAllByRole("button", { name: "Base" }), screen.getAllByRole("button", { name: "Compare" })];
    fireEvent.click(baseButtons[0]!);
    fireEvent.click(compareButtons[1]!);
    fireEvent.change(screen.getByLabelText("Comparison key columns"), { target: { value: "id" } });
    fireEvent.click(screen.getByRole("button", { name: "Compare selected runs" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/runs/compare"), expect.objectContaining({ method: "POST", body: JSON.stringify({ base_run_id: "run_a", compare_run_id: "run_b", key_columns: ["id"] }) })));
    await waitFor(() => expect(screen.getByText(/matched by id/)).toBeInTheDocument());
  });

  it("promotes the result and hands off to Clean, retaining the new dataset as lineage", async () => {
    const promotion = { run: { run_id: "run_1", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [{ name: "revenue", data_type: "float64" }], row_count: 2, returned_row_count: 2, truncated: false, duration_ms: 4, warnings: [], provenance: { ...provenance, downstream_objects: ["dataset:ds_result"] } }, dataset: { dataset_id: "ds_result", revision: 0, source_name: "SQL result run_1", source_fingerprint: "d".repeat(64), row_count: 2, column_count: 1 } };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      const body = path.endsWith("/connections") ? [connection]
        : path.endsWith("/snippets") ? []
        : path.includes("/schema") ? schema
        : path.endsWith("/history") ? []
        : path.includes("/promote") ? promotion
        : path.endsWith("/runs") ? { run_id: "run_1", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [{ name: "revenue", data_type: "float64" }], row_count: 2, returned_row_count: 2, truncated: false, duration_ms: 4, warnings: [], provenance }
        : path.includes("/results") ? { run: { run_id: "run_1", state: "succeeded", risk: "safe_read", sql: "SELECT * FROM data", result_columns: [{ name: "revenue", data_type: "float64" }], row_count: 2, returned_row_count: 2, truncated: false, duration_ms: 4, warnings: [], provenance }, offset: 0, limit: 100, rows: [{ revenue: 10 }, { revenue: 12 }] }
        : {};
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    });
    vi.stubGlobal("fetch", fetchMock);
    const onDatasetReady = vi.fn();
    const onOpenWorkflow = vi.fn();
    render(<QueryStudio onSelectContext={vi.fn()} onDatasetReady={onDatasetReady} onOpenWorkflow={onOpenWorkflow} />);

    await waitFor(() => expect(screen.getByRole("heading", { name: "Untitled query" })).toBeInTheDocument());
    fireEvent.keyDown(screen.getByLabelText("PRISM Query Studio editor"), { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(screen.getByRole("button", { name: "Use in Clean" })).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Use in Clean" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/promote"), expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(onDatasetReady).toHaveBeenCalledWith("ds_result"));
    expect(onOpenWorkflow).toHaveBeenCalledWith("clean");
  });
});
