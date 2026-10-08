import { expect, test } from "@playwright/test";

const API = `${process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000"}/api/v1`;

function largeIdentifierCsv(rows: number): string {
  const lines = ["invoice_id,amount"];
  for (let i = 0; i < rows; i += 1) lines.push(`INV-${String(i).padStart(6, "0")},${10 + (i % 50)}.5 kg`);
  return lines.join("\n") + "\n";
}

// Proves SERVER-side cancellation, not merely a fast UI return. Opt-in only: the
// production default (PRISM_PATTERN_VERIFY_TEST_DELAY_MS unset/zero) makes a
// full scan too fast to reliably interrupt mid-flight over real network/browser
// latency, so without the delay this test would be flaky by construction rather
// than a genuine proof - it skips itself rather than quietly passing on luck.
//
// Reproduce: PRISM_PATTERN_VERIFY_TEST_DELAY_MS=60 npm run test:e2e:live -- pattern-review-verify-cancellation-live.spec.ts
test("cancelling a full verification stops the server's own scan loop, not just the UI", async ({ page, request }) => {
  test.skip(!process.env.PRISM_PATTERN_VERIFY_TEST_DELAY_MS || process.env.PRISM_PATTERN_VERIFY_TEST_DELAY_MS === "0",
    "Requires PRISM_PATTERN_VERIFY_TEST_DELAY_MS set on the API process - see this file's header for the reproduce command.");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: /Overview native/i }).click();
  const [uploadResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().endsWith("/api/v1/overview/datasets") && response.request().method() === "POST"),
    page.setInputFiles("#overview-upload", { name: "verify-cancellation.csv", mimeType: "text/csv", buffer: Buffer.from(largeIdentifierCsv(20_000)) }),
  ]);
  const { dataset_id: datasetId } = await uploadResponse.json() as { dataset_id: string };
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "verify-cancellation.csv" })).toBeVisible();

  await page.getByRole("button", { name: /Clean native/i }).click();
  const findingButton = page.locator(".clean-issues .finding-list button").filter({ has: page.locator("strong", { hasText: /^invoice_id$/ }) }).first();
  await expect(findingButton).toBeVisible({ timeout: 15_000 });
  await findingButton.click();
  await expect(page.locator(".pattern-family-list li").first()).toBeVisible();

  const uiCancelStarted = Date.now();
  const [startResponse] = await Promise.all([
    page.waitForResponse((response) => response.url().includes("/verify/start") && response.request().method() === "POST"),
    page.getByRole("button", { name: "Verify all rows" }).click(),
  ]);
  const { job_id: jobId, rows_total: rowsTotal } = await startResponse.json() as { job_id: string; rows_total: number };
  expect(rowsTotal).toBe(20_000);

  // Wait for the UI to show real, non-zero progress before cancelling - this
  // confirms the job was genuinely mid-scan, not cancelled before it started.
  await expect(page.getByRole("button", { name: /Verifying [1-9][\d,]* of 20,000…/ })).toBeVisible({ timeout: 10_000 });

  const cancelButton = page.getByRole("button", { name: "Cancel" });
  await expect(cancelButton).toBeVisible();
  await cancelButton.click();
  await expect(cancelButton).toBeHidden(); // UI cancellation latency (separate from the server proof below)
  const uiCancelResponseMs = Date.now() - uiCancelStarted;

  // The decisive, server-side proof: poll the job directly over the API,
  // independent of whatever the UI displays, until it reaches a terminal state.
  let status: { state: string; rows_checked: number; rows_total: number; finding: unknown } | null = null;
  for (let attempt = 0; attempt < 100; attempt += 1) {
    const response = await request.get(`${API}/clean/datasets/${datasetId}/patterns/columns/invoice_id/verify/jobs/${jobId}`);
    status = await response.json();
    if (status!.state !== "running") break;
    await page.waitForTimeout(100);
  }
  expect(status).not.toBeNull();
  expect(status!.state).toBe("cancelled");
  expect(status!.finding).toBeNull(); // a cancelled job never publishes verified=true
  // The scan loop itself stopped short of the full 20,000 rows - this is what a
  // client-side AbortController alone could never prove, since it only stops the
  // browser from listening, not the server from working.
  expect(status!.rows_checked).toBeLessThan(20_000);

  console.log("PRISM_VERIFY_CANCELLATION_PROOF", JSON.stringify({ ui_cancel_response_ms: uiCancelResponseMs, server_rows_checked_at_cancel: status!.rows_checked, server_rows_total: status!.rows_total }));
});
