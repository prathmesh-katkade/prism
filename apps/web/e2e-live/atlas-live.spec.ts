import { expect, test } from "@playwright/test";

const CSV = "segment,revenue\nNorth,10\nSouth,12\nNorth,14\n";
const externalStack = Boolean(process.env.PRISM_LIVE_E2E_BASE_URL);

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

  // Immersive shell: entering Atlas gets a dedicated identity/status strip
  // and a "Back to PRISM" escape -- real navigation, not a dead end.
  await expect(page.getByText("Immersive Cortex")).toBeVisible();
  await expect(page.getByRole("button", { name: "Back to PRISM" })).toBeVisible();

  // System status (Command Center: recent runs, model trust, certification)
  // is real but secondary -- collapsed by default so the Cortex stays the
  // default screen, expanded on demand via a real, keyboard-operable toggle.
  const systemToggle = page.getByRole("button", { name: "System status" });
  await expect(systemToggle).toHaveAttribute("aria-expanded", "false");
  await systemToggle.click();
  await expect(systemToggle).toHaveAttribute("aria-expanded", "true");

  // The isolated suite database has no production pointer. An explicit
  // external-stack run instead uses whatever the local backend actually
  // reports; both paths verify rendered state rather than inventing model or
  // certification facts in the browser.
  const commandCenter = page.getByLabel("Atlas command center");
  if (externalStack) {
    await expect(commandCenter.getByRole("heading", { level: 1 })).toBeVisible({ timeout: 10_000 });
  } else {
    await expect(commandCenter.getByText("NO PRODUCTION MODEL")).toBeVisible({ timeout: 10_000 });
    await expect(commandCenter.getByText("VERIFIED", { exact: true })).not.toBeVisible();
    await expect(commandCenter.getByText("Qwen", { exact: false })).not.toBeVisible();
  }

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

  // Bottom command bar: the primary input, Enter-to-submit, and a
  // truthfully disabled microphone -- voice input has no backend in this
  // phase, so it must be visibly unavailable, never fake recording.
  const micButton = page.getByRole("button", { name: /Microphone input is unavailable/ });
  await expect(micButton).toBeDisabled();
  const objectiveInput = page.getByLabel("Investigation objective");
  await objectiveInput.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByText(/deterministic first-pass assessment/)).toBeVisible({ timeout: 15_000 });

  // The result panel starts collapsed (the Cortex is the default screen)
  // and expands on demand to reveal the same real answer.
  const resultToggle = page.getByRole("button", { name: /Grounded answer ready/ });
  await expect(resultToggle).toHaveAttribute("aria-expanded", "false");
  await resultToggle.click();
  await expect(resultToggle).toHaveAttribute("aria-expanded", "true");

  // Command Core pipeline reflects this real run's own persisted state.
  // Real stage buttons (each now clickable, wired to the unified inspector)
  // still carry the same "is-reached" class on their <li>, not the button.
  const pipeline = page.getByLabel("Atlas request pipeline");
  await expect(pipeline.locator("li", { hasText: "Result" })).toHaveClass(/is-reached/);

  // The new central journey is sourced from this run's declared plan steps.
  // Selecting its real specialist keeps the plan and the Cortex projection
  // connected; it never manufactures a second live activity stream.
  const journey = page.getByLabel("Atlas active investigation journey");
  const profileJourneyStep = journey.getByRole("button", { name: /Profile the active dataset/ });
  await expect(profileJourneyStep).toHaveAttribute("aria-pressed", "true");

  // Specialists: only real roster identities, idle where this run never
  // assigned them a step -- never hidden, never animated as if working.
  const specialists = page.getByText("SPECIALISTS", { exact: true }).locator("..");
  await expect(specialists.getByText("Scout")).toBeVisible();
  await expect(specialists.getByText("completed").first()).toBeVisible();
  await expect(specialists.getByText("idle").first()).toBeVisible();
  await specialists.getByRole("button", { name: /Scout/ }).click();
  await expect(profileJourneyStep).toHaveAttribute("aria-pressed", "true");

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

  // Cortex: the real durable graph, now a 3D scene in a real browser (never
  // the jsdom/no-WebGL fallback), plus its accessible node chip row --
  // clicking a real node updates the detail panel with that node's actual
  // persisted facts, never an invented one.
  const cortex = page.getByLabel("Cortex real-state graph");
  await expect(cortex).toBeVisible();
  await expect(cortex.locator(".cortex-stage canvas")).toBeVisible();
  const cortexNodes = page.getByLabel("Cortex nodes");
  const runNodeButton = cortexNodes.getByRole("button", { name: "Focus Atlas run" });
  await expect(runNodeButton).toBeVisible();
  await runNodeButton.click();
  const cortexDetail = page.getByLabel("Selected Cortex node");
  await expect(cortexDetail).toBeVisible();
  await expect(cortexDetail.getByText("run", { exact: true })).toBeVisible();

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
  await page.getByRole("button", { name: "System status" }).click();
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

  // In the isolated database, no candidate has been certified. With a local
  // external stack, the same panels must surface its server-owned records;
  // this smoke deliberately makes no model/certification claim of its own.
  const commandCenterAfterReload = page.getByLabel("Atlas command center");
  await expect(commandCenterAfterReload.getByRole("heading", { name: "Operational Certification", exact: true })).toBeVisible();
  if (!externalStack) {
    await expect(commandCenterAfterReload.getByText("PASSED", { exact: true })).not.toBeVisible();
    await expect(commandCenterAfterReload.getByText(/No AtlasBench run recorded/)).toBeVisible();
    await expect(commandCenterAfterReload.getByText(/No live Operational Certification run recorded/)).toBeVisible();
  }
});
