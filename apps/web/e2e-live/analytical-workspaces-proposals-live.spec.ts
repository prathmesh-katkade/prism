import { expect, test } from "@playwright/test";

test("installed local model offers a reviewed SQL draft without running it", async ({ page }) => {
  test.skip(process.env.PRISM_AI_PROVIDER !== "ollama", "Live local-model provider is opt-in.");
  test.setTimeout(90_000);
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", {
    name: "proposal-safe.csv", mimeType: "text/csv",
    buffer: Buffer.from("segment,revenue\nNorth,10\nSouth,20\n"),
  });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "proposal-safe.csv" })).toBeVisible();
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  const panel = page.getByRole("region", { name: "sql local model proposal" });
  await panel.getByRole("textbox", { name: "What would you like to do?" }).fill("Count rows by segment");
  await panel.getByRole("button", { name: "Request proposal" }).click();
  await expect(panel.getByText("Local model draft")).toBeVisible({ timeout: 45_000 });
  await expect(panel).toContainText("SELECT");
  await expect(panel).toContainText("Source ds_");
  await panel.getByRole("button", { name: "Review in workspace" }).click();
  await expect(page.locator(".monaco-editor .view-lines")).toContainText("SELECT");
  await expect(page.getByText("100 returned / 100 total rows")).toHaveCount(0);
});
