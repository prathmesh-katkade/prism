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
      if (path.includes("/recipes")) return json([]);
      if (path.endsWith("/atlas")) return json({ action: "explain_issue", summary: "1 rows are exact duplicates of another row.", uncertainty: "Issue detection is a deterministic screening pass; it flags candidates for review, not confirmed defects.", evidence: [], proposed_operation: { operation: "drop_duplicates" } });
      if (path.endsWith("/preview")) return json({ operation: "drop_duplicates", review_token: "review_issue", source_revision: 0, affected_rows: 1, affected_columns: [], before_sample: [{ segment: "a" }], after_sample: [{ segment: "a" }], warnings: [], projected_health: health });
      if (path.endsWith("/apply")) { applied = true; return json({ dataset: dataset1, transformation, issues: [], health }, 201); }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("1 found")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Dataset[\s\S]*exact duplicates/ }));

    await waitFor(() => expect(screen.getByText(/affects/)).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Apply reviewed change" })).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed change" }));
    fireEvent.click(screen.getByRole("button", { name: /Apply reviewed change|Applying/ }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/apply"), expect.objectContaining({ method: "POST" })));
    expect(fetchMock.mock.calls.filter(([input]) => String(input).endsWith("/apply"))).toHaveLength(1);
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
      if (path.includes("/recipes")) return json([]);
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
      if (path.includes("/recipes")) return json([]);
      if (path.endsWith("/preview")) return json({ operation: "drop_column", review_token: "review_manual", source_revision: 0, affected_rows: 5, affected_columns: ["notes"], before_sample: [{ notes: "x" }], after_sample: [{}], warnings: [], projected_health: health });
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

    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed change" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/apply"), expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(screen.getByText(/revision 1/)).toBeInTheDocument());
  });

  it("switches the inspector away from a selected pattern finding when starting a manual operation or selecting an issue, instead of leaving it stuck on the old finding", async () => {
    const finding = { finding_id: "find_1", dataset_id: "ds_1", column: "invoice_id", detector_kind: "identifier_structure", detector_version: 1, source_revision: 0, source_fingerprint: dataset0.source_fingerprint, rows_examined: 5, total_rows: 5, sampling_method: "bounded_sample", verified: false, families: [{ family_signature: "sig1", label: "3 letters, '-', 6 digits", matching_count: 3, example_values: ["INV-000123"] }], missing_count: 0, exception_count: 2, created_at: "2026-08-28T00:00:00Z" };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return json({ dataset: dataset0, issues: [issue], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      if (path.includes("/recipes")) return json([]);
      if (path.endsWith("/discover")) return json([finding]);
      if (path.includes("/decisions")) return json([]);
      if (path.endsWith("/atlas")) return json({ action: "explain_issue", summary: "x", uncertainty: "x", evidence: [] });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("invoice_id")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /invoice_id[\s\S]*identifier structure/ }));
    await waitFor(() => expect(screen.getByText("PATTERN REVIEW")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "+ New manual operation" }));
    expect(screen.getByText("MANUAL OPERATION")).toBeInTheDocument();
    expect(screen.queryByText("PATTERN REVIEW")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Operation")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /invoice_id[\s\S]*identifier structure/ }));
    await waitFor(() => expect(screen.getByText("PATTERN REVIEW")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Dataset[\s\S]*exact duplicates/ }));
    await waitFor(() => expect(screen.getByText("SELECTED ISSUE")).toBeInTheDocument());
    expect(screen.queryByText("PATTERN REVIEW")).not.toBeInTheDocument();
  });

  it("saves a manual operation as a named recipe, lists it, and applies it from the recipe list", async () => {
    let saved: { recipe_id: string; name: string; version: number; steps: unknown[] } | null = null;
    let applied = false;
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/state")) return applied ? json({ dataset: dataset1, issues: [], history: [], health }) : json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      if (path.endsWith("/recipes") && init?.method === "POST") {
        saved = { recipe_id: "recipe_1", name: "Drop duplicates nightly", version: 1, steps: [{ step_id: "s1", request: { operation: "drop_duplicates" }, enabled: true }] };
        return json(saved, 201);
      }
      if (path.endsWith("/recipes")) return json(saved ? [saved] : []);
      if (path.includes("/recipes/recipe_1/preview")) return json({ recipe_id: "recipe_1", recipe_version: 1, source_revision: 0, source_fingerprint: dataset0.source_fingerprint, review_token: "review_1", before_sample: [{ segment: "a" }], after_sample: [{ segment: "a" }], step_impacts: [1], projected_health: health });
      if (path.includes("/recipes/recipe_1/apply")) { applied = true; return json({ dataset: dataset1, recipe_id: "recipe_1", recipe_version: 1, applied_steps: [], issues: [], health }); }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("None saved yet")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ New manual operation" }));
    fireEvent.change(screen.getByLabelText("Operation"), { target: { value: "drop_duplicates" } });

    fireEvent.click(screen.getByRole("button", { name: "Save as recipe" }));
    await waitFor(() => expect(screen.getByText("Name the recipe before saving it.")).toBeInTheDocument()); // a visible, concrete reason, not a silent no-op
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/recipes"), expect.objectContaining({ method: "POST" }));

    fireEvent.change(screen.getByLabelText("Recipe name"), { target: { value: "Drop duplicates nightly" } });
    fireEvent.click(screen.getByRole("button", { name: "Save as recipe" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/recipes"), expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Drop duplicates nightly", steps: [{ request: { operation: "drop_duplicates" }, enabled: true }] }) })));
    await waitFor(() => expect(screen.getByText("Drop duplicates nightly")).toBeInTheDocument());
    expect(screen.getByText("v1 · 1/1 step(s) enabled")).toBeInTheDocument();
    expect(screen.getByLabelText("Drop duplicates nightly steps")).toHaveTextContent("01");
    expect(screen.getByLabelText("Drop duplicates nightly steps")).toHaveTextContent("Saved");

    fireEvent.click(screen.getAllByRole("button", { name: "Preview" })[0]!);
    await waitFor(() => expect(screen.getByText(/Recipe version 1 reviewed/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed recipe" }));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/recipes/recipe_1/apply"), expect.objectContaining({ method: "POST" })));
    await waitFor(() => expect(screen.getByText(/revision 1/)).toBeInTheDocument());
  });

  it("surfaces the specific schema-mismatch reason when a recipe no longer matches the dataset, without pretending it applied", async () => {
    const recipe = { recipe_id: "recipe_2", name: "Stale recipe", version: 1, steps: [{ step_id: "s1", request: { operation: "drop_column", column: "retired_column" }, enabled: true }] };
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      if (path.endsWith("/recipes")) return json([recipe]);
      if (path.includes("/recipes/recipe_2/preview")) return json({ detail: "Recipe step 1 (drop_column on retired_column) no longer matches this dataset's schema: Column 'retired_column' is not in the active dataset." }, 409);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("Stale recipe")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(screen.getByText(/no longer matches this dataset's schema/)).toBeInTheDocument());
    expect(screen.getByText("5 rows · 3 columns · revision 0")).toBeInTheDocument(); // never claims a later revision happened
  });

  it("builds a category mapping from real distinct values, previews unresolved exceptions, and applies", async () => {
    const columnValues = { column: "region", total_distinct: 3, truncated: false, values: [{ value: "Bangalore", count: 8 }, { value: "BENGALURU", count: 3 }, { value: "Mumbai", count: 2 }] };
    let applied = false;
    const fetchMock = vi.fn(async (input: string | URL, _init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/state")) return applied ? json({ dataset: dataset1, issues: [], history: [], health }) : json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/columns/region/values")) return json(columnValues);
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({ columns: [{ name: "region", semantic_type: "categorical" }] });
      if (path.includes("/recipes")) return json([]);
      if (path.endsWith("/preview")) return json({ operation: "category_mapping", review_token: "review_mapping", source_revision: 0, affected_rows: 11, changed_rows_total: 11, changed_rows: [{ source_row: "0", status: "changed", before: { region: "Bangalore" }, after: { region: "Bengaluru" } }], exception_rows_total: 1, exception_rows: [{ source_row: "3", status: "unresolved", before: { region: "Mumbai" }, after: { region: "Mumbai" } }], affected_columns: ["region"], before_sample: [{ region: "Bangalore" }], after_sample: [{ region: "Bengaluru" }], warnings: ["1 distinct value(s) in 'region' were not covered by the mapping and were left unchanged."], unresolved_values: ["Mumbai"], projected_health: health });
      if (path.endsWith("/apply")) { applied = true; return json({ dataset: dataset1, transformation: { transformation_id: "t3", operation: "category_mapping", column: "region", parameters: {}, affected_rows: 11, affected_columns: ["region"], source_revision: 0, resulting_revision: 1, source_fingerprint: dataset0.source_fingerprint, resulting_fingerprint: "e".repeat(64), reversible: true, created_at: "2026-08-28T00:00:00Z" }, issues: [], health }, 201); }
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/Rows 1–5 of 5/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ New manual operation" }));
    fireEvent.change(screen.getByLabelText("Operation"), { target: { value: "category_mapping" } });
    fireEvent.change(screen.getByLabelText("Column"), { target: { value: "region" } });

    await waitFor(() => expect(screen.getByText("Bangalore")).toBeInTheDocument());
    expect(screen.getByText("BENGALURU")).toBeInTheDocument();

    const bangaloreCheckbox = screen.getByText("Bangalore").closest("label")!.querySelector("input")!;
    const bengaluruVariantCheckbox = screen.getByText("BENGALURU").closest("label")!.querySelector("input")!;
    fireEvent.click(bangaloreCheckbox);
    fireEvent.click(bengaluruVariantCheckbox);
    fireEvent.change(screen.getByLabelText("Map selected values to"), { target: { value: "Bengaluru" } });
    fireEvent.click(screen.getByRole("button", { name: "Assign mapping" }));

    expect(screen.getAllByText("Bengaluru", { selector: "code" })).toHaveLength(2); // one mapping-summary row per assigned source value
    fireEvent.click(screen.getByRole("button", { name: "Preview" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/preview"), expect.objectContaining({ method: "POST" })));
    const previewCall = fetchMock.mock.calls.find(([, requestInit]) => String(requestInit?.method) === "POST" && (requestInit as RequestInit | undefined)?.body && String((requestInit as RequestInit).body).includes("category_mapping"));
    expect(previewCall).toBeTruthy();
    const sentBody = JSON.parse(String((previewCall![1] as RequestInit).body));
    expect(sentBody.category_mapping).toEqual({ Bangalore: "Bengaluru", BENGALURU: "Bengaluru" });

    fireEvent.click(screen.getByRole("tab", { name: "Exceptions (1)" }));
    await waitFor(() => expect(screen.getByText(/1 distinct unresolved value/)).toBeInTheDocument());
    expect(screen.getAllByText(/Mumbai/, { selector: "code" }).length).toBeGreaterThan(0); // source row and unresolved value remain inspectable

    fireEvent.click(screen.getByRole("button", { name: "Apply reviewed change" }));
    await waitFor(() => expect(screen.getByText(/revision 1/)).toBeInTheDocument());
  });

  it("builds a duplicate-survivorship request from selected columns and a rule, with a concrete reason when a required field is missing", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({ columns: [{ name: "customer_id", semantic_type: "text" }, { name: "region", semantic_type: "categorical" }, { name: "revenue", semantic_type: "numeric" }] });
      if (path.includes("/recipes")) return json([]);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText(/Rows 1–5 of 5/)).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ New manual operation" }));
    fireEvent.change(screen.getByLabelText("Operation"), { target: { value: "deduplicate_survivorship" } });

    expect(screen.getByRole("button", { name: "Preview" })).toBeDisabled();
    expect(screen.getByText("Choose at least one column to group duplicates by.")).toBeInTheDocument();

    const survivorshipColumnList = document.querySelector(".clean-survivorship")!;
    fireEvent.click(Array.from(survivorshipColumnList.querySelectorAll("label")).find((label) => label.textContent?.includes("customer_id"))!.querySelector("input")!);
    fireEvent.change(screen.getByLabelText("Survivorship rule"), { target: { value: "max_by_column" } });
    expect(screen.getByText("Choose a column to keep the highest value from.")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Tiebreak column"), { target: { value: "revenue" } });
    expect(screen.getByRole("button", { name: "Preview" })).not.toBeDisabled();
  });

  it("creates a validation rule, runs it, and shows the real pass/fail result", async () => {
    const rule = { rule_id: "rule_1", name: "Unique customers", kind: "uniqueness", column: "customer_id", before_column: null, after_column: null, created_at: "2026-08-28T00:00:00Z" };
    let ruleSaved = false;
    const fetchMock = vi.fn(async (input: string | URL, init?: RequestInit) => {
      const path = String(input);
      if (path.endsWith("/state")) return json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      if (path.includes("/recipes")) return json([]);
      if (path.endsWith("/validation-rules") && init?.method === "POST") { ruleSaved = true; return json(rule, 201); }
      if (path.endsWith("/validation-rules")) return json(ruleSaved ? [rule] : []);
      if (path.includes("/validation-rules/rule_1/run")) return json({ rule, dataset_revision: 0, total_checked: 5, violation_count: 2, passed: false, sample_violations: [{ customer_id: "c1" }] });
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("No rules saved")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Add validation rule"));
    fireEvent.change(screen.getByLabelText("Validation rule name"), { target: { value: "Unique customers" } });
    fireEvent.change(screen.getByLabelText("Validation rule column"), { target: { value: "customer_id" } });
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("/validation-rules"), expect.objectContaining({ method: "POST", body: JSON.stringify({ name: "Unique customers", kind: "uniqueness", column: "customer_id" }) })));
    await waitFor(() => expect(screen.getByText("Unique customers")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: "Run" }));
    await waitFor(() => expect(screen.getByText(/2 violation\(s\)/)).toBeInTheDocument());
    expect(screen.getByText(/5 checked/)).toBeInTheDocument();
  });

  it("shows a concrete reason instead of saving a validation rule with a missing required field", async () => {
    const fetchMock = vi.fn(async (input: string | URL) => {
      const path = String(input);
      if (path.endsWith("/state")) return json({ dataset: dataset0, issues: [], history: [], health });
      if (path.includes("/rows")) return json(rowsPage);
      if (path.includes("/profile")) return json({});
      if (path.includes("/recipes")) return json([]);
      if (path.endsWith("/validation-rules")) return json([]);
      return json({});
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<CleanWorkspace datasetId="ds_1" onSelectContext={vi.fn()} onOpenWorkflow={vi.fn()} />);

    await waitFor(() => expect(screen.getByText("No rules saved")).toBeInTheDocument());
    fireEvent.click(screen.getByText("Add validation rule"));
    fireEvent.click(screen.getByRole("button", { name: "Save rule" }));
    await waitFor(() => expect(screen.getByText("Name the rule before saving it.")).toBeInTheDocument());
    expect(fetchMock).not.toHaveBeenCalledWith(expect.stringContaining("/validation-rules"), expect.objectContaining({ method: "POST" }));
  });
});

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
}
