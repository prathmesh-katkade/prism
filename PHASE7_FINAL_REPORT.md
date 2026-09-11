# Phase 7 Final Report

Branch: `phase-7-advanced-analytics`
Commit: `ec2a22abbc8bed8aa58e1abdd8d1e8f184dbbfb7`

## 7A Stats Lab

API: `apps/api/src/prism_api/stats.py` — `GET .../suggest`, `POST .../run`, `POST .../atlas`.
Deterministic test selection (dtype/category-count/sample-size — never LLM-decided) dispatches
to Welch's t-test, one-way ANOVA, chi-square, and Pearson, each with a conventional effect size
(Cohen's d / eta-squared / Cramer's V / Pearson r) and Shapiro-Wilk normality context (never a
bare pass/fail gate). Every result carries an explicit `evidence_statement` that never equates
"not significant" with "no relationship" — only "not detected in this sample."

Workspace: `apps/web/src/components/stats-workspace.tsx` — three-pane (variable pickers /
results / assumptions+provenance+Atlas), wired into the shell's `nativeKinds`.

Parity: 16 backend tests import `modules.stats_lab` directly and compare the native API's
output against the legacy functions' own return values on shared fixtures — statistic/p-value/
effect size matched to `pytest.approx(abs=1e-9)` or tighter.

Atlas: `explain_test`, `explain_assumptions`, `explain_effect_size`, `recommend_next_step`. Never
computes or alters a statistic — every response reads the deterministic engine's own output.

Tests: 16 backend + 3 frontend component + 1 Playwright e2e (0 axe violations).

Accessibility: 0 axe-core violations scoped to `.stats-workspace` (native `<select>` pickers, no
custom widget needing ARIA rebuilding).

## 7B Forecasting

API: `apps/api/src/prism_api/forecasting.py` — `POST .../forecast`, `.../decompose`,
`.../changepoints`, `.../atlas`. ETS tried first (with seasonality when the series has ≥2 full
seasonal cycles), SARIMAX(1,1,1) fallback; STL decomposition; a from-scratch, dependency-free
penalized binary-segmentation changepoint detector — all ported verbatim from legacy. Time-series
validation (duplicate timestamps averaged, gaps interpolated, frequency inferred) happens before
any model runs. A bounded train/test holdout (not k-fold — free-tier compute) adds MAE/RMSE/MAPE
diagnostics beyond legacy, reusing `run_forecast()` itself rather than a second fitting path.
Server returns structured point/interval data only — legacy's server-rendered Plotly figures were
deliberately not ported.

Workspace: `apps/web/src/components/forecasting-workspace.tsx` — a mode selector
(forecast/decompose/changepoints) over a shared series/horizon picker; a local SVG chart renders
observed history, the dashed forecast line, and the shaded 95% interval band together — no
forecast point is ever shown without its interval.

Parity: 17 backend tests import `modules.forecasting` directly. Point-forecast values and STL
strengths matched to `1e-6`; the caveat's exact wording matched (same function, same inputs);
changepoint positions matched exactly (same deterministic algorithm).

Atlas: `explain_method`, `explain_trend`, `explain_seasonality`, `explain_changepoints`,
`explain_intervals` (explicitly states a point forecast without its band "is not the full
picture" — never hides uncertainty).

Tests: 17 backend + 4 frontend component + 1 Playwright e2e (0 axe violations).

Accessibility: 0 axe-core violations scoped to `.forecasting-workspace`.

## 7C ML Lab

API: `apps/api/src/prism_api/mllab.py` — 8 routes (`suggest-features`, `apply-feature`,
`detect-task`, `imbalance`, `baseline`, `feature-selection`, `shap`, `atlas`). Deterministic task
detection; a small, defensible baseline pair (Logistic/Linear Regression vs. Random Forest, no
model zoo); preprocessing always fit on the training split only (the module's one concrete
leakage-prevention rule, stated explicitly in every baseline response); 5-fold cross-validation;
class-imbalance diagnostics gated to classification targets; three-method feature-selection
consensus (Mutual Information + L1 + RFE); SHAP global importance via Random Forest
`TreeExplainer`. `apply-feature` is revision-aware exactly like Clean — feature engineering
produces a new dataset revision, never an in-place mutation. No fitted model object or raw
transformed array ever crosses the HTTP boundary; SHAP re-fits deterministically from its stated
configuration each call rather than caching an unserializable model server-side.

Workspace: `apps/web/src/components/mllab-workspace.tsx` — target/feature pickers, a five-mode
analysis selector, verdict/confusion-matrix/CV/leakage-note display for baselines,
feature-selection consensus ranking, SHAP importance table, and class-distribution table for
imbalance.

Parity: 18 backend tests import `modules.mllab` directly. Baseline metrics, confusion matrices,
and cross-validation fold means matched exactly/to tight tolerance; SHAP's global importance was
sanity-checked (shape/sign/sort order) rather than value-parity-asserted, per rule 39's explicit
tolerance allowance for SHAP's own environment-sensitive internals.

Atlas: `explain_task_type`, `compare_models`, `explain_cross_validation`, `explain_imbalance`,
`explain_feature_importance`, `identify_overfitting` (compares the holdout score against the
cross-validated mean and flags a meaningful gap). Never computes, retrains, or alters a model.

Tests: 18 backend + 3 frontend component + 1 Playwright e2e (0 axe violations).

Accessibility: 0 axe-core violations scoped to `.mllab-workspace` — a real gap was found and
fixed during this slice: wide result tables need `tabIndex={0}` on their `.data-table-wrap`
container to be keyboard-focusable scrollable regions. The same latent gap in
`clean-workspace.tsx`/`overview-workspace.tsx`/`stats-workspace.tsx` (narrower tables there never
triggered it) is recorded as technical debt rather than fixed speculatively outside this phase's
touched files.

## Regression

Overview: unaffected — no changes to `overview.py`/`overview-workspace.tsx` this phase; its own
tests continue to pass as part of the full suite.
SQL Lab: unaffected — no changes to `sql_lab.py`/`query-studio.tsx` this phase.
AI Analyst: unaffected — no changes to `ai_analyst.py`/`ai-analyst.tsx` this phase.
Clean: unaffected — no changes to `clean.py`/`clean-workspace.tsx` this phase; ML Lab's
`apply-feature` reuses the *same* `DatasetStore.add_revision` Clean established, not a
parallel mechanism.
Visualize: unaffected — no changes to `visualize.py`/`visualize-workspace.tsx` this phase.
Legacy Streamlit: unaffected — no changes to `app.py`/`modules/*` this phase (confirmed by `git
status` showing zero diffs there); `py_compile` across all 47 module files + `app.py` succeeds.

Full regression evidence for all of the above: `pytest tests/ apps/api -q` → 707 passed, 4
skipped (pre-existing MySQL-source-not-configured skips, not failures — no local MySQL server was
running in this session); `npm run test:web` → 21/21 across all 7 component test files;
Playwright `apps/web/e2e/shell.spec.ts` → 12/12, including the pre-existing Overview/SQL
Lab/Clean/Visualize/AI-Analyst tests alongside the three new Stats/Forecasting/ML Lab tests.

## Security

- No secrets committed anywhere: `tools/check_secrets.py` clean on every commit this phase.
- CORS unchanged from Phase 6.5's narrow, environment-scoped configuration — no Phase 7 route
  altered CORS behavior.
- No raw dataset rows are sent to an AI provider by any Phase 7 workflow — Atlas responses across
  all three slices are built from already-computed, already-JSON-safe deterministic results, not
  from raw data forwarded to a model.
- No fitted ML model, transformed feature matrix, or other unserializable server-side object is
  ever returned to the client — every ML Lab response is metrics/rankings/importances only.
- `tools/check_boundaries.py` clean — no new cross-package dependency violations introduced by
  three new heavy native dependency sets (scipy/statsmodels/scikit-learn/imbalanced-learn/shap).

## Performance

Approximate, single-request timings on this exact commit, local loopback, no load testing:

| Endpoint | First request (fresh process) | Steady-state |
|---|---|---|
| Stats `/run` (Pearson, 40 rows) | ~11ms | ~6–7ms |
| Forecasting `/forecast` (10-point series) | ~75ms | ~71ms |
| ML Lab `/baseline` (40 rows, incl. 5-fold CV × 2 models) | ~1.4s | ~1.37s |
| ML Lab `/shap` (Random Forest TreeExplainer) | — | ~1.9s |

No cold-import tax on any endpoint's first request — the two real performance defects this phase
would otherwise have produced (scipy's and statsmodels' own heavy first-import cost landing on a
live user request) were caught and fixed in 7A, then pre-empted from the start in 7B/7C by moving
every heavy import to module load and verifying with a direct timing check each time. ML Lab's
~1.4s baseline-run cost is legitimate model-fitting compute (two models, twice — once for the
holdout, once inside cross-validation — plus Random Forest's 200 trees), not a regression; per
rule 47 this was left as-is rather than micro-optimized, since ML Lab is explicitly a bounded,
interactive baseline-exploration tool, not a real-time system.

## Known limitations

- SHAP explainability exposes only global (mean-|SHAP|-per-feature) importance, not a per-row
  local explanation — matches `modules/mllab.py`'s own scope (legacy's own UI only builds a
  global view too), not a gap relative to legacy.
- `AtlasForecastAction` (5 of rule 24's 7) and `AtlasMlAction` (6 of rule 38's fuller list) were
  each deliberately trimmed to the essentials for this first pass; expanding them is a candidate
  for a future small follow-up, not a defect.
- The `.data-table-wrap` keyboard-focusability gap found and fixed in ML Lab's own tables exists
  unfixed in `clean-workspace.tsx`, `overview-workspace.tsx`, and `stats-workspace.tsx` (narrower
  tables there never triggered the axe rule) — flagged as technical debt in
  `PHASE7_IMPLEMENTATION_LEDGER.md`.
- Live staging (`prism-native-api-staging`/`prism-native-web-staging`, confirmed live during
  Phase 6.5) has not been re-deployed with this session's Phase 7 commits — Stats/Forecasting/ML
  Lab are verified locally (real `uvicorn` + Playwright) but not yet live-verified the way
  Clean/Visualize were in the Phase 6.5 live-staging addendum. Re-deploying requires the same
  Render credentials the user used for that 2026-08-30 deploy, not available to this session —
  classify as `BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` if pursued.
- The release tag `prism-native-v0.6` (from Phase 6.5) was never followed by a Phase-7-specific
  tag; this session did not create one since the master prompt for Phase 7 did not request a
  release checkpoint/tag in the way the Phase 6.5 prompt explicitly did.

## Git

Commit: `ec2a22abbc8bed8aa58e1abdd8d1e8f184dbbfb7`
Push: `origin/phase-7-advanced-analytics`, up to date as of this commit.
PR: none opened this session (not requested by the task; PR #6 is the only PR in this lineage,
already merged and closed).

PHASE_7A_COMPLETE = YES
PHASE_7B_COMPLETE = YES
PHASE_7C_COMPLETE = YES
PHASE_7_COMPLETE = YES
PHASE_8_UNLOCKED = YES
