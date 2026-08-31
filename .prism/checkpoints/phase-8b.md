# Phase 8B Checkpoint — Analytical Object Registry + Read-Only Retrieval

- Branch: `phase-8b-registry-read-model`
- Base branch: `phase-6.5-integration-staging`
- Base commit: `4912610be584e2b3e9902500bd6585aeebb8a506` (PR #10 / Phase 8A merge)
- Date: 2026-08-31
- Status: LOCALLY COMPLETE, PR PENDING

## Scope

Phase 8B completes 8A's provenance foundation with dataset-revision identity,
direct-parent wiring across the remaining native workflows (SQL Lab,
Visualize, Forecasting, ML Lab, AI Analyst), and a read-only lineage API. It
does not build a dependency graph, staleness/invalidation propagation, a
rerun engine, Atlas lineage awareness, a lineage UI, persistence, or Phase 9
behavior.

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| 8A merged | PASS | PR #10 merged into `phase-6.5-integration-staging` at `4912610be584e2b3e9902500bd6585aeebb8a506`. |
| Dataset revision objects | PASS | `ensure_dataset_revision` — deterministic id, idempotent, correct direct-parent chain; tested for first-touch, repeated-call idempotency, cross-revision distinctness, and historical immutability. |
| Registry producer coverage | PASS | SQL Lab (local connection only), Visualize, Forecasting, ML Lab (baseline/feature-selection/SHAP as three separate objects), AI Analyst (ANSWERED outcome only) all register. Overview, ML Lab's `apply-feature`/`imbalance`, SQL Lab against SQLite/external connections, and AI Analyst's non-ANSWERED outcomes are deliberately excluded with reasons recorded in `PHASE8_IMPLEMENTATION_LEDGER.md`. |
| Direct parent semantics | PASS | Every producer's object points at the one dataset-revision object it actually ran against; Clean/dataset-revision ancestry verified across two consecutive transformations. |
| SQL producer | PASS | Registered with correct revision, direct parent, and sanitized reproducibility (SQL text, dialect, connection id, bind parameters). |
| Visualize producer | PASS | Registered with the deterministic chart spec (mark/intent/dimension/measure/aggregation/filters), not a rendered payload. |
| Forecast producer | PASS | Registered with datetime/numeric columns, horizon, inferred frequency, and model used — never the fitted statsmodels object. |
| ML producer | PASS | Baseline/feature-selection/SHAP each register as independent `ml_model` objects with target/features/task-type/seed/split/method metadata; no fitted estimator, transformed matrix, or raw SHAP array. |
| AI producer | PASS | Registered only for a completed `ANSWERED` outcome; the causal-refusal and unexecuted-SQL-draft outcomes are not registered (nothing completed to preserve). |
| Read-only object retrieval | PASS | `GET /objects/{id}` and `GET /datasets/{id}/objects` reviewed and kept unchanged in shape; no write route exists under `/lineage`. |
| Dataset/revision/kind filtering | PASS | Each filter and their combinations tested, including an empty-result case. |
| Deterministic ordering | PASS | `created_at DESC, object_id DESC`, confirmed stable across repeated identical calls. |
| Immutable snapshots | PASS | Mutating a returned HTTP payload never mutates registry state (8A test, still passing; extended coverage this session). |
| Secret safety | PASS | Nested-secret redaction verified over the live HTTP response body for a SQL run's bind parameters and an AI Analyst question; recursive dict/list redaction unit-tested directly. |
| OpenAPI/TS contracts | PASS | `tools/generate_typescript_contracts.py --check` clean after regenerating; new `AnalyticalObject`/`ObjectKind`/lineage types now in `packages/api-contracts/typescript/src/generated.ts`. |
| Backward compatibility | PASS | No touched producer route's response model, status code, or external contract changed. Full existing suite passes unchanged. |
| Performance sanity | PASS | 1,000 synthetic objects across 10 revisions/2 kinds; 50 filtered `list_for_dataset` calls complete well under a second. |
| Python tests | PASS | `pytest tests/ apps/api -q` → 756 passed, 4 pre-existing skips (no local MySQL). |
| Lint and mypy | PASS | `ruff check` (repo-wide) clean; `mypy --follow-imports=skip --allow-subclassing-any --allow-untyped-decorators --no-warn-return-any apps/api/src packages` (CI's exact invocation) clean — fixed a real gap this session found in the inherited `lineage.py` (missing `from __future__ import annotations`, needed for its `X \| None` syntax under this repo's Python 3.9 mypy target). |
| Frontend gates | PASS | `npm run lint`, `npm run typecheck`, `npm run test:web` (22 tests), `npm run a11y:baseline`, `npm run build:web` all clean. |
| Legacy regression | PASS | Zero diff to `app.py`/`modules/`; `py_compile` clean; `eval/autocleaner_eval.py` 8/8. |
| CI | PENDING | Not yet pushed/opened as a PR from this checkpoint. |

## Verdict

**LOCALLY COMPLETE.** Every gate above that can be verified without a live
CI run passes. The branch is ready to push and open as a PR into
`phase-6.5-integration-staging`; merge only once CI is green there too.

## Known limitation, restated

The registry remains process-local and in-memory. An API process restart
resets all analytical history. Persistent history needs a dedicated
architecture decision (a database-backed registry) for a later phase — not
attempted in 8A or 8B.

## 8C starting point

Phase 8C — Deterministic Dependency Graph / Lineage Traversal — builds
ancestor/descendant traversal on top of the direct `parent_refs` links 8A and
8B already record (every object has at most one meaningful direct parent: a
dataset-revision object it read, or, for Clean and the dataset-revision chain
itself, the prior revision). 8C's task is to walk that graph transitively,
not to add new parent links. Do not implement graph traversal, visualization,
staleness propagation, invalidation propagation, rerun/reproduction
execution, Atlas lineage reasoning, lineage/evidence frontend UI,
persistence, or Phase 9 work under this checkpoint.

PHASE_8A_COMPLETE = YES
PHASE_8B_COMPLETE = YES
PHASE_8C_STARTED = NO
