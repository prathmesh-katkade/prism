# PRISM Claude Session Handoff

Timestamp: 2026-08-28T22:28:23Z
Repository: prathmesh-katkade/prism
Current branch: phase-7-advanced-analytics
Current commit: 0d6753c8cb04597e0acfd55f52a169ee050bdff7
Remote tracking branch: origin/phase-7-advanced-analytics
Working tree clean: YES (before this handoff commit)

## Canonical migration lineage
Current migration base: `phase-5-ai-analyst` ← merged PR #6 (Phase 5 + Phase 6) at merge commit
`a203eea` ← Phase 6.5 work on `phase-6.5-integration-staging` (head `ee17be4`) ← Phase 7 branch
`phase-7-advanced-analytics` created from that head, currently one commit ahead (`6872670`,
the planning brief) plus this handoff commit.
Phase 6.5 merge status: COMPLETE. `phase-6.5-integration-staging` is pushed to origin
(`ee17be4`), release-gated (`PHASE6_5_RELEASE_REPORT.md`), tagged locally as
`prism-native-v0.6` at `349943f` (tag push to origin blocked by session credential scope —
branch pushes work, tag-ref pushes return HTTP 403 from GitHub; documented, not re-attempted
without cause). No PR has been opened yet for `phase-6.5-integration-staging` itself (only
PR #6, which is already merged, preceded it).
Phase 7 branch status: EXISTS, PUSHED (`phase-7-advanced-analytics` @ origin), contains
**planning only** — `PHASE7_BRIEF.md`. **No Phase 7 implementation code exists anywhere in the
repository.**

## Current phase
Phase: 7 (unlocked, not started)
Slice: 7A — Stats Lab (not yet begun; this is the designated first slice per `PHASE7_BRIEF.md`)
Overall status: Phase 6.5 fully complete and release-gated. Phase 7 has a written brief and
priority order but zero lines of Phase 7 implementation code, contracts, routes, components,
or tests. This session did NOT begin Stats Lab implementation — per the fresh-session-handoff
instructions, no new large implementation unit was started this turn.

## Completed in this session
- Verified working tree was clean on `phase-6.5-integration-staging` (already the case; no
  stray edits, `next-env.d.ts` already reverted from a prior turn).
- Confirmed no Phase 7 code exists anywhere (`apps/api/src/prism_api`, `apps/web/src` both
  searched — no `stats`, `forecast`, or `ml` native modules).
- Updated `docs/migration/CURRENT_PHASE.md` to reflect the true current state (was stale,
  still described Phase 6A/6B as current; now correctly describes Phase 6.5 as complete and
  Phase 7 as unlocked-but-unstarted, naming Stats Lab as the designated first slice).
- Wrote this handoff file.
- Did NOT write `PHASE7_IMPLEMENTATION_LEDGER.md` or `.prism/checkpoints/phase-7a.md` — both
  would be premature/empty since no Phase 7A implementation work has happened yet; creating
  them now would fabricate a ledger for work that doesn't exist. Create them when 7A's first
  vertical slice actually lands.

## Currently implemented
- Native Overview, SQL Lab, AI Analyst, Clean, Visualize (Phases 1–6, all `ReleaseChannel.ENABLED`
  in `apps/api/src/prism_api/migration.py` and `apps/web/src/state/shell-model.ts`).
- Phase 6.5 hardening: single typed frontend API config boundary
  (`apps/web/src/config/api.ts`), `/api/v1/platform/ready` readiness endpoint (config-only,
  never live-probes Ollama), structured request logging (`prism_api` logger,
  `_configure_logging()` in `main.py`), bundled (non-CDN) Monaco, ARIA-correct workspace tablist,
  additive staging deployment config in `render.yaml`.

## In progress
- Nothing. No partially-edited production files exist. No Phase 7A code has been started.

## NOT implemented
- Stats Lab (7A): no `apps/api/src/prism_api/stats.py`, no Stats contracts, no Stats workspace
  component, no parity tests against `modules/stats_lab.py`.
- Forecasting (7B): not started, and per this task's stop boundary, **forbidden** until 7A is
  fully gated.
- ML Lab (7C): not started, forbidden until 7A and 7B are fully gated.
- Live staging deployment of `prism-native-api-staging` / `prism-native-web-staging`: still
  `BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` (no hosting credential in any session so far).
- `prism-native-v0.6` tag is not pushed to `origin` (local-only; see lineage section above).

## Exact next task
Implement the first Stats Lab vertical slice, smallest safe unit, in this exact order:

1. **Contracts first** — in
   `packages/api-contracts/python/prism_api_contracts/models.py`, add (mirroring the
   `CleanIssueKind`/`CleanIssue`/`AtlasCleanAction` pattern already in that file):
   - `StatTestKind(str, Enum)`: `T_TEST`, `ANOVA`, `CHI_SQUARE`, `PEARSON` (matches the four
     tests in `modules/stats_lab.py`: `run_ttest`, `run_anova`, `run_chi2`, `run_pearson`).
   - `StatSuggestionRequest` (`dataset_id: str`, `column_a: str`, `column_b: str`).
   - `StatSuggestionResponse` (`test: StatTestKind`, `rationale: str`, `normality: dict | None`
     — mirrors legacy `suggest_test()`'s return shape, `modules/stats_lab.py:69-128`, including
     the Shapiro-Wilk pre-check surfaced via `_shapiro_check`, `modules/stats_lab.py:49-67`).
   - `StatTestRequest` (`dataset_id`, `test: StatTestKind`, `column_a`, `column_b`).
   - `StatTestResult` (`test`, `statistic: float`, `p_value: float`, `effect_size: float | None`,
     `effect_size_label: str | None`, `interpretation: str`, `warnings: list[str]`, `provenance`
     — mirrors `interpret_result()`/`normality_warnings()`, `modules/stats_lab.py:250-289`).
   - Export all five from
     `packages/api-contracts/python/prism_api_contracts/__init__.py`.
   - Regenerate the TypeScript side: `python tools/generate_typescript_contracts.py`.
2. **API router** — new file `apps/api/src/prism_api/stats.py`, `APIRouter(prefix="/api/v1/stats",
   tags=["stats"])`, following `clean.py`'s and `visualize.py`'s existing shape exactly (they are
   the two closest precedents — read both before writing this file):
   - Reuse `prism_overview_analytics.service.detect_column_types(df)` (already used by
     `overview.py`) to get the `column_types` dict `suggest_test()` needs — do not reimplement
     type inference.
   - `suggest_test(dataset_id: str, column_a: str, column_b: str) -> StatSuggestionResponse` —
     port the logic of `modules/stats_lab.py::suggest_test()` (lines 69–128) against the
     dataset's current revision pulled from the shared `DatasetStore` (`overview.py`'s
     `DatasetStore`, same one Clean/Visualize already use — do not create a second store).
   - `run_test(request: StatTestRequest) -> StatTestResult` — dispatches to ported versions of
     `run_ttest`/`run_anova`/`run_chi2`/`run_pearson` (`modules/stats_lab.py:129-235`), then
     `interpret_result()`/`normality_warnings()` for the human-readable fields.
   - Routes: `GET /api/v1/stats/datasets/{dataset_id}/suggest?column_a=...&column_b=...`,
     `POST /api/v1/stats/datasets/{dataset_id}/run`. Add an `AtlasStatsAction`/Request/Response
     trio and a `POST .../atlas` route only after the two above are solid — do not build Atlas
     wiring before the deterministic path is correct and tested.
   - Register in `apps/api/src/prism_api/main.py`: add
     `from .stats import router as stats_router` near the other five router imports (line ~22),
     and `app.include_router(stats_router)` in `create_app()` (after line 63's
     `visualize_router`).
3. **Tests first, before the frontend** (this repo's established pattern for every prior
   slice) — new file `tests/api/test_stats.py`, structured like `tests/api/test_clean.py`:
   - `test_suggest_test_recommends_pearson_for_two_numeric_columns`
   - `test_suggest_test_recommends_ttest_for_one_numeric_one_two_level_categorical`
   - `test_suggest_test_recommends_anova_for_one_numeric_one_multi_level_categorical`
   - `test_suggest_test_recommends_chi_square_for_two_categorical_columns`
   - `test_run_test_pearson_matches_legacy_stats_lab_on_a_fixture` — direct parity assertion:
     build the same fixture DataFrame, call `modules.stats_lab.run_pearson()` directly (import
     the legacy module in the test) and the new native `run_test()`, assert statistic/p-value
     match to a tight tolerance (`pytest.approx`, not exact float equality — same precedent Phase
     6.5 set for MySQL: analytical parity, not bit-exact equality).
   - Repeat the parity assertion for t-test, ANOVA, and chi-square.
   - `test_suggest_test_flags_non_normality_and_run_test_surfaces_the_warning` — the
     Shapiro-Wilk path.
4. **Migration state** — add a `stats` entry to `PHASE_1_MIGRATIONS` in
   `apps/api/src/prism_api/migration.py` at `ReleaseChannel.SHADOW` (not `ENABLED` — it isn't
   user-facing until the frontend slice lands too) with `legacy_reference="modules/stats_lab.py"`,
   and the matching entry in `apps/web/src/state/shell-model.ts`'s `phaseTwoMigrations`.
5. **Only after 1–4 are green**, start the frontend workspace component
   (`apps/web/src/components/stats-workspace.tsx`, following `clean-workspace.tsx`'s three-pane
   layout) and its test file. Do not start this before the backend slice has passing parity
   tests — that ordering is what let Phase 6's Clean/Visualize slices land clean.

Do not touch Forecasting or ML Lab code in the same sitting as 7A — see Stop Boundary below.

## Files changed in this session
- `docs/migration/CURRENT_PHASE.md` — corrected from stale Phase 6A/6B description to the true
  current state (Phase 6.5 complete, Phase 7 unlocked-but-unstarted, Stats Lab named as 7A).
- `CLAUDE_SESSION_HANDOFF.md` — this file (new).

No production code, contracts, or tests were changed this session — this was a state-preservation
turn only, per the explicit instruction not to start a new large implementation unit.

## Contracts added/changed
None this session. (Next session's first code task adds the five Stats contracts listed in
"Exact next task" step 1 above.)

## Tests added
None this session.

## Latest verification
(Unchanged since Phase 6.5's release gate — nothing was modified this session that would
invalidate these. Full detail in `PHASE6_5_RELEASE_REPORT.md`.)
Python: `pytest tests/ apps/api -q` → 659 passed, 1 failed (sandbox-only DuckDB
extension-download block, external/environmental, not a code defect — see "Known failures").
`ruff`, `mypy`, `check_boundaries.py`, `check_secrets.py`, `generate_typescript_contracts.py
--check` → all clean.
Frontend: `npm run lint`, `npm run typecheck`, `npm run test:web` (4 files/11 tests),
`npm run a11y:baseline`, `npm run build:web` → all clean/passing.
Playwright: mocked suite (`playwright.config.ts`) 9/9 passed, incl. ARIA-tablist and
Monaco-offline regression tests. Live suite (`playwright.live.config.ts`, real `uvicorn` + real
`next dev`, no mocks) 5/5 passed, incl. the Clean/Visualize round-trip integration tests.
Parity: MySQL connector parity fixed and passing against a real local MySQL 8.0 server
(`_normalize_decimal_columns`, integer-kind assertion instead of exact-dtype equality).
Accessibility: 0 axe-core violations on the workspace tablist with 2+ tabs open.
CI: GitHub Actions was green on PR #6 before merge; no new PR opened since (Phase 6.5 and Phase
7-brief work pushed directly to their own branches, no PR requested by the task).

## Known failures
- `test_mysql_results_schema_nulls_order_plan_and_legacy_parity` (in
  `tests/sql_lab/test_mysql_connector_parity.py` or adjacent — see Phase 6.5 report) fails only
  in this sandbox because `extensions.duckdb.org` and Docker Hub's CDN are both blocked by this
  environment's egress policy. **External/environmental blocker, not an implementation defect.**
  Passes in real CI which has network access.
- Live staging deployment: `BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` — no Render (or other) hosting
  credential or deployment MCP tool has been available in any session so far. Deployment
  configuration itself (`render.yaml`) is complete and untested-live.
- `git push origin prism-native-v0.6` (the tag ref): persistent HTTP 403 from GitHub after 4
  retries with backoff, while branch pushes succeed — this session's git-push credential appears
  scoped to branch refs only. **External credential-scope limitation, not a code or CI issue.**
  Do not keep retrying this without a reason to believe the scope changed.

## Statistical/architecture decisions made
(Carried over from Phase 6.5, still governing; no new decisions this session.)
- Cross-engine/cross-library numeric comparisons use tolerance-based parity (`pytest.approx` /
  kind-equality), never exact bit-width or float equality — established for MySQL/DuckDB in
  Phase 6.5, explicitly extended in this handoff's "Exact next task" to Stats Lab's parity tests
  against `modules/stats_lab.py`.
- Every native workflow operates on the single shared `DatasetStore` (`overview.py`) so
  Overview/SQL Lab/AI Analyst/Clean/Visualize (and Stats Lab, once built) always see the same
  object identity and revision history — never a second, parallel store.
- Readiness (`/api/v1/platform/ready`) must never live-probe an optional provider (Ollama) —
  config-only status, so it can never hang or make the service falsely "not ready."
- Custom ARIA widgets use non-native elements (`<span>`, not `<button>`) for pointer-only
  affordances nested inside a `role="tab"`/similar container, with the real keyboard path
  provided separately (e.g. Delete/Backspace) — avoids the `nested-interactive` axe violation
  that a real `<button>` triggers even with `aria-hidden`+negative `tabindex`.

## Important invariants
- Legacy Streamlit app (`app.py`, `modules/*`) is the parity/rollback reference for every native
  slice and must never be modified as part of native-stack work; it remains production-default.
- No native workflow's `ReleaseChannel` flips to `ENABLED` until its own parity/quality gate
  passes — `stats` must land at `SHADOW` first (see "Exact next task" step 4).
- No secrets committed anywhere; `tools/check_secrets.py` must stay clean.
- CORS never `*` for credentialed traffic; SSE headers
  (`text/event-stream`, `Cache-Control: no-cache`, `X-Accel-Buffering: no`) must be preserved
  on any new streaming endpoint.
- Ollama must never be publicly exposed; any AI-adjacent slice (Stats' Atlas explain action
  included, once built) must work with `PRISM_AI_PROVIDER=deterministic` and no Ollama reachable.

## Git
Latest commit: `0d6753c8cb04597e0acfd55f52a169ee050bdff7` (this handoff's own commit)
Push status: `phase-7-advanced-analytics` is pushed and in sync with origin as of `0d6753c`.
PR: none open for `phase-7-advanced-analytics` (not requested by the task; PR #6, the only PR
in this lineage, is already merged and closed).
PR target: N/A (no open PR)
CI state: N/A for this branch (no PR triggers CI on a bare branch push in this repo's current
Actions config, per prior observation — only PR events did).

## Phase 7A gate status
Native Stats API: NOT STARTED
Stats workspace: NOT STARTED
Suggestion engine: NOT STARTED (port of `modules/stats_lab.py::suggest_test()`)
t-test: NOT STARTED
ANOVA: NOT STARTED
Chi-square: NOT STARTED
Pearson: NOT STARTED
Normality: NOT STARTED (Shapiro-Wilk pre-check port)
Assumption handling: NOT STARTED
Effect sizes: NOT STARTED (`_effect_size_label` port)
Insufficient-evidence semantics: NOT DESIGNED YET — needs a decision in the next session: what
`StatTestResult` returns when a column pair has too few non-null paired observations for a valid
test (legacy `modules/stats_lab.py` behavior on this case should be read and matched, not
reinvented).
Provenance: NOT STARTED — should follow the same `provenance` shape (`source_fingerprint`,
`dataset_revision`, `parameters`, `service_version`, `computed_at`) every other native workflow
already uses (see `AiContextPacket`/`VisualizationSpec` for the pattern).
Atlas integration: NOT STARTED — explicitly deferred until after the deterministic suggest/run
path is solid (see "Exact next task" step 2).
Legacy parity: NOT STARTED — parity tests are specified in "Exact next task" step 3 but not
written.
Accessibility: NOT APPLICABLE YET (no UI exists).
Regression: NOT APPLICABLE YET (no code exists to regress).

## Exact continuation order
1. Contracts: five new Pydantic models in `packages/api-contracts/python/prism_api_contracts/models.py`
   + `__init__.py` exports + regenerate TypeScript (`python tools/generate_typescript_contracts.py`).
2. Backend: `apps/api/src/prism_api/stats.py` (`suggest_test`, `run_test`, two routes), registered
   in `main.py`; `tests/api/test_stats.py` with the parity tests listed above, run against the
   real legacy `modules/stats_lab.py` functions in-process (import them directly in the test).
3. Migration state: `stats` entry at `SHADOW` in both `migration.py` and `shell-model.ts`.
4. Only once 1–3 are green (`pytest tests/api/test_stats.py -q`, `ruff`, `mypy` all clean):
   frontend `stats-workspace.tsx` + its test file, following `clean-workspace.tsx`'s pattern.
5. Atlas wiring (`AtlasStatsAction` + `.../atlas` route) after the deterministic path is fully
   tested — not before.
6. Flip `stats` to `ENABLED` only after a Playwright regression test (mocked) and an
   `e2e-live` integration test both pass, matching the bar every prior slice cleared.

## Files the next session should read first
- `PHASE7_BRIEF.md` (this branch) — full Stats/Forecasting/ML Lab priority and risk analysis.
- `modules/stats_lab.py` — the exact legacy logic to port (289 lines, small).
- `apps/api/src/prism_api/clean.py` — closest existing precedent for a native router's shape
  (detect/preview/apply/undo/atlas pattern; Stats needs suggest/run/atlas, a subset of this).
- `apps/api/src/prism_api/overview.py` — the shared `DatasetStore` Stats must read from.
- `packages/overview-analytics/python/prism_overview_analytics/service.py` — has
  `detect_column_types()`, which Stats' `suggest_test()` needs and must reuse, not reimplement.
- `packages/api-contracts/python/prism_api_contracts/models.py` — see the `CleanIssueKind`/
  `CleanIssue`/`AtlasCleanAction` section for the contract-shape pattern to mirror.
- `docs/migration/CURRENT_PHASE.md` — updated this session, states true current status.

## Files/directories the next session should NOT reread unless needed
- `RECOVERY_REPORT.md`, `PHASE5_FINAL_REPORT.md`, `PHASE6_IMPLEMENTATION_LEDGER.md`,
  `.prism/checkpoints/phase-6.md`, `.prism/checkpoints/phase-6.5-start.md`,
  `PRISM_IMPLEMENTATION_LEDGER.md` — historical, already fully reflected in
  `docs/migration/CURRENT_PHASE.md` and this handoff.
- `PHASE6_5_RELEASE_REPORT.md`, `.prism/checkpoints/phase-6.5.md`, `docs/ROLLBACK.md` — only
  needed if a Phase 6.5 regression is suspected; not needed for Stats Lab work.
- `modules/forecasting.py`, `modules/mllab.py` — Phase 7B/7C references, out of scope until 7A
  is gated (see Stop Boundary).
- `app.py` and the rest of `modules/*` beyond `stats_lab.py` — the legacy Streamlit app is the
  rollback reference, not something to read for Stats Lab implementation beyond that one file.

## Stop boundary
**Forecasting (Phase 7B) and ML Lab (Phase 7C) are forbidden until Stats Lab (7A) is fully
implemented, parity-tested against `modules/stats_lab.py`, accessibility-checked, and gated to
at least `SHADOW` (ideally `ENABLED` after its own frontend + e2e coverage lands).** Do not begin
either in the same session as 7A work without an explicit new instruction to do so.
