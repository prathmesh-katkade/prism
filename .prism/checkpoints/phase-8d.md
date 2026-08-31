# Phase 8D Checkpoint — Versioning + Staleness Propagation

- Branch: `phase-8-completion`
- Base: `phase-6.5-integration-staging` at `68377c7` (PR #12 / Phase 8C merge + docs)
- Date: 2026-08-31
- Status: **locally complete**

## Scope

Contextual freshness (`current`/`stale`/`superseded`/`unknown`/`invalid`),
computed live against `DatasetStore`'s active identity on every read.
`AnalyticalObject` stays immutable — freshness is never stored on it, never
mutates historical evidence. No new graph engine: per-object freshness is a
direct `(dataset_id, revision, source_fingerprint)` comparison (every
producer already pins the exact identity it consumed); the one place
Phase 8C's own `descendants()` traversal is reused is to size the "N objects
still depend on this revision" reason text on a superseded dataset-revision
object.

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| Freshness model | PASS | `FreshnessState` (current/stale/superseded/unknown/invalid) + `FreshnessAssessment`, in `prism_analytical_schemas` next to `AnalyticalObject`. |
| Fingerprint-aware identity | PASS | Freshness compares the full `(dataset_id, revision, source_fingerprint)` tuple, never revision alone; an abandoned undo/redo branch reads `stale`, never `current`, even when its revision number is reused by the active branch. |
| Current semantics | PASS | An object whose own dataset ref exactly matches DatasetStore's active identity is `current`. |
| Stale semantics | PASS | A non-dataset-revision object whose upstream revision is no longer active is `stale`; multiple descendants of one superseded revision go stale together, immediately (no propagation lag - lazy per-read computation). |
| Supersession semantics | PASS | Reserved for `DATASET_REVISION` objects only - an old revision object (or an abandoned same-revision-number branch) is `superseded`, never `stale`; a non-revision analytical result is never marked `superseded`. |
| Partial-history handling | PASS | A dataset_id the process-local `DatasetStore` no longer knows about (e.g. after a restart) reads `unknown`/`freshness_known=false` - never guessed as current or stale. |
| Undo/revert | PASS | Reused-revision-number branching tested directly against the freshness endpoint. |
| Immutable evidence | PASS | No field on `AnalyticalObject` changes; freshness is a separate, uncached, recomputed-per-read response. |
| Freshness API | PASS | `GET /objects/{id}/freshness` (404 for an unknown object), `GET /datasets/{id}/freshness` (empty list, never 404, for an untouched dataset). No mutation route added. |
| Tests | PASS | `tests/api/test_phase8d_freshness.py`, 13 tests: current/stale/superseded/unknown, multi-descendant staleness, dataset-revision vs. analysis distinction, immediate (non-lagged) staleness, fingerprint-safe undo/redo, partial-history safety, 8C traversal unaffected, secret safety, performance at 1,000 synthetic objects. |
| ruff / mypy | PASS | Repo-wide `ruff check` clean; CI's exact mypy invocation clean. |
| Contracts fresh | PASS | `tools/generate_typescript_contracts.py --check` clean after regenerating (`FreshnessState`/`FreshnessAssessment` now in `generated.ts`). |
| Full regression | PASS | `pytest tests/ apps/api -q` → 797 passed, 4 pre-existing skips. |
| Boundaries / secret scan | PASS | `tools/check_boundaries.py`, `tools/check_secrets.py` clean. |

## Verdict

**LOCALLY COMPLETE.** Proceeding immediately to Phase 8E per the mega-run's
autonomous-continuation instruction.
