# Phase 8G Checkpoint — Atlas Lineage Awareness

- Branch: `phase-8-completion`
- Base: Phase 8F commit on this branch
- Date: 2026-08-31
- Status: **locally complete**

## Scope

Atlas becomes provenance-aware: it can explain what produced a result, why
it is stale, its lineage shape, what to consider rerunning, evidence
behind it, and how two objects compare — grounded entirely in Phase 8A-8F's
own recorded data.

## Critical design fact

**Atlas, everywhere in this codebase (`stats.py`/`visualize.py`/
`forecasting.py`'s own existing `/atlas` routes), is a deterministic
rule-based explainer over already-computed results — not an LLM call.**
`apps/api/src/prism_api/atlas_lineage.py` follows that exact established
pattern: every field in an `AtlasLineageResponse` traces back to one
`registry`/`freshness_service` call, never to free-text generation. "No
invented dependencies/versions/stale reasons/evidence/parameters" is
therefore structural, not a prompting concern — there is no model in the
loop to hallucinate, and no chain-of-thought exists to leak.

## Delivered

**8G.1 tools** (thin, typed — never expose raw registry internals): the
module wraps `registry.get`/`get_parents`/`get_children`/`ancestors`/
`descendants` and `freshness_service.assess_object` directly; no new
indexing or traversal logic (Phase 8C/8D's own is reused as-is).

**8G.2 actions:** `explain_provenance`, `explain_staleness`,
`explain_lineage`, `compare_versions`, `recommend_reruns`,
`explain_evidence` — matching the exact `AtlasEvidence`/summary/uncertainty
response shape every other workspace's Atlas action already uses, plus one
addition: an optional `limitation` field, used precisely for 8G.4's
"missing lineage → limitation, not hallucination" requirement (an
unresolvable dataset identity, a missing comparison target, no recorded
evidence — each reported as `limitation`, never guessed around).

**8G.3 rerun recommendations:** `recommend_reruns` walks
`registry.descendants()` (Phase 8C, unchanged) and reports only objects
whose live `freshness_service.assess_object` call actually returns `stale`
— never a blanket "everything downstream." Nothing is ever auto-rerun; the
response only names candidates for the existing, explicit Phase 8F
`/rerun` action.

**8G.5 UI integration:** the Evidence Inspector gained an "ATLAS ·
LINEAGE-AWARE" section with five one-click actions ("Why is this stale?"
etc.) that fire against the currently-selected object id automatically —
no manual id entry, reusing the exact `.atlas-action-row`/`.atlas-result`
CSS classes every other native workspace's Atlas UI already uses, for
visual consistency.

**API:** `POST /api/v1/lineage/objects/{object_id}/atlas`, body
`{"action": ..., "compare_to_object_id"?: ...}` — read-only (no analytical
side effect), 404 for an unknown object.

## Gate summary

| Gate | Status | Evidence |
|---|---|---|
| Atlas provenance tools | PASS | Thin wrappers over existing registry/freshness_service calls; no raw internals exposed to the response layer. |
| Freshness awareness | PASS | `explain_staleness`'s summary is verified to literally contain the same `reason` text the `/freshness` endpoint itself returns for the same object. |
| Lineage awareness | PASS | `explain_lineage`'s evidence counts verified against direct-parent/child and total ancestor/descendant counts for a real multi-revision chain. |
| Evidence explanation | PASS | `explain_evidence` reflects recorded `evidence_refs`; a dataset-revision object (which carries none) reports a `limitation`, not a fabricated summary. |
| Rerun recommendation | PASS | `recommend_reruns` returns empty before a revision changes and lists exactly the object that goes stale after one, verified directly. |
| No invented dependencies | PASS | Every response field is asserted to originate in the registry/freshness_service call it wraps; `compare_versions` without a target, or against an unknown object, returns a `limitation`, never a guess. |
| Partial-history safety | PASS | `explain_staleness` against a synthetic dataset_id absent from a fresh `DatasetStore` returns `freshness_known=false`-derived `limitation` text, mirroring Phase 8D's own test. |
| UI context integration | PASS | Atlas actions in the Evidence Inspector fire against the current `objectId` prop with no id-entry field; verified the outgoing request body is exactly `{"action": ...}`. |
| Tests | PASS | `tests/api/test_phase8g_atlas_lineage.py`, 11 tests. 2 new frontend tests (ask-and-render, limitation-not-hallucination). |
| Full regression | PASS | `pytest tests/ apps/api -q` → 820 passed, 4 pre-existing skips. `npm run test:web` → 31 passed. |
| ruff / mypy / contracts / frontend gates | PASS | Repo-wide `ruff check` clean; CI's exact mypy invocation clean; `tools/generate_typescript_contracts.py --check` clean after regenerating (`AtlasLineageAction`/`AtlasLineageRequest`/`AtlasLineageResponse` now in `generated.ts`); `npm run lint`, `npm run typecheck`, `npm run a11y:baseline`, `npm run build:web` all clean. |

## Verdict

**LOCALLY COMPLETE.** Proceeding immediately to Phase 8H per the mega-run's
autonomous-continuation instruction.
