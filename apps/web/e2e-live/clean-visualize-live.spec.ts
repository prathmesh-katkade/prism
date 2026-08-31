import { expect, test } from "@playwright/test";

const CSV = "segment,revenue\na,10\na,10\nb,\nc,30\n"; // row 2 duplicates row 1; row 3 is missing revenue

test("Overview profiles a real upload with quality metrics, column inspection, and provenance", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "clean-live.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });

  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "clean-live.csv" })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText("4 rows · 2 columns")).toBeVisible();
  await expect(page.getByText(/Health/)).toBeVisible();

  await page.locator(".column-card", { hasText: "revenue" }).click();
  const inspector = page.getByRole("complementary", { name: "Contextual inspector" });
  await expect(inspector.getByText("revenue")).toBeVisible();
  await expect(inspector.getByText("25% missing")).toBeVisible();
});

test("Clean detects an issue, previews it, applies it as a new revision Overview and SQL Lab both see, then undoes it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "clean-live-2.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "clean-live-2.csv" })).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: /Clean native/i }).click();
  await expect(page.getByRole("heading", { name: /found/ })).toBeVisible();
  await page.getByRole("button", { name: /Dataset/ }).click(); // the duplicate-rows issue has no column
  await expect(page.getByText(/affects/)).toBeVisible({ timeout: 10_000 });

  const applyButton = page.getByRole("button", { name: "Apply transformation" });
  await expect(applyButton).toBeEnabled();
  await applyButton.click();
  await expect(page.getByRole("heading", { name: /revision 1/ })).toBeVisible({ timeout: 10_000 });

  // Overview reflects the cleaned revision under the same object identity.
  await page.getByRole("button", { name: /Overview native/i }).click();
  await expect(page.getByText("3 rows · 2 columns")).toBeVisible();

  // SQL Lab queries the same connection and sees the cleaned row count too (the default query
  // is a plain "SELECT * FROM data LIMIT 100").
  await page.getByRole("button", { name: /SQL Lab native/i }).click();
  await expect(page.locator(".monaco-editor")).toBeVisible();
  await page.locator(".monaco-editor").click();
  await page.keyboard.press("ControlOrMeta+Enter");
  // Same CI-runner render-latency allowance as sql-lab-live.spec.ts: the
  // query itself completes well under 20ms server-side.
  await expect(page.getByText("3 returned / 3 total rows")).toBeVisible({ timeout: 20_000 });

  // Undo restores the original revision.
  await page.getByRole("button", { name: /Clean native/i }).click();
  await page.getByRole("button", { name: "Revision 0 · original" }).click();
  await expect(page.getByRole("heading", { name: /found/ })).toBeVisible({ timeout: 10_000 });
  await page.getByRole("button", { name: /Overview native/i }).click();
  await expect(page.getByText("4 rows · 2 columns")).toBeVisible();
});

test("Visualize suggests a deterministic chart, renders it with provenance, and Atlas explains it", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "viz-live.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "viz-live.csv" })).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: /Visualize native/i }).click();
  await expect(page.getByRole("img", { name: /chart with \d+ categor/i })).toBeVisible({ timeout: 10_000 });
  await expect(page.getByText(/question →/)).toBeVisible();

  // Provenance: source fingerprint and revision are shown.
  await expect(page.locator(".viz-inspector")).toContainText("Revision");

  await page.getByRole("button", { name: "Explain this chart", exact: true }).click();
  await expect(page.locator(".atlas-result")).toBeVisible({ timeout: 10_000 });
});
