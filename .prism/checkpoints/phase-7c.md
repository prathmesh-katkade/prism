# Phase 7C Checkpoint — Native ML Lab

- Branch: `phase-7-advanced-analytics`
- Head commit: `ec2a22a`
- Date: 2026-08-29
- Legacy reference: `modules/mllab.py` (unchanged, remains the parity/rollback oracle)

## Gate summary (PASS/FAIL)

| Gate | Status | Notes |
|---|---|---|
| Native ML API | PASS | `apps/api/src/prism_api/mllab.py`: 8 routes (suggest-features, apply-feature, detect-task, imbalance, baseline, feature-selection, shap, atlas), registered in `main.py`. |
| Native ML workspace | PASS | `apps/web/src/components/mllab-workspace.tsx`, three-pane with a mode selector (suggest/baseline/feature-selection/shap/imbalance). |
| Task detection | PASS | Deterministic dtype/cardinality dispatch, parity-tested for both classification and regression targets. |
| Baseline models | PASS | Logistic/Linear Regression + Random Forest, 80/20 (stratified for classification) split, metrics matched exactly against legacy on shared fixtures. |
| Cross-validation | PASS | 5-fold (capped for small/imbalanced data, exactly like legacy), fold means matched to 1e-6. |
| Metrics | PASS | Accuracy/F1 for classification, RMSE/R² for regression — task-appropriate, never all metrics indiscriminately. |
| Class imbalance diagnostics | PASS | Parity-tested; gated to classification targets only (422 for regression). |
| Feature engineering | PASS | Encode/scale/datetime-expand/interaction suggestions parity-tested; `apply-feature` is revision-aware exactly like Clean — a new dataset revision, never an in-place mutation. |
| Feature selection | PASS | Mutual Information + L1 + RFE three-method consensus; recommended-features set parity-tested. |
| Explainability | PASS | SHAP global importance via Random Forest TreeExplainer (including the ported additivity-check workaround); shape/sign/ordering sanity-checked per rule 39's tolerance allowance rather than exact-value parity. |
| Leakage protections | PASS | Preprocessing (impute/scale/encode) fit on the training split only — the one concrete leakage-prevention rule this module exists to enforce — stated explicitly in every baseline response's `leakage_note`, verified by a disjoint-split-size test. |
| Reproducibility | PASS | Every result's provenance records its exact configuration (features, target, task type, seed=42, split strategy); SHAP deliberately re-fits from that same configuration each call rather than caching an unserializable model object across requests. |
| Provenance | PASS | Bound to `dataset_id`/`revision`/`source_fingerprint`, tested directly. |
| Atlas integration | PASS | 6 actions (`explain_task_type`, `compare_models`, `explain_cross_validation`, `explain_imbalance`, `explain_feature_importance`, `identify_overfitting`); `compare_models`/`identify_overfitting` cross-checked against the deterministic detector's own output in tests. Atlas never computes, retrains, or alters a model. |
| Legacy parity | PASS | Direct, in-process parity tests against `modules/mllab.py`'s own functions on shared fixtures. |
| Accessibility | PASS | 0 axe-core violations scoped to `.mllab-workspace` — see the real defect found and fixed, below. |
| Performance | PASS | sklearn/imblearn/shap imported at module load from the start (applying the 7A/7B lesson); verified no cold-import tax; ~1.4s per baseline run (including 5-fold CV across two models) is legitimate compute, not a regression. |
| Earlier-phase regression | PASS | Full pytest 707 passed / 4 skipped (pre-existing MySQL-source-not-configured skips); ruff/mypy/boundary-scan/secret-scan/contract-freshness all clean; frontend lint/typecheck/vitest (21/21)/a11y-baseline/production build all clean; Playwright `shell.spec.ts` 12/12 passed. |

## Migration state

`ml` promoted from `SHADOW` to `ReleaseChannel.ENABLED` in both
`apps/api/src/prism_api/migration.py` and `apps/web/src/state/shell-model.ts`.
**This closes Phase 7** — all three slices (Stats Lab, Forecasting, ML Lab)
are native and `ENABLED`, alongside Overview/SQL Lab/AI Analyst/Clean/
Visualize from earlier phases. Every navigation workflow in the shell now
opens a native surface.

## Real defect found and fixed during this slice

Accessibility: wide result tables (the 5–6-column cross-validation and
feature-selection ranking tables) can overflow their `.data-table-wrap`
container and become a scrollable region with no way for a keyboard user to
focus and scroll it — a latent gap in the shared `.data-table-wrap` pattern
also present in Clean/Overview/Stats, just never triggered by their
narrower tables before. Fixed in this component with `tabIndex={0}` on every
`.data-table-wrap`; the same gap in the other three components is recorded
as technical debt in `PHASE7_IMPLEMENTATION_LEDGER.md` rather than fixed
speculatively outside this phase's scope.

## Process lessons carried forward and applied

Two lessons from Phase 7A were pre-empted this time rather than
rediscovered: (1) `scikit-learn`, `imbalanced-learn`, and `shap` were added
to `apps/api/requirements.txt` *before* writing the router, verified with a
clean-venv install; (2) all three heavy libraries were imported at module
load, verified with a direct timing check showing no cold-import tax.

## Rollback

Flip `ml`'s `channel` to `SHADOW`/`LEGACY` in `migration.py` and
`shell-model.ts` — no data migration, no code removal. See `docs/ROLLBACK.md`
for the general per-workflow rollback mechanism (unchanged by this slice).

## Next

Phase 7 is complete. See `PHASE7_FINAL_REPORT.md` for the full summary and
`PHASE8_HANDOFF.md` for minimal next-phase context. Phase 8 itself is
explicitly out of scope for this session.
