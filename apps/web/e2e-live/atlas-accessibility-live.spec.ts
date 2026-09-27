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
