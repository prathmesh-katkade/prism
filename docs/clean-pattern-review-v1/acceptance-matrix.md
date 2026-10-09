# Clean Pattern Review v1 — acceptance matrix

## FINAL acceptance status — 2026-10-08 (read this section first)

This section is authoritative. The "Superseding integration status — 2026-10-07"
section below it, and the original table below that, are retained as a
historical record of what was known at each earlier point — they are not
current and must not be read as approval. If anything below conflicts with
an earlier section in this file, this section wins.

**What changed since the 2026-10-07 superseding note.** That note named two
open, mandatory criteria: (1) server-side verification cancellation did not
exist — a browser `AbortController` stopped the client from listening, but
the server's synchronous scan kept running; (2) exact-GUI visual comparison
against the three supplied references was in progress but unfinished. Both
are now closed:

1. **Server-side cancellation and progress** (`apps/api/src/prism_api/clean_patterns.py`):
   full verification now runs as a background job (`QueryJobRuntime`, reused
   as-is from SQL Lab's existing interruptible-job seam, not a new mechanism).
   New endpoints: `POST .../verify/start`, `GET .../verify/jobs/{id}`,
   `POST .../verify/jobs/{id}/cancel`, each enforcing that the job actually
   belongs to the `dataset_id`/`column` named in the URL, not just a bare
   `job_id` lookup (`test_verify_job_poll_and_cancel_enforce_dataset_and_column_ownership`).
   A cancelled job's `finding` is always `null`; `verified=true` can only
   follow an uninterrupted scan, checked again at the moment the scan loop
   returns (closing the completion/cancel race).
   - **Exact checkpoint guarantee, per detector** (do not round this up to a
     universal claim): `identifier_structure` and `numeric_unit` checkpoint
     every `PROGRESS_CHECKPOINT_ROWS` (2,000) row-equivalents, rescaled across
     their two internal passes so `rows_checked` is monotonically
     non-decreasing end to end
     (`test_verify_job_progress_never_decreases_across_a_multi_pass_detector`);
     `delimited_compound` likewise checkpoints every 2,000 rows, rescaled
     across its up-to-7 per-delimiter passes. `date_ambiguity` does **not**
     have row-level checkpoints - it delegates to `clean.py`'s shared,
     already-vectorized date parser, which has no internal interruption
     point. Its cancellation is coarse: checked immediately before and
     immediately after that one call, so a cancel request lands either before
     the parse starts or after it has already finished the whole column, not
     at a 2,000-row granularity mid-parse. This is a stated, bounded scope
     decision (`_detect_date_ambiguity`'s own comment), not a gap discovered
     after the fact, and not the detector either the 100k measurements or the
     live cancellation proof exercise (both use `identifier_structure`).
   - **Completion/cancel race and job lifecycle**: `_verify_records` is
     in-memory only, keyed by job_id, never persisted - a process restart
     wipes it, so a GET for a pre-restart job_id correctly 404s rather than
     claiming a false result; an in-flight job is not expected to, and does
     not, survive a restart (`restart-evidence.md`'s FINAL section). Jobs run
     under a 120-second timeout via `QueryJobRuntime`'s existing `Timer`
     mechanism (the same one SQL Lab's query runs already use). Finished job
     records are retained for the life of the process (not evicted) - this is
     a real, acknowledged resource-bound limitation for long-running
     production use, not something this pass claims to have solved; it is
     bounded in practice by job records being small (no row data, only
     counts/state) and by the existing `_verify_records` dict never growing
     across a restart.
   - The pre-existing synchronous `POST .../verify` endpoint is unchanged and
     still available for direct/programmatic callers; the UI now calls the
     job endpoints instead, since only those can be cancelled.
   - **API-level proof** (`tests/api/test_clean_patterns.py`): a 20,000-row
     scan with a test-only, env-var-gated per-checkpoint delay
     (`PRISM_PATTERN_VERIFY_TEST_DELAY_MS`, unset/zero in production and in
     every other test) is cancelled mid-scan; the job reaches
     `state="cancelled"` with `rows_checked < rows_total` and `finding=None`,
     a second poll stays cancelled, and cancelling an already-succeeded job
     is a verified no-op (no retroactive downgrade).
   - **Live-browser proof**, separating UI latency from server termination
     (`apps/web/e2e-live/pattern-review-verify-cancellation-live.spec.ts`,
     opt-in via the same env var so the normal suite run isn't slowed):
     `PRISM_VERIFY_CANCELLATION_PROOF {"ui_cancel_response_ms":471,"server_rows_checked_at_cancel":12000,"server_rows_total":20000}`.
     The server's own scan loop stopped at row 12,000 of 20,000 — a client
     `AbortController` alone could never demonstrate this, since it only
     stops the browser from listening.
2. **Visual fidelity against the three supplied references - OPEN, not
   accepted.** The owner asked for the GUI to match the supplied images
   closely. That has not been fully achieved, and this document does not
   decide on the owner's behalf that the remaining gap is acceptable. See
   `reference-discrepancy-audit.md` for the full, itemized comparison;
   `reference-comparisons/*-side-by-side.png` for the actual side-by-side
   captures at the references' exact 1586×992 size, dark/light, plus
   400×844 narrow; `evidence/connected-workflow-20261007.webm` for a real
   connected-workflow recording. Named, unresolved differences: typography/
   control density in Clean and SQL Lab remain smaller than the references;
   SQL Lab's toolbar/result-action density is higher than the reference;
   Visualize's bar thickness/margins and saved-view composition remain less
   dense than pictured; Reports has no approved reference and is styled from
   the shared system only. None of these are content fabrications (no
   invented totals, no fake avatars, no auto-approved mappings, no fictional
   join counts) — they are composition/
   density gaps, named rather than hidden.

**Fresh final gates, run on this exact tree (not inherited from an earlier
run) immediately before this section was written:**

| Gate | Result |
|---|---|
| `npm run lint` | clean |
| `npm run typecheck` | clean |
| `npm run test:web` | 106 passed / 16 files |
| `npm run build:web` | clean |
| `npm run a11y:baseline` | passed |
| `ruff check` (CI's exact path set) | all checks passed |
| `mypy` (CI's exact flags) | no issues in 102 source files |
| `python tools/check_boundaries.py` | passed |
| `python tools/check_secrets.py` | passed |
| `python tools/generate_typescript_contracts.py --check` | clean (no diff) |
| Full `pytest` | 1,359 passed, 7 skipped, 43 warnings |
| `npm run test:visual` (desktop/mobile, Playwright) | 14 passed, 0 failed, no snapshot changes needed |
| `npm run test:e2e:live` against disposable MySQL 8.4.9 (matches CI's `phase-4-live-e2e` exactly) | 23 passed, 5 skipped, 0 failed (2.6m) |
| `npm run test:e2e:live` against isolated SQLite | 23 passed, 5 skipped, 0 failed (2.7m) |
| Genuine two-OS-process restart proof | passed (649ms) — see `restart-evidence.md` for the current-tree rerun, including both process IDs and the second process's own request log |

A false alarm during this verification pass is worth recording precisely
because it was investigated rather than assumed: an initial SQLite live-suite
rerun showed two tests failing on "strict mode violation: resolved to N
elements" (apparent duplicate validation-rule entries). Direct reproduction
proved the backend's `/clean/validation-rules` list was always correct
(count 1) for a single created rule; the duplication was a self-inflicted
test-environment artifact — Playwright's `webServer.command` runs with its
cwd at the config file's directory (`apps/web/`), so the SQLite history file
actually in use was `apps/web/.prism/runtime/analytical-history.sqlite`, a
57MB file accumulated across this session's many earlier runs, not the
repo-root `.prism/runtime/` path being cleared between attempts. Once the
correct file was cleared, every rerun passed cleanly and reproducibly. No
product code changed to "fix" this - there was nothing in the product to fix.

The MySQL run's 5 skipped is one more than the historical 4: the new
cancellation-proof spec correctly self-skips when the opt-in env var isn't
set, rather than running unreliably fast and flaking.

**Fresh 100k measurement** (`performance-100k.json`, regenerated by this
MySQL run, not reused from before this feature's changes):
`upload_to_profile_visible_ms=4547, sample_discovery_visible_ms=17670,
full_verify_100k_ms=895, exception_page_ms=885,
extraction_preview_ms=10689, extraction_apply_ms=26471,
cancel_response_ms=123`. The uncancelled full-scan path still completes
in under a second at 100k rows with the new job/checkpoint machinery in
place — the checkpoint overhead (progress callback + cancellation check
every 2,000 rows) is not measurable at this scale.

## Superseding integration status — 2026-10-07

The table below records an earlier Pattern Review backend/UI checkpoint and
its then-current gate results. It is **not** the acceptance state of the
reference-driven Clean/SQL Lab/Visualize/Reports integration requested later.
At the current unlanded feature worktree, exact GUI comparison remains open.
The new exception paging, nonmatching counts, horizontal bars, shared visual
pass and browser workflow fixes require final fresh gates and visual review.
Do not use the historical “Verified” labels below to approve landing.

| Added integration criterion | Current state |
|---|---|
| Supplied 1586 × 992 references copied and compared with live captures | Captured; discrepancies in `reference-discrepancy-audit.md`; visual acceptance open. |
| Pattern exception row identity and bounded paging | New API/UI and focused API test pass; full suite pending. |
| Horizontal bar aggregation and contributing rows | Focused API test and live browser capture pass; full suite pending. |
| Connected Clean → SQL → Visualize → Reports workflow | Targeted live browser rerun passed after fixing an Atlas control obstruction. |
| SQLite entire live browser suite | First full run: 20 passed, 3 failed, 4 skipped; fixes made; full rerun pending. |
| MySQL entire live browser suite | Disposable MySQL 8.4 parity tests: 31 passed; full browser run in progress. |
| Genuine restart, second-dataset validation, stale/duplicate/suppression proof after latest changes | Historical evidence exists; current-SHA repeat pending. |
| Main integration, exact-SHA CI, tag, and user app switch | Not done. |

Update after the latest targeted MySQL browser run: exception paging and the
join inspector passed in a 3/3 run; the 100k measurement is in
`performance-100k.json`. The earlier "Cancellation during
verification" row below proves UI cancellation only. It does **not** meet the
requested cancellable API scan with progress; the server can continue working
after the browser aborts. This remains a mandatory open criterion. The
historical "This file reflects the final" sentence below is superseded by
this section.

The later full MySQL browser run passed 23 tests with 4 skips on fresh,
disposable databases after the latest code changes. Full pytest passed 1,355
with 7 skips and 43 warnings; 106/106 web unit tests passed on rerun; 14/14
desktop/mobile visual tests passed without snapshot update. Static/build
gates passed. The live connected-flow recording is
`evidence/connected-workflow-20261007.webm`; the two-source SQL inspector
capture is `evidence/sql-join-dark-1586x992.png`. Server-side cancellation
and progress, final visual acceptance, main landing and exact-SHA CI remain
open. No release assertion is warranted.

Baseline snapshot: 2026-10-07, branch `prism/clean-pattern-review-v1`, branched
from verified `origin/main` at `bc72625` (tag `prism-native-v1.0`, CI success
confirmed via `gh run list` immediately before branching — not assumed).
Final snapshot: 2026-10-07, same branch, HEAD after all checkpoints below.

| Area | Status | Evidence |
|---|---|---|
| ADR 0025 | Written | `docs/architecture/adr/0025-clean-pattern-review-v1-boundaries.md` - reuse of source identity/preview-apply/validation-rule infrastructure, new durable concepts, detector/sampling/extraction/context rules, explicit deferrals, written before any detector code. |
| Detectors | Verified | Four deterministic detectors (`clean_patterns.py`), semantics and limits documented in `detector-semantics.md`. No Ollama dependency anywhere in this feature. |
| Multiple legitimate families accepted together | Verified | `test_multiple_legitimate_families_can_be_accepted_together`: two families accepted in one decision; a saved rule using both reports zero violations. |
| Minority ≠ error | Verified | Singleton/rare values are bucketed as exceptions, never auto-flagged as errors or auto-repaired; `scientific-measurements.csv`'s consistent-but-short `sample_id` format is reported as one legitimate family, not flagged for being rare. |
| Sample findings stay provisional | Verified | `sampling_method`/`verified` fields; UI renders "Provisional: sampled N of M" distinctly from "Verified against all N". |
| Full counts reconcile exactly | Verified | `test_full_counts_reconcile_exactly_against_rows_examined`: `Σfamily.matching_count + exception_count + missing_count == rows_examined`. |
| Missing values: explicit denominator + policy | Verified | `missing_count` always reported separately; `missing_value_policy` (allow/reject) on saved rules, both branches tested. |
| Exceptions map to correct source rows | Verified | `exception_source_rows` checked against real pandas index values in both the fixture tests and the business-fixture's `AB12` → row 6. |
| Cancellation during verification | Verified, design documented | Full-scan verify measured at 888ms-917ms for 100k rows (and 82-385ms per isolated detector) - too fast to need background-job cancellation. Client-side `AbortController` + request-sequencing ref implemented; live-browser 100k test confirms Cancel returns control in ~124ms. |
| Stale-source / superseded-response protection | Verified | Decisions require `reviewed_source_revision`/`reviewed_source_fingerprint` and 409 if the dataset changed (`test_decision_rejects_a_stale_reviewed_source`); frontend's `verifyRequestId` ref discards an out-of-order verify response. |
| Suppression scope and revocation | Verified (bug found and fixed) | `suppress_rule` persists across revisions until revoked; `ignore_revision` is scoped to the exact revision. A real bug was found and fixed: the "Revoke" action's own decision record was independently re-hiding the finding through the ignore_revision path it rode on - see `test_revoking_a_suppression_restores_it_to_the_ranked_list` and the commit that fixed it. |
| Durable decisions: source identity + detector version | Verified | `detector_version` auto-filled and persisted; `source_revision`/`source_fingerprint` persisted and enforced. |
| Extraction/standardisation | Verified | Three `CleanOperation` members through the *existing* preview/apply/review-token flow. Leading zeros preserved (screenshot + test), units never converted, output-collision 422 with zero mutation, stale-preview rejection (409), one-use apply tokens, no eval/arbitrary regex (identifier extraction only accepts a detector-generated signature, re-validated server-side). |
| Context-dependent patterns (user-chosen grouping) | Verified | `group_by_column`/`group_value`; scoping verified to actually change family counts and to require `group_value` when a grouping column is set; a saved grouped rule verified to scope its check (3 US rows, not all 5). |
| Reusable validation | Verified | `ValidationRuleKind.PATTERN_FAMILY` via an idempotent nullable-column migration on the existing store. Schema-compatibility 422 on an incompatible dataset; correct violations on a compatible one; rule-saving never mutates data. |
| Interface (Patterns panel) | Verified | New PATTERNS nav section beside Issues/Recipes/Validation, column explorer, grouping selector, finding review with plain-language families/exceptions/counts, accept/ignore/suppress/revoke actions, decision list. Real screenshots (light/dark, 1440/400) in `screenshots/`; visually inspected, not just DOM-tested. |
| Accessibility/responsive | Verified | Reuses the existing `three-pane`/`clean-issues` responsive CSS unchanged; 400px screenshot confirmed no horizontal overflow, stacked layout; all new controls are plain labelled `<button>`/`<select>`/`<input>` elements (keyboard-operable by construction, same as the rest of Clean). |
| Fixtures (business/scientific) | Verified | `fixtures/business-invoices.csv` (9 rows) and `fixtures/scientific-measurements.csv` (8 rows); every fact in `fixtures/README.md` checked against a live run before being written down; 10 regression tests lock the facts in. Includes one honestly-documented boundary (impossible dates like `31/02/2026` are not flagged - day/month-order ambiguity only, not calendar validity). |
| 100k performance | Verified, with a real regression found and fixed | Found and fixed a genuine O(n) bug (`_row_inspection` materializing ~99,500 row-detail objects to display 100): preview dropped from 32.1s to 2.5s (isolated) / 17.9s (full browser run with a second column). Full-scan verify: 888ms. Discovery: 278ms server-side (gated behind Clean's pre-existing slow `/state` load, not this feature's own cost). Documented honestly in `performance-100k.md`, including what remains un-optimized and why that's out of scope. |
| Restart proof | Verified, genuinely | `pattern-review-restart-live.spec.ts`: two separate `npx playwright test` invocations (two distinct OS processes, confirmed by differing PIDs) against the same database file. A same-process "reopen the store" test exists too but is explicitly relabeled to say it is *not* the restart proof - see `restart-evidence.md`. |
| Existing Clean/SQL/Visualize/Reports workflows | Verified | Full pytest (1353 passed, 0 regressions vs. the 1312-baseline) and full web unit suite (106/16, 0 regressions) throughout; no other workspace's code was touched. |
| Final gates | Passed, fresh | lint, typecheck, build:web, a11y:baseline, ruff, mypy, boundaries, secrets, contract-check: all clean on the final HEAD. Full pytest: 1353 passed, 7 skipped. Full `npm run test:e2e:live` run **twice** under MySQL (matching CI's phase-4-live-e2e exactly): first run had 2 transient failures in pre-existing (not Pattern-Review) specs, investigated (isolated re-run passed; full re-run passed both) rather than dismissed - second run: 23 passed, 0 failed, 4 skipped. Also run clean under the ordinary SQLite-backed path: 23 passed, 0 failed, 4 skipped. |
| Explicitly deferred | Documented | Fuzzy duplicate merging/entity resolution, automatic cross-column relationship discovery, statistical anomaly detection, automatic drift comparison, model-written explanations - named in ADR 0025 and confirmed empirically absent (e.g. `supplier_name` with similar-but-distinct entity names produces zero findings). |
| Landing | See release-status.md | — |

This file reflects the final, verified state of the feature - not a
snapshot frozen mid-implementation.
