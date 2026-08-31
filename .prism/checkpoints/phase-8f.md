# Phase 8F Checkpoint — Reproducibility + Safe Rerun

- Branch: `phase-8-completion`
- Base: Phase 8E commit on this branch
- Date: 2026-08-31
- Status: **locally complete**

## Scope

Turns preserved reproducibility metadata into safe reruns. A rerun **never**
overwrites an existing analytical object — it always creates a brand-new one
via the exact same producer logic the original run used; the original
object's id, provenance, parameters, evidence, and timestamp are untouched.

## Design

`apps/api/src/prism_api/reproduction_service.py` reconstructs a producer's
original request purely from the object's own recorded
`provenance.reproducibility` (never from a client payload — the rerun HTTP
request supplies only `mode`), then calls the exact same computation each
route already runs, extracted into `execute_*` helpers
(`forecasting.execute_forecast`, `mllab.execute_baseline`/
`execute_feature_selection`/`execute_shap`) so no logic is duplicated; Stats'
`run_test(stored, request)` already took an explicit `stored` and needed no
change. `same_revision` mode resolves the *exact* `(revision,
source_fingerprint)` identity the original object recorded via
`DatasetStore.revisions()` — never revision number alone, extending the same
disambiguation Phase 8B/8D established; if that exact identity is no longer
in this process's history (an abandoned undo/redo branch, or a restart),
the outcome is `source_revision_unavailable`, never a silent rerun against
the wrong data. `current_revision` mode resolves DatasetStore's current
active identity. A missing column fails as a typed `validation_failed`
outcome, not a silent substitution.

**Supported kinds:** `analysis` (Stats), `forecast`, `ml_model` (baseline/
feature-selection/SHAP), `visualization`. **Deliberately unsupported, with a
documented reason returned in the response itself:** `dataset_revision` (an
identity record, nothing to rerun), `cleaning_plan` (Clean already has its
own deterministic apply/undo — that *is* its rerun mechanism), `query_result`
(SQL Lab runs execute asynchronously; the synchronous rerun endpoint doesn't
support that flow in this phase), `profile` (a read-only snapshot),
`evidence` (AI Analyst involves a provider call, out of deterministic-rerun
scope this phase) — the same kind of documented, non-silent scope choice
Phase 8B made for its own producer coverage gaps.

## API

`POST /api/v1/lineage/objects/{object_id}/rerun` with body `{"mode":
"same_revision"|"current_revision"}` — the only field a caller may supply.
Response is a typed `ReproductionResponse` (`outcome`: `created`/
`unsupported`/`validation_failed`/`source_revision_unavailable`,
`new_object` only on `created`). No arbitrary analytical payload is ever
accepted from the client.

## UI

The Evidence Inspector's Reproducibility section gained two actions,
"Reproduce on original revision" and "Rerun on current data" — inline, no
modal. Before either fires, the panel already shows original revision,
dataset id, and method (from the existing Identity/Parameters sections).
After a run, an inline outcome panel shows what happened — a `created`
result offers "View new result" (navigates the inspector to the new object,
reusing 8E's existing navigation); any other outcome shows its `detail`
message plainly, `role="alert"`.

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| Reproducibility completeness | PASS | Stats/Forecast/ML/Visualize reproducibility specs verified sufficient to reconstruct their original request exactly; SQL/Clean/dataset-revision/profile/evidence explicitly and honestly marked unsupported. |
| Rerun service | PASS | `reproduction_service.py` — no HTTP-handler logic duplication; reuses each producer's own extracted `execute_*`/`run_test` function. |
| Same-revision rerun | PASS | Resolves the exact `(revision, fingerprint)` via `DatasetStore.revisions()`; reports `source_revision_unavailable` honestly when an abandoned branch's identity is gone from history. |
| Current-revision rerun | PASS | Resolves DatasetStore's active identity via `overview_store.get()`. |
| Historical immutability | PASS | Original object's `created_at`/`object_id` verified byte-identical after a rerun. |
| New analytical object created | PASS | Every `created` outcome's `new_object.object_id` differs from the original; repeated reruns each create a distinct object. |
| Validation failures | PASS | A dropped column fails as `validation_failed` with a clear message, not a silent substitution. |
| Inspector rerun action | PASS | Two inline actions, an inline (non-modal) outcome panel, "View new result" navigation wired through the existing lineage-navigation pattern. |
| Security | PASS | Rerun response for a redacted SQL bind parameter verified to carry no secret text. |
| Tests | PASS | `tests/api/test_phase8f_reproduction.py`, 12 tests (Stats same/current-revision, missing-column failure, Forecast/ML/Visualize rerun, SQL/dataset-revision unsupported, abandoned-branch unavailability, no-overwrite across repeated reruns, 404, secret safety); 2 new frontend tests (created outcome + view-new-result, unsupported outcome). |
| Full regression | PASS | `pytest tests/ apps/api -q` → 809 passed, 4 pre-existing skips. `npm run test:web` → 29 passed (27 pre-existing + 2 new). |
| ruff / mypy / contracts | PASS | Repo-wide `ruff check` clean; CI's exact mypy invocation clean; `tools/generate_typescript_contracts.py --check` clean after regenerating (`ReproductionMode`/`ReproductionOutcome`/`ReproductionResponse` now in `generated.ts`). |
| Frontend gates | PASS | `npm run lint`, `npm run typecheck`, `npm run a11y:baseline`, `npm run build:web` all clean. |

## Verdict

**LOCALLY COMPLETE.** Proceeding immediately to Phase 8G per the mega-run's
autonomous-continuation instruction.
