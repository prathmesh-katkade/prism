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
