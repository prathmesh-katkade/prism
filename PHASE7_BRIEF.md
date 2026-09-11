# PRISM — Phase 7 Brief: Advanced Analytics

**Status: planning only. No Phase 7 implementation is included in this
branch.** This document exists to unlock a clean phase boundary after
Phase 6.5's release gate passed (`PHASE_7_UNLOCKED = YES` — see
`PHASE6_5_RELEASE_REPORT.md`).

- Branch: `phase-7-advanced-analytics`
- Based on: `phase-6.5-integration-staging` @ `ee17be4`
  (equivalently, `prism-native-v0.6` @ `349943f` plus the release-report
  amendment commit)

---

## 1. Scope

Phase 7 migrates the remaining legacy Streamlit analytical modules to the
native Next.js + FastAPI stack, following the same vertical-slice pattern
established in Phase 5 (AI Analyst) and Phase 6 (Clean, Visualize): each
module gets a native API router backed by the shared `DatasetStore`
(including its revision history), a native React workspace panel wired
into the shell's tab system, an `AtlasCleanAction`/`AtlasVisualizeAction`-style
contract for Atlas explain/trust integration, and full parity/provenance
guarantees with its legacy counterpart before its migration channel flips
from `LEGACY`/`SHADOW` to `ENABLED`.

Three legacy modules are in scope, in the priority order below:

### 7A. Stats Lab (`modules/stats_lab.py`, 289 lines) — highest priority
Deterministic, no ML dependency, smallest surface — good first slice to
re-establish the migration rhythm.
- `suggest_test()` — picks an appropriate statistical test (t-test, ANOVA,
  chi-squared, Pearson) from column types, including a Shapiro-Wilk
  normality pre-check (`_shapiro_check`).
- `run_ttest`/`run_anova`/`run_chi2`/`run_pearson()` — the four test
  implementations.
- `interpret_result()` / `normality_warnings()` — plain-language
  interpretation and caveats, which map naturally onto AI Analyst's
  existing `uncertainty`/`limiting_factors` evidence pattern.
- **Native migration shape**: `apps/api/src/prism_api/stats.py` with
  routes mirroring Clean's shape (`GET .../suggest`, `POST .../run`,
  `POST .../atlas`), reusing `DatasetStore` for the active revision so a
  stats test always runs against the same object identity Overview/SQL
  Lab/Clean are showing.
- **Risk**: low. All four tests are pure `scipy`/`numpy` computations with
  no external I/O — parity testing is a direct value-for-value comparison
  against the legacy module's output on the same fixture dataset.

### 7B. Forecasting (`modules/forecasting.py`, 453 lines) — second priority
- `prepare_series()` / `run_forecast()` — time-series prep and forecasting
  (uses `statsmodels`-family models judging by `_infer_seasonal_periods`
  and seasonal decomposition).
- `decompose_series()` / `detect_changepoints()` — STL-style decomposition
  and a custom changepoint detector (`_best_split`/`_segment_ss` — a
  variance-minimizing binary-split algorithm, not a third-party
  dependency, so it should port cleanly).
- Legacy module also builds Plotly figures directly
  (`build_forecast_chart`, `build_decomposition_chart`,
  `build_changepoint_chart`) — Phase 7's native version should instead
  return structured data (points, bands, changepoint markers) through the
  API and let the frontend render it, following Visualize's existing
  `VisualizationDataResponse` pattern rather than shipping server-rendered
  Plotly figures to the client.
- **Risk**: medium. Time-series parity is more sensitive to library-version
  differences than Stats Lab's closed-form tests; forecast confidence
  bands in particular should be compared with a tolerance, not exact
  equality, consistent with the MySQL-parity precedent set in Phase 6.5
  ("analytical semantic parity matters more than exact numeric equality").

### 7C. ML Lab (`modules/mllab.py`, 729 lines) — third priority, largest scope
- `suggest_features()` / `apply_suggestion()` — feature engineering
  suggestions and application (likely needs the same revision-aware
  `DatasetStore.add_revision` pattern Clean already established, since
  feature engineering is itself a data transformation).
- `run_baseline_models()` / `run_cross_validation()` — baseline model
  training and CV, per `detect_task_type()` (classification vs.
  regression).
- `explain_with_shap()` / `shap_for_display()` — SHAP-based
  explainability — this is the most natural hook into Atlas's
  explain/trust surface (`AtlasVisualizeAction`-equivalent
  `AtlasMlAction`), since SHAP values are themselves a
  "why did the model produce this" evidence object.
- `check_class_imbalance()` / `run_feature_selection()` — additional
  diagnostics.
- **Risk**: highest of the three. Model training is non-deterministic
  across library versions/seeds even with fixed random_state in some
  cases (SHAP KernelExplainer sampling, cross-validation fold assignment);
  parity testing will need explicit seeding and either exact-match on
  deterministic paths or documented tolerance bands elsewhere, mirroring
  Phase 6.5's stance on cross-engine numeric parity rather than demanding
  bit-exact reproduction. This module is also the most compute-heavy of
  the three — worth an early check on Render's free-tier CPU/memory limits
  before committing to hosting baseline model training there.

---

## 2. Existing scaffolding to build on

Two packages already exist in the monorepo as forward-looking scaffolding,
not yet wired into any router or component:

- **`packages/analytical-schemas`** (`prism_analytical_schemas`) —
  `ObjectKind` enum already includes `ANALYSIS` alongside `PROFILE`,
  `QUERY_RESULT`, `CLEANING_PLAN`, `VISUALIZATION`; `AnalyticalObject` (a
  generic `dataset`+`kind`+`payload` envelope) is the natural contract for
  a Stats/Forecasting/ML result to travel through the API as an
  Atlas-explainable object, the same way `VisualizationSpec` does today.
- **`packages/atlas-interfaces`** (`prism_atlas_interfaces`) —
  `AtlasCommand`/`AtlasCommandType`/`AtlasCommandStatus` (NAVIGATE/ANALYZE/
  QUERY, with a `requires_confirmation` flag) look like the intended
  general command surface Atlas will eventually use across all workflows,
  as opposed to the per-workflow `AtlasCleanAction`/`AtlasVisualizeAction`
  request/response pairs added ad hoc in Phase 6. Phase 7 is a good point
  to decide whether to adopt this generalized command contract for
  Stats/Forecasting/ML's Atlas integration, or continue the per-workflow
  pattern — worth a short design decision at the start of Phase 7 rather
  than mid-slice.

Both packages currently have no consumers (`tools/check_boundaries.py`
should confirm this at the start of Phase 7, to catch any drift since this
brief was written).

---

## 3. Migration state machine

`apps/api/src/prism_api/migration.py` (`PHASE_1_MIGRATIONS`) and
`apps/web/src/state/shell-model.ts` (`phaseTwoMigrations`) will need three
new entries — `stats`, `forecasting`, `ml-lab` — each starting at
`ReleaseChannel.SHADOW` (or `LEGACY`, matching whatever the repo's existing
convention is for a not-yet-user-facing native slice) and flipping to
`ENABLED` only once that slice's own parity/quality gate passes, exactly
as Overview/SQL Lab/AI Analyst/Clean/Visualize did.

---

## 4. Suggested sequencing

1. **Stats Lab** first — smallest, deterministic, fastest to re-establish
   the vertical-slice rhythm and prove the pattern still holds after the
   Phase 6.5 infrastructure changes (config boundary, readiness endpoint,
   structured logging).
2. **Forecasting** second — introduces the "server computes, client
   renders" chart-data contract shift (moving off server-rendered Plotly
   figures), which is worth landing before ML Lab so ML Lab's own charts
   (confusion matrix, feature importance, class distribution) can reuse
   the same contract instead of inventing another one.
3. **ML Lab** last — largest, most compute-sensitive, and the first true
   test of Atlas's explain/trust surface against a genuinely
   non-deterministic computation (model training), so it benefits most
   from the contract and parity conventions the first two slices settle.

Each slice should repeat Phase 5/6/6.5's now-established loop: native API
router → native workspace component → shared `DatasetStore`
integration → parity test against the legacy module on a fixture
dataset → Atlas action wiring → accessibility check → migration channel
flip → checkpoint doc.

---

## 5. Explicit non-goals for this brief

This document is planning only. Per Phase 6.5's closing instruction, no
Phase 7 code, contracts, routes, or components are implemented in this
branch — that work starts in a future session once this brief is
reviewed.
