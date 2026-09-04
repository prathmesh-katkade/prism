# Phase 10 Implementation Ledger — Atlas Local Intelligence Foundry

## Phase status

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`

Canonical starting point: `phase-6.5-integration-staging` at `ab75b5a`.
Phase 9 remains complete; its externally blocked Render certification is not an
engineering blocker for this phase.

## CI recovery increment (2026-09-04, before the Foundry wave)

A prior session's Foundry work was interrupted mid-wave with PR #15's CI red.
Recovery check found no interrupted local work anywhere (fresh clone, empty
`git status`/`diff`/`stash`, no Foundry-named branch or commit repo-wide) — the
pushed HEAD (`351f299`) was the honest last state. Fixed, tested, and pushed
(`9134f99`, `eb3a12b`, `65faec8`):

- Windows-only mypy symbols (`subprocess.CREATE_NEW_PROCESS_GROUP`,
  `ctypes.windll`) isolated behind a new `atlas_platform` module so Linux CI
  type-checks; Windows behavior unchanged, POSIX now gets real memory
  telemetry instead of always `None`.
- `CREATE INDEX IF NOT EXISTS` (invalid on MySQL 8.0) replaced with an
  Inspector-checked, restart-safe, MySQL/SQLite-portable `_ensure_index()`.
- A third, previously CI-unreached failure: `-> None` DELETE routes made
  FastAPI infer a truthy `NoneType` response_model, tripping its 204 assert
  at import time and breaking every test/tooling import of `prism_api.main`.
  Fixed with explicit `response_model=None`; stale generated TS contract
  regenerated.

- A fourth failure, found only once the live-MySQL job got this far:
  `prism_atlas_knowledge_chunks.source_ref` was indexed at its full
  `String(2000)` length, exceeding MySQL InnoDB's 3072-byte max index key
  under utf8mb4 (error 1071) — failing at `DurableAtlasMemoryStore`
  construction, i.e. `prism_api.main` import time. Fixed (`27923a4`) with a
  short `source_ref_hash` lookup column; `source_ref` keeps its full value
  and exact-equality semantics for callers. The MySQL-safe index helper was
  extracted into a shared `atlas_schema_utils` module used by both durable
  stores.

Local evidence: `ruff`/`mypy` clean (exact CI invocation), `pytest tests/api
tests/contracts tests/migration tests/overview tests/sql_lab` → 246 passed, 4
skipped, boundaries/secrets/contract-freshness all pass.

**CI on PR #15 is confirmed green at `27923a4`**: `phase-1-python`,
`phase-1-web`, `phase-4-live-e2e` (the real MySQL 8.0 job), `legacy-regression`,
and `secret-scan` all passed; `mergeable_state: clean`. The live-MySQL fixes
could not be reproduced locally in this sandbox (no Docker daemon, no
installable `mysql-server`), so this CI run is the authoritative
confirmation. **The Foundry wave (10M–10R) begins now.**

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

- `pytest tests/api/test_atlas_runtime.py tests/api/test_atlas_durable_runtime.py tests/api/test_atlas_sandbox.py tests/api/test_atlas_memory_resources_research.py -q` → **16 passed** (one non-failing FastAPI deprecation warning).
- `npm run typecheck`, `npm run lint`, and `npm run test:web` → **passed** (35 frontend tests).
- `python tools/check_boundaries.py`, `python tools/check_secrets.py`, and TypeScript contract freshness → **passed**.
- `npm run build:web` is **BLOCKED_LOCAL_WORKTREE**: Next/Turbopack rejects this worktree's `node_modules` symlink because it points outside the worktree root. This is not a source compilation/type failure; supported CI must build from a normal checkout.
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
