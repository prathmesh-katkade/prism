import { mkdir, copyFile } from "node:fs/promises";
import path from "node:path";
import { expect, test } from "@playwright/test";

const output = path.resolve("docs/atlas/investigation-collaboration");
const API = "http://127.0.0.1:8000/api/v1";

test("capture Atlas investigation proof from isolated real records and labelled samples", async ({ page, request, browser }) => {
  await mkdir(output, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Atlas native/i }).click();
  await expect(page.getByRole("heading", { name: "What decision are you trying to make?" })).toBeVisible();
  await page.screenshot({ path: path.join(output, "05-empty-dark.png") });
  await page.getByRole("button", { name: "Open sample investigation" }).click();
  await page.getByRole("button", { name: /Collaboration/ }).click();
  await page.screenshot({ path: path.join(output, "02-collaboration-sample-objection.png") });
  await page.getByRole("button", { name: "Evidence" }).click();
  await page.getByRole("button", { name: /Illustrative cohort counts/ }).click();
  await page.screenshot({ path: path.join(output, "03-selected-sample-evidence.png") });
  await page.locator(".atlas-section").screenshot({ path: path.join(output, "04-sql-handoff-unavailable.png") });
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await page.screenshot({ path: path.join(output, "06-light-theme.png") });
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await page.screenshot({ path: path.join(output, "06-dark-theme.png") });

  const upload = await request.post(`${API}/overview/datasets`, { multipart: { file: { name: "atlas-proof.csv", mimeType: "text/csv", buffer: Buffer.from("segment,revenue\nNorth,10\nSouth,12\nNorth,14\n") } } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  const started = await request.post(`${API}/atlas/runs`, { data: { dataset_id: dataset.dataset_id, objective: "Use SQL to compare groups and review causal attribution." } });
  expect(started.status()).toBe(202);
  const run = await started.json() as { run_id: string };
  await expect.poll(async () => (await (await request.get(`${API}/atlas/runs/${run.run_id}`)).json() as { plan: { state: string } }).plan.state, { timeout: 20000 }).toBe("completed");
  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}&run_id=${encodeURIComponent(run.run_id)}&atlas_panel=history`);
  await expect(page.getByText(/deterministic first-pass assessment/)).toBeVisible();
  await page.screenshot({ path: path.join(output, "01-investigation-real-run.png") });

  const mobile = await browser.newContext({ viewport: { width: 400, height: 844 }, deviceScaleFactor: 1 });
  const mobilePage = await mobile.newPage();
  await mobilePage.goto("/");
  await mobilePage.getByRole("button", { name: /Atlas native/i }).click();
  await mobilePage.getByRole("button", { name: "Open sample investigation" }).click();
  await mobilePage.screenshot({ path: path.join(output, "07-mobile-sample.png") });
  await mobile.close();

  const large = await browser.newContext({ viewport: { width: 1440, height: 900 }, recordVideo: { dir: output, size: { width: 1440, height: 900 } } });
  const largePage = await large.newPage();
  await largePage.goto("/");
  await largePage.getByRole("button", { name: /Atlas native/i }).click();
  await largePage.getByRole("button", { name: "Open 200-task sample" }).click();
  await expect(largePage.locator(".atlas-work-map > li")).toHaveCount(200);
  await largePage.screenshot({ path: path.join(output, "08-large-sample-200-tasks.png") });
  await largePage.reload();
  await largePage.getByRole("button", { name: /Atlas native/i }).click();
  await largePage.getByRole("button", { name: "Open sample investigation" }).click();
  await largePage.getByRole("button", { name: "Investigation", exact: true }).click();
  await largePage.getByRole("button", { name: /Recorded output/ }).first().click();
  await largePage.getByRole("button", { name: /Collaboration/ }).click();
  await largePage.getByRole("button", { name: "Activity" }).click();
  await largePage.getByRole("button", { name: "Next event" }).click();
  await large.close();
  const recordedVideo = await largePage.video()?.path();
  if (recordedVideo) await copyFile(recordedVideo, path.join(output, "09-interaction.webm"));
});
