# PRISM Phase 6A/6B checkpoint

**Status:** PASS — code complete locally; external delivery and release gates remain unverified.

## Scope

Phase 6 enables the native Clean (6A) and Visualize (6B) vertical slices. It preserves
`modules/cleaning.py`, `modules/autocleaner.py`, and `modules/visualization.py` as the Streamlit
parity/rollback reference and leaves Stats, Forecasting, ML, full autonomous Atlas orchestration,
governance, desktop, and publication work untouched.

## Native path — Clean

- Dataset revisions: `overview.DatasetStore` gained `add_revision`/`revert`/`revisions`, additive
  to the existing `put`/`get`/`latest` API every other Phase 3-5 module already depends on. A
  Clean transformation appends a new revision under the same `dataset_id` — it never mutates a
  dataset in place — so Overview, SQL Lab, and AI Analyst see the cleaned data immediately without
  any of those modules knowing revisions exist. Undo is a linear stack: reverting drops later
  revisions rather than branching.
- Issue detection reuses Overview's own deterministic `build_overview` profile (missing values,
  duplicate rows, all-null columns, outlier burden) — no quality logic is duplicated.
- Transformations: drop duplicates, fill missing (mean/median/mode/constant/forward-fill), drop
  missing rows, convert type (numeric/text/datetime/boolean), rename/drop column, trim whitespace,
  normalize case. Every operation rejects an unknown column rather than guessing, and every
  malformed conversion becomes an explicit warning + missing value, never a silent guess.
- Preview-before-apply: `/preview` computes the same operation as `/apply` on a throwaway copy of
  the frame and returns before/after samples, affected-row/column counts, and projected health —
  nothing is persisted until `/apply`.
- Atlas: `explain_issue`, `propose_fix`, `compare_before_after` actions are grounded in the same
  detected issues and never apply a transformation themselves — every proposal still goes through
  `/preview` and requires an explicit `/apply`.

## Native path — Visualize

- `VisualizationSpec` (mark, intent, dimension, measure, aggregation, filters, max_categories) is
  the renderer-agnostic contract; the frontend renders it with a small dependency-free inline-SVG
  renderer so the analytical semantics never couple to a specific charting library.
- `/suggest` picks a mark deterministically from column semantic types and intent — the same
  inputs always produce the same suggestion, no AI guessing.
- `/render` always aggregates server-side (groupby, category cap, scatter sampling); the browser
  never receives raw rows. Category truncation and overplotting sampling are returned as explicit
  warnings, not silently applied.
- Atlas: `explain_chart`, `identify_anomaly`, `propose_alternative` (trust check) are grounded in
  the same server-aggregated data Visualize already computed.

## Local acceptance evidence

- Python suite: 652 passed, 4 intentionally skipped environment-dependent tests (up from 637/4 at
  the Phase 5.1 checkpoint — all 15 new tests are Clean/Visualize, zero regressions).
- New coverage: cross-module integration (a Clean transformation is immediately visible to
  Overview's profile and to a live SQL Lab query against the same connection), preview-never-mutates,
  unknown-column rejection, undo-then-reapply revision correctness, server-side aggregation/category
  capping/overplotting-sample warnings, deterministic suggestion idempotence.
- Mypy, Ruff, generated-contract freshness, boundary scan, and secret scan: PASS.
- TypeScript, ESLint, Vitest (4 new component tests), accessibility baseline, and Next production
  build: PASS. A live Chromium + axe-core scan (this sandbox's browser, scoped to Clean's own
  subtree) verifies the full upload → detect → preview → apply → new-revision flow keyboard-first
  with zero accessibility violations; Visualize's suggest → render → Atlas-explain flow is
  verified the same way.

## Known pre-existing gaps surfaced (not introduced by Phase 6, filed as follow-ups)

- The workspace tab bar's close button breaks the ARIA tablist pattern when 2+ tabs are open —
  pre-existing Phase 2 shell chrome, only surfaced because Phase 6's own axe scan opened two tabs
  (Overview + Clean) where prior scans never did. Filed as `task_8c392fdd`.
- SQL Lab's Monaco editor has no offline/local-asset fallback (CDN-only loader) — pre-existing
  Phase 4 SQL Lab infra. Filed as `task_2fd6fb0f` during Phase 5 verification.

## External release gates

- Push/PR, staging deployment, and staging smoke tests require configured external
  credentials/access (see `PHASE5_FINAL_REPORT.md` for what was and wasn't available in this
  session).

## Rollback

Set `clean` and `visualize` to `legacy` in the API migration map and shell migration state, then
remove the additive Phase 6 routes, contracts, workspace components, tests, and this checkpoint.
The `DatasetStore` revision-history additions are backward compatible and can stay even if Clean
is rolled back (Overview/SQL Lab/AI Analyst never call the new methods). The Streamlit Clean and
Visualize modules remain the reference implementation throughout.
