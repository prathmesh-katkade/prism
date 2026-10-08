import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const CSV = [
  "invoice_id,amount,note",
  "INV-000123,10.5 kg,ok",
  "INV-000456,20 kg,ok",
  "INV-000789,<0.05 kg,detection limit",
  "AB12,99 lb,malformed id",
  "ZZZZZZ,abc,malformed id and unit",
].join("\n") + "\n";

async function capture(page: Page, name: string) {
  const directory = path.resolve("docs/clean-pattern-review-v1/screenshots");
  mkdirSync(directory, { recursive: true });
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["dark", "light"] as const) {
      if (!(await page.locator(".prism-shell").getAttribute("class"))?.includes(`theme-${theme}`)) {
        await page.getByRole("button", { name: `Switch to ${theme} theme` }).click();
      }
      await page.screenshot({ path: path.join(directory, `${name}-${theme}-${width}.png`) });
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("Pattern Review: discover, inspect evidence, accept a family, extract, and save a reusable rule", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  const [upload] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/api/v1/overview/datasets") && response.request().method() === "POST"),
    page.setInputFiles("#overview-upload", { name: "pattern-review.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) }),
  ]);
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "pattern-review.csv" })).toBeVisible();
  expect(upload.ok()).toBe(true);

  await page.getByRole("button", { name: /Clean native/i }).click();
  await expect(page.getByRole("heading", { name: "No issues detected" })).toBeVisible(); // this fixture has no missing/duplicate/outlier data by design

  // Ranked shortlist: discovery runs automatically and surfaces the invoice_id finding.
  // An exact match on the column name (not a substring) matters once extraction adds
  // invoice_id_part1/part2 columns later in this test - those would also match "invoice_id".
  const findingButton = page.locator(".clean-issues .finding-list button").filter({ has: page.locator("strong", { hasText: /^invoice_id$/ }) }).first();
  await expect(findingButton).toBeVisible({ timeout: 15_000 });
  await capture(page, "shortlist");
  await findingButton.click();

  // Central review area: plain-language structure, families, exceptions.
  await expect(page.locator(".clean-preview-summary", { hasText: "identifier structure" })).toBeVisible();
  await expect(page.getByText(/Provisional: sampled/)).toBeVisible();
  const familyItem = page.locator(".pattern-family-list li").first();
  await expect(familyItem).toBeVisible();
  await expect(page.getByRole("tab", { name: /Exceptions \(2\)/ })).toBeVisible();
  await capture(page, "family-review");

  // Verify all rows: a real full scan, not a bigger sample.
  await page.getByRole("button", { name: "Verify all rows" }).click();
  await expect(page.getByText(/Verified against all 5 row\(s\)/)).toBeVisible({ timeout: 10_000 });

  // Accept the family: multiple legitimate families could be selected; here there is one.
  await familyItem.getByRole("checkbox").check();
  await capture(page, "family-accepted");
  await page.getByRole("button", { name: /Accept 1 selected family/ }).click();
  await expect(page.getByText("active")).toBeVisible({ timeout: 10_000 });

  // Extraction preview through the ordinary Clean preview/apply flow - leading zeros must survive.
  await familyItem.getByRole("button", { name: "Preview extraction for this family" }).click();
  await expect(page.getByRole("tab", { name: "Changes" })).toBeVisible({ timeout: 10_000 });
  await capture(page, "extraction-preview");
  const applyButton = page.getByRole("button", { name: "Apply reviewed change" });
  await expect(applyButton).toBeEnabled();
  await applyButton.click();
  await expect(page.locator(".clean-preview header")).toContainText("revision 1", { timeout: 10_000 });

  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.locator(".column-card", { hasText: "invoice_id_part2" }).click();
  const inspector = page.getByRole("complementary", { name: "Contextual inspector" });
  await expect(inspector.getByText("invoice_id_part2")).toBeVisible();

  // Save the accepted family as a reusable validation rule and confirm it shows under Validation.
  await page.getByRole("button", { name: /Clean native/i }).click();
  await findingButton.click();
  await familyItem.getByRole("checkbox").check();
  await page.getByRole("textbox", { name: "Pattern validation rule name" }).fill("Invoice ID format");
  await page.getByRole("button", { name: "Save selected families as a validation rule" }).click();
  await expect(page.getByText("Invoice ID format")).toBeVisible({ timeout: 10_000 });
  await capture(page, "saved-rule");
});

test("Pattern Review: ignore and suppress are distinct from accept, and suppress is revocable", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "pattern-review-2.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "pattern-review-2.csv" })).toBeVisible();

  await page.getByRole("button", { name: /Clean native/i }).click();
  const findingButton = page.locator(".clean-issues .finding-list button", { hasText: "invoice_id" }).first();
  await expect(findingButton).toBeVisible({ timeout: 15_000 });
  await findingButton.click();

  await page.getByRole("button", { name: "Suppress this rule" }).click();
  await expect(page.getByText("suppress rule")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator(".clean-recipe-list small", { hasText: /^active/ })).toBeVisible();

  await page.getByRole("button", { name: "Revoke" }).click();
  await expect(page.getByText("revoked")).toBeVisible({ timeout: 10_000 });
});
