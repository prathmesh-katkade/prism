import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8000/api/v1";
const PROOF = "docs/atlas/production-investigation-v1/verification";

test.use({ video: "on" });

test("uploaded data produces a recorded SQL result and exact-query handoff", async ({ page, request }) => {
  const upload = await request.post(`${API}/overview/datasets`, { multipart: {
    file: { name: "atlas-sql.csv", mimeType: "text/csv", buffer: Buffer.from("region,revenue\nwest,10\neast,7\nwest,5\n") },
  } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}`);
  await page.getByRole("button", { name: /Atlas native/i }).click();
  await page.getByLabel("Investigation objective").fill("Sum revenue by region using SQL");
  await page.getByLabel("Optional SQL aggregate").selectOption("sum");
  await page.getByLabel("Measure column").selectOption("revenue");
  await page.getByLabel("Group by column").selectOption("region");
  await page.getByRole("button", { name: "Run investigation" }).click();
  await expect(page.getByText(/Recorded SQL result run_/)).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Inspect supporting SQL evidence" }).click();
  await page.getByRole("button", { name: /SQL Lab aggregate/ }).click();
  await expect(page.getByText("Recorded original; edits in SQL Lab create a draft.")).toBeVisible();
  await expect(page.getByText('SELECT "region" AS group_value, SUM("revenue") AS result_value FROM "data" GROUP BY "region" ORDER BY "region" LIMIT 100')).toBeVisible();
  await page.screenshot({ path: `${PROOF}/atlas-sql-evidence.png`, fullPage: true });
  await page.getByRole("button", { name: "Open exact query in SQL Lab" }).click();
  await expect(page.getByRole("heading", { name: "Write against evidence, not assumptions." })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Source" })).toHaveValue(`local:${dataset.dataset_id}`);
  await expect(page.locator(".monaco-editor")).toContainText('SUM("revenue")');
  await page.screenshot({ path: `${PROOF}/atlas-sql-lab-handoff.png`, fullPage: true });
  await page.getByRole("tab", { name: "Atlas" }).click();
  await expect(page.getByText(/Recorded SQL result run_/)).toBeVisible();
  await page.getByRole("button", { name: "Inspect supporting SQL evidence" }).click();
  await page.getByRole("button", { name: /SQL Lab aggregate/ }).click();
  await expect(page.getByText("Recorded original; edits in SQL Lab create a draft.")).toBeVisible();
  const video = page.video();
  await page.close();
  await video?.saveAs(`${PROOF}/atlas-sql-workflow.webm`);
});

test("declared two-source join keeps the sales grain and opens its query in SQL Lab", async ({ page, request }) => {
  const joinedUpload = await request.post(`${API}/overview/datasets`, { multipart: {
    file: { name: "segments.csv", mimeType: "text/csv", buffer: Buffer.from("product_id,segment\nA,west\nB,east\n") },
  } });
  expect(joinedUpload.ok()).toBe(true);
  const joined = await joinedUpload.json() as { dataset_id: string };
  const salesUpload = await request.post(`${API}/overview/datasets`, { multipart: {
    file: { name: "sales.csv", mimeType: "text/csv", buffer: Buffer.from("product_id,revenue\nA,10\nA,5\nB,7\n") },
  } });
  expect(salesUpload.ok()).toBe(true);
  const sales = await salesUpload.json() as { dataset_id: string };
  await page.goto(`/?dataset_id=${encodeURIComponent(sales.dataset_id)}`);
  await page.getByRole("button", { name: /Atlas native/i }).click();
  await page.getByLabel("Investigation objective").fill("Sum sales revenue by segment using SQL");
  await page.getByLabel("Optional SQL aggregate").selectOption("sum");
  await page.getByLabel("Measure column").selectOption("revenue");
  await expect(page.getByLabel("Optional registered join source")).toContainText("segments.csv");
  await page.getByLabel("Optional registered join source").selectOption(joined.dataset_id);
  await page.getByLabel("Active dataset key").selectOption("product_id");
  await page.getByLabel("Joined dataset key").selectOption("product_id");
  await page.getByLabel("Declared join cardinality").selectOption("many_to_one");
  await page.getByLabel("Group source").selectOption("joined");
  await page.getByLabel("Group by column").selectOption("segment");
  await page.getByRole("button", { name: "Run investigation" }).click();
  await expect(page.getByText(/Recorded SQL result run_/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText(/"group_value": "east", "result_value": 7\.0.*"group_value": "west", "result_value": 15\.0/)).toBeVisible();
  await page.getByRole("button", { name: "Inspect supporting SQL evidence" }).click();
  await page.getByRole("button", { name: /SQL Lab aggregate/ }).click();
  await expect(page.getByText(/INNER JOIN "joined"/)).toBeVisible();
  await page.getByRole("button", { name: "Open exact query in SQL Lab" }).click();
  await expect(page.getByRole("combobox", { name: "Source" })).toHaveValue(`localjoin:${sales.dataset_id}:${joined.dataset_id}`);
  await expect(page.locator(".monaco-editor")).toContainText('INNER JOIN "joined"');
  await page.getByRole("button", { name: /Run query/ }).click();
  await expect(page.getByRole("grid", { name: "Query results" })).toBeVisible();
  await expect(page.getByRole("gridcell", { name: "west" })).toBeVisible();
  await expect(page.getByRole("gridcell", { name: "15" })).toBeVisible();
  await page.getByRole("tab", { name: "Atlas" }).click();
  await expect(page.getByText(/Recorded SQL result run_/)).toBeVisible();
  await page.screenshot({ path: `${PROOF}/atlas-join-evidence.png`, fullPage: true });
  const video = page.video();
  await page.close();
  await video?.saveAs(`${PROOF}/atlas-join-workflow.webm`);
});
