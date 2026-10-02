import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CleanWorkspace } from "./clean-workspace";

const issue = { issue_id: "issue_duplicate_rows", kind: "duplicate_rows", column: null, severity: "medium", affected_rows: 1, description: "1 rows are exact duplicates of another row.", suggested_operation: "drop_duplicates" };
const dataset0 = { dataset_id: "ds_1", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 5, column_count: 3 };
const dataset1 = { ...dataset0, revision: 1, row_count: 4 };
const health = { completeness: 30, consistency: 25, uniqueness: 12, validity: 15, outlier_burden: 15, total: 97 };
const provenance = { source_fingerprint: dataset0.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" };
const rowsPage = { dataset: dataset0, offset: 0, limit: 30, total_rows: dataset0.row_count, rows: [{ segment: "a" }, { segment: "b" }], provenance };

afterEach(() => vi.restoreAllMocks());

describe("Clean workspace", () => {
  it("prompts to load a dataset first when none is active", () => {
    render(<CleanWorkspace datasetId={undefined} onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    expect(screen.getByText("Load a dataset in Overview first.")).toBeInTheDocument();
  });

  it("selects an issue, previews Atlas's proposed fix, and applies it without ever mutating in place until confirmed", async () => {
    const transformation = { transformation_id: "t1", operation: "drop_duplicates", column: null, parameters: {}, affected_rows: 1, affected_columns: [], source_revision: 0, resulting_revision: 1, source_fingerprint: dataset0.source_fingerprint, resulting_fingerprint: "b".repeat(64), reversible: true, created_at: "2026-08-28T00:00:00Z" };
    let applied = false;
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return applied ? json({ dataset: dataset1, issues: [], history: [transformation], health }) : json({ dataset: dataset0, issues: [issue], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      if (path.endsWith("/atlas")) return json({ action: "explain_issue", summary: "1 rows are exact duplicates of another row.", uncertainty: "Issue detection is a deterministic screening pass; it flags candidates for review, not confirmed defects.", evidence: [], proposed_operation: { operation: "drop_duplicates" } });
      if (path.endsWith("/preview")) return json({ operation: "drop_duplicates", affected_rows: 1, affected_columns: [], before_sample: [{ segment: "a" }], after_sample: [{ segment: "a" }], warnings: [], projected_health: health });
      if (path.endsWith("/apply")) { applied = true; return json({ dataset: dataset1, transformation, issues: [], health }, 201); }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("1 found")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Dataset[\s\S]*exact duplicates/ }));

    await waitFor(() => expect(screen.getByText(/affects/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Apply transformation" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Apply transformation" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/apply"), expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(screen.getByText(/revision 1/)).toBeInTheDocument());
  });

  it("shows the error state with a retry control, never an indefinite loading spinner, when the initial load fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("offline"); }));
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);
    await waitFor(() => expect(screen.getByText("Clean could not load this dataset.")).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
    expect(screen.queryByText("Scanning for quality issues")).not.toBeInTheDocument();
  });

  it("shows the live dataset table by default, with no issue selected, instead of an empty centre pane", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/Rows 1–5 of 5/)).toBeInTheDocument());
    expect(screen.getByRole("columnheader", { name: "segment" })).toBeInTheDocument();
    expect(screen.getByText("Select an issue from the navigator, or start a manual operation, to inspect it and preview a fix.")).toBeInTheDocument();
  });

  it("builds, previews, and applies a manual operation that was never a detected issue", async () => {
    let applied = false;
    const transformation = { transformation_id: "t2", operation: "drop_column", column: "notes", parameters: {}, affected_rows: 5, affected_columns: ["notes"], source_revision: 0, resulting_revision: 1, source_fingerprint: dataset0.source_fingerprint, resulting_fingerprint: "c".repeat(64), reversible: true, created_at: "2026-08-28T00:00:00Z" };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return applied ? json({ dataset: dataset1, issues: [], history: [transformation], health }) : json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({ columns: [{ name: "notes", semantic_type: "text" }] });
      if (path.endsWith("/preview")) return json({ operation: "drop_column", affected_rows: 5, affected_columns: ["notes"], before_sample: [{ notes: "x" }], after_sample: [{}], warnings: [], projected_health: health });
      if (path.endsWith("/apply")) { applied = true; return json({ dataset: dataset1, transformation, issues: [], health }, 201); }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/Rows 1–5 of 5/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ New manual operation" }));

    fireEvent.change(screen.getByLabelText("Operation"), { target: { value: "drop_column" } });
    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled(); // no column chosen yet — a concrete, visible reason, not a silent no-op
    expect(screen.getByText("Choose a column first.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Column"), { target: { value: "notes" } });
    expect(screen.getByRole("button", { name: "Preview" })).not.toBeDisabled();
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/preview"), expect.objectContaining({ method: "POST", body: JSON.stringify({ operation: "drop_column", column: "notes" }) })));
    await waitFor(() => expect(screen.getByText(/affects/)).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Apply transformation" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/apply"), expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(screen.getByText(/revision 1/)).toBeInTheDocument());
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
