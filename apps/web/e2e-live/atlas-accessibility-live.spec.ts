import { expect, test, type Page } from "@playwright/test";

const API = "http://127.0.0.1:8000/api/v1";
const CSV = "segment,revenue\nNorth,10\nSouth,12\nNorth,14\n";

type AxeViolation = { id: string; impact: string | null; help: string; nodes: unknown[] };

async function seriousAxeViolations(page: Page, selector: string): Promise<AxeViolation[]> {
  await page.addScriptTag({ path: "node_modules/axe-core/axe.min.js" });
  return page.evaluate(async (rootSelector: string) => {
    const root = document.querySelector(rootSelector);
    if (!root) throw new Error(`Axe root was not found: ${rootSelector}`);
    const axe = (window as typeof window & {
      axe: { run(context: Element, options: object): Promise<{ violations: AxeViolation[] }> };
    }).axe;
    const result = await axe.run(root, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] },
    });
    return result.violations.filter((item) => item.impact === "serious" || item.impact === "critical");
  }, selector);
}

test("Atlas deep link is accessible in dark and light themes on desktop and mobile", async ({ page, request }, testInfo) => {
  if (!testInfo.project.name.includes("mobile")) {
    await page.setViewportSize({ width: 1440, height: 900 });
  }
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("requestfailed", (requestFailure) => {
    // The Command Center's stale-response protection (see use-atlas-resource.ts)
    // deliberately aborts an in-flight fetch when its context is superseded
    // (a re-render fetches a newer path, or the owning component unmounts) --
    // that is correct, intended behavior, not a network failure to catch here.
    if (requestFailure.failure()?.errorText === "net::ERR_ABORTED") return;
    failedRequests.push(requestFailure.url());
  });

  const upload = await request.post(`${API}/overview/datasets`, {
    multipart: { file: { name: "atlas-a11y.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) } },
  });
  expect(upload.ok()).toBe(true);
  const dataset = (await upload.json()) as { dataset_id: string };
  const started = await request.post(`${API}/atlas/runs`, {
    data: { dataset_id: dataset.dataset_id, objective: "Profile this dataset and preserve the evidence." },
  });
  expect(started.status()).toBe(202);
  const run = (await started.json()) as { run_id: string };

  await expect
    .poll(async () => {
      const response = await request.get(`${API}/atlas/runs/${run.run_id}`);
      const body = (await response.json()) as { plan: { state: string } };
      return body.plan.state;
    }, { timeout: 20_000 })
    .toBe("completed");

  await page.goto(`/?dataset_id=${encodeURIComponent(dataset.dataset_id)}&run_id=${encodeURIComponent(run.run_id)}&atlas_panel=history&atlas_focus=${encodeURIComponent(`run:${run.run_id}`)}`);
  const atlas = page.locator(".atlas-immersive");
  await expect(atlas).toBeVisible();
  await expect(page.getByLabel("Atlas command center")).toBeVisible();
  await expect(page.getByLabel("Cortex real-state graph")).toBeVisible();
  await expect(page.getByLabel("Cortex real-state graph").getByLabel("Cortex nodes")).toBeVisible();
  await expect(page.getByLabel("Selected Cortex node")).toContainText("run");

  const darkViolations = await seriousAxeViolations(page, ".atlas-immersive");
  expect(darkViolations, JSON.stringify(darkViolations, null, 2)).toEqual([]);

  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.locator("main.theme-light")).toBeVisible();
  const lightViolations = await seriousAxeViolations(page, ".atlas-immersive");
  expect(lightViolations, JSON.stringify(lightViolations, null, 2)).toEqual([]);

  if (testInfo.project.name.includes("mobile")) {
    await page.getByRole("button", { name: "Inspector" }).click();
    const inspector = page.getByRole("dialog", { name: "Atlas context inspector" });
    await expect(inspector).toBeVisible();
    const inspectorViolations = await seriousAxeViolations(page, ".atlas-inspector-scrim");
    expect(inspectorViolations, JSON.stringify(inspectorViolations, null, 2)).toEqual([]);
    const inspectorWidth = await inspector.evaluate((element) => ({ client: element.clientWidth, scroll: element.scrollWidth }));
    expect(inspectorWidth.scroll).toBeLessThanOrEqual(inspectorWidth.client + 1);
    await inspector.getByRole("button", { name: "Close inspector" }).click();
  }

  const overflow = await atlas.evaluate((root) => {
    const documentElement = document.documentElement;
    return {
      documentClientWidth: documentElement.clientWidth,
      documentScrollWidth: documentElement.scrollWidth,
      rootClientWidth: root.clientWidth,
      rootScrollWidth: root.scrollWidth,
    };
  });
  expect(overflow.documentScrollWidth).toBeLessThanOrEqual(overflow.documentClientWidth + 1);
  expect(overflow.rootScrollWidth).toBeLessThanOrEqual(overflow.rootClientWidth + 1);
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
});
