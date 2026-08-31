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

## 8B — Analytical Object Registry + Read-Only Retrieval (COMPLETE — merged)

**Status update:** [PR #11](https://github.com/prathmesh-katkade/prism/pull/11)
passed final CI (all 5 checks green on head `63daaafa4e80b2527618af3def2162be808f8476`)
and merged into `phase-6.5-integration-staging` at merge commit
`670d670ee0cdaaff7a6a62f1281d2df8b6802cf8` on 2026-08-31. Codex's automated
post-merge-review pass found two real gaps in this session's own new code
before merge, both fixed and covered by regression tests in the final head:
(P1) the dataset-revision object id was keyed on `(dataset_id, revision)`
only, so `DatasetStore.revert()` reusing a revision number for different
data after an undo would silently resolve to the abandoned branch's object —
fixed by keying on `(dataset_id, revision, source_fingerprint[:16])`; (P2)
concurrent first-touch registration wasn't race-safe and could surface a
duplicate-id `ValueError` as a 500 — fixed by catching it in
`ensure_dataset_revision` and returning the registry's winning record. See
`.prism/checkpoints/phase-8b.md` for the full gate record.

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

## 8C — Deterministic Dependency Graph / Lineage Traversal (COMPLETE — merged)

**Status update:** [PR #12](https://github.com/prathmesh-katkade/prism/pull/12)
passed CI on its only head (`125b3f9b70a06a7465bd8ed63d92791e8d842e6e`, all 5
checks green, no re-run needed) and merged into
`phase-6.5-integration-staging` at merge commit
`79b059f40a85a3ce5dc71500ca23286178ce5948` on 2026-08-31. No review comments
or threads were raised before merge. See `.prism/checkpoints/phase-8c.md` for
the full gate record.

**Base:** `phase-6.5-integration-staging` at
`670d670ee0cdaaff7a6a62f1281d2df8b6802cf8` (PR #11 / Phase 8B merge). Branch:
`phase-8c-lineage-traversal`.

**Objective:** Make the direct `parent_refs` graph 8A/8B already record
*walkable* — direct parent/child lookup, transitive ancestor/descendant BFS
with depth and bounded `max_depth`, a compact combined graph view, and an
optional shortest path — entirely read-only, entirely deterministic, no AI
inference, no new parent links, no staleness/rerun/persistence/UI.

**Graph semantics:** `parent → child` means "child depends on parent" (a
`forecast_result` object's parent is the `dataset_revision` it read). Parent =
immediate upstream dependency; child = immediate downstream dependent;
ancestor = transitive upstream; descendant = transitive downstream. Held
consistently across the registry, the service layer, and every route.

**Reverse child index:** `AnalyticalObjectRegistry._child_index:
dict[object_id, list[object_id]]`, maintained inline in `register()` — for
every `parent_ref` a newly-registered object declares, that object's id is
appended under its parent's id. No backfill pass, no scan: a child lookup is
one dict access. It does not require the parent to already be registered
(see partial-graph handling below), and it is covered by the same `RLock` as
every other registry mutation.

**Direct relationships:** `registry.get_parents(object_id)` /
`get_children(object_id)` — `None` if `object_id` itself is not registered
(→ HTTP 404); `[]` for a root/leaf; otherwise the immediate
parent/child `AnalyticalObject`s, sorted by `object_id` for determinism. A
`parent_ref` pointing at an id the registry does not currently hold (a
partial-graph gap) is skipped, never fabricated.

**Traversal algorithm:** `registry.ancestors(object_id, max_depth=None)` /
`descendants(...)` — iterative BFS (`_traverse`), no recursion, so there is no
stack-depth risk on a long chain. A `depths: dict[object_id, int]` doubles as
the visited set: a node is expanded at most once, the moment it is first
discovered, which also gives BFS's usual shortest-hop-count guarantee. Every
edge actually crossed (including a re-encounter of an already-visited node —
the diamond-convergence case) is recorded in a `set[tuple[parent_id,
child_id]]`, so fan-in is captured without duplicating the node itself.
Returns `None` only if the root itself is not registered.

**Depth semantics:** `parent_refs`/`children`/`ancestors`/`descendants` all
exclude the requested root from their result (the caller already has that
object). The compact `/graph` endpoint is the one exception: it includes the
root at `depth=0`. This is a fixed convention, not per-call configurable.

**Max depth:** optional `max_depth`, validated `1 <= max_depth <= 100`
(`MAX_LINEAGE_DEPTH` in `lineage.py`) via FastAPI `Query(..., ge=1, le=100)` —
an out-of-range value is a typed 422, not a silent clamp. `truncated=True`
means the walk was cut off by `max_depth` while at least one more,
unexplored neighbor genuinely existed beyond it — not merely that the graph
ended there naturally.

**Cycle safety:** the registry's own `register()` cannot construct a cycle
(only immediate self-parenting is rejected there), so a cycle is not a
reachable outcome of normal use — but traversal itself must not assume that.
`test_a_malformed_cycle_in_registry_state_does_not_hang_traversal` directly
corrupts registry internals to prove a 3-hop cycle still terminates and
never double-emits a node, purely from the `depths`/visited-set discipline
in `_traverse`.

**Ordering:** deterministic `(depth ASC, object_id ASC)` for traversal nodes;
edges sorted `(parent_object_id ASC, child_object_id ASC)`. Direct
parent/child lists are `object_id ASC`. Chosen over a `created_at`-based
tie-break because `object_id` alone is already unique and sufficient — one
fewer field for two BFS branches to disagree on.

**API routes (all read-only, all under the existing `/api/v1/lineage`
router):**

```
GET /objects/{object_id}/parents
GET /objects/{object_id}/children
GET /objects/{object_id}/ancestors      ?max_depth=
GET /objects/{object_id}/descendants    ?max_depth=
GET /objects/{object_id}/graph          ?direction=upstream|downstream|both&max_depth=
GET /path                               ?from_object_id=&to_object_id=
```

No `POST`/`PATCH`/`DELETE` route exists, or was added, anywhere under
`/lineage`. `apps/api/src/prism_api/lineage.py` stays a thin HTTP-shape layer
(404 translation, query validation); the actual composition (turning registry
traversal results into typed responses, merging ancestors+descendants for
`/graph`) lives in the new `apps/api/src/prism_api/lineage_service.py`, which
has no FastAPI dependency and is directly unit-testable.

**Shortest path:** `registry.shortest_path(from_id, to_id)` — BFS over both
parent and child edges treated as one undirected connectivity graph (a path
can legitimately run through a shared ancestor neither object directly
touches), each edge tagged with its true direction so the reconstructed path
still reports correctly-oriented `parent_object_id`/`child_object_id` edges.
Three outcomes, kept distinct: `None` (either id unknown → 404), `found=False`
(both exist, no path — a legitimate answer, not an error), `found=True` with
the ordered path.

**Contracts:** `LineageDirection`, `LineageNode` (wraps `AnalyticalObject` +
`depth`, no field duplication), `LineageEdge`, `LineageTraversal`,
`LineagePath` — added to `packages/analytical-schemas/python/
prism_analytical_schemas/models.py` alongside `AnalyticalObject` itself
(the same package `lineage.py` already imports directly from), exported via
that package's `__init__.py`. `prism_api_contracts` is untouched.

**Fingerprint-aware identity, extended into traversal:** 8B fixed dataset-
revision object identity to include `source_fingerprint`, not just
`(dataset_id, revision)`, so a revert-then-different-redo never resolves to
the abandoned branch. 8C traversal only ever walks `object_id`s (which
already encode that full identity) — there is no separate place traversal
could regress into revision-number-only comparison. Regression-tested
directly: two `ensure_dataset_revision` calls sharing `(dataset_id=
"ds_fp_test", revision=1)` but different fingerprints produce distinct
objects, and `ancestors()` on a child of one never includes the other.

**Partial-graph / process-local behavior, unchanged and still true:** the
registry only holds history observed since the current process started; a
`parent_ref` pointing outside that history is skipped, not invented, at both
the direct-lookup and the BFS layer. An API restart still resets all
analytical history, including the lineage graph — no persistence was added.

**Security:** traversal returns nothing that registration did not already
sanitize — `_restore` still reconstructs every node from the same
`model_validate`-on-read snapshot Phase 8A/8B use, and the reproducibility
field validators (secret-key/secret-value redaction) already ran at
`register()` time, before any traversal endpoint exists to serve it. Verified
directly: a SQL Lab run's `api_key` bind parameter stays `[redacted]` through
both the `/descendants` and `/graph` HTTP responses.

**Performance:** no full-registry scan anywhere in the traversal path — only
`_child_index` dict lookups and each visited node's own `parent_refs`. Tested
at a 1,000-node long chain (`ancestors()` on the tail) and a 5,000-child wide
tree (`get_children()`, repeated calls, and a `max_depth=1` descendant walk) —
all comfortably sub-second per call.

**Producers:** untouched. All 8C work is concentrated in
`packages/analytical-schemas/.../registry.py` (the reverse index and
traversal methods), the new `lineage_service.py`, `lineage.py`'s routes, the
new lineage contracts, tests, and this documentation.

**Backward compatibility:** the two pre-existing routes (`GET
/objects/{object_id}`, `GET /datasets/{dataset_id}/objects`) are byte-for-byte
unchanged; every Phase 3–7 producer route is untouched. All 8C routes are
additive.

**Tests:** `tests/api/test_phase8c_lineage_traversal.py` (26 tests) — direct
parents/children (including root/leaf/unknown-404), ancestor chain depth and
ordering, descendant fan-out and branch traversal, `max_depth` bounding and
truncation reporting, invalid `max_depth` (422), diamond-convergence
duplicate safety, a synthetic-cycle non-hang proof, fingerprint-aware
identity under traversal, immutable-snapshot safety, partial-graph handling,
secret redaction through traversal endpoints, the compact graph endpoint
(root-inclusion, direction filtering, 404), shortest path (found/not-found/
unknown-endpoint), the two pre-existing routes' continued behavior, and
performance at synthetic scale. All 26 pass; all pre-existing Phase 8A/8B
tests (`tests/api/test_analytical_object_integration.py`,
`tests/api/test_phase8b_registry_producers.py`) remain green, unmodified.

**Known limitations, unchanged from 8A/8B:** the registry is process-local
and in-memory (an API restart resets all lineage history); dataset-revision
identity still depends on `(dataset_id, revision, source_fingerprint)`, never
revision number alone.

**Rollback:** revert the merge commit for PR into
`phase-6.5-integration-staging`; nothing outside `registry.py`,
`lineage_service.py` (new file), `lineage.py`, the new lineage contracts in
`models.py`/`__init__.py`, the new test file, and the regenerated
`generated.ts` is touched, so rollback is a clean, isolated revert.

**Exact 8D starting point (do not implement here):** Phase 8D — Versioning +
Staleness Propagation — will answer "a dataset revision changed; which
downstream analytical objects are now stale?" using exactly the descendant
traversal 8C already built (`registry.descendants(dataset_revision_object_id)`
gives the full, correctly-ordered set of everything that would need
re-evaluation). 8D's actual job is to decide what "stale" means as a
lifecycle state, mutate `AnalyticalObject.lifecycle` (currently `COMPLETED`
records are never touched again after registration — the registry is
append-only, not update-in-place, so this is a real design decision, not a
one-line change), and expose that as a read (and only a read) surface. 8C
does not do any of that: no object's `lifecycle` was set to `STALE`, no
invalidation logic exists, no rerun/reproduction path exists, and no such
work should start without a fresh, explicit 8D scope decision.

**Quality gates this session:** `pytest tests/ apps/api -q` → 784 passed, 4
skipped; `ruff check` (repo-wide) → clean; `mypy --follow-imports=skip
--allow-subclassing-any --allow-untyped-decorators --no-warn-return-any
apps/api/src packages` (CI's exact invocation) → clean; `tools/
check_boundaries.py` → clean; `tools/check_secrets.py` → clean; `tools/
generate_typescript_contracts.py --check` → clean (after regenerating — the
new `LineageDirection`/`LineageNode`/`LineageEdge`/`LineageTraversal`/
`LineagePath` types are now in
`packages/api-contracts/typescript/src/generated.ts`); `npm run lint`, `npm
run typecheck`, `npm run test:web` (22 tests, unchanged — no frontend code
touched), `npm run a11y:baseline`, `npm run build:web` → all clean. Legacy
Streamlit: zero diff to `app.py`/`modules/`, `py_compile` clean,
`eval/autocleaner_eval.py` 8/8.

## 8D — Versioning + Staleness Propagation

**Base:** `phase-6.5-integration-staging` at `68377c7` (PR #12 / Phase 8C
merge + docs). Branch: `phase-8-completion`.

**Objective:** Contextual freshness (`current`/`stale`/`superseded`/`unknown`/
`invalid`) computed live against `DatasetStore`'s active identity, with
`AnalyticalObject` staying fully immutable — freshness is a read-time
assessment, never a stored field.

**Model:** `FreshnessState` + `FreshnessAssessment` in
`prism_analytical_schemas`, alongside `AnalyticalObject`. `CURRENT`: exact
`(dataset_id, revision, source_fingerprint)` match against DatasetStore's
active identity. `STALE`: a non-`DATASET_REVISION` object whose upstream
identity is no longer active — old is not invalid, and remains valid
historical evidence. `SUPERSEDED`: reserved for `DATASET_REVISION` objects
themselves (an old revision, or a same-revision-number branch abandoned by
undo/redo) — a version is superseded, not stale. `UNKNOWN`
(`freshness_known=false`): the process-local `DatasetStore` no longer
resolves the dataset_id (e.g. after a restart) — never guessed. `INVALID`:
defined per spec, reserved for genuine corruption; no code path in this
implementation produces it (age alone never does).

**No new graph engine:** `apps/api/src/prism_api/freshness_service.py`
computes per-object freshness as a direct identity comparison — every
producer already pins the exact revision/fingerprint it consumed into its own
`provenance.dataset` (Phase 8A/8B), so propagation is "free": every
descendant of a superseded revision is, by construction, already pointing at
that old identity, with no separate propagation step or lag. The one place
Phase 8C's own `registry.descendants()` is called is to size the "N objects
still depend on this revision" text in a superseded dataset-revision object's
reason — reusing 8C's traversal rather than writing a second one.

**API:** `GET /api/v1/lineage/objects/{object_id}/freshness` (404 for an
unknown object), `GET /api/v1/lineage/datasets/{dataset_id}/freshness`
(empty list, never 404, matching `/datasets/{id}/objects`'s own convention).
No mutation route (no `POST /mark-stale`, no `PATCH /freshness`).

**Tests:** `tests/api/test_phase8d_freshness.py`, 13 tests — current/stale/
superseded/unknown states, multiple descendants staling together, the
dataset-revision-vs-analysis distinction, immediate (non-lagged) staleness on
a further Clean apply, fingerprint-safe undo/redo (an abandoned branch never
reads current just because its revision number was reused), partial-history
safety (a synthetic dataset_id absent from a fresh `DatasetStore`), Phase 8C
traversal unaffected, secret redaction through the freshness endpoint, and
performance at 1,000 synthetic objects.

**Quality gates:** `pytest tests/ apps/api -q` → 797 passed, 4 pre-existing
skips; `ruff check` clean; CI's exact mypy invocation clean;
`tools/check_boundaries.py`/`tools/check_secrets.py` clean;
`tools/generate_typescript_contracts.py --check` clean after regenerating
(`FreshnessState`/`FreshnessAssessment` now in `generated.ts`). Full gate
record: `.prism/checkpoints/phase-8d.md`.

## 8E — Evidence + Lineage Inspector UI

**Objective:** Make the Phase 8A–8D backend intelligence visible in the
product — a dedicated, reusable evidence/lineage inspector, integrated
additively into the existing PRISM shell.

**Delivered:** `apps/web/src/components/evidence-inspector.tsx` — identity,
freshness (text+icon badge), dataset revision, provenance, method/
parameters, warnings, evidence, upstream/downstream direct dependencies
(clickable, with back-navigation), reproducibility. Pure GET-driven viewer,
never mutates. `InspectorObjectState` gained an optional
`analyticalObjectId`; the shell's `Inspector` renders `EvidenceInspector`
when it's set, additive to the existing architecture. Stats Lab wired as
the flagship integration (resolves the real object id via the unchanged
`GET /datasets/{id}/objects?kind=analysis` read endpoint after a run);
extending the same pattern to the other native workspaces is a documented,
low-risk follow-up, not done in this pass — the same kind of deliberate
scope choice Phase 8A made picking representative producers before 8B
expanded coverage.

**Design:** reuses PRISM's existing hairline/eyebrow/inspector CSS patterns
and dark/light custom properties exactly; no new theming logic. Lineage
navigation is a compact clickable list, not a graph-canvas library, per the
task's explicit preference for progressive expansion over a heavyweight
visualization dependency.

**Tests:** `evidence-inspector.test.tsx`, 5 new tests (identity/freshness/
parameters, stale-vs-current text distinction, parent navigation + back,
not-found handling, close button). `npm run test:web` → 27 passed (22
pre-existing + 5 new), zero regressions. `npm run lint`, `npm run
typecheck`, `npm run a11y:baseline`, `npm run build:web` all clean. Full
gate record: `.prism/checkpoints/phase-8e.md`.

## 8F — Reproducibility + Safe Rerun

**Objective:** Turn preserved reproducibility metadata into safe reruns. A
rerun never overwrites an existing object — it always creates a new one.

**Delivered:** `apps/api/src/prism_api/reproduction_service.py` reconstructs
a producer's original request purely from its own recorded
`provenance.reproducibility` (never from a client payload), then calls the
exact same computation the original route used — extracted as `execute_*`
helpers in `forecasting.py`/`mllab.py` (behavior-preserving, mechanical
extraction; `stats.run_test` already took an explicit `stored`, unchanged).
`same_revision` mode resolves the exact `(revision, source_fingerprint)`
identity via `DatasetStore.revisions()` — never revision number alone;
`current_revision` resolves DatasetStore's active identity. Supported:
`analysis`/`forecast`/`ml_model`/`visualization`. Deliberately unsupported,
each with a documented reason returned in the response: `dataset_revision`,
`cleaning_plan` (Clean's own apply/undo already is its rerun mechanism),
`query_result` (SQL Lab's async run/poll flow isn't supported by this
synchronous endpoint yet), `profile`, `evidence` — the same documented,
non-silent scope-boundary pattern Phase 8B established for producer
coverage gaps.

**API:** `POST /api/v1/lineage/objects/{id}/rerun` — body is `{"mode":
"same_revision"|"current_revision"}`, the only field a caller may supply.
Typed `ReproductionResponse` (`outcome`: created/unsupported/
validation_failed/source_revision_unavailable).

**UI:** Evidence Inspector's Reproducibility section gained "Reproduce on
original revision" / "Rerun on current data" (inline, no modal), plus an
inline outcome panel — a `created` result offers "View new result"
navigating the inspector to it; any other outcome shows its `detail`
message, `role="alert"`.

**Tests:** `tests/api/test_phase8f_reproduction.py`, 12 tests (Stats same/
current-revision, missing-column failure, Forecast/ML/Visualize rerun, SQL/
dataset-revision unsupported, abandoned-branch source-unavailability,
no-overwrite across repeated reruns, 404, secret safety). 2 new frontend
tests. `pytest tests/ apps/api -q` → 809 passed, 4 pre-existing skips; `npm
run test:web` → 29 passed. `ruff`/mypy (CI's exact invocation)/contracts/
frontend gates all clean. Full gate record:
`.prism/checkpoints/phase-8f.md`.
