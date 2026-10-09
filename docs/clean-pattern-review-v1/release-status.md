# Clean Pattern Review v1 — release status

## FINAL status — 2026-10-09, third pass (read this section first; supersedes everything below)

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
