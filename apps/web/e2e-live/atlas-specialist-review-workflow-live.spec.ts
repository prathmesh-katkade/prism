import { expect, test } from "@playwright/test";

const API = "http://127.0.0.1:8000/api/v1";
const PROOF = "docs/atlas/production-investigation-v1/verification";

test.use({ video: "on" });

async function runOnceAndCheckForReview(request: import("@playwright/test").APIRequestContext, attempt: number): Promise<{ runId: string; datasetId: string } | null> {
  const upload = await request.post(`${API}/overview/datasets`, { multipart: {
    file: { name: `review-recording-${attempt}.csv`, mimeType: "text/csv", buffer: Buffer.from("region,revenue\nwest,10\neast,7\nwest,5\n") },
  } });
  expect(upload.ok()).toBe(true);
  const dataset = await upload.json() as { dataset_id: string };
  const started = await request.post(`${API}/atlas/runs`, { data: {
    dataset_id: dataset.dataset_id, objective: "Sum revenue by region using SQL",
    sql_analysis: { aggregate: "sum", measure: "revenue", group_by: "region" },
  } });
  expect(started.status()).toBe(202);
  const run = await started.json() as { run_id: string };
  let finalRun: { plan: { state: string }; messages: { origin: string }[]; events: { type: string; step_id: string | null }[] } | null = null;
  // plan.state flips to "completed" before the best-effort, non-blocking Atlas
  // synthesis review attempt runs; wait for that attempt's own terminal event
  // (always appended, success or failure) rather than just "completed", or
  // this check races a review call that simply hasn't finished yet.
  for (let i = 0; i < 300; i += 1) {
    finalRun = await (await request.get(`${API}/atlas/runs/${run.run_id}`)).json();
    const settled = finalRun.events.some((event) => event.type === "step_completed" && event.step_id === "synthesis");
    if (finalRun.plan.state === "completed" && settled) break;
    if (finalRun.plan.state !== "completed" && finalRun.plan.state !== "running") break;
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  if (!finalRun || finalRun.plan.state !== "completed") return null;
  if (!finalRun.messages.some((message) => message.origin === "model")) return null;
  return { runId: run.run_id, datasetId: dataset.dataset_id };
}

test("real workflow recording: computation, specialist objection, evidence inspection, exact-query handoff", async ({ page, request }) => {
  test.skip(process.env.PRISM_AI_PROVIDER !== "ollama", "Requires PRISM_AI_PROVIDER=ollama for a genuine specialist review.");

  // The production model's bounded review is real inference, not a scripted
  // fixture; retry a fresh run a few times in the rare case a given run's
  // review comes back ungrounded (recorded as review_unavailable) rather
  // than a grounded claim/objection, so the recording reliably shows one.
  let result: { runId: string; datasetId: string } | null = null;
  for (let attempt = 0; attempt < 4 && !result; attempt += 1) {
    result = await runOnceAndCheckForReview(request, attempt);
  }
  expect(result, "A real specialist review did not produce a grounded contribution after several attempts").not.toBeNull();
  const { runId, datasetId } = result!;

  await page.goto(`/?dataset_id=${encodeURIComponent(datasetId)}&run_id=${encodeURIComponent(runId)}&atlas_panel=history`);
  // 1. Computation: the deterministic SQL result.
  await expect(page.getByText(/Recorded SQL result run_/)).toBeVisible({ timeout: 20_000 });
  await page.screenshot({ path: `${PROOF}/specialist-review-01-computation.png`, fullPage: true });

  // 2. Specialist contribution and objection.
  await page.getByRole("button", { name: /Collaboration/ }).click();
  const exchange = page.locator(".atlas-section", { hasText: "Recorded exchange" });
  await expect(exchange.getByText("proposal | model").or(exchange.getByText("objection | model")).first()).toBeVisible({ timeout: 10_000 });
  await page.screenshot({ path: `${PROOF}/specialist-review-02-contribution-and-objection.png`, fullPage: true });

  // 3. Evidence inspection.
  await page.getByRole("button", { name: "Evidence", exact: true }).click();
  await page.getByRole("button", { name: /SQL Lab aggregate/ }).click();
  await expect(page.getByText("Recorded original; edits in SQL Lab create a draft.")).toBeVisible();
  await page.screenshot({ path: `${PROOF}/specialist-review-03-evidence-inspection.png`, fullPage: true });

  // 4. Exact-query handoff.
  await page.getByRole("button", { name: "Open exact query in SQL Lab" }).click();
  await expect(page.getByRole("heading", { name: "Write against evidence, not assumptions." })).toBeVisible();
  await expect(page.locator(".monaco-editor")).toContainText('SUM("revenue")');
  await page.screenshot({ path: `${PROOF}/specialist-review-04-exact-query-handoff.png`, fullPage: true });

  const video = page.video();
  await page.close();
  await video?.saveAs(`${PROOF}/specialist-review-workflow.webm`);
});
