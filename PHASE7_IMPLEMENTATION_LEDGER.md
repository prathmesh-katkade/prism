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

## 7B — Forecasting (COMPLETE, ENABLED)

**Objective**: Give an analyst a bounded, deterministic path from a raw time
series to a forecast with visible uncertainty, a trend/seasonality
breakdown, and structural-break detection — never a point estimate
presented as certainty.

**Legacy reference**: `modules/forecasting.py` (453 lines) —
`prepare_series`, `run_forecast`, `forecast_caveat`, `can_decompose`,
`decompose_series`, `decomposition_verdict`, `detect_changepoints`,
`changepoint_verdict`, `_best_split`, `_segment_ss`.

**Files changed**:
- `packages/api-contracts/python/prism_api_contracts/models.py`,
  `__init__.py` — new contracts (below).
- `packages/api-contracts/typescript/src/generated.ts` — regenerated.
- `apps/api/src/prism_api/forecasting.py` (new) — the native router.
- `apps/api/src/prism_api/main.py` — router registration.
- `apps/api/src/prism_api/migration.py` — `forecasting` entry, `SHADOW` → `ENABLED`.
- `apps/api/requirements.txt` — `statsmodels==0.14.6` added *before*
  writing the router (applying 7A's own lesson), verified with a
  clean-venv install.
- `apps/web/src/components/forecasting-workspace.tsx` (new) — the workspace.
- `apps/web/src/components/prism-shell.tsx` — wired into `nativeKinds` and
  the workspace-surface dispatch.
- `apps/web/src/state/shell-model.ts` — `WorkspaceTab.kind` gained
  `"forecasting"`; `phaseTwoMigrations`' entry corrected `legacy` →
  `shadow` → `enabled`.
- `apps/web/app/prism.css` — `.forecasting-fields`, `.forecasting-canvas`,
  chart band/line/marker classes.
- `pyproject.toml` — `statsmodels`/`statsmodels.*` added to mypy's
  ignore-missing-imports.
- Tests: `tests/api/test_forecasting.py` (new, 17), `tests/api/test_contracts.py`
  and `tests/migration/test_phase_1_parity_hooks.py` (updated),
  `apps/web/src/components/forecasting-workspace.test.tsx` (new, 4),
  `apps/web/src/components/prism-shell.test.tsx` (updated),
  `apps/web/e2e/shell.spec.ts` (new Forecasting e2e test).

**Contracts**: `ForecastPoint`, `ForecastInterval`, `ForecastMetrics`,
`ForecastRequest`, `ForecastResult`, `DecomposeRequest`,
`DecompositionResult`, `ChangepointRequest`, `ChangepointFinding`,
`ChangepointResult`, `AtlasForecastAction/Request/Response`. Every result
reuses `OverviewProvenance`. Structured point/interval data only — legacy's
`build_forecast_chart`/`build_decomposition_chart`/`build_changepoint_chart`
(server-rendered Plotly figures) were deliberately **not** ported; the
frontend renders from this structured data instead, per rule 19.

**Analytical method**: `run_forecast()` tries Exponential Smoothing (ETS,
with a seasonal component when the series has ≥2 full seasonal cycles at
its inferred frequency) first, falling back to SARIMAX(1,1,1) on failure —
both ported verbatim, including the exact seasonal-period-by-frequency
table. `decompose_series()` runs STL (Seasonal-Trend decomposition using
LOESS) and computes trend/seasonal "strength" via the Hyndman &
Athanasopoulos variance-ratio heuristic. `detect_changepoints()` is a
from-scratch, dependency-free penalized binary segmentation (no `ruptures`
package), vectorized via prefix sums, with a BIC-style penalty as the
stopping rule.

**Assumptions**: Time-series validation happens before any model runs
(rule 20): duplicate timestamps are averaged, gaps are interpolated after
resampling to an inferred regular frequency, and a series with too few
distinct timestamps, an unparseable datetime column, or (for decomposition)
fewer than 2 full seasonal cycles fails as HTTP 422 with a specific reason.

**Parity**: Direct, in-process tests import `modules.forecasting` and
compare the native API's output against the legacy functions' own return
values on identical fixture series. Point-forecast values and STL
strengths matched to `pytest.approx(abs=1e-6)`; the forecast caveat's exact
wording matched (same function called with the same arguments — legitimately
exact, not a tolerance case); changepoint positions matched exactly (same
deterministic algorithm). No intentional behavioral corrections were made.
One genuine addition beyond legacy: a single train/test holdout (not k-fold,
per rule 37's bounded-compute constraint) that reuses `run_forecast()`
itself to compute MAE/RMSE/MAPE-when-not-degenerate as a diagnostic never
presented as the forecast itself.

**Tests**: 17 backend (`tests/api/test_forecasting.py`) + 4 frontend
component (`forecasting-workspace.test.tsx`) + 1 Playwright e2e with
axe-core (0 violations) + 2 updated cross-cutting migration-state
regression tests.

**Provenance**: Every result's `provenance` binds `source_fingerprint`/
`dataset_revision` to the exact revision the analysis ran against, via the
same shared `DatasetStore` every other workflow reads.

**Atlas**: Five actions — `explain_method` (why ETS vs. SARIMAX, with or
without seasonality), `explain_trend`, `explain_seasonality` (both reuse
`decompose_series()`'s own output), `explain_changepoints` (reuses
`detect_changepoints()`'s own output — cross-checked in tests against the
dedicated changepoints endpoint's result), `explain_intervals` (explicitly
states a point forecast without its band "is not the full picture" — never
hides uncertainty, per rule 23). Atlas never computes or alters a value.

**Accessibility**: 0 axe-core violations scoped to `.forecasting-workspace`
— native `<select>`/`<input>` elements for the series/mode/horizon
pickers, consistent with Stats' choice to avoid a custom widget where a
plain form control is the more accessible default.

**Performance**: No regression. Applied 7A's lesson from the start —
`statsmodels` imported at module load, verified with a direct timing check
that the very first request in a fresh process (~75ms) is in line with
every subsequent one (~71ms), i.e. no cold-import tax. The ~70ms itself is
legitimate ETS-fit compute time on a 10-point series, not a regression.

**Risks**: Medium (higher than Stats' low, matching the brief's original
risk assessment) — statsmodels' MLE fitting can occasionally raise
`ConvergenceWarning` on short or near-degenerate synthetic series (observed
in tests, not a failure — the fit still returns a usable result, matching
legacy's own tolerance for this). Real-world series with more natural
variation are less likely to trigger this than the clean synthetic
fixtures used in tests.

**Technical debt**: The `ForecastMetrics` diagnostic (holdout MAE/RMSE/MAPE)
has no legacy equivalent — it is a deliberate, bounded addition (rule 21),
not a gap. `AtlasForecastAction` was trimmed from rule 24's full seven-item
list to five (dropped `identify_weak_conditions` and
`suggest_alternative_horizon`) as under-scoped for this slice's first pass;
revisit if a future session finds analysts asking for them.

**Rollback**: Flip `forecasting`'s `channel` to `SHADOW`/`LEGACY` in
`migration.py` and `shell-model.ts` — no data migration, no code removal.

---

## 7C — ML Lab (COMPLETE, ENABLED)

**Objective**: Give an analyst a bounded baseline-exploration tool —
feature engineering suggestions, two comparable baseline models with
cross-validated stability, class-imbalance and leakage awareness, and
model explainability — framed throughout as *baseline exploration, not a
deployment pipeline*.

**Legacy reference**: `modules/mllab.py` (729 lines) — `suggest_features`,
`apply_suggestion`, `detect_task_type`, `run_baseline_models`,
`run_cross_validation`, `build_verdict`, `check_class_imbalance`,
`imbalance_explanation`, `explain_with_shap`, `shap_for_display`,
`run_feature_selection`.

**Files changed**:
- `packages/api-contracts/python/prism_api_contracts/models.py`,
  `__init__.py` — new contracts (below).
- `packages/api-contracts/typescript/src/generated.ts` — regenerated.
- `apps/api/src/prism_api/mllab.py` (new) — the native router.
- `apps/api/src/prism_api/main.py` — router registration.
- `apps/api/src/prism_api/migration.py` — `ml` entry, `SHADOW` → `ENABLED`.
- `apps/api/requirements.txt` — `scikit-learn==1.6.1`,
  `imbalanced-learn==0.12.4`, `shap==0.49.1` added *before* writing the
  router, verified with a clean-venv install.
- `apps/web/src/components/mllab-workspace.tsx` (new) — the workspace.
- `apps/web/src/components/prism-shell.tsx` — wired into `nativeKinds` and
  the workspace-surface dispatch (the last of the eight navigation
  workflows to leave the migration bridge).
- `apps/web/src/state/shell-model.ts` — `WorkspaceTab.kind` gained `"ml"`;
  `phaseTwoMigrations`' entry corrected `legacy` → `shadow` → `enabled`.
- `apps/web/app/prism.css` — `.mllab-fields`, `.mllab-results`,
  `.mllab-checkbox`, `.mllab-feature-list`.
- `pyproject.toml` — `sklearn`/`sklearn.*`, `imblearn`/`imblearn.*`,
  `shap`/`shap.*` added to mypy's ignore-missing-imports.
- Tests: `tests/api/test_mllab.py` (new, 18), `tests/api/test_contracts.py`
  and `tests/migration/test_phase_1_parity_hooks.py` (updated),
  `apps/web/src/components/mllab-workspace.test.tsx` (new, 3),
  `apps/web/src/components/prism-shell.test.tsx` (updated),
  `apps/web/e2e/shell.spec.ts` (new ML Lab e2e test).

**Contracts**: `MlSuggestionType`, `MlFeatureSuggestion(s)`,
`MlApplyFeatureRequest/Response`, `MlTaskType`, `MlTaskDetectionResponse`,
`MlImbalanceInfo`, `MlCvMetric/Result`, `MlFeatureImportance`,
`MlBaselineRequest/Result`, `MlFeatureSelectionRequest/Result`,
`MlFeatureRankingRow`, `MlShapRequest/Result`, `MlShapImportance`,
`AtlasMlAction/Request/Response`. Every result reuses `OverviewProvenance`.
No fitted model object or raw transformed array ever crosses the HTTP
boundary (rule 46) — only JSON-serializable metrics, rankings, and
importances.

**Analytical method**: Task detection is dtype/cardinality-driven,
deterministic, never LLM-decided (numeric + ≤15 distinct values + <5% of
rows → classification; else regression; non-numeric → classification).
Baseline models are a small, defensible pair (Logistic/Linear Regression
vs. Random Forest, `n_estimators=200`) — no model zoo. Preprocessing is a
`ColumnTransformer` (median-impute + standard-scale numeric, most-frequent-
impute + one-hot categorical) fit on the training split only. Feature
selection cross-checks three independent methods (Mutual Information, an
L1-regularized linear model, Recursive Feature Elimination with a Random
Forest estimator) and reports consensus rather than trusting any single
ranking. SHAP explains the Random Forest specifically via `TreeExplainer`
(fast, exact for tree ensembles), collapsing multi-class output to the
class the model's decisions hinge on most.

**Assumptions**: Class imbalance is checked and reported (`<20%` minority
threshold, matching legacy), gated to classification targets only. SMOTE
(when requested) is applied to the training set alone, after the split —
`modules/mllab.py`'s own `SMOTE_TEST_SET_NOTE` reasoning, preserved as this
module's `LEAKAGE_NOTE`. Cross-validation fold counts are capped down for
small or imbalanced datasets exactly like legacy, degrading gracefully
rather than raising.

**Parity**: Direct, in-process tests import `modules.mllab` and compare the
native API's output against the legacy functions' own return values on
identical fixture DataFrames (fixed `random_state=42` throughout, matching
legacy exactly). Baseline metrics, confusion matrices, and cross-validation
fold means matched exactly/to tight tolerance. SHAP's global importance
was sanity-checked (shape, sign, sort order) rather than parity-asserted
value-by-value — TreeExplainer is deterministic for a fixed model, but
SHAP's own internals are more sensitive to environment/version drift than
scipy's closed-form tests, so this follows rule 39's explicit tolerance
allowance rather than 7A's stricter bar. No intentional behavioral
corrections were made.

**Tests**: 18 backend (`tests/api/test_mllab.py`) + 3 frontend component
(`mllab-workspace.test.tsx`) + 1 Playwright e2e with axe-core (0
violations) + 2 updated cross-cutting migration-state regression tests.

**Provenance**: Every result's `provenance` binds `source_fingerprint`/
`dataset_revision` to the exact revision the analysis ran against, via the
same shared `DatasetStore` every other workflow reads. `apply-feature`
(which modifies data) produces a new revision rather than mutating in
place, exactly like Clean.

**Atlas**: Six actions — `explain_task_type`, `compare_models`,
`explain_cross_validation`, `explain_imbalance`, `explain_feature_importance`,
`identify_overfitting` (compares the holdout score against the cross-
validated mean and flags a meaningful gap) — trimmed from rule 38's full
list to the essentials for this first pass (SHAP-specific and leakage/
overfitting-risk actions beyond `identify_overfitting` were judged
under-scoped; the SHAP endpoint's own `note` field already carries
explanatory framing). Atlas never computes, retrains, or alters a model —
every response reads `run_baseline_models()`'s own deterministic output.

**Accessibility**: 0 axe-core violations scoped to `.mllab-workspace`. A
real gap was found and fixed here: wide result tables need `tabIndex={0}`
on their `.data-table-wrap` container to be keyboard-focusable scrollable
regions — see "Technical debt" below for the same latent gap elsewhere.

**Performance**: No regression. Applied 7A/7B's lessons from the start —
all three heavy libraries imported at module load, verified with a direct
timing check that the very first ML request in a fresh process is in line
with subsequent ones. ~1.4s per baseline run (fitting 2 models twice —
once for the holdout, once inside 5-fold CV — plus Random Forest's 200
trees) is legitimate bounded compute for an interactive baseline-
exploration tool, not a regression to fix.

**Risks**: Highest of the three 7A/7B/7C slices, as anticipated in
`PHASE7_BRIEF.md`'s original risk assessment — model training carries more
moving parts (SMOTE's neighbor-count sensitivity on small classes, SHAP's
additivity-check false positive on ensemble averaging, both already
encountered and handled during this slice using legacy's own documented
workarounds) than the closed-form computations in 7A/7B.

**Technical debt**:
- The `.data-table-wrap` keyboard-focusability gap (see Accessibility)
  exists in `clean-workspace.tsx`, `overview-workspace.tsx`, and
  `stats-workspace.tsx` too — not fixed there in this slice since none of
  those files were otherwise touched this phase; a small follow-up should
  add `tabIndex={0}` to their `.data-table-wrap` usages too.
- SHAP's local (per-row) explanation was scoped out — only global
  (mean-|SHAP|-per-feature) importance is exposed, per this slice's
  bounded first pass. `modules/mllab.py` itself only builds a global
  explainability view in its own UI too, so this is parity, not a gap
  relative to legacy.
- `AtlasMlAction` was trimmed from rule 38's full list — see Atlas above.

**Rollback**: Flip `ml`'s `channel` to `SHADOW`/`LEGACY` in `migration.py`
and `shell-model.ts` — no data migration, no code removal.

---

**Phase 7 is now complete.** All three slices (7A Stats Lab, 7B
Forecasting, 7C ML Lab) are native and `ENABLED`. See
`PHASE7_FINAL_REPORT.md` for the full cross-slice summary.
