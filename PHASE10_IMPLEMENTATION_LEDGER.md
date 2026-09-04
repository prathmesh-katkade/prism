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
| 10A Runtime/provider abstraction | ADVANCED | Deterministic fallback is always available. Ollama may now propose JSON plans from capped compact metadata only; schema/tool validation rejects invalid output and records provider/model/prompt-schema provenance. It cannot execute tools or receive raw rows. |
| 10B Orchestrator/planning | ADVANCED | SQLAlchemy-backed runs/event journal, deterministic event sequence, idempotency key, durable cancellation intent/replay, dynamic typed planner, declared-tool validation, and safe insufficient-context blocking. |
| 10C Specialist team/Council | ADVANCED | Visible Atlas/Scout/Curator/Stat/Auditor identities; Curator now performs actual quality review. Query/Forge/Oracle/Lens are typed plan identities only when the required native request context exists; none is faked as an executor. |
| 10D Secure Python sandbox | PARTIAL | Native-worker process boundary now has an empty user environment, new process group/tree termination, deny-by-default network/import/filesystem policy, bounded output, artifacts, health/capability reporting, and honest Windows quota status. Hard CPU/memory enforcement requires a configured container worker and remains unclaimed. |
| 10E Memory/RAG | PARTIAL | SQL-backed scoped memory CRUD/reinforcement/supersession/audit plus project-isolated lexical knowledge indexing, source version/reindex/delete, provenance and prompt-injection flags. Local embedding adapter and analytical-history ingestion remain next increments. |
| 10F Researcher | PARTIAL | Explicit server-side allowlisted-HTTPS Researcher has typed results/citations, offline/blocked behavior, bounded untrusted content, and injection flags. It is not unrestricted search or a sandbox capability. |
| 10G Cortex graph data model | ADVANCED | Cortex projects durable run, dataset, plan, specialist, declared tool, and evidence IDs only. |
| 10H Cortex visual system | PARTIAL | Native SVG Cortex V1 provides organic curved paths, state styling, Focus Lens, zoom controls, and reduced-motion mode over only real graph records. Dense/3D visualization remains out of scope. |
| 10I Observable execution UI | ADVANCED | Native Atlas operations desk renders objective, state, live SSE-updated plan, specialist activity, Council/evidence, cancellation, errors, grounded answer, and Cortex V1. |
| 10L Resource Governor | PARTIAL | Typed priority leases, cancellation-aware preemption, concurrency admission, CPU/RAM/storage snapshot, optional GPU telemetry, and truthful no-GPU reporting. Cross-process scheduling and Foundry integration remain future work. |
| 10J–10K, 10M–10T | NOT STARTED | Multimodal, voice, Foundry, training, benchmarks, promotion, experiments, and desktop packaging remain future internal gates. |
| 10U–10W | NOT STARTED | Flagship workflow and final certification remain out of scope for this first wave. |

## Invariants preserved

- Existing AI Analyst remains compatible and retains its compact, server-only
  context plus SQL Lab-only execution path.
- Atlas invokes only declared deterministic tools. Python is a separately typed,
  constrained project sandbox; it has no generic shell, network, package-install,
  model-download, or inferred-code path. SQL remains SQL Lab-only.
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

Certify this second wave in supported Python 3.11/CI, then harden the sandbox
with a platform worker/container boundary before enabling run-integrated custom
Python or any package-management path. Do not start Phase 11.
