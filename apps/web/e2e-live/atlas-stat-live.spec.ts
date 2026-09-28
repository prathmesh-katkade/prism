import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8000/api/v1";

test("missing statistical inputs wait durably and resume with a recorded result", async ({ page, request }) => {
  const upload = await request.post(`${API}/overview/datasets`, { multipart: {
    file: { name: "atlas-stat.csv", mimeType: "text/csv", buffer: Buffer.from("exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n") },
  } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}`);
  await page.getByRole("button", { name: /Atlas native/i }).click();
  await page.getByLabel("Investigation objective").fill("Test correlation significance");
  await page.getByRole("button", { name: "Run investigation" }).click();
  await expect(page.getByRole("heading", { name: "Stat needs a clarification" })).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("Waiting for your statistical inputs; completed evidence is saved.")).toBeVisible();
  await page.getByLabel("Statistical method").selectOption("pearson");
  await page.getByLabel("Outcome or first comparison column").selectOption("exposure");
  await page.getByLabel("Group or second comparison column").selectOption("outcome");
  await page.getByLabel("Study design").selectOption("linear_association");
  await page.getByRole("button", { name: "Save answer and resume" }).click();
  await expect(page.getByRole("button", { name: /Atlas completed.*Stats Lab pearson:/ })).toBeVisible({ timeout: 20_000 });
  await page.getByRole("button", { name: "Inspect supporting statistical evidence" }).click();
  await page.getByRole("button", { name: /Stats Lab pearson/ }).click();
  await expect(page.getByRole("heading", { name: "Recorded statistical computation" })).toBeVisible();
  await expect(page.getByText(/analyzed: 5; excluded: 0/)).toBeVisible();
  await page.screenshot({ path: "docs/atlas/production-investigation-v1/verification/atlas-stat-evidence.png", fullPage: true });
});
