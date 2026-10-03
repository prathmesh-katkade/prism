import { expect, test } from "@playwright/test";
import { writeFileSync } from "node:fs";
import path from "node:path";

function fixture(): Buffer {
  const lines = ["record_id,segment,revenue,ordered_at"];
  for (let index = 0; index < 100_000; index += 1) {
    const actual = index % 100 === 99 ? index - 1 : index;
    const segment = ["North", "South", "East", "West"][actual % 4];
    const revenue = actual % 50 === 0 ? "" : String((actual % 20) * 10 + 5);
    lines.push(`r${actual},${segment},${revenue},2025-01-${String(actual % 28 + 1).padStart(2, "0")}`);
  }
  return Buffer.from(lines.join("\n") + "\n");
}

test("100k-row UI observation through Overview, Clean, SQL, and Visualize", async ({ page }) => {
  test.setTimeout(90_000);
  const timings: Record<string, number> = {};
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  let started = Date.now();
  await page.setInputFiles("#overview-upload", { name: "generated-100k.csv", mimeType: "text/csv", buffer: fixture() });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "generated-100k.csv" })).toBeVisible();
  timings.upload_to_profile_visible_ms = Date.now() - started;

  started = Date.now();
  await page.getByRole("button", { name: /Clean native/i }).click();
  await expect(page.getByRole("heading", { name: /found/ })).toBeVisible({ timeout: 30_000 });
  timings.clean_workspace_open_ms = Date.now() - started;
  started = Date.now();
  await page.getByRole("button", { name: /revenue.*missing/i }).click();
  await expect(page.getByRole("tab", { name: /Affected rows/ })).toBeVisible({ timeout: 30_000 });
  timings.clean_preview_visible_ms = Date.now() - started;

  started = Date.now();
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await expect(page.locator(".monaco-editor")).toBeVisible();
  timings.sql_workspace_open_ms = Date.now() - started;
  started = Date.now();
  await page.getByRole("button", { name: /Run query/ }).click();
  await expect(page.getByText("100 returned / 100 total rows")).toBeVisible({ timeout: 30_000 });
  timings.sql_result_visible_ms = Date.now() - started;

  started = Date.now();
  await page.getByRole("button", { name: /Visualize native/i }).click();
  await expect(page.getByRole("img", { name: /(chart with|Histogram with)/ })).toBeVisible({ timeout: 30_000 });
  timings.chart_visible_ms = Date.now() - started;
  const result = { rows: 100_000, timings_ms: timings, scope: "Single local Chromium run at 1440x900; browser navigation plus local API and rendering wall clock; no warmup or pass threshold. Default SQL query is SELECT * FROM data LIMIT 100, returning 100 rows." };
  writeFileSync(path.resolve("docs/analytical-workspaces-v1/performance-100k-ui.json"), JSON.stringify(result, null, 2) + "\n");
  console.log(`PRISM_100K_UI ${JSON.stringify(result)}`);
});
