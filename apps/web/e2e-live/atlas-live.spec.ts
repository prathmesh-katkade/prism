import { expect, test } from "@playwright/test";

const CSV = "segment,revenue\nNorth,10\nSouth,12\nNorth,14\n";

/**
 * First Light, verified against a real FastAPI backend and a real browser --
 * not a mocked component test. This is the one spec in the repo that opens
 * the Atlas tab and drives a real investigation end to end, so every
 * assertion here is either a truthful-empty-state check (no production has
 * ever been promoted in this live suite's database) or a check against a
 * state this run actually produced -- nothing is asserted that the backend
 * did not really persist.
 */
test("ATLAS First Light: honest system state, a real investigation, and the recent-run browser all reflect real backend state", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: /Atlas native/i }).click();

  // Command Center renders and, since no candidate has ever been promoted in
  // this live database, truthfully says so -- never a hardcoded
  // "Qwen • VERIFIED • PRODUCTION" claim.
  const commandCenter = page.getByLabel("Atlas command center");
  await expect(commandCenter.getByText("NO PRODUCTION MODEL")).toBeVisible({ timeout: 10_000 });
  await expect(commandCenter.getByText("VERIFIED", { exact: true })).not.toBeVisible();
  await expect(commandCenter.getByText("Qwen", { exact: false })).not.toBeVisible();

  // Run activity: this live suite's specs share one backend and database,
  // so earlier spec files (or an earlier run of this one) may already have
  // left real Atlas runs in history -- this only asserts the panel shows a
  // truthful state (the honest-empty message, or real recorded rows),
  // never a fabricated "live" feed with neither.
  const activityPanel = commandCenter.getByText("Run activity").locator("..");
  await expect(activityPanel).toBeVisible();
  await expect(activityPanel).toContainText(/No Atlas investigation has been recorded yet|Could not reach|completed|running|failed|cancelled/);

  // A real dataset makes the Atlas workspace below usable.
  await page.getByRole("button", { name: /Overview native/i }).click();
  await page.setInputFiles("#overview-upload", { name: "atlas-live.csv", mimeType: "text/csv", buffer: Buffer.from(CSV) });
  await expect(page.getByLabel("Central tabbed workspace").getByRole("heading", { name: "atlas-live.csv" })).toBeVisible({ timeout: 10_000 });

  await page.getByRole("button", { name: /Atlas native/i }).click();
  const runButton = page.getByRole("button", { name: "Run investigation" });
  await expect(runButton).toBeEnabled();
  await runButton.click();
  await expect(page.getByText(/deterministic first-pass assessment/)).toBeVisible({ timeout: 15_000 });

  // Command Core pipeline reflects this real run's own persisted state.
  const pipeline = page.getByLabel("Atlas request pipeline");
  await expect(pipeline.getByText("Result")).toHaveClass(/is-reached/);

  // Specialists: only real roster identities, idle where this run never
  // assigned them a step -- never hidden, never animated as if working.
  const specialists = page.getByText("SPECIALISTS", { exact: true }).locator("..");
  await expect(specialists.getByText("Scout")).toBeVisible();
  await expect(specialists.getByText("completed").first()).toBeVisible();
  await expect(specialists.getByText("idle").first()).toBeVisible();

  // Tool activity: the real profiling tool this run actually executed.
  const toolTimeline = page.getByLabel("Atlas tool execution timeline");
  await expect(toolTimeline.getByText("overview.profile")).toBeVisible();
  await expect(toolTimeline.getByText("COMPLETED").first()).toBeVisible();

  // Guardrails: the server always records a decision (checked or blocked);
  // a plain profiling objective clears every check with nothing to flag.
  const guardrails = page.getByLabel("Atlas server guardrails");
  await expect(guardrails.getByText("checked")).toBeVisible();
  await expect(guardrails.getByText(/No findings/)).toBeVisible();

  // Evidence: real dataset-revision evidence this run actually recorded,
  // keyboard-expandable (native <details>/<summary>, not a custom widget).
  const evidence = page.getByLabel("Atlas evidence");
  await expect(evidence.getByText(/RECORD/)).toBeVisible();
  const firstEvidenceDetail = evidence.locator("details").first();
  await firstEvidenceDetail.locator("summary").focus();
  await page.keyboard.press("Enter");
  await expect(firstEvidenceDetail.getByText("Summary")).toBeVisible();

  // Memory/RAG: a brand-new run cites no prior memory and has received no
  // feedback -- the truthful empty state, not a hidden or broken panel.
  const memoryTrace = page.getByLabel("Atlas memory used by this run");
  await expect(memoryTrace.getByText(/No persisted ATLAS memory or feedback is linked to this run yet/)).toBeVisible();

  // Reload back to a fresh shell mount so the Command Center's recent-run
  // browser performs its own independent fetch, proving the run this test
  // just created is durably visible system-wide -- not only within the
  // workspace instance that created it.
  await page.reload();
  await page.getByRole("button", { name: /Atlas native/i }).click();
  const reloadedActivity = page.getByLabel("Atlas command center").getByText("Run activity").locator("..");
  // Newest-first: the run this test just created is the top row. Other
  // live-suite specs run sequentially in this same shared backend and may
  // leave their own earlier Atlas runs in history, so this does not assert
  // it is the *only* row -- only that it is the most recent one. The row is
  // a real <button> (native keyboard operability, no custom widget).
  const runRow = reloadedActivity.getByRole("button", { name: /Profile this dataset and identify the evidence needed for the next decision\./ }).first();
  await expect(runRow).toBeVisible({ timeout: 10_000 });
  await runRow.focus();
  await page.keyboard.press("Enter");
  await expect(reloadedActivity.getByLabel("Atlas request pipeline")).toBeVisible();
  await expect(reloadedActivity.getByLabel("Atlas specialist activity")).toBeVisible();

  // AtlasBench V2 and Operational Certification: no candidate has ever been
  // verified or certified in this live database, so both stay honestly
  // absent -- never a hardcoded run id, and never PASSED without evidence.
  const commandCenterAfterReload = page.getByLabel("Atlas command center");
  await expect(commandCenterAfterReload.getByText("Operational Certification", { exact: true })).toBeVisible();
  await expect(commandCenterAfterReload.getByText("PASSED", { exact: true })).not.toBeVisible();
  await expect(commandCenterAfterReload.getByText(/No AtlasBench run recorded/)).toBeVisible();
});
