import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8000/api/v1";

async function seriousViolations(page: Page, selector: string) {
  await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
  return page.evaluate(async (rootSelector) => {
    const root = document.querySelector(rootSelector);
    if (!root) throw new Error(`Axe root was not found: ${rootSelector}`);
    const axe = (window as typeof window & { axe: { run(context: Element, options: object): Promise<{ violations: { id: string; impact: string | null }[] }> } }).axe;
    const result = await axe.run(root, { runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] } });
    return result.violations.filter((violation) => violation.impact === "serious" || violation.impact === "critical");
  }, selector);
}

test("Atlas record selection and shared inspector work in dark, light, and mobile layouts", async ({ page, request }, testInfo) => {
  const mobile = testInfo.project.name.includes("mobile");
  if (!mobile) await page.setViewportSize({ width: 1440, height: 900 });
  const upload = await request.post(`${API}/overview/datasets`, { multipart: { file: { name: "atlas-a11y.csv", mimeType: "text/csv", buffer: Buffer.from("segment,revenue\nNorth,10\nSouth,12\n") } } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  const started = await request.post(`${API}/atlas/runs`, { data: { dataset_id: dataset.dataset_id, objective: "Profile and review this dataset." } });
  expect(started.status()).toBe(202);
  const run = await started.json() as { run_id: string };
  await expect.poll(async () => (await (await request.get(`${API}/atlas/runs/${run.run_id}`)).json() as { plan: { state: string } }).plan.state, { timeout: 20000 }).toBe("completed");

  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}&run_id=${encodeURIComponent(run.run_id)}&atlas_panel=history`);
  const atlas = page.getByLabel("Atlas investigation workspace");
  await expect(atlas).toBeVisible();
  await expect(atlas.getByText("Supporting evidence not linked.")).toBeVisible();
  expect(await seriousViolations(page, ".atlas-investigation")).toEqual([]);
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  expect(await seriousViolations(page, ".atlas-investigation")).toEqual([]);

  await atlas.getByRole("button", { name: /Recorded output/ }).first().click();
  if (mobile) {
    const drawer = page.getByRole("dialog", { name: "Selected Atlas record" });
    await expect(drawer).toBeVisible();
    await expect(drawer).toContainText("Recorded in run");
    expect(await seriousViolations(page, ".atlas-mobile-inspector-layer")).toEqual([]);
    await page.keyboard.press("Escape");
    await expect(drawer).not.toBeVisible();
  } else {
    await expect(page.getByLabel("Contextual inspector")).toContainText("Recorded in run");
  }
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
});

test("statistical clarification and evidence remain accessible at narrow width", async ({ page, request }, testInfo) => {
  const mobile = testInfo.project.name.includes("mobile");
  if (!mobile) await page.setViewportSize({ width: 400, height: 844 });
  const upload = await request.post(`${API}/overview/datasets`, { multipart: { file: {
    name: "atlas-mobile-stat.csv", mimeType: "text/csv", buffer: Buffer.from("exposure,outcome\n1,2\n2,4\n3,6\n4,8\n5,10\n"),
  } } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}`);
  await page.getByRole("button", { name: /Atlas native/i }).click();
  await page.getByLabel("Investigation objective").fill("Test correlation significance");
  await page.getByRole("button", { name: "Run investigation" }).click();
  await expect(page.getByRole("heading", { name: "Stat needs a clarification" })).toBeVisible({ timeout: 20_000 });
  expect(await seriousViolations(page, ".atlas-investigation")).toEqual([]);
  await page.getByLabel("Statistical method").selectOption("pearson");
  await page.getByLabel("Outcome or first comparison column").selectOption("exposure");
  await page.getByLabel("Group or second comparison column").selectOption("outcome");
  await page.getByLabel("Study design").selectOption("linear_association");
  await page.getByRole("button", { name: "Save answer and resume" }).click();
  await expect(page.getByRole("button", { name: "Inspect supporting statistical evidence" })).toBeVisible({ timeout: 20_000 });
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  expect(await seriousViolations(page, ".atlas-investigation")).toEqual([]);
  if (mobile) await page.screenshot({ path: "docs/atlas/production-investigation-v1/verification/atlas-stat-mobile.png", fullPage: true });
});
