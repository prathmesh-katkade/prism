# Phase 7 Implementation Ledger

Tracks each Phase 7 capability against the required fields: Objective,
Legacy reference, Files changed, Contracts, Analytical method, Assumptions,
Parity, Tests, Provenance, Atlas, Accessibility, Performance, Risks,
Technical debt, Rollback.

---

## 7A — Stats Lab (COMPLETE, ENABLED)

**Objective**: Give an analyst a guided path from "pick two variables" to a
statistically sound test result — deterministic test selection, the
statistic/p-value/effect size, explicit assumption warnings, and an
evidence statement that never overstates what a null result means.

**Legacy reference**: `modules/stats_lab.py` (289 lines) — `suggest_test`,
`run_ttest`, `run_anova`, `run_chi2`, `run_pearson`, `interpret_result`,
`normality_warnings`, `_shapiro_check`, `_effect_size_label`.

**Files changed**:
- `packages/api-contracts/python/prism_api_contracts/models.py`,
  `__init__.py` — new contracts (below).
- `packages/api-contracts/typescript/src/generated.ts` — regenerated.
- `apps/api/src/prism_api/stats.py` (new) — the native router.
- `apps/api/src/prism_api/main.py` — router registration.
- `apps/api/src/prism_api/migration.py` — `stats` entry, `SHADOW` → `ENABLED`.
- `apps/web/src/components/stats-workspace.tsx` (new) — the workspace.
- `apps/web/src/components/prism-shell.tsx` — `StatsWorkspace` wired into
  `nativeKinds` and the workspace-surface dispatch.
- `apps/web/src/state/shell-model.ts` — `WorkspaceTab.kind` gained `"stats"`;
  `phaseTwoMigrations`' `stats` entry corrected `legacy` → `shadow` → `enabled`.
- `apps/web/app/prism.css` — `.stats-fields`, `.stats-results`, `.stat-evidence`.
- `pyproject.toml` — `scipy`/`scipy.*` added to mypy's ignore-missing-imports.
- `.gitignore` — `*.tsbuildinfo`.
- Tests: `tests/api/test_stats.py` (new, 16), `tests/api/test_contracts.py`
  and `tests/migration/test_phase_1_parity_hooks.py` (updated for the new
  workflow), `apps/web/src/components/stats-workspace.test.tsx` (new, 3),
  `apps/web/src/components/prism-shell.test.tsx` (updated), `apps/web/e2e/shell.spec.ts`
  (new Stats e2e test).

**Contracts**: `StatTestKind`, `StatNormalityCheck`, `StatSuggestionResponse`,
`StatTestRequest`, `StatTestResult`, `AtlasStatsAction`, `AtlasStatsRequest`,
`AtlasStatsResponse`. `StatTestResult` reuses the existing `OverviewProvenance`
shape rather than inventing a parallel one.

**Analytical method**: Deterministic test selection by column dtype pair
(numeric+numeric → Pearson; numeric+categorical → t-test if the categorical
column has exactly 2 levels, else one-way ANOVA up to `MAX_GROUPS_FOR_TEST`
(10); categorical+categorical → chi-square). Test implementations use
`scipy.stats` (`ttest_ind` with `equal_var=False`, i.e. Welch's t-test;
`f_oneway`; `chi2_contingency`; `pearsonr`), each paired with a conventional
effect size (Cohen's d, eta-squared, Cramer's V, Pearson r) and the
small/medium/large thresholds from `modules/stats_lab.py` verbatim.

**Assumptions**: Shapiro-Wilk normality check (subsampled above 5,000
points, matching legacy's `SHAPIRO_MAX_N`) surfaced as p-value + note, never
a bare pass/fail — the UI and Atlas can explain why a "non-normal" flag on
a huge sample means less than it would on a small one. Chi-square flags when
>20% of expected cell counts fall below 5. Minimum-sample and
minimum-group-count preconditions (mirroring legacy) raise HTTP 422 with a
specific message rather than silently returning a degenerate result.

**Parity**: Direct, in-process tests import `modules.stats_lab` and compare
the native API's JSON response against the legacy function's own return
value on identical fixture DataFrames — not a re-derivation, the actual
legacy code path. Tolerance-based (`pytest.approx`, abs 1e-6–1e-9), per the
precedent Phase 6.5 set for cross-library numeric comparison. No
intentional behavioral corrections were made in this slice — the native
implementation matches legacy's statistics, warnings-triggering thresholds,
and effect-size conventions exactly. One adaptation (not a correctness
fix): normality checks are returned as a typed list (`subject`/`p_value`/
`is_normal`/`note`) instead of legacy's `{name: check}` dict, for stable
JSON shape regardless of group-name characters.

**Tests**: 16 backend (`tests/api/test_stats.py`) + 3 frontend component
(`stats-workspace.test.tsx`) + 1 Playwright e2e with axe-core (0
violations) + 2 updated cross-cutting migration-state regression tests.

**Provenance**: Every `StatTestResult.provenance` binds
`source_fingerprint`/`dataset_revision` to the exact revision the test ran
against (via the shared `DatasetStore`, the same one Overview/SQL
Lab/AI Analyst/Clean/Visualize read), plus `service_version` and
`computed_at`. Verified with a dedicated test that the returned provenance
matches the dataset's actual current revision.

**Atlas**: Four actions — `explain_test` (why this test was suggested),
`explain_assumptions` (what the warnings mean), `explain_effect_size` (what
the magnitude means, using the exact number `run_test()` computed — verified
by cross-checking the value in both the API and component test suites),
`recommend_next_step` (a next analytical step, e.g. "inspect the raw
distribution" when not significant). Atlas never computes or alters a
statistic — every response is built from a `run_test()`/`suggest_test()`
call, not invented.

**Accessibility**: 0 axe-core violations scoped to `.stats-workspace`
(native `<select>` elements for variable pickers, no custom widget needing
ARIA rebuilding — deliberately avoided reinventing Clean/Visualize's
button-list pattern here since a plain dropdown is the more accessible
default for "pick one of N options").

**Performance**: See the checkpoint's "Real defect found and fixed" note —
scipy's import moved from lazy (inside each handler) to module-load time
after measuring a ~365ms first-request cost; fixed to ~11ms.

**Risks**: Low. All four tests are closed-form `scipy.stats` calls with no
external I/O, no model training, no non-determinism beyond `numpy`'s fixed-
seed Shapiro subsampling (seeded at 0, matching legacy).

**Technical debt**: None introduced. The `StatSuggestionResponse` and
`StatTestRequest` contracts intentionally share nullable
`numeric_col`/`cat_col` fields across all four test kinds (only
t-test/ANOVA use them) rather than a discriminated union per test kind —
mirrors `CleanTransformationRequest`'s existing precedent of one shape with
optional fields rather than a union, for consistency with the rest of the
contract layer.

**Rollback**: Flip `stats`'s `channel` to `SHADOW`/`LEGACY` in
`migration.py` and `shell-model.ts` — no data migration, no code removal.

---

## 7B — Forecasting (NOT STARTED)

Not implemented in this session. See `PHASE7_BRIEF.md` for the planned
scope (`modules/forecasting.py`: series prep, decomposition, forecast
generation with intervals, changepoint detection) and sequencing rationale.

## 7C — ML Lab (NOT STARTED)

Not implemented in this session. See `PHASE7_BRIEF.md` for the planned
scope (`modules/mllab.py`: task detection, baseline models, cross-
validation, feature selection, SHAP) and sequencing rationale.
