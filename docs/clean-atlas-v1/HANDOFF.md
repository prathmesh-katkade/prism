# Clean + Atlas presentation — handoff

One durable file, updated at every checkpoint rather than left to scatter
across phase docs. Read this first in any new session.

## Current continuation — 2026-10-25

Focused visual-acceptance pass against the approved references (05, 01, 06,
and 03's composition only - its mascot is superseded). Full detail, evidence
paths, and an honest "what remains open" list are in
[`acceptance-20261025.md`](acceptance-20261025.md) - read that first, this is
a pointer. In short: found and fixed three real instances of the exact
"white-primary"/unstyled-button anti-pattern the brief named (one of them -
Plan review's "Approve included steps" - had *no* styling at all, the
browser's own default button bevel), all backed by `getComputedStyle()`
evidence rather than visual guessing (two other buttons that looked wrong in
a screenshot thumbnail turned out, on direct inspection, to already be
correct - reported, not hidden). Partway through, Claude Code's own
memory-pressure guard killed the dev server; per its explicit instruction it
was not restarted, so the step-marker composition gap (circle + connecting
line vs. the current flat colour bar) and an after-state screenshot are
honestly left open rather than guessed at blind. Rebuilt the desktop app and
ran MySQL parity against a fresh disposable instance (31/31) independent of
the dev server; re-confirmed and formalized the controlled baseline for the
two full-suite pytest failures (1390/1390 clean with it).

## Current continuation — 2026-10-24

Claude (this session) took over from Codex, who left six tracked source/test
files with intentional, uncommitted continuation work on top of the pushed
`5021448` checkpoint (verified clean, CI green at that SHA; remote main
unchanged at `c9472ca`). The current acceptance table is
[`acceptance-20261024.md`](acceptance-20261024.md). Ending checkpoint:
`bcb1aad87734e479e238f69e970d830fcadd3ef6`, pushed.

**Reviewed and landed the six Codex files** (schema-constrained `clean`
proposal responses with an explicit 4-shape `anyOf` and `additionalProperties:
false`; server-side rejection of a model-chosen ambiguous `date_format` and of
a `category_mapping` inventing a source value; the SQLGlot-dialect
sidecar-packaging fix; the plan-review left-rail stepper; Saved-recipes
collapsed-by-default). Found and fixed one regression before landing: the
Saved-recipes auto-open removal broke a real e2e-live assertion in
`analytical-workspaces-connected-live.spec.ts` that expected the just-saved
recipe visible with no disclosure-opening step. This batch of work was
committed as `a269938` earlier in this session.

**One real bug found and fixed this round, via live verification against the
rebuilt desktop app** (not assumed, not from code reading alone): the
left-rail's own "Model proposal" vs. "Deterministic rule" tag — the exact
distinction this brief's work order requires — never actually fired.
`addDraftStep` read `pendingStepReason.current` *inside* the `setStepReasons`
updater function; React invokes that updater after the synchronous
`pendingStepReason.current = null` on the next line had already run, so the
ref was always null by the time it was read, and every step (Atlas-proposed
or hand-built) landed in plan review tagged "Deterministic rule". Found by
building a step from a real Atlas proposal, opening Plan Review, and seeing
the wrong tag; confirmed the exact mechanism with a temporary debug trace
(`console.log` in both `onReview` and `addDraftStep`, later removed) showing
`pendingStepReason.current` held the real explanation text at the moment
`addDraftStep` ran but `stepReasons` ended up storing `null` for that step
anyway. Fixed by capturing the ref into a local (`const reason =
pendingStepReason.current`) before clearing it. Reverified clean on a second,
isolated repro (a fresh page load, a fresh Atlas proposal, immediately into
Plan Review) and added a regression test
(`clean-workspace.test.tsx`: "tags a step added from an Atlas proposal as a
model proposal in plan review, distinct from a manually built step").

**Structured proposal verification**: six real requests against the real
local Ollama instance (`qwen2.5:3b`), covering explanation-only (1), valid
structured proposals (3: drop_duplicates, trim_whitespace, category_mapping),
a correctly-triggered clarification (1: ambiguous `signup_date`), and a
correct rejection (1: mapping an invented "Nroth" value - the server
returned `provider: "unavailable"`, confirming the live validation fires
against a real model's actual output, not just the unit-test fixtures). No
truncated response was observed. Recorded in
`evidence/milestone-20261024/structured-proposal-probe.json`.

**Packaged SQL join inspection, confirmed in the frozen sidecar**: a real
two-source `localjoin:` query (`INNER JOIN ... ON data.region = joined.region`)
against a 12-row dataset and a 5-row lookup table returned exactly 4 matched
rows, 8 unmatched left, 2 unmatched right - predicted independently before
running the query and confirmed exact. `unsupported_notes: []` in the real
response confirms the SQLGlot-dialect packaging fix holds in the actual
frozen binary, not just the dev environment. Recorded in
`evidence/milestone-20261024/packaged-sql-join-evidence.json`.

**Full connected release-proof chain**, in the real app against its real
packaged sidecar (`fixture.csv`, revision 0 -> 2): asked Atlas a real
question, got a real structured category-mapping proposal, inspected its
evidence disclosure, handed it off to Step settings, added it as step 1
(model-authored); built step 2 by hand (trim whitespace, deterministic);
opened Plan Review and confirmed the "Model proposal"/"Deterministic rule"
distinction rendered correctly (the bug above, now fixed); approved both
steps atomically to revision 2; ran the default SQL Lab query against
revision 2 (12/12 rows, cleaned region values); opened Visualize
(`amount by region`, correct auto-measure selection on the numeric `amount`
field rather than an identifier column); split into small multiples by
`customer_id` and drilled into one panel's contributing rows (2 rows for
`customer_id = C1001, region = Bengaluru`, matching the known duplicate-row
fixture exactly); hand-verified the chart's own aggregation
(Bengaluru sum = 120.5 + 80 + 95.25 + 120.5 = 416.25, matched exactly); saved
the chart with its explicit source revision/fingerprint; created a named
report, added the saved chart, and added an explanatory note. Separately,
earlier in the same session, a deliberately ambiguous manually-built
`convert_type` step (no `date_format`) was confirmed to still show "Needs
clarification"/"Excluded until you decide" in Plan Review - the Oct 22
clarification-exclusion fix still holds against this round's rebuilt app and
the new left-rail.

**Native verification**: the rebuilt desktop app (`app.exe`) was running
throughout, with its real packaged sidecar (`prism-api.exe`) as a confirmed
child process (`Get-CimInstance Win32_Process`). Evaluated Tauri's documented
Windows WebDriver route per the brief's instruction: `tauri-driver.exe` is
installed (`C:\Users\Admin\.cargo\bin\tauri-driver.exe`), but the WebDriver
backend it wraps on Windows, `msedgedriver.exe` matching the installed
WebView2 runtime (155.0.4283.62), is not present and would need to be
downloaded from Microsoft - not done autonomously, since fetching and
executing a new binary requires the owner's explicit confirmation. Raw
native-window UI automation therefore remains unverified this round; the
release-proof chain above used the established matched-origin browser method
(the identical frontend bundle against the same real sidecar) instead.

**Gates, full required set**: web lint (0 warnings), typecheck, a11y
baseline, 149 unit tests across 19 files, and the production build all
clean. Backend ruff and mypy (CI's exact `phase-1-python` flags), boundaries,
`contract:check`, and the local secrets scan all clean. CI-selected pytest
(`tests/api tests/contracts tests/migration tests/overview tests/sql_lab`,
the exact `.github/workflows/ci.yml` invocation) against a cleared runtime
store: 780 passed, 7 skipped, 0 failed. Full repo pytest (`tests/`): 1388
passed, 7 skipped, **2 failed** -
`test_atlas_combined_sft_dataset.py::test_combined_sft_dataset_route_includes_synthetic_teacher_end_to_end`
and
`test_phase8c_lineage_traversal.py::test_ancestors_never_cross_into_a_different_fingerprint_sharing_the_same_revision_number`.
Investigated rather than dismissed: both tests import the real, module-level
`prism_api.analytical_objects.registry` singleton directly rather than
through an isolated per-test database, so when no
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` override is set they fall back to a
shared, persistent on-disk default (`.prism/runtime/analytical-history.sqlite`,
gitignored, accumulated across many past local sessions) and register
literal, non-unique IDs (`fp_child`, `ds_fp_test`) against it - a second run,
or a run where some other test touches those same IDs first, collides.
Confirmed via `git diff` against this round's verified starting point that
neither implicated file has changed, so this is pre-existing and not a
regression from any reviewed or authored work this round; confirmed CI itself
never hits it, since CI's own pytest invocation is scoped to exactly the five
directories verified clean above. Not fixed in code (an isolation fix for
these two tests is a separate, unscoped change); the local runtime store was
cleared to get a true reading rather than relabelling the finding as flaky.
MySQL live-parity suite skipped (no disposable MySQL instance running this
session); the SQLite path is exercised throughout the rest of the suite.

Desktop app `app.exe` left running for owner inspection (packaged sidecar
`prism-api.exe` as its child process). Pushed to
`prism/clean-pattern-review-v1` as `bcb1aad`; PR #18 (open, targeting `main`)
picked up a fresh CI run on push - check its result before merging or
tagging. No merge or tag performed this round, per the brief's explicit
instruction to wait for owner visual acceptance.

## Current continuation — 2026-10-22

Claude resumed from pushed feature SHA `2a4afe9f4dc71ff9729c74ff123d763d72606206`
(verified clean, CI green at that exact SHA) and remote main unchanged at
`c9472ca822293e8767ec7d8dc617e8be964232d8`, per the Oct 22 delivery brief's
Clean/Atlas visual-acceptance milestone (Oct 22-28). The current acceptance
table is [`acceptance-20261022.md`](acceptance-20261022.md) - read that for
the structured requirement-by-requirement status; this entry covers what
happened and why, including two real bugs this round's own new feature work
surfaced and fixed.

**Reference composition finished this round** (all three concrete gaps named
in `reference-implementation-spec-20261012.md` that were still open):
1. Clean's header workflow strip is now a numbered circular stepper matching
   references 05/06's geometry (current stage filled, connecting lines)
   instead of the old flat pill row.
2. A real "Suggested mapping" card in the recipe pane groups a category
   column's own already-fetched distinct values by trimmed, case-insensitive
   spelling - explicitly labeled "Rule-based", never claiming model
   involvement - with "Apply suggested grouping", matching reference 05/06's
   "Mapping proposal" card region.
3. **New**: `plan-review.tsx` - the approved "Review Atlas's cleaning plan"
   screen (reference #03). Every draft step gets a real why/example,
   Deterministic-rule/Model-proposal and Preview-checked/Needs-clarification
   tags, an Include toggle, real affected-row counts from the existing
   `recipe-draft/preview` endpoint, a "what stays unchanged" summary from
   real profile columns, and one explicit "Approve included steps" action.
   Deliberately reuses the existing recipe create -> preview -> apply chain
   verbatim (the same atomic, transactional, revision-bound publication every
   saved recipe already goes through) - **no new backend endpoint**, per the
   brief's own "inspect existing contracts first, reuse working capabilities"
   instruction.

**Two real bugs found and fixed, both via live verification against a real
multi-step fixture (not assumed, not from code reading alone)** - each has a
regression test confirmed to fail pre-fix and pass post-fix:

1. **Reopening a draft category-mapping step lost its own mapping.** A
   column-values-fetch effect reset `categoryMapping` to `{}` immediately
   after `loadRequestIntoForm` had just restored it from the step's own real
   request, whenever the operation/column transitioned back onto that step -
   every row in the review table then showed "Leave unchanged"/"Preserved"
   while the preview summary above still correctly reported the real
   affected-row count, a direct, confusing contradiction. Fixed with a
   one-shot ref (`pendingMappingRestore`) the effect consumes instead of
   unconditionally resetting.
2. **Critical: a plan-review step marked "Excluded until you decide" could
   still be applied.** The plan-review screen visually forces a
   needs-clarification step's Include toggle off (the same condition the
   real backend's date-ambiguity check would flag), but `approvePlan()` sent
   each step's raw, untouched `enabled` flag to the backend - so a genuinely
   ambiguous date-convert step the screen showed as excluded was applied to
   real data anyway on the first live run. Found the moment the real
   `signup_date` column showed converted ISO timestamps after an "approval"
   that should have excluded that exact step. Fixed by recomputing the same
   `needsClarification` condition in `approvePlan()` before sending anything
   to the backend. Reverified clean on a second real run after the fix
   (`signup_date` stayed unconverted).

**A third real bug, found only while verifying restart-recovery against the
real packaged sidecar** (not a frontend bug - a backend data-integrity gap):
`apply_recipe`'s atomic multi-step publish inserts/reactivates `_revisions`
rows with direct SQL, bypassing `add_revision()` entirely - so those rows
never got a `sequence` value, the real column this branch's earlier
same-second-ordering fix added. `list_current()`/`latest()` (coalescing a
NULL sequence to 0) ranked a dataset's plan-review-applied revision *below*
its own earlier, singly-applied revision - `GET /overview/datasets` reported
revision 1 for a dataset whose `/state` correctly showed revision 3. This is
the exact ordering restart-recovery, SQL Lab's connection list, and AI
Analyst all resolve "most recent" through, so every plan-review approval was
silently making its own dataset look stale in every such listing. `get()`/
profile were unaffected throughout (they order by revision alone). Fixed by
having both the insert and reactivate branches call the store's own
`_next_sequence()` under the same transaction, exactly like `add_revision()`
already does. Reverified clean against the real rebuilt sidecar, including
across a genuine restart (see below).

**Real workflow proof** (against the real packaged sidecar, a real local
Ollama instance, and a real multi-step fixture with whitespace variants, 10
category spelling variants, 2 exact duplicate rows, and both ambiguous and
unambiguous dates - expected outcomes recorded independently before testing
and confirmed exactly: 5 whitespace-affected rows, 2 exact duplicates, 8
mapped category labels across 4 groups):
- Real Atlas explanation obtained (`qwen2.5:3b`, via the real Ollama
  instance the packaged sidecar auto-configures), evidence disclosure
  inspected. Multiple real attempts at a *structured* `clean_operation`
  proposal (not just an explanation) were not reliably obtainable from the
  models currently installed on this machine - some returned explanation-
  only responses, others were correctly rejected by the existing model-
  contradiction safety check (a different installed model than Oct 17's
  session hallucinating "no missing values" against a real 8.3%-missing
  column - the safety net generalizes across models, confirmed independently
  this round). This is an honest finding about current local-model
  reliability for structured output, not a regression - manual Step
  Settings and the plan-review's own suggested-mapping card completed the
  rest of the workflow on real data either way.
- Plan built (trim whitespace -> applied; category mapping -> applied via
  the new suggested-grouping card; convert_type on an ambiguous date ->
  correctly excluded; deduplicate survivorship -> applied) and approved
  through the real plan-review screen: revision 3, 10 rows (12 minus 2 exact
  duplicates), region spellings standardized - all independently predicted
  before testing and confirmed exact.
- SQL Lab: real `GROUP BY region` query against revision 3 returned exactly
  the predicted per-region counts.
- Visualize: real deterministic `amount by region` chart (confirms the
  identifier-exclusion fix from Oct 13 still holds against new installed-
  model variance), real row-inspection on click (3 real contributing rows
  for Bengaluru, matching source data exactly).
- Reports: real chart saved with its explicit source revision/fingerprint
  into a named report.
- **Restart recovery**: real desktop-app restart (`CloseMainWindow`,
  confirmed no orphan sidecar process afterward - both `app.exe` and the
  sidecar exited together) against the final rebuilt binary. `GET
  /overview/datasets` reported the identical dataset_id, revision (2),
  fingerprint, and row_count (10) before and after the restart.

**Known limitation, unchanged from every prior session**: raw UI automation
into the actual packaged Tauri window still does not reliably land. Tried
three different mechanisms this round (Win32 `mouse_event`, `SendInput`, and
UI Automation `InvokePattern` by element name) - none clicked the sidebar
reliably, and `InvokePattern` could not even find a "Clean"-named element in
the webview's accessibility tree. Real native evidence this round is
therefore: (a) genuine `PrintWindow`-based captures of the real packaged
window at the reachable project-desk state, at 1586x992/1440x900/400x844,
confirming the rebuilt binary launches and renders correctly; (b) the full
interactive workflow and visual verification above, run through a browser
instance pointed at the real packaged sidecar (matched origin, not a
separate dev backend) serving the *identical* `next build
--PRISM_BUILD_TARGET=desktop` static bundle Tauri itself serves - the same
code path, exercised through the one automatable surface available.

**Gates, all rerun fresh this round**: web lint/typecheck/a11y-baseline/149
unit tests/production build all clean. Backend ruff, mypy (CI's exact
`--follow-imports=skip --allow-subclassing-any --allow-untyped-decorators
--no-warn-return-any` invocation, which avoids the pre-existing anyio/
Python-3.9 environment mismatch the plain `mypy` invocation still hits),
boundaries, contract-check, and local secrets scan all clean. CI's exact
`phase-1-python` test selection (`tests/api tests/contracts tests/migration
tests/overview tests/sql_lab`) is 778/778 passing against a fresh store -
one test
(`test_phase8c_lineage_traversal.py::test_ancestors_never_cross_into_a_different_fingerprint_sharing_the_same_revision_number`)
fails only when rerun repeatedly against this local working directory's
accumulated default SQLite file (confirmed via git-stash to fail identically
with or without this round's changes, and to pass cleanly 26/26 against a
fresh file) - a known pre-existing local-only artifact
(`.prism/runtime/analytical-history.sqlite` defaults to a *persistent* file
absent an explicit `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`, documented
already in this file's Oct 17 entry), not something CI's always-fresh
checkout is subject to. Full live SQLite/MySQL e2e suites were not rerun
locally this round given the time already spent on live verification above;
rely on CI's `phase-4-live-e2e` for that gate at the exact pushed SHA.

**Not attempted this round** (named explicitly, not silently skipped): the
Atlas preview-check card's remaining pixel-level geometry match to reference
#01 (the underlying real-predicate/coverage-percentage behavior was already
correct going into this round); SQL Lab/Visualize's own remaining spec-sheet
mismatches (join-evidence population, saved-view density) untouched this
round, deferred to the Oct 29-Nov 4 milestone per the delivery brief's own
phasing; light-theme and narrow-width captures of the *populated* Clean
recipe/plan-review states in the real packaged window specifically (captured
instead via the matched-bundle browser, per the native-automation limitation
above). The separate Atlas desktop-assistant concept (#04) remains deferred
by design, unchanged.

## Historical continuation: 2026-10-17

Claude resumed from pushed feature SHA `557cd37a13f5af04b7fdfe27d6ff2742f7715b1b`
(Codex's prior continuation, both CI jobs and local gates green at that
SHA) and remote main unchanged at `c9472ca822293e8767ec7d8dc617e8be964232d8`.
`verification-20261013.md` and `reference-implementation-spec-20261012.md`
are the authoritative status/spec docs for the visual-fidelity work - this
entry does not repeat them, it only tracks what changed on top.

**Correctness fixes this round** (each independently verified: typecheck,
lint, full web test suite, full relevant pytest selection, ruff, mypy,
boundaries, secrets, contract-check all clean; new regression tests
confirmed to fail against the pre-fix code and pass against the fix):
1. Preserved and committed Claude's own uncommitted date-clarification work
   that Codex had built on - confirmed intact, nothing lost across the
   handoff.
2. `_choose_installed_model`'s selection is appropriate for this
   explicitly-separate, non-governed lane (confirmed by the module's own
   docstring), but the chosen model was never visible to the analyst -
   added a `model` field to `WorkspaceProposalResponse`, surfaced in
   Atlas's dock ("Atlas explained (qwen2.5:3b)" instead of an unlabeled
   "(local model)").
3. **Real bug**: `activeDatasetId` in `prism-shell.tsx` only ever hydrated
   from a `?dataset_id=` URL query param - a genuine app restart is a
   fresh load with no query string, so it never restored, exactly matching
   verification-20261013.md's "active dataset selection was not reliably
   restored" finding. Now falls back to `GET /api/v1/overview/datasets`
   (already ordered most-recent-first by this session's earlier
   sequence-tiebreaker fix) and restores its first entry. Proved end to
   end: uploaded a dataset to the real packaged app's sidecar, stopped the
   app (clean exit, no orphan), relaunched it, confirmed the dataset
   survived, then verified through a real browser against the identical
   frontend code (matched-CORS instance, since the packaged window's own
   CORS config doesn't allow an ad-hoc browser origin) that a plain reload
   with no query string restores it as the active dataset in Clean -
   evidence: `evidence/restart-recovery-verified-20261017.png`. A raw
   Win32 coordinate-click on the actual packaged window to drive this same
   proof directly in-app still doesn't land reliably (same limitation
   already noted in this file's history) - not pursued further given the
   browser-based proof exercises the identical code path.
4. **Real CI failure found and fixed**: `test_a_client_disconnect_...`
   (my own test, predating Codex's autodiscovery addition) only mocked
   `httpx.AsyncClient.post`, not the new `GET /api/tags` autodiscovery
   call - passed locally only because a real local Ollama happens to be
   reachable here, failed in CI with a genuine `ConnectError`. Fixed by
   setting `PRISM_OLLAMA_MODEL` explicitly so the test exercises only
   cancellation, which is what it's named for.
5. Added a `ResizeObserver` stub to the web test setup (jsdom doesn't
   implement it; real browsers do) - surfaced by the restart-recovery
   test being the first `prism-shell` test to reach a real loaded-dataset
   render.

**Desktop rebuild**: sidecar + frontend + Tauri release rebuilt from the
final commit below; launched, sidecar auto-spawn confirmed, window
renders correctly (`evidence/desktop-smoke-20261017.png`). Left running
for the owner to inspect.

**Figma MCP**: confirmed still connected (same owner account used for the
existing `KaDgBRjmB9iqgs7essB4A1` geometry spec) - not used further this
round; the existing spec and approved PNGs remain authoritative, and no
further Figma setup was needed per the owner's own instruction not to
repeat it.

**Not attempted this round** (scope decision, not an oversight): the
exhaustive pixel-level reference-matching work in
`reference-implementation-spec-20261012.md`'s mismatch column (recipe/
mapping/inspector geometry, the full cleaning-plan review composition,
the Atlas preview-check card, SQL Lab join-evidence population, same-
state light/dark/narrow native comparisons) - that remains exactly as
documented in `verification-20261013.md`'s "Open acceptance gaps", not
re-verified or re-scoped here. Treat those gaps as still open; this
round's commits only close the specific correctness bugs listed above.

See the commit log from `557cd37` forward for the exact pushed SHAs, and
the PR's CI checks for the exact-SHA gate results at landing time.

## Historical handoff: 2026-10-12

The `2246880` entry below is a historical handoff, not the current HEAD.
Codex started from pushed feature SHA `282bbbde23c7c427655d75f0b70da1e6223d1dd0`
and remote main `c9472ca822293e8767ec7d8dc617e8be964232d8`.
Claude's intentional uncommitted date-clarification contract and tests were
preserved and completed with the Atlas choice UI and a real Clean re-preview.
Current verification and visual evidence are tracked in
[`verification-20261012.md`](verification-20261012.md). The rebuilt desktop
executable contains the code committed at `ca824b3af0a57603f99a29aae72081ccb3c4ad0c`
and is running against `.prism/desktop-user-test-20261012`; a genuine
stop/start preserved the same dataset fingerprint and revision. Windows
Computer Use auto-review rejected native-window inspection (“Computer Use was
not approved to use app”), so browser captures must not be presented as
packaged-app screenshots. Main integration and tagging remain open until all
required verification and approval gates are satisfied.

## Historical handoff below

## State as of this entry

- Branch: `prism/clean-pattern-review-v1`
- HEAD: `2246880` ("Fix live-e2e assertions for the collapsed-by-default
  Clean disclosures") — pushed. This entry is written after that push, so
  it is not itself part of that commit.
- Working tree: clean except pre-existing, unrelated modified
  screenshots/recordings regenerated by running test suites this session
  (`docs/analytical-workspaces-v1/screenshots/*`,
  `docs/atlas/investigation-collaboration/*`,
  `docs/clean-pattern-review-v1/reference-comparisons/*`,
  `docs/clean-pattern-review-v1/evidence/sql-join-*`) and untracked
  `.prism/*`/`apps/web/_scratch_real_e2e.mjs` scratch files from this and
  earlier sessions' test runs — none of this is mine to touch; preserved,
  not discarded, not committed.
- PR #18 open against `main` (unmodified at `c9472ca`); direct `git push`
  to `main` is blocked by this environment's own "Merge Without Review"
  permission gate — landing goes through the PR.
- The owner's own desktop app instance (previously PID 23512, running
  throughout Phases 1-3) has since closed on its own; port 8000 and
  `app.exe` are free. The desktop app has been rebuilt and smoke-tested
  this session (see below) — not blocked anymore.

## This session: closing the "gap list" (Phases 2-4 completion)

A reviewer's gap list ("Phase 1 substantially complete; Phases 2 and 3
partial; Phase 4 unfinished") drove this session, structured as three
sections. Status of each:

### 1. Real assistant contract — done
`WorkspaceProposalRequest` now carries `selected_operation`,
`selected_column`, bounded `history` (last 3 turns), and
`expected_revision` (rejected outright with 409 if stale, not silently
swallowed into "unavailable"). Conversation + pending decisions persist
across reload via `localStorage` (`atlas-dock:<dataset_id>`), a deliberate
choice over a new backend `ObjectKind` (investigated; out of scope — see
Phase 3 doc). Cancellation is genuine (`AbortController`, proven via the
request's own `AbortSignal`, not a hidden spinner). A `previewRequestId`
race guard discards late-arriving preview responses. Proposal→Step
settings handoff now loads the full form (`loadRequestIntoForm`), not
just the preview.

### 2. Visual surface — done
One header launcher; the floating `.atlas-presence` bubble no longer
shows on the Clean tab (Clean has its own docked launcher). Mapping
editing is one unified table (`renderMappingTable`) used both pre- and
post-preview, replacing two previously different-looking UIs. Check
statuses come from real predicates throughout (no placeholders). Atlas
mascot silhouette refined (limb nubs added for recognizability). Populated
workflow proven in dark/light/narrow — see
`docs/clean-atlas-v1/evidence/phase4-real-ollama/` for a real (non-mocked)
run. The real desktop app has been rebuilt and visually confirmed this
session (screenshot: `evidence/desktop-app-smoke-test.png`) — not just the
dev server.

### 3. Verify and land — in progress, see below

## What this session fixed (verified, not just documented)

**~10 pre-existing stale e2e/e2e-live test failures**, all traced to the
same two root causes and fixed without weakening any assertion:
1. Issues/Patterns/Validation/History/Saved-recipes are `<details>`
   disclosures, collapsed by default — buttons inside need an explicit
   open-click; several pre-dated the disclosure and never had one.
2. Several assertions were stale from before that restructuring
   (`getByRole("heading", {name:/found/})`, `.clean-preview header`,
   `"No issues detected"` heading — none of these exist in current markup).

Files fixed and **execution-verified** against a live server:
- `apps/web/e2e/shell.spec.ts` — green (`test:visual`: 9 passed, 5 failed,
  all 5 confirmed pre-existing/unrelated — Stats/Forecasting/ML-Lab/
  generic-shell-axe/Atlas-mobile-viewport).
- `apps/web/e2e-live/clean-visualize-live.spec.ts` — green. Also fixed a
  real assertion bug of my own (expected "1" issue, fixture genuinely has
  2 — 1 duplicate-row + 1 missing-value), and a second collapsed-disclosure
  miss (History, for the revision-undo buttons).
- `apps/web/e2e-live/pattern-review-live.spec.ts` — green. Added
  `openDisclosure()` helper; had to scope it to `.clean-disclosure >
  summary` (direct child) after discovering Validation nests a second,
  unrelated `<details>` ("Add validation rule") whose summary text also
  contains "validation" case-insensitively.
- `apps/web/e2e-live/analytical-workspaces-connected-live.spec.ts` —
  green. Also fixed: a per-step "Disable/Enable" action now lives behind a
  collapsed `<details class="clean-step-menu">` "more actions" menu; the
  recipe draft container's aria-label changed from "Recipe draft editor"
  to "Unified transformation recipe" (only wraps the `<ol>`, not the
  sibling status paragraph — used the broader nav label instead); "Save as
  recipe" button text is actually "Save recipe"; the saved-recipe list can
  have >1 matching `<li>` across repeated local runs against a reused DB
  (not a real bug — see DB note below).
- `apps/web/e2e-live/analytical-workspaces-states-live.spec.ts` — green.
  Found and fixed a **real, non-test bug**: at ≤760px the always-visible
  ATLAS/AI topbar status badges and the command-trigger's `kbd` hint didn't
  shrink, overflowing the viewport by up to ~115px (confirmed via direct
  `scrollWidth` measurement and a Playwright element-rect scan, same
  methodology as every other narrow-width fix this project has used).
  Fixed in `prism.css`: badge text constrained to 54px at ≤760px, `kbd`
  hidden. Also fixed a real CSS specificity bug found while fixing this —
  an existing ≤1000px rule for the same selector was winning over the
  new ≤760px rule by source order despite being less specific to the
  viewport, since both rules have equal selector specificity (0,1,0) and
  CSS cascades by source order in a tie; moved the narrower rule to appear
  after the wider one.
- `apps/web/e2e-live/analytical-workspaces-100k-live.spec.ts` — green
  (confirmed via full isolated run; no code bug, same disclosure pattern).
- `apps/web/e2e-live/pattern-review-100k-live.spec.ts` — fixed a **real
  pre-existing test-logic bug**, found only because the disclosure fix let
  the test run far enough to reach it: after the invoice_id extraction
  step applies (splitting it into `invoice_id_part1`/`_part2`), the test
  re-clicked the original `invoice_id` finding button for a second
  cancellation-responsiveness check — but that button is genuinely gone
  post-extraction (correct app behavior). Fixed to reuse the still-present
  `amount` (numeric-unit) finding instead. **Not execution-reverified**
  after this specific fix — the rerun was killed by the harness for system
  memory pressure (not a test failure) and the harness said not to
  auto-retry; the fix itself is small, mechanical, and traced directly
  against the current source (`clean-workspace.tsx`), high confidence.
  CI's real `phase-4-live-e2e` MySQL job will exercise it for real.
- `apps/web/e2e-live/pattern-review-verify-cancellation-live.spec.ts` —
  proactively fixed (same Patterns-disclosure pattern); this test is
  skipped by default (`PRISM_PATTERN_VERIFY_TEST_DELAY_MS` unset) and was
  not separately execution-verified this session.

**Important operational note on local live-e2e reruns**: leaving
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` unset makes the API fall back to a
**persistent** file (`.prism/runtime/analytical-history.sqlite`, relative
to the API process's cwd), not an ephemeral one — repeated manual runs
against that default accumulate state (duplicate saved recipes, duplicate
validation rules) and produce misleading "strict mode violation: N
elements" failures that look like bugs but are purely reused-DB
contamination. Always pass an explicit, unique
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` for manual reruns. CI's own
`phase-4-live-e2e` job uses a fresh MySQL service container per run and is
not affected by this.

## Exact failed or unrun checks (as of this entry)

- CI at `2246880`: `legacy-regression` pass, `phase-1-python` pass,
  `secret-scan` pass. `phase-1-web` **failed** —
  `atlas-command-center.test.tsx`'s Cortex graph test
  ("Unable to find a label with the text of: Selected Cortex node").
  Confirmed **flaky, not a regression**: this file/component was not
  touched this session (only `prism.css`, e2e-live specs, and evidence
  files changed — none of which can affect a jsdom/RTL unit test's DOM
  query), and the test passed 5/5 on local reruns immediately after the
  CI failure. Re-run via `gh run rerun <run-id> --failed` queued once the
  full run finishes (was still waiting on `phase-4-live-e2e` when this
  entry was written — rerun cannot be queued while the parent run is still
  in progress). `phase-4-live-e2e` itself: pending at write time: see git
  log / PR #18 for the resolved status.
- `pattern-review-100k-live.spec.ts`'s fix is source-verified but not
  execution-reverified locally (see above) — rely on CI's MySQL job or a
  fresh local rerun with a new isolated DB file.
- mypy: last known blocked by a pre-existing environment issue (anyio
  needs Python 3.10+, repo pins 3.9) — not re-investigated this session;
  rerun as part of final gates.
- Full backend gate suite (pytest/ruff/mypy/boundaries/secrets/contracts):
  last run clean earlier (758 passed, 7 skipped on the relevant pytest
  selection, after the `WorkspaceProposalRequest` contract extension) —
  not rerun again this session since no further `apps/api` source changed
  after that point.

## Desktop build (this session)

Rebuilt for real, from the current HEAD, after the owner's own instance
freed `app.exe`:
1. `apps/api/build_sidecar.py` rebuilt the ~212MB PyInstaller sidecar
   (prior one was stale — predated the `WorkspaceProposalRequest`
   contract extension). Verified directly (not just a clean build log):
   launched standalone, `GET /api/v1/atlas/specialists` and
   `/api/v1/platform/ready` both responded correctly, and
   `POST /api/v1/workspace-proposals` returned the real
   dataset-not-found 404 (proving the route + validation logic from this
   session's backend fix is present in the frozen binary).
2. `npm run build:desktop --workspace=@prism/web` — clean static export
   with every frontend fix from this session included.
3. `npx tauri build --no-bundle` in `apps/desktop-shell` — clean release
   build, `target/release/app.exe` (19.3MB), built from commit `2246880`.
4. Smoke test: launched the real `app.exe`, confirmed its sidecar
   auto-spawned (not just a log line — checked the real process + a real
   `/platform/health` 200), confirmed the real current UI renders
   (screenshot: `evidence/desktop-app-smoke-test.png`, captured via
   `PrintWindow` against the window's own buffer — a first attempt using a
   raw screen-region copy accidentally captured unrelated on-screen
   content and was deleted immediately, never committed). Quit cleanly —
   confirmed via process list that both `app.exe` and the sidecar exited
   together, no orphan (matching the README's documented fix for that
   exact prior regression).
5. **Not done this session**: driving the real packaged window through
   the actual Clean/Atlas workflow via UI automation (one attempted
   coordinate-click to open the Clean tab didn't land, likely a
   focus/timing issue with the raw Win32 mouse-event approach used; not
   worth further raw-input risk given the identical frontend build was
   already exhaustively verified via Playwright against `next dev`
   serving the same `build:desktop` output).

## Reference-image paths

`docs/clean-atlas-v1/references/01` through `06` (indexed in
`phase-1-capability-and-plan.md`'s table). `01`/`02` are the current Atlas
mascot direction; `03`'s layout still informs design but its mascot (the
cat) is superseded; `04` (detached assistant) is explicitly deferred
per the brief; `05` is the primary Clean layout reference; `06` is the
already-matched palette.

## Next concrete actions

1. Once the in-flight CI run at `2246880` finishes, queue
   `gh run rerun <run-id> --failed` for the flaky `phase-1-web` job and
   confirm it goes green on retry (if it fails identically twice, treat
   that as a real signal and investigate further rather than assuming
   flake).
2. Confirm `phase-4-live-e2e` (CI's real MySQL job) is green at this SHA —
   this is the primary gate this session's work targets.
3. If both go green: tag the release per the standing instruction ("tag
   only after mandatory checks pass"). If `phase-4-live-e2e` is still red
   for a *new* reason (not the pre-existing stale-assertion issues this
   session fixed), name that reason explicitly rather than tag anyway.
4. Final report to the owner: executable path (`apps/desktop-shell/
   src-tauri/target/release/app.exe`), build SHA (`2246880`), CI link,
   before/after evidence, and the one known limitation (packaged-window UI
   automation not exercised end-to-end this session, though the identical
   frontend build was via `next dev`).
