# Phase 10 Implementation Ledger — Atlas Local Intelligence Foundry

## Phase status

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`

Canonical starting point: `phase-6.5-integration-staging` at `ab75b5a`.
Phase 9 remains complete; its externally blocked Render certification is not an
engineering blocker for this phase.

## First implementation wave

| Internal gate | Status | Evidence |
| --- | --- | --- |
| 10A Runtime/provider abstraction | PARTIAL | Typed deterministic/Ollama provider capability registry; deterministic fallback is always available and raw data policy is `never`. |
| 10B Orchestrator/planning | PARTIAL | Typed three-step plan, declared tool names, capped retry contract, stored run state, cancellation request, SSE events. |
| 10C Specialist team/Council | PARTIAL | Visible Atlas/Scout/Stat/Auditor identities; Scout profile, Stat methodology objection, Auditor evidence audit; Atlas is sole user-facing speaker. |
| 10D Secure Python sandbox | NOT STARTED | ADR only; no Python/shell execution surface exists. |
| 10E Memory/RAG | CONTRACT ONLY | Scope/provenance contract and ADR; no persistence or retrieval implementation. |
| 10F Researcher | NOT STARTED | No web tool is exposed in the first slice. |
| 10G Cortex graph data model | PARTIAL | Cortex API projection maps only real run/step/specialist/evidence IDs. |
| 10H Cortex visual system | NOT STARTED | Deliberately deferred until graph data is durable and stable. |
| 10I Observable execution UI | BACKEND ONLY | SSE and visible state contracts exist; web UI is not yet added. |
| 10J–10T | NOT STARTED | Multimodal, voice, resource governor implementation, Foundry, training, benchmarks, promotion, experiments, desktop packaging remain future internal gates. |
| 10U–10W | NOT STARTED | Flagship workflow and final certification remain out of scope for this first wave. |

## Invariants preserved

- Existing AI Analyst remains compatible and retains its compact, server-only
  context plus SQL Lab-only execution path.
- Atlas invokes only declared deterministic first-wave tools. It has no generic
  shell, Python, SQL, network, package-install, or model-download endpoint.
- DatasetStore remains the revision/content authority. Atlas evidence references
  its active identity and never changes it.
- No historical analytical object, lineage edge, audit event, or freshness value
  is mutated by this wave.
- Cortex derives from stored runtime records; it does not expose fabricated
  thoughts or a chain of thought.

## First demonstrator

`unknown CSV → Overview profile → Scout conclusion → Stat methodology review →
Auditor evidence review → Atlas grounded answer`, with events available through
`GET /api/v1/atlas/runs/{run_id}/events` and the real-state graph through
`GET /api/v1/atlas/runs/{run_id}/cortex`.

## Verification to date

- `pytest tests/api/test_atlas_runtime.py tests/api/test_ai_analyst.py tests/api/test_contracts.py -q` → **19 passed**.
- Broader API/contract/parity run reached **42 passed** before the known local
  Python 3.9 incompatibility in pre-existing Forecasting tests
  (`zip(..., strict=True)`, a Python 3.10+ API). This is not an Atlas failure;
  authoritative full certification requires the project CI's supported Python
  3.11 environment.
- `ruff check` over the new runtime, public contracts, and tests → **passed**.
- targeted `mypy` over the new runtime and contracts → **passed**.
- TypeScript public contract regenerated and freshness check passed.
- Full repository, browser, sandbox-isolation, memory, model-trust, AtlasBench,
  and accessibility gates are intentionally not yet certification evidence.

## Exact next task

Persist Atlas runs/events with the Phase 9 durable-history boundary, then add a
safe project-scoped sandbox contract and tests before enabling generated Python
execution. Do not start Phase 11.
