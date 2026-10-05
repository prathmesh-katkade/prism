import { expect, test } from "@playwright/test";

const API = `${process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000"}/api/v1`;
const CSV = "segment,revenue\nNorth,10\nSouth,12\nNorth,14\n";

test("Atlas shows a real run, preserves its refusal, and persists a targeted human intervention", async ({ page, request }) => {
  const upload = await request.post(`${API}/overview/datasets`, { multipart: { file: { name: "atlas-investigation.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}`);
  await page.getByRole("button", { name: /Atlas native/i }).click();
  await expect(page.getByRole("heading", { name: "What decision are you trying to make?" })).toBeVisible();
  await expect(page.getByLabel("PRISM workspace navigation")).toBeVisible();
  await expect(page.getByLabel("Open workspace tabs")).toBeVisible();

  await page.getByLabel("Investigation objective").fill("Use SQL to compare groups and test causal attribution.");
  await page.getByRole("button", { name: "Run investigation" }).click();
  await expect(page.getByText(/deterministic first-pass assessment/)).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Supporting evidence not linked.")).toBeVisible();
  await expect(page.getByRole("button", { name: /Execution refusal/ }).first()).toBeVisible();
  await page.getByRole("button", { name: "Collapse details" }).click();
  await expect(page.getByRole("button", { name: /Execution refusal/ }).first()).toBeVisible();

  const firstOutput = page.getByRole("button", { name: /Recorded output/ }).first();
  await firstOutput.click();
  await expect(page.getByLabel("Contextual inspector")).toContainText("Recorded in run atlas_");
  await page.getByRole("button", { name: /Collaboration/ }).click();
  await expect(page.getByRole("heading", { name: "Work map" })).toBeVisible();
  await expect(page.getByText("Persisted specialist contributions and human notes")).toBeVisible();
  await expect(page.getByText(/Model: none/).first()).toBeVisible();
  await page.getByLabel("Challenge a selected record or request a check").fill("Check exclusions before relying on the profile.");
  await page.getByRole("button", { name: "Save intervention" }).click();
  await expect(page.getByText("Saved as a human note. No check was executed.")).toBeVisible();
  await expect(page.getByText("Check exclusions before relying on the profile.")).toBeVisible();

  await page.getByRole("button", { name: "Activity" }).click();
  await expect(page.getByText(/Historical state reconstruction is unavailable/)).toBeVisible();
  await page.getByRole("button", { name: "Next event" }).click();
  await expect(page.getByText(/Event 2 of/)).toBeVisible();
  await page.getByRole("button", { name: "Evidence" }).click();
  await expect(page.getByRole("button", { name: /Open exact query in SQL Lab/ })).toBeDisabled();
});
