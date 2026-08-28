import { expect, test } from "@playwright/test";

test("SQL Lab completes a real browser to FastAPI analytical flow", async ({ page, request }) => {
  const upload = await request.post("http://127.0.0.1:8000/api/v1/overview/datasets", {
    multipart: {
      file: {
        name: "phase4-live.csv",
        mimeType: "text/csv",
        buffer: Buffer.from("id,revenue,segment\n1,10,North\n2,12,South\n3,14,North\n")
      }
    }
  });
  expect(upload.status()).toBe(201);

  const started = Date.now();
  await page.goto("/");
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await expect(page.getByRole("heading", { name: "Write against evidence, not assumptions." })).toBeVisible();
  await expect(page.locator(".monaco-editor")).toBeVisible();
  expect(Date.now() - started).toBeLessThan(8_000);

  await page.locator(".monaco-editor").click();
  await page.keyboard.press("ControlOrMeta+Enter");
  await expect(page.getByText("3 returned / 3 total rows")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("button", { name: "Create dataset" })).toBeVisible();
  if (process.platform === "win32") {
    await expect(page).toHaveScreenshot("sql-lab-live-results.png", { animations: "disabled", fullPage: true, maxDiffPixelRatio: 0.01 });
  }

  await page.getByRole("button", { name: "Inspect plan", exact: true }).click();
  await expect(page.getByRole("tab", { name: "plan" })).toHaveAttribute("aria-selected", "true");
  await page.getByRole("tab", { name: "results" }).click();
  await page.getByRole("button", { name: "Create dataset" }).click();
  await expect(page.getByRole("heading", { name: /SQL result run_/ })).toBeVisible();
});
