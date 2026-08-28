# PRISM implementation ledger

Running record of meaningful units of work across the migration. Newest first.
Phase-specific detail lives in `.prism/implementation-ledger/` and
`.prism/checkpoints/`; this file tracks cross-phase engineering decisions and
verification units that don't belong to a single phase checkpoint.

---

## Unit: Phase 6A/6B — native Clean and Visualize vertical slices

**Objective:** Migrate Clean and Visualize from the Streamlit reference into native, deeply
integrated vertical slices (Overview/SQL Lab/AI Analyst/Atlas/provenance), per
`PHASE6_IMPLEMENTATION_LEDGER.md`.

**Files changed:** `apps/api/src/prism_api/{clean,visualize}.py` (new), `overview.py` (additive
`DatasetStore` revision history), `main.py`/`migration.py` (routers + enabled channels),
`packages/api-contracts/python/prism_api_contracts/{models,__init__}.py` (new contracts),
`packages/api-contracts/typescript/src/generated.ts` (regenerated),
`apps/web/src/components/{clean,visualize}-workspace.tsx` (new),
`apps/web/src/components/prism-shell.tsx`/`overview-workspace.tsx`/`state/shell-model.ts`
(wiring), `apps/web/app/prism.css` (new component styles, reusing existing design tokens),
`tests/api/test_{clean,visualize}.py`, `apps/web/src/components/{clean,visualize}-workspace.test.tsx`,
`apps/web/e2e/shell.spec.ts` (2 new specs), plus two Phase-5-era exact-set tests updated to
include the newly-enabled workflows (expected evolution, not a broken guardrail).

**Contracts changed:** Additive only — `Clean*`/`AtlasClean*`/`Visualization*`/`Viz*`/
`AtlasVisualize*` models. `DatasetStore.add_revision`/`revert`/`revisions` added; `put`/`get`/
`latest` unchanged (verified via the full pre-existing Overview/SQL Lab/AI Analyst suite passing
unmodified after the change).

**Tests:** 652 Python passed / 4 skipped (was 637/4 before this unit — 15 new tests, 0
regressions). 10 Vitest passed (was 5 before). 2 new Playwright specs, verified live in this
sandbox with a substituted Chromium executable path (not committed — see
`RECOVERY_REPORT.md`/`PHASE5_FINAL_REPORT.md` for why) including a real axe-core accessibility
scan. Ruff, mypy (CI invocation), boundary scan, secret scan, TS contract freshness, ESLint,
tsc, a11y baseline, Next build: all clean.

**Parity:** Legacy `modules/cleaning.py`, `modules/autocleaner.py`, `modules/visualization.py`
untouched; capability parity documented in `PHASE6_IMPLEMENTATION_LEDGER.md` (datetime feature
extraction, join, export-as-script deliberately not ported in this slice — noted, not silently
dropped).

**Performance:** No raw dataset reaches the browser from either workspace. Clean previews sample
10 rows; Visualize aggregates server-side with an explicit category cap and scatter sampling,
reusing the same server-side execution pattern SQL Lab already established.

**Security:** `tools/check_secrets.py` and `tools/check_boundaries.py` re-run clean. No new
external dependency introduced (Visualize's renderer is dependency-free inline SVG).

**Architecture decision:** Extend the existing `overview.store` with revision history rather than
building a separate Clean-specific dataset store, so Overview/SQL Lab/AI Analyst get Clean's
output for free through the store they already query — verified by an integration test that
cleans a dataset then queries it live through SQL Lab and reads the cleaned state back through
Overview. Visualize's renderer is decoupled from its analytical spec (`VisualizationSpec`)
specifically so a real charting library can replace the current inline-SVG renderer later without
touching `visualize.py`.

**Risk:** `DatasetStore.revert` truncates revision history past the reverted point (a linear undo
stack, not a branching version tree) — documented in code and the checkpoint; a future "redo"
feature would need a real design decision, not an assumption.

**Technical debt surfaced (not fixed in this unit, filed separately):**
- `task_8c392fdd` — workspace tab bar's close button breaks the ARIA tablist pattern with 2+ tabs
  open (pre-existing Phase 2 shell chrome, only surfaced by this unit's own accessibility testing).
- `task_2fd6fb0f` — SQL Lab's Monaco editor has no offline asset fallback (pre-existing Phase 4).
- Visualize's `box` mark is accepted by the spec/suggestion alternatives but not yet given a true
  quartile-based aggregation in `_aggregate`; it currently falls through to the generic groupby
  path. Not selected by default suggestion, so no user-facing gap today, but worth a real box-plot
  aggregation before `box` is offered as a first-class suggested mark.

**Rollback:** Set `clean`/`visualize` to `legacy` in `migration.py` and `shell-model.ts`, remove
the additive routes/contracts/components/tests/checkpoint. `DatasetStore`'s revision-history
additions are backward compatible and safe to keep regardless.

**Remaining gates:** See `PHASE6_IMPLEMENTATION_LEDGER.md` definition-of-done table — all PASS.
Phase 7 not started.

---

## Unit: Phase 5 lineage recovery + verification

**Objective:** Recover the true migration branch (previous environments had lost
track of it — `main` and the previously-designated branch pointed at the
Streamlit-only line with no Next.js/FastAPI code), then verify every Phase 5
status claim against real code and test runs rather than trusting prior reports.

**Files changed:**
- `RECOVERY_REPORT.md` (new) — lineage recovery evidence.
- `PHASE5_FINAL_REPORT.md` (new) — gate-by-gate verified Phase 5 status.
- `PRISM_IMPLEMENTATION_LEDGER.md` (new, this file).
- Branch pointer `claude/prism-phase-5-6-95ai73` reset from `main`'s tip
  (Streamlit-only) to `origin/phase-5-ai-analyst`'s tip (the real migration
  lineage). No source files were modified.

**Contracts changed:** none.

**Tests:** Ran the full existing suite rather than adding new tests (verification
unit, not a feature unit): 637 Python tests passed (pytest), ruff clean, mypy
clean (CI-matching invocation), boundary/secret scans clean, npm lint/typecheck/
a11y-baseline/vitest/build all clean, Playwright axe-core scan clean (0
violations). See `PHASE5_FINAL_REPORT.md` for the full breakdown including what
was `BLOCKED_EXTERNAL` (live MySQL e2e — no container runtime in this sandbox;
Ollama live check — this sandbox's loopback is not the user's machine; Monaco CDN
— sandbox network policy; staging deploy — no existing infra for the migrated
stack, not created unilaterally).

**Parity:** No Streamlit files touched; parity reference untouched.

**Performance:** N/A (verification unit).

**Security:** Re-ran `tools/check_secrets.py` and `tools/check_boundaries.py`;
both clean. No new attack surface introduced.

**Architecture decision:** Treat `origin/phase-5-ai-analyst` as the source of
truth for the migration going forward, not `main`. `main` continues to receive
Streamlit-only parity fixes from unrelated agents and should not be assumed to
carry migration work again in future sessions — always verify with
`git ls-tree -r --name-only <branch> | grep package.json` before trusting a
branch name or timestamp.

**Risk:** Branch pointer for `claude/prism-phase-5-6-95ai73` was force-pushed
with `--force-with-lease`. Justified only because the prior remote tip was
bit-identical to `main` (zero unique unmerged commits) — documented in
`RECOVERY_REPORT.md`. Do not repeat a force-push on this branch once it carries
unique commits without the same zero-unique-history justification.

**Technical debt surfaced (not fixed in this unit):**
- Atlas is currently the AI Analyst's execution identity (SSE `atlas.*` events,
  contextual actions) rather than the distinct ambient operating-layer surface
  the target product model describes. Forward-looking contracts already exist
  (`packages/atlas-interfaces/python`) but aren't wired into `apps/api` yet.
- SQL Lab's Monaco editor has no offline/local-asset fallback (CDN-only loader);
  filed as a follow-up task (`task_2fd6fb0f`) rather than patched blind here.
- No Linux Playwright visual-regression baselines are committed (only `win32`).

**Rollback:** Revert the branch pointer to its prior tip (`main`'s commit
`6327029`) if this recovery is judged incorrect — safe, since no source changed.

**Remaining gates:** See `PHASE5_FINAL_REPORT.md` — `CODE_COMPLETE = YES`,
`STAGING_READY = NO`, `RELEASE_READY = NO`.
