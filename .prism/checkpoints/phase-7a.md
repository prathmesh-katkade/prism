# Phase 7A Checkpoint — Native Stats Lab

- Branch: `phase-7-advanced-analytics`
- Head commit: `17adb67`
- Date: 2026-08-29
- Legacy reference: `modules/stats_lab.py` (unchanged, remains the parity/rollback oracle)

## Gate summary (PASS/FAIL)

| Gate | Status | Notes |
|---|---|---|
| Native Stats API | PASS | `apps/api/src/prism_api/stats.py`: `GET .../suggest`, `POST .../run`, `POST .../atlas`, registered in `main.py`. |
| Native Stats workspace | PASS | `apps/web/src/components/stats-workspace.tsx`, three-pane (variables / results / assumptions+provenance+Atlas). |
| Suggestion engine | PASS | Deterministic dtype/category-count/sample-size dispatch, direct port of legacy `suggest_test()`; 4 tests cover all four outcomes. |
| t-test | PASS | Welch's t-test (`equal_var=False`), Cohen's d, parity-tested against `modules/stats_lab.py::run_ttest`. |
| ANOVA | PASS | One-way ANOVA, eta-squared, parity-tested against `run_anova`. |
| Chi-square | PASS | Chi-square test of independence, Cramer's V, low-expected-cell warning, parity-tested against `run_chi2`. |
| Pearson | PASS | Pearson r + significance, parity-tested against `run_pearson`. |
| Normality handling | PASS | Shapiro-Wilk surfaced as context (p-value + note), never a bare pass/fail gate; large-sample subsampling ported (`SHAPIRO_MAX_N`). |
| Assumption warnings | PASS | Non-normality and low-expected-cell warnings surfaced in both the API response and the UI. |
| Effect sizes | PASS | Cohen's d / eta-squared / Cramer's V / Pearson r, each with the legacy small/medium/large convention (`_effect_size_label`, exact thresholds ported). |
| Insufficient-evidence semantics | PASS | Every result carries an explicit `evidence_statement` distinct from the headline interpretation; a non-significant result never claims "no relationship," only "not detected in this sample" — dedicated test (`test_evidence_statement_never_claims_absence_only_insufficient_evidence`) and a UI regression test enforce this. |
| Provenance | PASS | `StatTestResult.provenance` reuses `OverviewProvenance` (source_fingerprint/dataset_revision/parameters/service_version/computed_at), bound to the dataset's current revision via the shared `DatasetStore`; tested directly. |
| Atlas integration | PASS | `explain_test`, `explain_assumptions`, `explain_effect_size`, `recommend_next_step` — all read the deterministic `run_test()`/`suggest_test()` output; Atlas never computes or alters a statistic. Effect-size evidence value cross-checked against `run_test()`'s own output. |
| Legacy parity | PASS | Direct, in-process parity tests (not just structural) against `modules/stats_lab.py`'s own functions on shared fixtures, tolerance-based (`pytest.approx`), consistent with the MySQL-parity precedent from Phase 6.5. |
| Accessibility | PASS | 0 axe-core violations scoped to `.stats-workspace` (Playwright, real browser). |
| Performance | PASS | Found and fixed a real regression during this slice: scipy's first import cost (~365ms) was being paid on whichever request happened to be first in a fresh process; moved to module-load time — verified first-request latency now ~11ms, matching every other endpoint. |
| Earlier-phase regression | PASS | Full pytest 672 passed / 4 skipped (pre-existing MySQL-source-not-configured skips, unrelated to this slice); ruff/mypy/boundary-scan/secret-scan/contract-freshness all clean; frontend lint/typecheck/vitest (14/14)/a11y-baseline/production build all clean; Playwright `shell.spec.ts` 10/10 passed. |

## Migration state

`stats` promoted from `SHADOW` to `ReleaseChannel.ENABLED` in both
`apps/api/src/prism_api/migration.py` (`PHASE_1_MIGRATIONS`) and
`apps/web/src/state/shell-model.ts` (`phaseTwoMigrations`), consistent with
how Overview/SQL Lab/AI Analyst/Clean/Visualize were each promoted only
after their own gate passed.

## Real defect found and fixed during this slice

Performance: the very first `POST .../run` call in a freshly started API
process took ~365ms because scipy's own module import (a genuinely heavy
one-time cost) was happening lazily inside the request handler instead of
at server startup. Whichever user's request happened to land first would
have silently absorbed that cost. Fixed by moving `from scipy import stats`
to module level; verified the first request in a fresh process now takes
~11ms, matching every other Stats endpoint and every other workflow.

## Rollback

Flip `stats`'s `channel` back to `SHADOW` (or `LEGACY`) in both
`migration.py` and `shell-model.ts` — no code removal, no data migration,
no deploy of new code required. See `docs/ROLLBACK.md` for the general
per-workflow rollback mechanism (unchanged by this slice).

## Next

Phase 7B — Forecasting (`modules/forecasting.py`), per `PHASE7_BRIEF.md`'s
sequencing. Not started in this slice.
