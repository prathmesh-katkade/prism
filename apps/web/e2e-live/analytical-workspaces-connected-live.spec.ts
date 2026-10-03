import { expect, test, type Page } from "@playwright/test";
import { mkdirSync } from "node:fs";
import path from "node:path";

const api = process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000";
test.use({ video: "on" });
const csv = [
  "customer_id,segment,revenue,ordered_at",
  "c1,North,10,2025-01-01",
  "c1,North,10,2025-01-01",
  "c2,South,20,2025-01-02",
  "c3,North,,2025-01-03",
  "c4,South,30,2025-01-04",
].join("\n") + "\n";

async function capture(page: Page, workspace: string) {
  const directory = path.resolve("docs/analytical-workspaces-v1/screenshots");
  mkdirSync(directory, { recursive: true });
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 });
    for (const theme of ["dark", "light"] as const) {
      if (!(await page.locator(".prism-shell").getAttribute("class"))?.includes(`theme-${theme}`)) {
        await page.getByRole("button", { name: `Switch to ${theme} theme` }).click();
      }
      await expect(page.locator(".prism-shell")).toHaveClass(new RegExp(`theme-${theme}`));
      await page.evaluate(() => { window.scrollTo(0, 0); document.querySelector(".workspace-content")?.scrollTo(0, 0); });
      await page.screenshot({ path: path.join(directory, `${workspace}-${theme}-${width}.png`) });
    }
  }
  await page.setViewportSize({ width: 1440, height: 900 });
}

test("real Clean to SQL to Visualize to Report flow keeps source versions explicit", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  const [upload] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/api/v1/overview/datasets") && response.request().method() === "POST"),
    page.setInputFiles("#overview-upload", { name: "business-export.csv", mimeType: "text/csv", buffer: Buffer.from(csv) }),
  ]);
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "business-export.csv" })).toBeVisible();
  const datasetId = (await upload.json() as { dataset_id: string }).dataset_id;

  await page.getByRole("button", { name: /Clean native/i }).click();
  await page.getByRole("button", { name: /Dataset/ }).click();
  await expect(page.getByRole("tab", { name: /Affected rows/ })).toBeVisible();
  await capture(page, "clean-review");
  await page.getByRole("button", { name: "Apply transformation" }).first().click();
  await expect(page.getByRole("tabpanel", { name: "Clean" })).toContainText("revision 1");

  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  const [sqlResults] = await Promise.all([
    page.waitForResponse((response) => /\/sql-lab\/runs\/[^/]+\/results/.test(response.url()) && response.status() === 200),
    page.getByRole("button", { name: /Run query/ }).click(),
  ]);
  expect(sqlResults.ok()).toBe(true);
  await expect(page.getByText("4 returned / 4 total rows")).toBeVisible();
  await capture(page, "sql-results");

  await page.getByRole("button", { name: /Visualize native/i }).click();
  await expect(page.getByRole("img", { name: /(chart with|Histogram with)/ })).toBeVisible();
  await capture(page, "visualize-chart");
  await page.getByRole("button", { name: "Save chart" }).click();
  await expect(page.getByText(/Chart saved with its source revision/)).toBeVisible();

  await page.getByRole("button", { name: /Reports native/i }).click();
  await page.getByRole("textbox", { name: "New report name" }).fill("Business review");
  await page.getByRole("button", { name: "Create report" }).click();
  await page.getByLabel("Add saved chart").selectOption({ index: 1 });
  await page.getByRole("button", { name: "Add chart" }).click();
  await expect(page.getByLabel("Report canvas").getByRole("img", { name: /(chart with|Histogram with)/ })).toBeVisible();
  await page.getByRole("textbox", { name: "New note" }).fill("North and South revenue after duplicate review.");
  await page.getByRole("button", { name: "Add note" }).click();
  await expect(page.getByText("North and South revenue after duplicate review.")).toBeVisible();
  await page.getByRole("textbox", { name: "Table title" }).fill("Reviewed source rows");
  await page.getByRole("checkbox", { name: "segment" }).check();
  await page.getByRole("checkbox", { name: "revenue" }).check();
  await page.getByRole("button", { name: "Add table snapshot" }).click();
  await expect(page.getByRole("heading", { name: "Reviewed source rows" })).toBeVisible();
  await page.getByRole("button", { name: "Move item 3 up" }).click();
  await expect(page.getByLabel("Report canvas")).not.toContainText("Report change failed");
  await page.getByRole("textbox", { name: "New note" }).fill("Temporary note to remove.");
  await page.getByRole("button", { name: "Add note" }).click();
  const temporary = page.locator(".report-item").filter({ hasText: "Temporary note to remove." });
  await temporary.getByRole("button", { name: "Remove" }).click();
  await expect(page.getByText("Temporary note to remove.")).toHaveCount(0);
  await capture(page, "reports-saved");

  const changed = await page.request.post(`${api}/api/v1/clean/datasets/${datasetId}/preview`, {
    data: { operation: "category_mapping", column: "segment", category_mapping: { North: "Northern" } },
  });
  expect(changed.ok()).toBe(true);
  const token = (await changed.json() as { review_token: string }).review_token;
  const applied = await page.request.post(`${api}/api/v1/clean/datasets/${datasetId}/apply`, {
    data: { operation: "category_mapping", column: "segment", category_mapping: { North: "Northern" }, review_token: token },
  });
  expect(applied.status()).toBe(201);
  await page.reload();
  await page.getByRole("button", { name: /Reports native/i }).click();
  await expect(page.getByText(/Source changed: saved revision/)).toBeVisible();
  await page.getByRole("button", { name: "Refresh from reviewed current source" }).click();
  await expect(page.getByLabel("Report canvas")).toContainText("Source revision 2");
  await expect(page.getByLabel("Report canvas")).toContainText("Previous version:");
});
