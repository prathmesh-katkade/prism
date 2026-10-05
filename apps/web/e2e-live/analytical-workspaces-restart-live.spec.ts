import { expect, test } from "@playwright/test";

// Run after analytical-workspaces-connected-live.spec.ts in a separate Playwright
// invocation with the same isolated history DB. Each invocation owns a fresh API
// process, so this verifies report and source restoration across a real restart.
test("reopen saved analytical report after a fresh API process starts", async ({ page }) => {
  test.skip(process.env.PRISM_LIVE_RESTART_PROOF !== "1", "Run in a second invocation after connected flow with the same isolated database.");
  await page.goto("/");
  await page.getByRole("button", { name: /Reports native/i }).click();
  await expect(page.getByRole("heading", { name: "Business review" })).toBeVisible();
  await expect(page.getByLabel("Report canvas").getByLabel(/Small multiples by segment/).getByRole("img")).toHaveCount(2);
  await expect(page.getByRole("heading", { name: "Reviewed source rows" })).toBeVisible();
  await expect(page.getByLabel("Report canvas")).toContainText("TABLE · REVISION 2");
  await page.getByText("Inspect previous table versions").click();
  await expect(page.getByLabel("Report canvas")).toContainText("revision 1 · 4 saved row(s)");
  await expect(page.getByLabel("Report canvas")).not.toContainText("Source unavailable");
});
