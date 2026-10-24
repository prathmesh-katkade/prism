# Clean Pattern Review v1 — release status

## STATUS — 2026-10-10, desktop inspector-hierarchy pass (read this section first; supersedes everything below)

**Starting point:** commit `33728f8` (branch `prism/clean-pattern-review-v1`), which already
included the ultrawide-layout fixes (percentage-based sizing, the 2060px centred cap, the
brown-gap fix, footer/floating-control alignment, the STEP-numbering/`editingStepIndex` fix and
its regression test). This pass's job was the remaining substantive gap: the right inspector
still put detailed mapping editing, Preview/Add-step, Recipe name and Save-as-recipe *before*
impact/review information for an inspected or previewed step.

**What changed in `clean-workspace.tsx` / `prism.css` / `prism-shell.tsx`:**
1. Reordered the manual-step inspector to: step identity → operation/column → compact parameters
   (always visible) → Preview → a collapsible `<details class="clean-mapping-editor">` holding the
   detailed value-chip mapping editor / survivorship column picker (open while building, closes
   automatically once that step has a preview, verified in a real browser - not just the `open`
   attribute in jsdom) → Impact → Review card → the step-commit action (Add step to draft/Update
   step N). Impact/review no longer requires scrolling past recipe-saving controls.
2. Moved Recipe name and Save/"Save recipe changes" out of the per-step inspector form entirely,
   onto the left recipe panel next to the existing "+ Add step" button, reusing the existing
   `recipeName`/`setRecipeName`/`saveAsRecipe`/`recipeError` state and validation unchanged.
3. Audited count labels in the new Impact/Review block: `exception_rows_total` was labelled
   "unresolved value(s)" (a distinct-values phrasing for a row count) - relabelled to "exception
   row(s)" to match what the field actually counts. Rows/distinct-values/exceptions are not
   interchangeable; `columnValues.total_distinct` (genuinely distinct) and
   `preview.unresolved_values.length` (genuinely distinct) were left as "distinct value(s)",
   correctly.
4. Checked "No report linked.": no dataset/clean-state field anywhere in this component, its
   props, or the wider frontend carries a report association for the active dataset - the static
   text was already honest, not hardcoded over a real association. Left unchanged.
5. **A real, previously-undiscovered regression found by direct measurement, not assumed fixed by
   inspection:** the fixed-position Clean apply bar and the floating Atlas presence bubble were
   aligned to the local inspector column with a `calc(50vw - constant)` formula reverse-engineered
   from one specific ultrawide viewport. The inspector column's width is a responsive
   `clamp(290px, 20%, 330px)`, not a constant, so that formula only holds at the exact width it was
   derived from. At an ordinary 1600px-wide window it left a ~40px gap between the footer/Atlas and
   the inspector's real left edge, exposing the grid's brown line colour underneath - the same
   visual defect class as the original brown-gap bug, just at a different width. Fixed by replacing
   the fixed formula with a `ResizeObserver`/`MutationObserver`-driven measurement in
   `prism-shell.tsx` that sets `--local-inspector-footer-left`, `--local-inspector-footer-right`
   and `--local-inspector-atlas-right` from the inspector's actual rendered edges on every local-
   inspector workspace (Clean, SQL Lab, Visualize, Reports), with the old formula kept only as the
   `var()` fallback for first paint. Verified by direct pixel measurement at both 1600px (gap
   closed to 0px) and 3440px (unchanged, gap still 0px) - screenshots in
   `evidence/2026-10-10-inspector-hierarchy/`.

**Gates run on this tree after the above edits:** lint, typecheck, `test:web` (120 passed, 0
failed, 18 files - includes one new test asserting the Impact/Review-before-Add-step-to-draft
ordering and the real-browser disclosure collapse), `build:web`, `a11y:baseline`: all clean.
Ruff: clean except one pre-existing, untouched `apps/api/desktop_entry.py` import-order finding
predating this branch (commit `bdf299d`). mypy: blocked by a pre-existing environment issue
unrelated to this change (`anyio` ships a `match` statement that needs Python 3.10+, while this
repo's mypy config pins `python_version = "3.9"`) - not caused by, or fixable within, this pass.
Full pytest on an explicit isolated SQLite file
(`PRISM_ANALYTICAL_HISTORY_DATABASE_URL=sqlite:///.../pytest-history.sqlite`, never the production
database): **1368 passed, 7 skipped**, 0 failed. Boundaries, secrets, generated-contract check:
clean. Desktop/mobile visual suite (`test:visual`): **8 passed, 6 failed** - see below. Live
browser suite on an explicit isolated SQLite file (`test:e2e:live`): **13 passed, 10 failed, 5
skipped** - see below.

**The 6 `test:visual` failures and 10 `test:e2e:live` failures are a pre-existing, dated
regression, not something introduced by this pass.** Every failure traced back to UI text/structure
(e.g. a `heading` named "1 found" / "No issues detected" in `clean-visualize-live.spec.ts` and
`pattern-review-live.spec.ts`) that no longer exists anywhere in the current component source
(confirmed by grep - zero matches), plus unrelated colour-contrast and mobile-overflow findings in
Stats/Forecasting/ML Lab/Atlas. `git log` on the failing spec files shows none of them have been
touched since `5f9f528` ("style(clean): Phase 1 visual reconstruction against the approved
reference"), 14 commits before this branch's starting point - the whole-sale Palette A / layout
reconstruction that ran between the fourth-pass checkpoint below (`4390375`, which recorded this
exact suite at 23/23/0) and `33728f8` changed the rendered UI enough to break these specs' text
assertions, and nothing since has reconciled them. This pass's diff (`clean-workspace.tsx`,
`clean-workspace.test.tsx`, `prism.css`, `prism-shell.tsx`) does not touch any of the failing spec
files or the headings/components they assert on. Rewriting this suite against the current UI is a
real, separate body of work, named here rather than hidden; it was not attempted in this pass.
**No disposable-MySQL live suite is wired into this repository's `npm`/`pytest` scripts** - only
SQLite is used for durable history (`history_database_url()` in `durable_registry.py`); a prior,
unrelated Pattern Review task left ad hoc disposable-MySQL scratch scripts under `.prism/`, but
there is no `test:e2e:live:mysql`-equivalent command for this change to run.

**Desktop verification:** rebuilt `apps/desktop-shell` in debug mode from this exact tree; the
packaged app's inspector hierarchy, disclosure-collapse behaviour and footer/Atlas alignment were
re-verified against the dev-server Playwright measurements above (the packaged WebView2 shares the
same `prism.css`/`clean-workspace.tsx` bundle). See the final report for the exact executable path
and desktop screenshots.

This pass did not touch Atlas, the desktop packaging/lifecycle code, or any file outside
`apps/web/src/components/clean-workspace.tsx`, `apps/web/src/components/clean-workspace.test.tsx`,
`apps/web/app/prism.css` and `apps/web/src/components/prism-shell.tsx`.

## FINAL status — 2026-10-09, fourth pass (read this section first; supersedes everything below)

**Scope closed this pass:** the owner's explicit GUI-reference completion
request - the four named Visualize functionality gaps (Sort by, Axis
starts at, Currency, a real Saved-views list / consolidated filter chips),
SQL Lab toolbar density, a freely-navigable Clean workflow strip, a full
continuous walkthrough, and a complete final-gate rerun. Full details,
exact test names, and the itemized still-open visual list are in
`acceptance-matrix.md`'s fourth-pass section and
`reference-discrepancy-audit.md`'s third-pass section - this section is a
summary, not a duplicate.

**Two real bugs found and fixed, both through direct inspection rather
than assumption:**
1. The Axis-starts-at control was permanently stuck showing "Custom…" on
   every freshly-suggested chart, before any user touched it - a
   `=== undefined` check that never matched pydantic's `null` serialization
   of an unset `Optional` field. Fixed with `== null`.
2. A saved chart's `axis_start`/`currency` silently reverted to bare
   defaults once viewed inside a Report - `reports-workspace.tsx` never
   forwarded them to `ChartCanvas`/`FacetCharts` the way
   `visualize-workspace.tsx` does. Found via the full walkthrough (not a
   targeted test), fixed, and the regression test was verified to actually
   fail without the fix before being confirmed to pass with it.

**Fresh, final gate counts on this exact tree** (commit `4390375`, all
rerun in this pass, not inherited): lint, typecheck, build:web, a11y
baseline, Ruff, mypy, dependency boundaries, secret scan, and
generated-contract check all clean; web unit tests **114 passed** (0
failed, +13 since the third pass: 8 Visualize + 1 Reports persistence + 4
behavioral tests already counted in the prior Clean/SQL-Lab density
commit); full pytest, isolated SQLite, **1,368 passed, 7 skipped, 43
warnings**; desktop/mobile visual suite **14 passed, 0 failed** (two
toolbar-density baselines intentionally updated after manual pixel
inspection confirmed they reflect the real, intended toolbar change, not
a regression); the entire live browser suite against isolated SQLite **23
passed, 5 skipped, 0 failed**; the entire live browser suite against
disposable MySQL 8.4.9 **23 passed, 5 skipped, 0 failed**; the opt-in
server-side cancellation proof **passed** (stopped at row 5,000 of
20,000); a genuine two-OS-process restart proof **passed**.

Two non-deterministic failures surfaced during MySQL runs and were
investigated to ground truth rather than retried blindly or dismissed:
accumulated same-named-recipe state from this session's own repeated test
invocations against an un-reset MySQL database (fixed by resetting it, not
a product bug), and the pre-existing, already-documented shared-process
"latest dataset" race in the live-suite architecture (reproduced once,
confirmed passing in isolation, unrelated to this pass's changes).

**Visual acceptance remains open** - substantially closer than the prior
pass (the four Visualize gaps are real functionality now, not absent
controls; SQL Lab's density closely matches the reference; Clean has the
workflow strip), but six specific, named composition/typography gaps
remain for the owner's judgment, listed in full in
`reference-discrepancy-audit.md`. This document does not accept them on
the owner's behalf.

**Landing**: see the final report for the exact landed SHA, CI link, and
tag status recorded at the end of this session.

## FINAL status — 2026-10-09, third pass

Landed `644a09a` (the second-pass commit below) and then independently
smoke-tested it with a real Chromium browser walkthrough against that exact
build, outside of any mocked test. This found one genuine, reproducible bug
that none of the unit/API/live-e2e suites had caught: after accepting a
pattern family and applying its extraction, clicking **"+ New manual
operation"** (or selecting a different quality issue) left the right
inspector frozen on the old **PATTERN REVIEW** panel instead of switching to
the requested one — `selectedFinding` was never cleared by
`startManualOperation()`/`selectIssue()`, and it took render precedence over
`manualMode`/`selectedIssue` in `clean-workspace.tsx`'s inspector branch
chain. The manual-operation form (Operation select, Preview, Add step to
draft) was unreachable from that state, and a still-running verify job for
the old finding could also resolve late and resurrect it. Fixed by clearing
`selectedFinding` (and cancelling any in-flight verify poll) in both
`startManualOperation()` and `selectIssue()`; a new regression test
(`clean-workspace.test.tsx`, "switches the inspector away from a selected
pattern finding...") covers both directions. Commit `439e4c3`, fast-forwarded
to `main` the same way as `644a09a`. Full web unit suite: **107 passed**
(106 + 1 new), 0 failed.

This is exactly why the smoke test existed: automated suites exercise one
flow per test and reset state between them, so they never clicked "new
manual operation" *after* a finding was already selected and applied. A real
walkthrough does. See the final report for the CI result and tag status at
this exact SHA.

## FINAL status — 2026-10-08, second pass

**Functional acceptance and visual acceptance are tracked separately below.
Passing functional/gate tests is not visual acceptance, and visual
discrepancies are not downgraded to "non-blocking" by this document - that
is the owner's call to make, not this report's.** An earlier draft of this
section described the remaining Clean/SQL Lab/Visualize composition and
typography differences as "non-blocking." That characterization is
withdrawn here; the owner asked for the GUI to match the supplied images
closely, and differences from that are left open and unresolved below
rather than silently accepted on the owner's behalf.

**Server-side cancellation (functional, closed):** cooperative, cancellable
full verification exists (`QueryJobRuntime` reused from SQL Lab; new
`/verify/start`, `/verify/jobs/{id}`, `/verify/jobs/{id}/cancel` endpoints,
each enforcing the job belongs to the URL's dataset/column). `rows_checked`
is checkpointed and rescaled to stay monotonically non-decreasing across
every detector's internal passes (`identifier_structure`, `numeric_unit`,
`delimited_compound`); `date_ambiguity` is cancellable only before/after its
one vectorized call, not at row granularity - a stated, bounded limit, not
a universal claim. 6 API-level tests
(`tests/api/test_clean_patterns.py`) cover a deterministic mid-scan
cancellation, dataset/column ownership enforcement, progress monotonicity,
and the completion/cancel race. The live-browser proof
(`pattern-review-verify-cancellation-live.spec.ts`, opt-in) showed the
server's own scan stopped at row 12,000 of 20,000 after a cancel request,
471ms of which was UI latency and the rest genuine server-side scan time
that never resumed. See `acceptance-matrix.md`'s FINAL section for the full
review findings and gate table.

**Visual acceptance against the three supplied references (open, not
accepted):** substantial, real progress exists - reference images copied
in, side-by-side captures taken at the references' own 1586×992 size plus
1440×900 and ~400px narrow in both themes, a horizontal-bar chart mark
implemented, SQL Lab's schema/source pane moved to match the reference
layout, Clean's recipe promoted to the dominant visual. This is not the
same as the owner's "match closely" requirement being met. Concrete,
named, unresolved differences remain in Clean (typography/control/pane
sizing smaller than the reference), SQL Lab (toolbar/result-action density
higher than the reference), and Visualize (thinner bars, wider margins,
sparser saved-view composition, different settings hierarchy than the
reference) - see `reference-discrepancy-audit.md` for the itemized list and
`reference-comparisons/*-side-by-side.png` for the actual images. These
remain **open** until corrected or the owner explicitly accepts the current
state; this document does not make that acceptance for them.

**Fresh, final gate counts on this exact tree**, all rerun in this
verification pass (not inherited): full pytest **1,359 passed, 7 skipped,
43 warnings**; web unit tests **106 passed / 16 files**; lint, typecheck,
build:web, a11y baseline, Ruff (CI's exact path set), mypy (CI's exact
flags), dependency boundaries, secret scan, and generated-contract check all
clean; desktop/mobile visual suite **14 passed, 0 failed, no snapshot
changes needed**; the entire live browser suite against disposable MySQL
8.4.9 (CI's exact `phase-4-live-e2e` recipe) **23 passed, 5 skipped, 0
failed**; the entire live browser suite against isolated SQLite **23
passed, 5 skipped, 0 failed**; the genuine two-OS-process restart proof
**passed (649ms)**. The MySQL/SQLite "5 skipped" (one more than the
historical 4) is the new cancellation-proof spec correctly self-skipping
when its opt-in env var isn't set, not a new gap.

Fresh 100k measurement (MySQL-backed, regenerated by this pass, not reused):
`sample_discovery_visible_ms=17670, full_verify_100k_ms=895,
exception_page_ms=885, extraction_preview_ms=10689,
extraction_apply_ms=26471, cancel_response_ms=123`. The new job/checkpoint
machinery adds no measurable overhead to the uncancelled full-scan path at
this scale.

**Landing**: see the final report for the exact landed SHA, CI link, and tag
recorded at the end of this session.

## Superseding status for the reference-driven GUI work

This page described the earlier Pattern Review checkpoint. The later request
adds exact supplied GUI references across Clean, SQL Lab, and Visualize plus
fresh end-to-end gates. Those criteria are still open. The feature branch has
not been integrated to main or tagged for this follow-on work. See
`reference-discrepancy-audit.md` and the superseding section of
`acceptance-matrix.md` before reading the historical gate claims below.

As of the 2026-10-07 reference-driven checkpoint, **release is blocked**.
The full-verification Cancel control aborts the browser request and rejects
its late result, but the synchronous API scan may keep running. There is no
server-side job cancellation or measured in-progress row count. The 100k-row
browser run measured 122 ms to return the UI to idle; that is not proof of
server cancellation. Visual comparison also remains open, especially the
Clean recipe population and Visualize chart/settings proportions. The
historical "shipped" and "final HEAD" statements below refer to the earlier
checkpoint and must not be used as approval for this integration.

Current uncommitted integration gates, after the latest UI changes: lint,
typecheck, build:web, a11y baseline, Ruff, mypy, dependency boundaries,
secret scan and generated-contract check pass. Web unit tests passed 106/106
on rerun after one unchanged Atlas Cortex timing failure. Desktop/mobile
visual tests passed 14/14 without snapshot update. Full pytest passed 1,355,
skipped 7, with 43 warnings on an explicit isolated SQLite path. The entire
MySQL-backed live browser suite passed 23, skipped 4 on disposable MySQL 8.4
databases; this includes the 100k Pattern test. The genuine two-API-process
restart proof is in `restart-evidence.md`. These green gates do not waive the
two open acceptance criteria above. The connected-flow recording from the
successful live suite is `evidence/connected-workflow-20261007.webm`.

See `acceptance-matrix.md` for the full, item-by-item evidence table;
`detector-semantics.md` for exact detector rules and limits;
`fixtures/README.md` for declared-and-verified fixture facts;
`performance-100k.md` for 100k-row measurements and a real regression found
and fixed; `restart-evidence.md` for the genuine two-process restart proof.

## What shipped

A complete, usable, durable Pattern Review workflow inside Clean:
discover → inspect evidence and exceptions → accept legitimate families
(one or several) → preview extraction/standardisation → explicitly apply →
save a reusable validation rule → reopen after a real process restart →
validate a subsequent, schema-compatible dataset. Ignore and suppress are
genuinely distinct in scope (revision-bound vs. persistent), and revocation
is append-only and inspectable.

## Explicitly deferred (not built, named as follow-up)

Fuzzy duplicate merging/entity resolution, automatic cross-column
relationship discovery, general statistical anomaly detection, automatic
recurring-export drift comparison, model-written explanations. Confirmed
empirically, not just by omission: similar-but-distinct supplier names in
the business fixture produce zero pattern findings, since no detector
attempts entity resolution.

## Known, documented boundaries (not gaps discovered after the fact)

- `date_ambiguity` checks day/month-order plausibility only, not calendar
  validity - `31/02/2026` is not flagged. This was ADR 0025's stated scope
  (reuse the existing check unchanged).
- Extraction preview/apply at 100k rows remains multi-second (not
  sub-second) due to pre-existing shared `_health()`/`add_revision()` cost,
  already measured at similar magnitude for other Clean operations in the
  prior analytical-workspaces release. This feature's own new code (the
  detectors, the extraction logic itself) is fast; a real O(n) regression in
  shared code that this feature's extraction exposed at unusual severity was
  found and fixed (see `performance-100k.md`), but the remaining shared cost
  is out of this feature's scope to optimize further.

## Gate results (final HEAD)

- Full pytest: **1353 passed, 7 skipped**, 0 regressions vs. the 1312
  baseline captured before any Pattern Review code existed.
- Web unit tests: **106 passed / 16 files**, 0 regressions.
- `npm run test:e2e:live` under MySQL (matching CI's `phase-4-live-e2e`
  exactly): run twice. First run had 2 transient failures in pre-existing,
  non-Pattern-Review specs; investigated (isolated re-run passed; full
  re-run passed both) rather than dismissed. Second run: **23 passed, 0
  failed, 4 skipped**.
- `npm run test:e2e:live` under the ordinary SQLite-backed path: **23
  passed, 0 failed, 4 skipped**.
- lint, typecheck, build:web, a11y:baseline, ruff, mypy, boundaries,
  secrets, generated-contract check: all clean.

## Branch and landing

- Feature branch: `prism/clean-pattern-review-v1`, pushed, all checkpoints
  verified before each push.
- Landing to `main`: see the final report for the exact SHA, CI link, and
  tag status at the time this session concluded.

## Production and Atlas state

Unchanged. This feature touches only Clean's durable stores, contracts, and
UI. No Atlas binding, promotion policy, or production database was read,
written, or configured.
