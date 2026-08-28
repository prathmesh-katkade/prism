import { expect, test } from "@playwright/test";

test("native shell has no automated axe accessibility violations", async ({ page }) => {
  await page.goto("/");
  await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
  const violations = await page.evaluate(async () => {
    const axe = (window as typeof window & { axe: { run(): Promise<{ violations: unknown[] }> } }).axe;
    return (await axe.run()).violations;
  });
  expect(violations).toEqual([]);
});

test("shell visual baseline and keyboard command surface", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("main")).toBeVisible();
  await expect(page).toHaveScreenshot("prism-shell-dark.png", { animations: "disabled", fullPage: true, maxDiffPixelRatio: 0.01 });
  await page.keyboard.press("ControlOrMeta+k");
  await expect(page.getByRole("dialog", { name: "PRISM command surface" })).toBeVisible();
});

test("native Overview empty state is visually stable and keyboard reachable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await expect(page.getByRole("heading", { name: "Start with the dataset, then follow the evidence." })).toBeVisible();
  await page.getByLabel("Choose dataset").focus();
  await expect(page.getByLabel("Choose dataset")).toBeFocused();
  await expect(page).toHaveScreenshot("overview-empty-dark.png", { animations: "disabled", fullPage: true, maxDiffPixelRatio: 0.01 });
});

test("native SQL Lab has a stable keyboard-first query studio surface", async ({ page }) => {
  await page.route("**/api/v1/sql-lab/connections", async (route) => route.fulfill({ json: [{ connection_id: "local:ds_sales", label: "sales.csv · local dataset", source_type: "local_dataset", dialect: "duckdb", status: "ready", capabilities: [{ name: "query_execution", supported: true }], source_fingerprint: "a".repeat(64) }] }));
  await page.route("**/api/v1/sql-lab/snippets", async (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/sql-lab/connections/local%3Ads_sales/schema", async (route) => route.fulfill({ json: { connection: { connection_id: "local:ds_sales", label: "sales.csv · local dataset", source_type: "local_dataset", dialect: "duckdb", status: "ready", capabilities: [{ name: "query_execution", supported: true }], source_fingerprint: "a".repeat(64) }, tables: [{ name: "data", columns: [{ name: "revenue", data_type: "float64", nullable: true, sample_count: 2 }] }], schema_fingerprint: "b".repeat(64) } }));
  await page.goto("/");
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await expect(page.getByRole("heading", { name: "Write against evidence, not assumptions." })).toBeVisible();
  await expect(page.getByText("revenue")).toBeVisible();
  await expect(page.locator(".monaco-editor")).toBeVisible();
  await expect(page).toHaveScreenshot("sql-lab-dark.png", { animations: "disabled", fullPage: true, maxDiffPixelRatio: 0.01 });
});

const cleanDataset = { dataset_id: "ds_sales", revision: 0, source_name: "sales.csv", source_fingerprint: "a".repeat(64), row_count: 5, column_count: 3 };
const cleanHealth = { completeness: 30, consistency: 20, uniqueness: 12, validity: 15, outlier_burden: 15, total: 92 };
const cleanIssue = { issue_id: "issue_duplicate_rows", kind: "duplicate_rows", column: null, severity: "medium", affected_rows: 1, description: "1 rows are exact duplicates of another row.", suggested_operation: "drop_duplicates" };

test("native Clean workspace previews a proposed fix and applies it as a new, reversible revision", async ({ page }) => {
  await page.route("**/api/v1/overview/datasets/*/profile", async (route) => route.fulfill({ json: { dataset: cleanDataset, provenance: { source_fingerprint: cleanDataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" }, quality: { n_rows: 5, n_cols: 3, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] }, health: cleanHealth, columns: [], correlations: [], suggestions: [] } }));
  await page.route("**/api/v1/overview/datasets/*/rows*", async (route) => route.fulfill({ json: { dataset: cleanDataset, offset: 0, limit: 20, total_rows: 5, rows: [], provenance: { source_fingerprint: cleanDataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" } } }));
  await page.route("**/api/v1/overview/datasets", async (route) => route.fulfill({ status: 201, json: cleanDataset }));
  let applied = false;
  await page.route("**/api/v1/clean/datasets/*/state", async (route) => route.fulfill({ json: applied ? { dataset: { ...cleanDataset, revision: 1, row_count: 4 }, issues: [], history: [{ transformation_id: "t1", operation: "drop_duplicates", column: null, parameters: {}, affected_rows: 1, affected_columns: [], source_revision: 0, resulting_revision: 1, source_fingerprint: cleanDataset.source_fingerprint, resulting_fingerprint: "b".repeat(64), reversible: true, created_at: "2026-08-28T00:00:00Z" }], health: cleanHealth } : { dataset: cleanDataset, issues: [cleanIssue], history: [], health: cleanHealth } }));
  await page.route("**/api/v1/clean/datasets/*/atlas", async (route) => route.fulfill({ json: { action: "explain_issue", summary: cleanIssue.description, uncertainty: "Issue detection is a deterministic screening pass; it flags candidates for review, not confirmed defects.", evidence: [], proposed_operation: { operation: "drop_duplicates" } } }));
  await page.route("**/api/v1/clean/datasets/*/preview", async (route) => route.fulfill({ json: { operation: "drop_duplicates", affected_rows: 1, affected_columns: [], before_sample: [{ segment: "a" }], after_sample: [{ segment: "a" }], warnings: [], projected_health: cleanHealth } }));
  await page.route("**/api/v1/clean/datasets/*/apply", async (route) => { applied = true; return route.fulfill({ status: 201, json: { dataset: { ...cleanDataset, revision: 1, row_count: 4 }, transformation: { transformation_id: "t1", operation: "drop_duplicates", column: null, parameters: {}, affected_rows: 1, affected_columns: [], source_revision: 0, resulting_revision: 1, source_fingerprint: cleanDataset.source_fingerprint, resulting_fingerprint: "b".repeat(64), reversible: true, created_at: "2026-08-28T00:00:00Z" }, issues: [], health: cleanHealth } }); });

  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("segment,revenue\na,10\n") });
  await expect(page.getByRole("heading", { name: "sales.csv" }).first()).toBeVisible();
  await page.getByRole("button", { name: /Clean native/i }).click();
  await expect(page.getByRole("heading", { name: "1 found" })).toBeVisible();
  await page.getByRole("button", { name: /Dataset/ }).click();
  await expect(page.getByText(/affects/)).toBeVisible();
  await page.getByRole("button", { name: "Apply transformation" }).focus();
  await expect(page.getByRole("button", { name: "Apply transformation" })).toBeFocused();
  await page.getByRole("button", { name: "Apply transformation" }).click();
  await expect(page.getByRole("heading", { name: /revision 1/ })).toBeVisible();
  // Scoped to Clean's own subtree: the shell chrome (tabs, rail, command palette) is covered by
  // the dedicated "native shell has no automated axe accessibility violations" baseline above.
  const violations = await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" }).then(() => page.evaluate(async () => (await (window as typeof window & { axe: { run(context: unknown): Promise<{ violations: unknown[] }> } }).axe.run(document.querySelector(".clean-workspace"))).violations));
  expect(violations).toEqual([]);
});

const vizProfile = { dataset: cleanDataset, provenance: { source_fingerprint: cleanDataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" }, quality: { n_rows: 5, n_cols: 3, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] }, health: cleanHealth, columns: [{ name: "segment", semantic_type: "categorical", missing_pct: 0, unique_count: 2, health: "good", issues: [], warnings: [], distribution: [] }, { name: "revenue", semantic_type: "numeric", missing_pct: 0, unique_count: 5, health: "good", issues: [], warnings: [], distribution: [] }], correlations: [], suggestions: [] };

test("native Visualize workspace suggests a deterministic chart and explains it through Atlas", async ({ page }) => {
  await page.route("**/api/v1/overview/datasets/*/profile", async (route) => route.fulfill({ json: vizProfile }));
  await page.route("**/api/v1/overview/datasets/*/rows*", async (route) => route.fulfill({ json: { dataset: cleanDataset, offset: 0, limit: 20, total_rows: 5, rows: [], provenance: vizProfile.provenance } }));
  await page.route("**/api/v1/overview/datasets", async (route) => route.fulfill({ status: 201, json: cleanDataset }));
  const spec = { mark: "bar", intent: "comparison", dimension: "segment", measure: "revenue", aggregation: "sum", filters: {}, max_categories: 20 };
  await page.route("**/api/v1/visualize/datasets/*/suggest*", async (route) => route.fulfill({ json: { spec, rationale: "Comparison question → bar chart of revenue by segment.", alternatives: ["line"] } }));
  await page.route("**/api/v1/visualize/datasets/*/render", async (route) => route.fulfill({ json: { spec, data: [{ label: "a", value: 30 }, { label: "b", value: 12 }], truncated: false, warnings: [], provenance: vizProfile.provenance } }));
  await page.route("**/api/v1/visualize/datasets/*/atlas", async (route) => route.fulfill({ json: { action: "explain_chart", summary: "This bar chart answers a comparison question using sum of revenue by segment.", uncertainty: "This explains what the chart shows; it does not establish why.", evidence: [] } }));

  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("segment,revenue\na,10\n") });
  await expect(page.getByRole("heading", { name: "sales.csv" }).first()).toBeVisible();
  await page.getByRole("button", { name: /Visualize native/i }).click();
  await expect(page.getByRole("img", { name: /Bar chart with 2 categories/ })).toBeVisible();
  await page.getByRole("button", { name: "Explain this chart", exact: true }).click();
  await expect(page.getByText(/answers a comparison question/)).toBeVisible();
});

test("native AI Analyst streams grounded evidence and requires SQL review", async ({ page }) => {
  await page.route("**/api/v1/ai-analyst/stream", async (route) => route.fulfill({
    contentType: "text/event-stream",
    body: [
      "event: atlas.state\nid: ai_test\ndata: {\"state\":\"context_selecting\"}\n\n",
      "event: atlas.token\nid: ai_test\ndata: {\"token\":\"I prepared a draft. \"}\n\n",
      "event: atlas.tool_wait\nid: ai_test\ndata: {\"tool\":\"sql-lab\",\"state\":\"review_required\"}\n\n",
      "event: atlas.complete\nid: ai_test\ndata: {\"request_id\":\"ai_test\",\"outcome\":\"sql_ready\",\"answer\":\"I prepared a draft.\",\"uncertainty\":\"It has not been executed.\",\"limiting_factors\":[\"SQL Lab is authoritative.\"],\"recommended_next_step\":\"Review it in SQL Lab.\",\"evidence\":[{\"kind\":\"dataset\",\"label\":\"Dataset\",\"value\":\"2 rows\",\"provenance_ref\":\"ds_sales\"}],\"context\":{\"dataset_id\":\"ds_sales\",\"source_fingerprint\":\"aaaaaaaaaaaaaaaa\",\"column_count\":2,\"row_count\":2,\"raw_sample_rows\":0,\"token_budget\":8000,\"prompt_version\":\"ai-analyst/evidence-first-v1\",\"config_version\":\"phase-5.1\"},\"provider\":\"deterministic\",\"sql_draft\":\"SELECT COUNT(*) AS row_count FROM data;\",\"sql_connection_id\":\"local:ds_sales\",\"provenance\":{}}\n\n"
    ].join("")
  }));
  await page.goto("/");
  await page.getByRole("button", { name: /AI Analyst native/i }).click();
  await expect(page.getByRole("heading", { name: "Ask what the evidence can actually support." })).toBeVisible();
  await page.getByLabel("Research question").focus();
  await expect(page.getByLabel("Research question")).toBeFocused();
  await page.getByRole("button", { name: "Ask Atlas" }).click();
  await expect(page.getByText("I prepared a draft.")).toBeVisible();
  await expect(page.getByText("SQL DRAFT · REVIEW REQUIRED")).toBeVisible();
  await expect(page).toHaveScreenshot("ai-analyst-dark.png", { animations: "disabled", fullPage: true, maxDiffPixelRatio: 0.01 });
});
