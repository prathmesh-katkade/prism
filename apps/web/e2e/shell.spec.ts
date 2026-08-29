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

test("workspace tab bar stays a valid ARIA tablist with 2+ tabs open, and arrow keys move between them", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.getByRole("button", { name: /SQL Lab native/i }).click();

  // Two closeable tabs are now open (plus the non-closeable Project desk tab): exactly the DOM
  // shape that previously broke the tablist's ARIA structure.
  const tabs = page.getByRole("tab");
  await expect(tabs).toHaveCount(3);
  await expect(page.getByRole("tab", { name: "SQL Lab" })).toHaveAttribute("aria-selected", "true");

  // Scoped to the tab bar itself: this test is about the tablist's ARIA structure, not the
  // content of whichever workspace happens to be open (that's covered by each workspace's own
  // tests) - the native shell's page-level axe baseline is asserted separately, above.
  await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
  const violations = await page.evaluate(async () => (await (window as typeof window & { axe: { run(context: unknown): Promise<{ violations: unknown[] }> } }).axe.run(document.querySelector(".workspace-tabs"))).violations);
  expect(violations).toEqual([]);

  // Keyboard: arrow-key roving tabindex moves focus and selection between tabs.
  await page.getByRole("tab", { name: "SQL Lab" }).focus();
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("tab", { name: "Overview" })).toBeFocused();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await page.keyboard.press("Home");
  await expect(page.getByRole("tab", { name: "Project desk" })).toBeFocused();
  await page.keyboard.press("End");
  await expect(page.getByRole("tab", { name: "SQL Lab" })).toBeFocused();

  // Keyboard: Delete on a focused, closeable tab closes it (the visual × button is a
  // pointer-only shortcut, intentionally out of the tab order - see the component's comment).
  await page.getByRole("tab", { name: "SQL Lab" }).focus();
  await page.keyboard.press("Delete");
  await expect(page.getByRole("tab", { name: "SQL Lab" })).toHaveCount(0);

  // Mouse: the visual × button still closes a tab by click.
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.locator(".tab.is-active .tab-close").click();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveCount(0);
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

test("SQL Lab's query editor works with no CDN reachable, and is genuinely interactive", async ({ page }) => {
  // Registered first so Playwright tries it last: every other host is blocked, simulating a
  // network-restricted enterprise/offline deployment. Monaco's default AMD loader would hang
  // forever here; the bundled-package loader (query-editor.tsx) must not make any such request.
  const blockedRequests: string[] = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "127.0.0.1" || url.hostname === "localhost") return route.continue();
    blockedRequests.push(route.request().url());
    return route.abort("blockedbyclient");
  });

  await page.route("**/api/v1/sql-lab/connections", async (route) => route.fulfill({ json: [{ connection_id: "local:ds_sales", label: "sales.csv · local dataset", source_type: "local_dataset", dialect: "duckdb", status: "ready", capabilities: [{ name: "query_execution", supported: true }], source_fingerprint: "a".repeat(64) }] }));
  await page.route("**/api/v1/sql-lab/snippets", async (route) => route.fulfill({ json: [] }));
  await page.route("**/api/v1/sql-lab/connections/local%3Ads_sales/schema", async (route) => route.fulfill({ json: { connection: { connection_id: "local:ds_sales", label: "sales.csv · local dataset", source_type: "local_dataset", dialect: "duckdb", status: "ready", capabilities: [{ name: "query_execution", supported: true }], source_fingerprint: "a".repeat(64) }, tables: [{ name: "data", columns: [{ name: "revenue", data_type: "float64", nullable: true, sample_count: 2 }] }], schema_fingerprint: "b".repeat(64) } }));

  await page.goto("/");
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await expect(page.locator(".monaco-editor")).toBeVisible();

  await page.locator(".monaco-editor").click();
  await page.keyboard.type("SELECT 1");
  await expect(page.locator(".monaco-editor")).toContainText("SELECT 1");

  expect(blockedRequests, `Monaco (or anything else) must never reach an external host offline; blocked: ${blockedRequests.join(", ")}`).toEqual([]);
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

const statsProfile = { dataset: { ...cleanDataset, row_count: 40 }, provenance: { source_fingerprint: cleanDataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" }, quality: { n_rows: 40, n_cols: 2, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] }, health: cleanHealth, columns: [{ name: "x", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] }, { name: "y", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] }], correlations: [], suggestions: [] };

test("native Stats workspace suggests a deterministic test, runs it with an honest evidence statement, and explains it through Atlas", async ({ page }) => {
  await page.route("**/api/v1/overview/datasets/*/profile", async (route) => route.fulfill({ json: statsProfile }));
  await page.route("**/api/v1/overview/datasets/*/rows*", async (route) => route.fulfill({ json: { dataset: statsProfile.dataset, offset: 0, limit: 20, total_rows: 40, rows: [], provenance: statsProfile.provenance } }));
  await page.route("**/api/v1/overview/datasets", async (route) => route.fulfill({ status: 201, json: statsProfile.dataset }));
  await page.route("**/api/v1/stats/datasets/*/suggest*", async (route) => route.fulfill({ json: { col_a: "x", col_b: "y", test: "pearson", reason: "Both 'x' and 'y' are numeric — testing whether they're linearly correlated.", numeric_col: null, cat_col: null, error: null } }));
  await page.route("**/api/v1/stats/datasets/*/run", async (route) => route.fulfill({ json: { test: "pearson", statistic: 0.87, p_value: 0.0001, effect_size: 0.87, effect_size_name: "Pearson r", effect_size_label: "large", groups: {}, means: {}, dof: null, n: 40, low_expected_pct: null, normality: [], significant: true, interpretation: "Significant correlation detected (p<0.0001, large effect, Pearson r=0.87).", evidence_statement: "This test found statistically significant evidence of a correlation in this sample. Statistical significance is not the same as practical importance or causation — read it together with the effect size, the assumption warnings below, and domain context.", warnings: [], provenance: statsProfile.provenance } }));
  await page.route("**/api/v1/stats/datasets/*/atlas", async (route) => route.fulfill({ json: { action: "explain_test", summary: "Both 'x' and 'y' are numeric — testing whether they're linearly correlated.", uncertainty: "This explanation describes a deterministic statistical result; it does not establish causation, and Atlas cannot alter the underlying computation.", evidence: [{ label: "Selected test", value: "pearson" }] } }));

  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("x,y\n1,2\n2,4\n") });
  await expect(page.getByRole("heading", { name: "sales.csv" }).first()).toBeVisible();
  await page.getByRole("button", { name: /Stats/i }).click();
  await expect(page.getByRole("button", { name: "Run test" })).toBeVisible();
  await page.getByRole("button", { name: "Run test" }).click();
  await expect(page.getByText("Significant correlation detected (p<0.0001, large effect, Pearson r=0.87).")).toBeVisible();
  await expect(page.getByText("Evidence found")).toBeVisible();
  await expect(page.getByText(/Statistical significance is not the same as practical importance/)).toBeVisible();

  await page.getByRole("button", { name: "explain test" }).click();
  await expect(page.getByText(/does not establish causation/)).toBeVisible();

  // Scoped to Stats' own subtree: the shell chrome is covered by the page-level axe baseline above.
  const violations = await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" }).then(() => page.evaluate(async () => (await (window as typeof window & { axe: { run(context: unknown): Promise<{ violations: unknown[] }> } }).axe.run(document.querySelector(".stats-workspace"))).violations));
  expect(violations).toEqual([]);
});

const forecastingProfile = { dataset: { ...cleanDataset, row_count: 10 }, provenance: { source_fingerprint: cleanDataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" }, quality: { n_rows: 10, n_cols: 2, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] }, health: cleanHealth, columns: [{ name: "date", semantic_type: "datetime", missing_pct: 0, unique_count: 10, health: "good", issues: [], warnings: [], distribution: [] }, { name: "revenue", semantic_type: "numeric", missing_pct: 0, unique_count: 10, health: "good", issues: [], warnings: [], distribution: [] }], correlations: [], suggestions: [] };
const forecastResult = { datetime_col: "date", numeric_col: "revenue", frequency: "D", model_used: "Exponential Smoothing (ETS)", horizon: 3, observed: [{ timestamp: "2026-01-01T00:00:00", value: 10 }, { timestamp: "2026-01-02T00:00:00", value: 12 }], forecast: [{ timestamp: "2026-01-03T00:00:00", value: 14 }, { timestamp: "2026-01-04T00:00:00", value: 16 }, { timestamp: "2026-01-05T00:00:00", value: 18 }], intervals: [{ timestamp: "2026-01-03T00:00:00", lower: 12, upper: 16 }, { timestamp: "2026-01-04T00:00:00", lower: 13, upper: 19 }, { timestamp: "2026-01-05T00:00:00", lower: 14, upper: 22 }], metrics: { mae: 1.2, rmse: 1.5, mape: null, holdout_points: 2, note: "Computed by fitting on all but the last 2 point(s)." }, caveat: "Fit on 10 historical observations to project 3 periods ahead using Exponential Smoothing (ETS). Confidence in this forecast is **reasonable**.", warnings: [], provenance: forecastingProfile.provenance };

test("native Forecasting workspace projects a point forecast with its interval, an honest caveat, and explains it through Atlas", async ({ page }) => {
  await page.route("**/api/v1/overview/datasets/*/profile", async (route) => route.fulfill({ json: forecastingProfile }));
  await page.route("**/api/v1/overview/datasets/*/rows*", async (route) => route.fulfill({ json: { dataset: forecastingProfile.dataset, offset: 0, limit: 20, total_rows: 10, rows: [], provenance: forecastingProfile.provenance } }));
  await page.route("**/api/v1/overview/datasets", async (route) => route.fulfill({ status: 201, json: forecastingProfile.dataset }));
  await page.route("**/api/v1/forecasting/datasets/*/forecast", async (route) => route.fulfill({ json: forecastResult }));
  await page.route("**/api/v1/forecasting/datasets/*/atlas", async (route) => route.fulfill({ json: { action: "explain_intervals", summary: "The shaded band is a 95% confidence interval around the point forecast — it widens further into the future because uncertainty compounds with each additional step. A point forecast without this band is not the full picture; treat the band's width, not just its center, as the forecast.", uncertainty: "This explanation describes a deterministic time-series computation; it does not establish causation, and Atlas cannot alter the underlying model or its output.", evidence: [] } }));

  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("date,revenue\n2026-01-01,10\n2026-01-02,12\n") });
  await expect(page.getByRole("heading", { name: "sales.csv" }).first()).toBeVisible();
  await page.getByRole("button", { name: /Forecasting/i }).click();
  await expect(page.getByLabel("Forecast canvas").getByText("Exponential Smoothing (ETS)", { exact: true })).toBeVisible();
  await expect(page.getByText("Reliability caveat")).toBeVisible();
  await expect(page.getByRole("img", { name: /Forecast chart/ })).toBeVisible();

  await page.getByRole("button", { name: "explain intervals" }).click();
  await expect(page.getByText(/not the full picture/)).toBeVisible();

  // Scoped to Forecasting's own subtree: the shell chrome is covered by the page-level axe baseline above.
  const violations = await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" }).then(() => page.evaluate(async () => (await (window as typeof window & { axe: { run(context: unknown): Promise<{ violations: unknown[] }> } }).axe.run(document.querySelector(".forecasting-workspace"))).violations));
  expect(violations).toEqual([]);
});

const mllabProfile = { dataset: { ...cleanDataset, row_count: 40, column_count: 3 }, provenance: { source_fingerprint: cleanDataset.source_fingerprint, dataset_revision: 0, parameters: {}, service_version: "x", computed_at: "2026-08-28T00:00:00Z" }, quality: { n_rows: 40, n_cols: 3, missing_by_column: {}, total_missing_cells: 0, total_missing_pct: 0, duplicate_rows: 0, memory_usage: "1KB", outliers: {}, all_null_columns: [] }, health: cleanHealth, columns: [{ name: "x1", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] }, { name: "x2", semantic_type: "numeric", missing_pct: 0, unique_count: 40, health: "good", issues: [], warnings: [], distribution: [] }, { name: "label", semantic_type: "categorical", missing_pct: 0, unique_count: 2, health: "good", issues: [], warnings: [], distribution: [] }], correlations: [], suggestions: [] };
const mllabBaseline = {
  task_type: "classification", results: { Baseline: { accuracy: 0.8, f1: 0.79 }, "Random Forest": { accuracy: 0.85, f1: 0.84 } },
  confusion_matrix: [[15, 2], [1, 14]], confusion_labels: ["no", "yes"],
  feature_importances: [{ feature: "x1", importance: 0.6 }, { feature: "x2", importance: 0.4 }],
  n_train: 32, n_test: 8, smote_before_after: null,
  cv: { results: { Baseline: { accuracy: { mean: 0.78, std: 0.05 } }, "Random Forest": { accuracy: { mean: 0.82, std: 0.04 } } }, n_splits: 5 }, cv_error: null,
  verdict: "Random Forest wins on F1 score (0.840 vs 0.790, 6% higher than the other model). Top driver: x1.",
  leakage_note: "Preprocessing (imputation, scaling, one-hot encoding) is fit on the training split only, then applied unchanged to the test split — the test set never influences how features are transformed, so its score is not inflated by information the model would not have at prediction time.",
  provenance: mllabProfile.provenance,
};

test("native ML Lab workspace runs baseline models with a leakage-protection note and explains model comparison through Atlas", async ({ page }) => {
  await page.route("**/api/v1/overview/datasets/*/profile", async (route) => route.fulfill({ json: mllabProfile }));
  await page.route("**/api/v1/overview/datasets/*/rows*", async (route) => route.fulfill({ json: { dataset: mllabProfile.dataset, offset: 0, limit: 20, total_rows: 40, rows: [], provenance: mllabProfile.provenance } }));
  await page.route("**/api/v1/overview/datasets", async (route) => route.fulfill({ status: 201, json: mllabProfile.dataset }));
  await page.route("**/api/v1/ml/datasets/*/suggest-features*", async (route) => route.fulfill({ json: { target_col: "label", suggestions: [{ kind: "scale", column: "x1", columns: null, method: "standard", reason: "Numeric feature — standardizing helps distance-based and linear models treat it fairly alongside other features." }] } }));
  await page.route("**/api/v1/ml/datasets/*/detect-task*", async (route) => route.fulfill({ json: { target_col: "label", task_type: "classification", reason: "Non-numeric target." } }));
  await page.route("**/api/v1/ml/datasets/*/imbalance*", async (route) => route.fulfill({ json: { target_col: "label", counts: { yes: 20, no: 20 }, proportions_pct: { yes: 50, no: 50 }, minority_pct: 50, is_imbalanced: false, explanation: "Balanced." } }));
  await page.route("**/api/v1/ml/datasets/*/baseline", async (route) => route.fulfill({ json: mllabBaseline }));
  await page.route("**/api/v1/ml/datasets/*/atlas", async (route) => route.fulfill({ json: { action: "compare_models", summary: mllabBaseline.verdict, uncertainty: "This explanation describes a deterministic model-evaluation result; it does not establish causation, and Atlas never retrains or alters a model outside an explicit PRISM command.", evidence: [] } }));

  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "ml.csv", mimeType: "text/csv", buffer: Buffer.from("x1,x2,label\n1,2,yes\n3,4,no\n") });
  await expect(page.getByRole("heading", { name: "sales.csv" }).first()).toBeVisible();
  await page.getByRole("button", { name: /ML/i }).click();
  await page.getByRole("combobox", { name: "Analysis" }).selectOption("baseline");
  await page.getByRole("button", { name: "Run baseline models" }).click();
  await expect(page.getByLabel("Analysis results").getByText(mllabBaseline.verdict)).toBeVisible();
  await expect(page.getByText("Leakage protection")).toBeVisible();

  await page.getByRole("button", { name: "compare models", exact: true }).click();
  await expect(page.getByLabel("Provenance and Atlas").getByText(mllabBaseline.verdict)).toBeVisible();

  // Scoped to ML Lab's own subtree: the shell chrome is covered by the page-level axe baseline above.
  const violations = await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" }).then(() => page.evaluate(async () => (await (window as typeof window & { axe: { run(context: unknown): Promise<{ violations: unknown[] }> } }).axe.run(document.querySelector(".mllab-workspace"))).violations));
  expect(violations).toEqual([]);
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
