# Phase 7B Checkpoint — Native Forecasting

- Branch: `phase-7-advanced-analytics`
- Head commit: `cb22c9f`
- Date: 2026-08-29
- Legacy reference: `modules/forecasting.py` (unchanged, remains the parity/rollback oracle)

## Gate summary (PASS/FAIL)

| Gate | Status | Notes |
|---|---|---|
| Native Forecast API | PASS | `apps/api/src/prism_api/forecasting.py`: `POST .../forecast`, `.../decompose`, `.../changepoints`, `.../atlas`, registered in `main.py`. |
| Native Forecast workspace | PASS | `apps/web/src/components/forecasting-workspace.tsx`, three-pane with a mode selector (forecast/decompose/changepoints). |
| Series preparation | PASS | `prepare_series()` ported exactly: duplicate-timestamp averaging, frequency inference with a median-gap fallback, gap interpolation. Validation-failure tests for bad frequency, unparseable dates, and too-few-points. |
| Forecast generation | PASS | ETS tried first, SARIMAX fallback, both ported exactly with the same seasonal-period inference. |
| Intervals | PASS | Every forecast point ships with its interval, in both the API response and the rendered chart; a dedicated test (`test_forecast_returns_a_point_forecast_with_an_interval_for_every_point`) and a component test assert this explicitly. |
| Decomposition | PASS | STL trend/seasonal/residual ported exactly; reconstruction verified (`observed = trend + seasonal + residual`, tolerance 1e-6). |
| Changepoints | PASS | The from-scratch penalized binary-segmentation algorithm ported exactly (no `ruptures` dependency, matching legacy); position and delta matched exactly against legacy on a planted level-shift fixture. |
| Diagnostics | PASS | A single train/test holdout (not k-fold — bounded, free-tier-friendly compute) reusing `run_forecast()` itself; MAE/RMSE always, MAPE only when the holdout has no zero actuals. A genuine analytical addition beyond legacy, never presented as the forecast itself. |
| Provenance | PASS | Every result's `provenance` binds `source_fingerprint`/`dataset_revision` to the exact revision forecast against, tested directly. |
| Atlas integration | PASS | `explain_method`, `explain_trend`, `explain_seasonality`, `explain_changepoints`, `explain_intervals` — all read the deterministic result; `explain_changepoints` cross-checked against the detector's own output in tests. Atlas never computes or alters a value, and `explain_intervals` explicitly states a point forecast without its band "is not the full picture." |
| Legacy parity | PASS | Direct, in-process parity tests against `modules/forecasting.py`'s own functions on shared fixtures: model choice and point-forecast values matched to 1e-6, caveat wording matched exactly (same function, same inputs), STL strengths matched to 1e-6, changepoint positions matched exactly. |
| Accessibility | PASS | 0 axe-core violations scoped to `.forecasting-workspace` (Playwright, real browser). |
| Performance | PASS | Applied Phase 7A's own lesson from the start: `statsmodels` imported at module load, verified no cold-import tax on the very first request in a fresh process (~75ms first request vs. ~71ms second — consistent, no warmup spike). The ~70ms per model fit is legitimate compute cost, not a regression. |
| Earlier-phase regression | PASS | Full pytest 689 passed / 4 skipped (pre-existing MySQL-source-not-configured skips); ruff/mypy/boundary-scan/secret-scan/contract-freshness all clean; frontend lint/typecheck/vitest (18/18)/a11y-baseline/production build all clean; Playwright `shell.spec.ts` 11/11 passed. |

## Migration state

`forecasting` promoted from `SHADOW` to `ReleaseChannel.ENABLED` in both
`apps/api/src/prism_api/migration.py` and `apps/web/src/state/shell-model.ts`,
consistent with the pattern every prior slice followed.

## Real process improvement applied from Phase 7A

Phase 7A's real deployment bug (a heavy native dependency missing from
`apps/api/requirements.txt`) was pre-empted this time: `statsmodels` was
added to that file *before* writing the router, then verified with a
clean-venv `pip install -r apps/api/requirements.txt` + `create_app()`
check — the same process gap that caused 7A's bug, closed proactively.
Similarly, the module-load-time import lesson from 7A's performance fix
was applied from the start, and verified with a direct timing check
showing no cold-import tax.

## Rollback

Flip `forecasting`'s `channel` to `SHADOW`/`LEGACY` in `migration.py` and
`shell-model.ts` — no data migration, no code removal. See `docs/ROLLBACK.md`
for the general per-workflow rollback mechanism (unchanged by this slice).

## Next

Phase 7C — ML Lab (`modules/mllab.py`), per `PHASE7_BRIEF.md`'s sequencing.
Not started as of this checkpoint.
