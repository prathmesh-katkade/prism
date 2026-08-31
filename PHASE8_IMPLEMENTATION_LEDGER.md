# Phase 8 Implementation Ledger

## 8A — Unified Provenance Foundation (COMPLETE — merged)

**Status update:** PR #10 passed final CI and merged into
`phase-6.5-integration-staging` at merge commit `4912610be584e2b3e9902500bd6585aeebb8a506`
on 2026-08-31. The "review fixes pending CI" status below reflects the point
this section was written at, before that merge; see `.prism/checkpoints/phase-8b.md`
for the current lineage state.

**Base:** `phase-6.5-integration-staging` at
`2741c2ef3c242d3edff7a46beda2acd437da25ac`.

**Objective:** Establish the canonical, framework-free representation of an
analytical object and its reproducible provenance without replacing
`DatasetStore` or widening existing Phase 3–7 HTTP responses.

**Delivered foundation:**

- `packages/analytical-schemas` now defines analytical object identity, kind,
  lifecycle, immutable dataset reference (id/revision/fingerprint), parent and
  evidence references, warnings, producer/service version, creation time, and
  typed cleaning/statistical/generic reproducibility specifications.
- Provenance parameter sanitization recursively redacts credential-like keys
  and common inline bearer/basic credentials or database connection strings.
- `AnalyticalObjectRegistry` is deliberately process-local and append-only.
  It supports `register`, `get`, `list_for_dataset`, and `exists`; rejects
  duplicate ids and self-parenting; and snapshots every record so callers
  cannot mutate historical registry state.
- `DatasetStore` remains the sole owner of dataset revision creation, lookup,
  history, and undo. The registry records a revision after a workflow has used
  that authoritative store; it never creates or rewrites a dataset revision.
- Stats registers each successfully completed deterministic test as an
  `analysis` object. Clean registers each successfully applied transformation
  as a `cleaning_plan` object bound to the new DatasetStore revision.

**Compatibility:** Existing `OverviewProvenance`, Stats, and Clean response
contracts are unchanged. The new registry is an internal foundation rather
than an incomplete public graph API.

**Not implemented (explicit 8A boundary):** dependency graph traversal,
staleness propagation, lineage UI, rerun engine, Atlas lineage awareness,
persistence/database, and Phase 9 work.

**Tests added:**

- `tests/contracts/test_analytical_objects.py` — secret redaction, duplicate
  and self-parent protection, dataset filtering, and immutable snapshots.
- `tests/api/test_analytical_object_integration.py` — Stats and Clean records
  against their active DatasetStore revisions.

**Quality-gate status:** CI run #98 is green for `ff8a6338814f67e4add58730b112464defe66787`:
phase-1-python, phase-1-web, legacy-regression, secret-scan, and phase-4-live-e2e
all passed. The first live-E2E attempt exposed a missing API runtime dependency
for `prism_analytical_schemas`; `apps/api/requirements.txt` now installs the
package. A subsequent SQL Lab browser assertion flaked after the API completed
its request; the failed job was rerun and passed. Local full-suite execution
remains unavailable under this checkout's Python 3.9 runtime because three
pre-existing Forecasting tests require Python 3.10+ `zip(..., strict=True)`;
the required Python 3.11 CI gate is certified.

**Post-CI review fixes:** PR review identified that Clean reproducibility could
omit a target column and Stats could record request fields instead of the
columns actually tested. Both paths now derive reproducibility data from the
completed operation/result and have focused regression coverage. The final
8A CI gate must validate these corrections before merge.

**8B starting point:** expose read-only registry lineage queries only after a
separate scope decision; do not build a dependency graph, staleness engine, or
UI from this in-process foundation without that decision.

## 8B — Analytical Object Registry + Read-Only Retrieval

**Base:** `phase-6.5-integration-staging` at `4912610be584e2b3e9902500bd6585aeebb8a506`
(PR #10 / Phase 8A merge). Branch: `phase-8b-registry-read-model`.

**Objective:** Turn 8A's provenance foundation into a useful, read-only
canonical analytical-history model — dataset-revision identity, direct-parent
wiring across the remaining native workflows, and a queryable read API —
without building a dependency graph, staleness/rerun engine, Atlas lineage
awareness, persistence, or a UI.

**Architecture:**

- `AnalyticalObjectRegistry` (`packages/analytical-schemas/.../registry.py`,
  extended in the first 8B commit before this session) indexes by
  `dataset_id`, `(dataset_id, revision)`, and `kind` for O(1) candidate lookup
  before the deterministic newest-first sort.
- `apps/api/src/prism_api/lineage.py` exposes exactly two read-only routes —
  `GET /api/v1/lineage/objects/{object_id}` and
  `GET /api/v1/lineage/datasets/{dataset_id}/objects` (optional `revision`,
  `kind` filters) — registered on the app in `main.py`. No write route exists
  under `/lineage`; analytical objects are only ever registered internally by
  the trusted workflow code that produced them.

**Registry changes made this session:**

- `ObjectKind` gained two values: `dataset_revision` (see below) and
  `evidence` (AI Analyst's grounded-answer results — qualitatively different
  from a deterministic Stats/Forecast/ML result, so given its own kind rather
  than overloading `analysis`).
- Fixed a real, CI-blocking gap in the code this session inherited:
  `lineage.py` was missing `from __future__ import annotations`, which every
  other module in this package has — its `int | None` / `ObjectKind | None`
  parameter types fail to parse under this repo's Python 3.9 mypy target
  without it. Also simplified `kind: ObjectKind | None = Query(default=None)`
  to a bare `= None` default (FastAPI needs no explicit `Query()` wrapper
  without extra validation), which incidentally also cleared a ruff B008
  finding that the more verbose form triggered.

**Dataset-revision objects (`analytical_objects.py::ensure_dataset_revision`):**

`DatasetStore` remains the sole revision authority — this only mirrors its
existing dataset/revision/fingerprint identity into the registry, once. Each
identity gets a deterministic object id (`dsrev_{dataset_id}_r{revision}`), so
`ensure_dataset_revision` is naturally idempotent: a second call for the same
identity is a lookup, not a re-registration, with no separate "does this
exist" check needed at any call site. `DatasetStore.add_revision` only ever
increments the current revision by exactly one, so the immediately preceding
revision (when it has already been registered) is always the correct direct
parent — no transitive graph, just one link. Every producer below points its
own object at the one dataset-revision object it actually ran against via a
shared `_derived_from(stored)` helper; Clean's `register_clean_transformation`
explicitly ensures both the *source* revision it read and the *resulting*
revision it created (in that order), so the chain is never missing a link
regardless of which revision in a dataset's history first gets touched by any
producer.

**Producer coverage added this session** (all in `analytical_objects.py`,
wired into each router's existing success path with no change to that route's
external response contract):

| Producer | Kind | Registered on | Direct parent |
|---|---|---|---|
| SQL Lab | `query_result` | A query against the **local in-memory dataset connection** reaching `succeeded` | the queried revision's dataset-revision object |
| Visualize | `visualization` | A successful `/render` (spec + aggregated data) | the rendered revision's dataset-revision object |
| Forecasting | `forecast` | A successful `/forecast` run | the forecasted revision's dataset-revision object |
| ML Lab | `ml_model` | Each of `/baseline`, `/feature-selection`, `/shap` independently | the revision the run used |
| AI Analyst | `evidence` | Only a completed `ANSWERED` outcome from `/analyze` | the answered revision's dataset-revision object |

**Deliberate exclusions, documented rather than forced:**

- **SQL Lab against a SQLite/external connection** is not registered — those
  connections have no `DatasetStore` revision identity to attach to; giving
  them one would mean inventing a second, differently-shaped provenance
  identity, out of scope here.
- **ML Lab's `apply-feature`** (a revision-producing transform, like Clean)
  is not registered as an analytical object this pass — the task's own
  producer list for ML Lab names baseline/feature-selection/SHAP/imbalance
  explicitly and does not include it; registering it well would need either a
  new `ObjectKind` or overloading `cleaning_plan` for a semantically different
  operation, better done as a deliberate follow-up than squeezed in here.
- **ML Lab's `imbalance` diagnostic** is not registered — it is a `GET`,
  side-effect-free class-balance check, not a discrete completed analytical
  action in the way a `POST /baseline` run is; registering every `GET` read
  would flood the registry with what are really profile-style reads (the same
  reasoning Overview's own profile was excluded from 8A).
- **Overview** still has no analytical object of its own, for the same reason
  8A gave: its profile is a derived, recomputed-on-read view of the current
  revision, not a discrete completed action with its own lifecycle worth
  preserving as history.
- **AI Analyst's `INSUFFICIENT_EVIDENCE` (causal refusal) and `SQL_READY`
  (unexecuted draft) outcomes** are not registered — neither carries a
  completed, evidence-grounded result worth preserving; the causal path has no
  evidence, and the SQL-draft path's SQL was never run. Only `ANSWERED` is.

**Security:** every producer's reproducibility `parameters` dict passes
through `sanitize_provenance_parameters` (recursive, `GenericReproducibilitySpec`'s
own field validator) before it can enter the registry — credential-shaped
keys and inline bearer/basic/connection-string values are redacted regardless
of nesting depth. SQL Lab's own `_safe_parameters` redaction (existing, 8A
era) and the registry's redaction now both apply to a SQL run's bind
parameters. AI Analyst's `question` field (free user text) passes through the
same redaction as defense in depth, even though its response shape has no
chain-of-thought or hidden-reasoning field to begin with. No fitted
model/estimator, transformed feature matrix, or raw SHAP array crosses into
any registered object — every ML Lab producer call site passes a hand-built
`parameters` dict of primitives only, never mllab.py's own internal result
dict (which does carry those unserializable objects, staying entirely inside
mllab.py).

**Performance:** the registry's dataset/revision/kind indexes (built in 8A's
own final commit) make `list_for_dataset` an index lookup plus a sort over
only the matching candidates, not a full scan. A new test registers 1,000
synthetic objects across 10 revisions and 2 kinds directly against the
registry and confirms 50 filtered lookups stay well under a second.

**Process-local limitation (unchanged from 8A, restated explicitly):** the
registry lives entirely in the API process's memory. An API process restart
resets all analytical history — nothing survives it. Persistent analytical
history is a dedicated architecture decision (likely a database-backed
registry) for a later phase; no MySQL/Postgres/SQLite persistence was added
here.

**Tests added:** `tests/api/test_phase8b_registry_producers.py` (21 tests) —
dataset-revision identity/idempotency/ancestry, Clean's two-transformation
ancestry chain, each new producer's registration/parent/reproducibility
content, AI Analyst's outcome-gated registration (including a secret-shaped
question), the read API's dataset/revision/kind filters and their
combinations, deterministic ordering, an empty-list case, 404 on a missing
object, nested-secret redaction verified over the live HTTP response body,
and the 1,000-object performance sanity check.

**Backward compatibility:** every touched producer route's existing pydantic
response model and status code are unchanged; `register_*` calls are pure
additions after the response is already built. The full existing Python suite
(756 tests total including the new ones, 4 pre-existing MySQL-source skips)
and the full frontend gate (lint, typecheck, `test:web`, `a11y:baseline`,
`build:web`) both pass unchanged.

**Quality gates this session:** `pytest tests/ apps/api -q` → 756 passed, 4
skipped; `ruff check` (repo-wide) → clean; `mypy --follow-imports=skip
--allow-subclassing-any --allow-untyped-decorators --no-warn-return-any
apps/api/src packages` (CI's exact invocation) → clean; `tools/check_boundaries.py`
→ clean; `tools/check_secrets.py` → clean; `tools/generate_typescript_contracts.py
--check` → clean (after regenerating — the new `AnalyticalObject`/`ObjectKind`/
lineage types are now in `packages/api-contracts/typescript/src/generated.ts`);
`npm run lint`, `npm run typecheck`, `npm run test:web` (22 tests), `npm run
a11y:baseline`, `npm run build:web` → all clean. Legacy Streamlit: zero diff
to `app.py`/`modules/`, `py_compile` clean, `eval/autocleaner_eval.py` 8/8.

**8C starting point (do not implement yet):** Phase 8C — Deterministic
Dependency Graph / Lineage Traversal — builds ancestor/descendant traversal on
top of the `parent_refs` (direct-parent-only) links this session and 8A
recorded. Every object in the registry now carries at most one meaningful
direct parent (a dataset-revision object it read, or — for Clean and the
dataset-revision chain itself — the prior revision). 8C's job is to walk that
graph transitively (ancestors/descendants), not to add new parent links; no
graph traversal, visualization, staleness propagation, invalidation
propagation, rerun/reproduction execution, Atlas lineage reasoning, or
lineage/evidence frontend UI was implemented in 8A or 8B and none of it should
be started without a separate scope decision.
