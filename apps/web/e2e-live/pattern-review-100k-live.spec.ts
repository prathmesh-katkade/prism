import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import path from "node:path";

function fixture(): Buffer {
  const lines = ["invoice_id,amount"];
  for (let index = 0; index < 100_000; index += 1) {
    const malformed = index % 500 === 0;
    const id = malformed ? `BAD${index}` : `INV-${String(index).padStart(6, "0")}`;
    const unit = index % 300 === 0 ? "abc" : index % 3 === 0 ? "lb" : "kg";
    const amount = unit === "abc" ? "abc" : `${(index % 1000) + 1}.5 ${unit}`;
    lines.push(`${id},${amount}`);
  }
  return Buffer.from(lines.join("\n") + "\n");
}

test("100k-row Pattern Review performance: discover, verify, extract preview, apply, cancel", async ({ page }) => {
  test.setTimeout(600_000);
  const timings: Record<string, number> = {};
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  let started = Date.now();
  await page.setInputFiles("#overview-upload", { name: "pattern-100k.csv", mimeType: "text/csv", buffer: fixture() });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "pattern-100k.csv" })).toBeVisible({ timeout: 150_000 });
  timings.upload_to_profile_visible_ms = Date.now() - started;

  started = Date.now();
  await page.getByRole("button", { name: /Clean native/i }).click();
  const findingButton = page.locator(".clean-issues .finding-list button").filter({ has: page.locator("strong", { hasText: /^invoice_id$/ }) }).first();
  await expect(findingButton).toBeVisible({ timeout: 150_000 }); // this is the initial bounded-sample discovery
  timings.sample_discovery_visible_ms = Date.now() - started;

  started = Date.now();
  await findingButton.click();
  await expect(page.locator(".pattern-family-list li").first()).toBeVisible({ timeout: 30_000 });
  timings.finding_review_render_ms = Date.now() - started;

  started = Date.now();
  await page.getByRole("button", { name: "Verify all rows" }).click();
  await expect(page.getByText(/Verified against all 100,000 row\(s\)/)).toBeVisible({ timeout: 150_000 });
  timings.full_verify_100k_ms = Date.now() - started;

  started = Date.now();
  await expect(page.locator(".data-table-wrap table tbody tr").first()).toBeVisible();
  timings.exception_table_render_ms = Date.now() - started;

  const numericFinding = page.locator(".clean-issues .finding-list button").filter({ hasText: "numeric unit" }).filter({ has: page.locator("strong", { hasText: /^amount$/ }) }).first();
  await numericFinding.click();
  await page.getByRole("button", { name: "Verify all rows" }).click();
  await expect(page.getByText(/Verified against all 100,000 row\(s\)/)).toBeVisible({ timeout: 150_000 });
  started = Date.now();
  await page.getByRole("button", { name: "Next exceptions" }).click();
  await expect(page.getByText(/Showing 11–20 of 334 exception row\(s\)/)).toBeVisible({ timeout: 30_000 });
  timings.exception_page_ms = Date.now() - started;
  await findingButton.click();

  started = Date.now();
  await page.locator(".pattern-family-list li").first().getByRole("button", { name: "Preview extraction for this family" }).click();
  await expect(page.getByRole("tab", { name: "Changes" })).toBeVisible({ timeout: 150_000 });
  timings.extraction_preview_ms = Date.now() - started;

  started = Date.now();
  await page.getByRole("button", { name: "Apply reviewed change" }).click();
  await expect(page.locator(".clean-preview header")).toContainText("revision 1", { timeout: 150_000 });
  timings.extraction_apply_ms = Date.now() - started;

  // Cancellation responsiveness: trigger a second verify, then cancel it immediately
  // and confirm the UI returns control (Cancel disappears) promptly rather than
  // blocking on the in-flight request.
  await findingButton.click();
  started = Date.now();
  await page.getByRole("button", { name: "Verify all rows" }).click();
  const cancelButton = page.getByRole("button", { name: "Cancel" });
  await expect(cancelButton).toBeVisible({ timeout: 5_000 });
  await cancelButton.click();
  await expect(cancelButton).toHaveCount(0, { timeout: 5_000 });
  timings.cancel_response_ms = Date.now() - started;

  const result = {
    rows: 100_000,
    timings_ms: timings,
    scope: `Single local Chromium run at 1440x900; browser navigation plus local API and rendering wall clock; ${process.env.PRISM_ANALYTICAL_HISTORY_DATABASE_URL?.startsWith("mysql") ? "MySQL" : "SQLite"} history store; no warmup or pass threshold. Discovery/extraction use invoice_id (identifier_structure); exception paging uses amount (numeric_unit).`,
  };
  writeFileSync(path.resolve("docs/clean-pattern-review-v1/performance-100k.json"), JSON.stringify(result, null, 2) + "\n");
  console.log(`PRISM_PATTERNS_100K ${JSON.stringify(result)}`);
});
