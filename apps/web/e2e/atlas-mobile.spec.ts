import { expect, test } from "@playwright/test";

test("Atlas shell remains usable at the supported mobile viewport", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Atlas native/i }).click();
  const atlas = page.locator(".atlas-immersive");
  await expect(atlas).toBeVisible();
  await expect(page.getByRole("button", { name: "System status" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Back to PRISM" })).toBeVisible();

  const viewportOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(viewportOverflow).toBeLessThanOrEqual(1);
});
