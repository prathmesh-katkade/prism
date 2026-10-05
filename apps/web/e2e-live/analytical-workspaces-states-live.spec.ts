import { expect, test } from "@playwright/test";
import path from "node:path";

test("empty workspace states remain usable with keyboard and narrow viewport", async ({ page, request }) => {
  if (process.env.PRISM_EMPTY_STATE_PROOF === "1") {
    const datasets = await request.get(`${process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000"}/api/v1/overview/datasets`);
    expect(await datasets.json()).toEqual([]);
  }
  await page.goto("/");
  for (const [name, button] of [["clean", "Clean native"], ["visualize", "Visualize native"], ["reports", "Reports native"], ["sql", "SQL Lab native"]] as const) {
    await page.getByRole("button", { name: button }).click();
    for (const width of [1440, 400]) {
      await page.setViewportSize({ width, height: 900 });
      for (const theme of ["dark", "light"] as const) {
        if (!(await page.locator(".prism-shell").getAttribute("class"))?.includes(`theme-${theme}`)) await page.getByRole("button", { name: `Switch to ${theme} theme` }).click();
        await page.screenshot({ path: path.resolve(`docs/analytical-workspaces-v1/screenshots/${name}-empty-${theme}-${width}.png`) });
      }
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${name} document overflow at ${width}px`).toBeLessThanOrEqual(1);
    }
    await page.keyboard.press("Tab");
    expect(await page.evaluate(() => document.activeElement !== document.body)).toBe(true);
  }
});

test("read-only SQL error is visible without losing the editing path", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "error-state.csv", mimeType: "text/csv", buffer: Buffer.from("segment,revenue\nNorth,10\n") });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "error-state.csv" })).toBeVisible();
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await page.locator(".monaco-editor").click();
  await page.keyboard.press("ControlOrMeta+A");
  await page.keyboard.insertText("DELETE FROM data");
  await page.getByRole("button", { name: /Run query/ }).click();
  await expect(page.getByRole("tabpanel", { name: "SQL Lab" })).toContainText(/read.only|blocked|not permitted|write/i);
  for (const width of [1440, 400]) {
    await page.setViewportSize({ width, height: 900 });
    await page.getByRole("heading", { name: "Query did not return a result." }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.resolve(`docs/analytical-workspaces-v1/screenshots/sql-error-dark-${width}.png`) });
  }
});

test("Visualize shows a useful loading state while a real suggestion is pending", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "loading-state.csv", mimeType: "text/csv", buffer: Buffer.from("segment,revenue\nNorth,10\nSouth,20\n") });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "loading-state.csv" })).toBeVisible();
  await page.route("**/visualize/datasets/*/suggest", async (route) => {
    const response = await route.fetch();
    await new Promise((resolve) => setTimeout(resolve, 1000));
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: /Visualize native/i }).click();
  await expect(page.getByRole("heading", { name: "Choosing a chart for this data" })).toBeVisible();
  await page.screenshot({ path: path.resolve("docs/analytical-workspaces-v1/screenshots/visualize-loading-dark-1440.png") });
  await page.setViewportSize({ width: 400, height: 900 });
  await page.screenshot({ path: path.resolve("docs/analytical-workspaces-v1/screenshots/visualize-loading-dark-400.png") });
  await expect(page.getByRole("img", { name: /(chart with|Histogram with)/ })).toBeVisible();
});
