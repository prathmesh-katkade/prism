# Phase 8C Checkpoint — Deterministic Dependency Graph / Lineage Traversal

- Branch: `phase-8c-lineage-traversal`
- Base branch: `phase-6.5-integration-staging`
- Base commit: `670d670ee0cdaaff7a6a62f1281d2df8b6802cf8` (PR #11 / Phase 8B merge)
- Date: 2026-08-31
- Status: **locally complete, PR pending**

## Scope

Phase 8C makes the direct `parent_refs` graph Phase 8A/8B already record
walkable: direct parent/child lookup, transitive ancestor/descendant BFS with
deterministic depth and ordering, bounded `max_depth`, a compact combined
graph view, and an optional shortest path. Entirely read-only, entirely
deterministic (no AI inference), no new parent links created, no staleness
propagation, invalidation propagation, rerun engine, Atlas lineage awareness,
lineage UI, database persistence, governance, or Phase 9 behavior.

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| 8A merged | PASS | PR #10 merged into `phase-6.5-integration-staging` at `4912610be584e2b3e9902500bd6585aeebb8a506`. |
| 8B merged | PASS | PR #11 merged into `phase-6.5-integration-staging` at `670d670ee0cdaaff7a6a62f1281d2df8b6802cf8`. |
| Reverse child index | PASS | `AnalyticalObjectRegistry._child_index` maintained inline in `register()`; a child lookup is a dict access, never a full-registry scan; covered by the same lock as every other mutation. |
| Direct parents | PASS | `get_parents` — correct parent for a non-root object, `[]` for a root, `None` (→ 404) for an unknown id; a parent_ref pointing outside the registry is skipped, not invented. |
| Direct children | PASS | `get_children` — all direct dependents of a revision, `[]` for a leaf, `None` (→ 404) for an unknown id. |
| Ancestor traversal | PASS | Iterative BFS, exact multi-hop revision chain with correct per-node depth, verified against a real 3-revision Clean chain. |
| Descendant traversal | PASS | Fan-out to multiple same-revision analyses and into the next revision's own descendants, at correct depth; branch traversal (two Clean branches sharing a source revision) never collapses or duplicates. |
| Depth semantics | PASS | `parents`/`children`/`ancestors`/`descendants` exclude the root; the compact `/graph` endpoint includes it at depth 0 — one documented, consistently-applied convention. |
| Depth limits | PASS | `max_depth` validated `1–100`; out-of-range is a typed 422; `truncated` correctly reflects whether real unexplored neighbors remained past the cutoff, tested at `max_depth=1`, `=2`, and full traversal. |
| Cycle safety | PASS | BFS visited/depth map guarantees termination and no duplicate emission regardless of graph shape; a directly-corrupted synthetic 3-hop cycle (not reachable via the public API) completes in well under a second with no duplicates. |
| Deterministic ordering | PASS | `(depth ASC, object_id ASC)` for nodes, `(parent_object_id ASC, child_object_id ASC)` for edges; identical repeated calls produce byte-identical responses. |
| Fingerprint revision identity | PASS | Traversal walks `object_id`s, which already encode `(dataset_id, revision, source_fingerprint)`; two dataset-revision objects sharing a revision number but differing fingerprint are proven to never cross-contaminate an ancestor set. |
| Partial graph handling | PASS | A `parent_ref` pointing at an object the process-local registry never observed is skipped safely, at both the direct-lookup and BFS layers; no crash, no fabricated node. |
| Read-only lineage API | PASS | Six new `GET` routes (`parents`/`children`/`ancestors`/`descendants`/`graph`/`path`) plus the two pre-existing ones; no `POST`/`PATCH`/`DELETE` exists, or was added, under `/lineage`. |
| Immutable responses | PASS | Mutating a returned traversal payload's nested object/list never mutates registry state on the next read — every node is a fresh `model_validate` reconstruction. |
| Secret safety | PASS | A SQL Lab bind parameter (`api_key`) stays `[redacted]` through both `/descendants` and `/graph` HTTP responses — traversal reuses already-sanitized registration-time snapshots, no new leak surface. |
| Performance sanity | PASS | 1,000-node long chain (`ancestors` on the tail) and a 5,000-child wide tree (`get_children`, repeated calls, depth-limited `descendants`) all complete comfortably sub-second per call; no full-registry scan anywhere in the traversal path. |
| Backward compatibility | PASS | The two pre-existing lineage routes are byte-for-byte unchanged; no Phase 3–7 producer route touched; all 8C routes are additive. |
| OpenAPI/TS contracts | PASS | `tools/generate_typescript_contracts.py --check` clean after regenerating; `LineageDirection`/`LineageNode`/`LineageEdge`/`LineageTraversal`/`LineagePath` now in `packages/api-contracts/typescript/src/generated.ts`. |
| Python tests | PASS | `pytest tests/ apps/api -q` → 784 passed, 4 pre-existing skips (no local MySQL); 26 new Phase 8C tests, all Phase 8A/8B tests unmodified and still green. |
| Lint and mypy | PASS | `ruff check` (repo-wide) clean; `mypy --follow-imports=skip --allow-subclassing-any --allow-untyped-decorators --no-warn-return-any apps/api/src packages` (CI's exact invocation) clean. |
| Boundaries and secret scan | PASS | `tools/check_boundaries.py` clean; `tools/check_secrets.py` clean. |
| Frontend gates | PASS | `npm run lint`, `npm run typecheck`, `npm run test:web` (22 tests, unchanged — no frontend code touched by 8C), `npm run a11y:baseline`, `npm run build:web` all clean. |
| Legacy regression | PASS | Zero diff to `app.py`/`modules/`; `py_compile` clean; `eval/autocleaner_eval.py` 8/8. |
| CI | PENDING | Not yet pushed/opened as a PR from this checkpoint. |

## Verdict

**LOCALLY COMPLETE.** Every gate checkable without a live CI run passes.
Ready to push `phase-8c-lineage-traversal` and open a PR into
`phase-6.5-integration-staging`.

## Known limitations, restated

The registry remains process-local and in-memory — an API restart resets all
analytical history, including the lineage graph built on top of it.
Persistent history still needs a dedicated architecture decision (a
database-backed registry) for a later phase, not attempted in 8A, 8B, or 8C.
Dataset-revision identity still depends on `(dataset_id, revision,
source_fingerprint)`, never revision number alone — 8C traversal inherits
this correctly by walking object ids, which already encode the full
identity.

## 8D starting point

Phase 8D — Versioning + Staleness Propagation — answers "a dataset revision
changed; which downstream analytical objects are now stale?" by reusing the
descendant traversal 8C already built
(`registry.descendants(dataset_revision_object_id)` already gives the full,
correctly-ordered set of everything that would need re-evaluation). 8D's
actual new work is deciding what "stale" means as a lifecycle state,
mutating `AnalyticalObject.lifecycle` for affected objects (the registry is
currently append-only, never update-in-place, so this is a real design
decision), and exposing that as a read surface. Do not implement staleness
mutation, invalidation propagation, a rerun/reproduction engine, Atlas
lineage reasoning, a lineage/evidence frontend UI, database persistence, or
Phase 9 work under this checkpoint.

```
PHASE_8A_COMPLETE = YES
PHASE_8B_COMPLETE = YES
PHASE_8C_COMPLETE = NO   (locally complete; flips to YES once PR CI is green and merged - see the "Status" line at the top of this file for the current state)
PHASE_8D_STARTED = NO
```
