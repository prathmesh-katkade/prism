import { expect, test } from "@playwright/test";

test("Atlas shell remains usable at the supported mobile viewport", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Atlas native/i }).click();
  const atlas = page.getByLabel("Atlas investigation workspace");
  await expect(atlas).toBeVisible();
  await expect(atlas.getByRole("heading", { name: "What decision are you trying to make?" })).toBeVisible();
  await expect(page.getByLabel("PRISM workspace navigation")).toBeVisible();
  await atlas.getByRole("button", { name: "Open sample investigation" }).click();
  await expect(atlas.getByText("Sample · no execution")).toBeVisible();

  const viewportOverflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(viewportOverflow).toBeLessThanOrEqual(1);
});
