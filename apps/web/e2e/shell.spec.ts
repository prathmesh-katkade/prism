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
