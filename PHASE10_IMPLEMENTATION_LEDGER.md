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
| 10L Resource Governor | PARTIAL | Typed priority leases, cancellation-aware preemption, concurrency admission, CPU/RAM/storage snapshot, optional GPU telemetry, truthful no-GPU reporting, **and now real Foundry-training integration** (`atlas_foundry_orchestration.start_training_job`/`reconcile_foundry_jobs`): every training job is admitted at `FOUNDRY_TRAINING` priority, and a preempting interactive lease hard-cancels the running job (an honest "yield," not a claimed graceful pause). |
| 10M Atlas Foundry | ADVANCED | `FoundryBackend` (ABC) / `MockFoundryBackend` / `SoupFoundryBackend` (real, tested against the actual `soup` CLI inspected from its upstream repo — v0.73.3's `soup.yaml` schema, `soup profile --json`, checkpoint conventions). Recipes reach Soup only via a validated `AtlasTrainingRecipe` rendered to YAML, never a string-built command. `soup` is absent in every environment this project runs in so far; every backend method degrades to an honest "unavailable" result rather than a crash or a pretend success. Resource-Governor-admitted job lifecycle (queue/start/poll/cancel) plus a durable, MySQL-safe job/recipe store. |
| Candidate Registry | ADVANCED | `DurableAtlasCandidateRegistry`: a completed job with real adapter output on disk registers exactly one `AtlasCandidateArtifact`, idempotently. Deliberately just the durable fact of what was produced — no promotion-status lifecycle (DISCOVERED/PROMOTED/...) is invented here; that is 10Q's concern once AtlasBench exists to gate it. |
| 10N Verified training-data generator | ADVANCED | `AtlasTrainingDatasetBuilder`: eligible-only (completed, evidence-backed, answered, ≥1 completed tool step), redacted a second time at the export boundary, deterministic ~80/10/10 split keyed on `dataset_id` so near-duplicates never straddle splits, content-hash dedup, deterministic JSONL export, idempotent durable versioned storage with preview/exclusion inspection. No hidden chain-of-thought: reuses Atlas's own typed, already-user-visible plan/council structures. |
| 10O SFT/DPO/KTO | PARTIAL | SFT is 10N. DPO (`AtlasPreferenceDatasetBuilder`) sources real chosen/rejected pairs from Atlas memory's existing `supersede()` correction workflow — never a manufactured negative example; a dangling successor or no-op correction is excluded, not faked. **KTO is deliberately not implemented**: no genuine binary accept/reject feedback signal exists anywhere in the product yet, and inventing one would violate the same rule that makes the DPO source trustworthy. PPO/GRPO remain explicitly out of scope. |
| 10P AtlasBench | ADVANCED (initial corpus) | 90 hand-authored, correctness-checked tasks across all ten required categories (SQL/statistics/ML/forecasting/causal-safety/agentic/evidence/Python-sandbox/personality/general) — an initial wave chosen for correctness over volume, not yet the "thousands of tasks" scale the architecture supports. Frozen, version-controlled answer key with no runtime write path (a candidate cannot see or influence its own judge); deterministic `run_suite()` scoring against a pluggable `AtlasBenchSubject`; append-only durable run history (a rerun is a new `run_id`, never an edit). |
| 10Q Shadow Brain / Promotion / Rollback | ADVANCED | `shadow_compare()` runs production and candidate through the identical AtlasBench corpus — non-mutation is structural (a subject only ever receives a prompt + choices, returns an index). `decide_promotion()` enforces the locked policy: IMPROVE TARGET CAPABILITY + NO UNACCEPTABLE CRITICAL REGRESSION, against `CRITICAL_CATEGORIES` (SQL/statistics/ML/causal-safety/agentic/evidence/Python-sandbox) — a candidate cannot win on aggregate score while regressing any one critical category. `DurableAtlasPromotionStore` is an append-only production-pointer event log: `promote()` is atomic and refuses any non-`PROMOTE_ELIGIBLE` decision at the storage boundary itself; `rollback()` restores the previous production candidate as a new explicit event, never an in-place undo — the full history IS the rollback list, and no row is ever overwritten. |
| Adapter Foundation | ADVANCED (honest stub) | Typed logical adapter identities (`atlas-core/sql/statistics/ml/forecast/research`) with a capability report that is truthfully all-`False` right now: no runtime wired into this project can load, unload, or hot-swap a LoRA adapter at inference time, and reporting otherwise would be exactly the fabricated-capability failure this module exists to prevent. Falls back to core Atlas by construction. |
| 10R Atlas Evolution UI | ADVANCED (real data, no live promotable candidate yet) | Native `EvolutionWorkspace` tab wired into the shell, reading Foundry capability, AtlasBench corpus summary, current/history promotion pointers, candidates, training/preference dataset versions, training jobs, and adapter capabilities from the routes below. Every panel renders a specific, honest empty state (no candidate trained, no promotion made, no job queued) rather than a placeholder — there is nothing to fake because no candidate has ever actually been trained or promoted in this environment. The only mutating action on the promotion panel is rollback (operator-supplied reason, never a client-supplied verdict); dataset builders and job reconciliation call the same read/write boundary the REST layer enforces. |
| 10J–10K, 10S–10T | NOT STARTED | Multimodal, voice, and desktop-packaging-adjacent gates remain future internal gates untouched by this wave. |
| 10U–10W | NOT STARTED | Flagship workflow and final certification remain out of scope for this wave. |

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

## Foundry wave (2026-09-04, 10M–10Q)

Built only after PR #15's foundation CI was confirmed green at `27923a4`, in
this order, one commit per coherent unit:

| Commit | Unit | Module(s) |
| --- | --- | --- |
| `b0926ca` | 10N | `atlas_foundry_dataset.py` |
| `4c6e8e4` | 10O | `atlas_foundry_preference.py` |
| `856fb30` | 10M-1/2/3 + Candidate Registry | `atlas_foundry_backend.py`, `atlas_foundry_orchestration.py`, `atlas_platform.py` additions |
| `1af8562` | 10P | `atlas_bench_corpus.py`, `atlas_bench_runner.py`, `atlas_bench_store.py` |
| `063de4d` | 10Q + Adapter Foundation | `atlas_promotion.py`, `atlas_adapter_foundation.py` |

Every commit above: `ruff`/`mypy` clean (exact CI invocation), full
`pytest tests/api tests/contracts tests/migration tests/overview
tests/sql_lab` suite green before pushing (288 passed / 4 skipped at
`063de4d`), boundaries/secrets/contract-freshness all pass. CI on PR #15
confirmed green through `1af8562`; `063de4d`'s run was in flight at last
check (see `.prism/checkpoints/phase-10-progress.md` for the live status).
`phase-4-live-e2e` intermittently fails on two different frontend Playwright
specs unrelated to any file this wave touched — a pre-existing,
Phase-9-documented CI-runner-timing flake (see the standing-down comment on
PR #15); not this wave's regression.

Deliberately not fabricated in this wave:
- **KTO** (10O): no genuine binary accept/reject feedback signal exists in
  the product.
- **Adapter hot-swap**: no runtime here can load/unload/hot-swap a LoRA
  adapter; `AtlasAdapterCapability` reports that honestly.
- **Real Soup training**: `soup` is not installed anywhere this project has
  run; `SoupFoundryBackend` is real, tested code, but has never actually
  launched a training subprocess outside its own "absent" path. The recipe
  → YAML rendering, capability probing, and process lifecycle logic are
  fully tested; the live end-to-end training path is not, and should not be
  claimed as verified until it has actually run against a real `soup`
  install.
- **A wired AtlasBench subject**: the corpus/runner/store are real and
  tested against reference subjects (Perfect/Worst/FirstChoice) that prove
  the harness itself is correct. No subject wrapping a live Atlas provider
  (deterministic or Ollama) exists yet — that is the natural next increment,
  not assumed done here.
- **REST endpoints / UI**: nothing in `atlas_foundry_dataset.py`,
  `atlas_foundry_preference.py`, `atlas_foundry_backend.py`,
  `atlas_foundry_orchestration.py`, `atlas_bench_*.py`, or `atlas_promotion.py`
  is wired to `apps/api/src/prism_api/atlas.py` (the FastAPI router) yet.
  Everything above is backend modules, durable stores, and tests only.

## REST wiring + 10R (2026-09-04, same session, continued autonomously)

| Commit | Unit | Module(s) |
| --- | --- | --- |
| `61124f5` | REST wiring for 10M–10Q | `atlas_foundry_routes.py` (new), `main.py` router registration, `generated.ts` regenerated |
| `779222b` | 10R Atlas Evolution UI | `evolution-workspace.tsx` (new), `evolution-workspace.test.tsx` (new), `prism-shell.tsx`, `shell-model.ts`, `prism.css` |

`atlas_foundry_routes.py` exposes `/api/v1/atlas/foundry`, `/api/v1/atlas/bench`,
`/api/v1/atlas/promotion`, and `/api/v1/atlas/adapters`, deliberately narrower
than the backend surface it wraps on two security-relevant boundaries: no
route ever returns an `AtlasBenchTask`'s `correct_choice`/`rationale` (only
the safe `AtlasBenchCorpusSummary` — counts, no answer key — is public), and
there is no "promote" endpoint — only read-only current-production/history
and the no-client-input `rollback` action, because a promotion decision must
come from a real server-side `decide_promotion()` call over a real suite run,
never a client-supplied `AtlasPromotionDecision`. 9 new integration tests
verify both boundaries plus the training/preference dataset build-list-preview
round trip, job start/cancel/reconcile, and clean 404s. 10R's
`EvolutionWorkspace` consumes exactly this surface; see the 10R row above for
what it renders and why every empty state is honest rather than a fabricated
"current model."

Both commits: `npm run typecheck`/`lint`/`test:web` pass (38/38 across 11
suites at `779222b`); `61124f5`'s backend changes also passed the full
`ruff`/`mypy`/pytest (297 passed)/boundaries/secrets/contract-freshness
pass locally before pushing. `phase-4-live-e2e` failed a third time at
`61124f5` (CI run #131) on the same pre-existing `history-live.spec.ts`
timing flake already documented in the standing-down PR comment (see
`b0926ca`/`4c6e8e4`'s occurrences above) — same assertion
(`'3 returned / 3 total rows'`), still nowhere near this wave's diff.
`779222b`'s CI run (#132) is the natural re-run this situation calls for;
see `.prism/checkpoints/phase-10-progress.md` for its outcome.

Deliberately not done in this increment:
- No live `AtlasBenchSubject` wraps a real Atlas provider yet, so there is
  no "run the benchmark suite" REST action — only read-only run history for
  whatever a caller runs out-of-band.
- No candidate has ever actually been promoted in any environment this
  project has run in, so the Evolution UI's production/candidate/history
  panels are exercised by tests against real (empty or seeded-in-test) durable
  state, not against a real end-to-end promotion that has actually happened.
- `soup` remains absent from every environment this project runs in; starting
  a real Foundry job through the UI will queue or fail honestly, exactly as
  the backend already did before this wiring.

## Exact next task

The build order specified for this session (10N, 10O, 10M, Candidate
Registry, 10P, 10Q, Promotion/Rollback, Adapter Foundation, 10R) is now
complete. Remaining natural next increments, none started here: wire a first
real `AtlasBenchSubject` around the existing deterministic Atlas provider so
`shadow_compare`/`decide_promotion` can run against a live subject instead of
only the reference (Perfect/Worst/FirstChoice) subjects; expose a "run the
benchmark suite" REST action once that subject exists; and exercise an actual
end-to-end `soup train` run against a real Soup install to move
`SoupFoundryBackend` from "real and tested" to "verified end-to-end."
`PHASE_10_COMPLETE` remains `NO`. Do not start Phase 11.

## Evolution activation hardening — canonical current state (2026-09-04)

This section supersedes earlier statements above that describe live AtlasBench,
Foundry REST wiring, History live-E2E, or promotion as not yet operational at
the software boundary. Those entries are retained as historical implementation
records.

### Gate status after activation

| Gate | Current state |
| --- | --- |
| 10M Atlas Foundry | **ADVANCED / PHYSICAL RUN PENDING.** Current upstream contract was re-verified and the first experiment is pinned to `soup-cli==0.74.0`; the normal API and local runner use the same typed `SoupFoundryBackend`. |
| 10N training data | **ADVANCED.** Normal Foundry and experiment activation export `TRAIN` only; validation/test-only versions fail closed. Hidden CoT, secrets, and raw private rows remain excluded. |
| 10P AtlasBench | **ADVANCED / LIVE OLLAMA SUBJECT IMPLEMENTED.** A real Ollama subject probes `/api/tags`, uses the production model/provider configuration, receives prompt+choices only, and persists no fake baseline when the runtime/model is unavailable. |
| 10Q Shadow/Promotion/Rollback | **ADVANCED / RUNTIME-EFFECTIVE.** Candidate→Ollama bindings are durable. A verified model digest is required before the first production rollback anchor may be created. Promotion requires an evaluator-owned eligible decision plus a real runtime binding, changes Atlas's active model, and rollback verifies/binds the previous runtime before changing the pointer. |
| 10R Evolution UI | **ADVANCED.** It reads durable production/candidate/benchmark/training/history state. Synthetic demo data is not introduced. |

### CI and browser recovery

The recurring History live-E2E failure was fixed at the actual synchronization
boundary: the test now binds SQL Lab to the exact dataset it created and waits
on real API state instead of depending on cross-test connection ordering or
arbitrary timeout growth. The duplicate AI Analyst evidence React key was also
removed.

Activation code head `5ee368e8df911c65c1121be346b0f8c9ccef504f`
is certified by PR #15 CI run **#166** (`33904258400`):

- `phase-1-python` PASS
- `phase-1-web` PASS
- `phase-4-live-e2e` PASS, including real MySQL 8.0/browser-to-API flow
- `legacy-regression` PASS
- `secret-scan` PASS

The earlier lifecycle head was independently all-green on run #163, and the
History root fix was independently all-green on run #152.

### One-command real evolution experiment

`tools/run_atlas_evolution_experiment.py` is now the canonical first physical
activation path. It:

1. restores any already-durable production runtime pointer;
2. benchmarks the actual reachable Ollama production model;
3. creates the first rollback anchor only from that successful model probe and
   digest;
4. builds/persists verified training data and exports TRAIN only;
5. installs/uses isolated pinned Soup 0.74.0 when required;
6. runs a Resource-Governor-admitted SFT LoRA/QLoRA smoke job using the first
   trust-locked base model `Qwen/Qwen2.5-0.5B-Instruct`;
7. requires actual adapter output before registering a candidate;
8. exports/deploys the candidate to Ollama and verifies it appears in
   `/api/tags`;
9. persists the candidate runtime binding;
10. runs candidate AtlasBench on the identical frozen corpus version/hash;
11. computes and persists the locked server-side verdict;
12. for `PROMOTE_ELIGIBLE` only, performs a real runtime promotion, verifies
    Atlas resolves to the candidate, then performs the mandatory rollback drill
    and verifies the exact pre-experiment production model is restored;
13. leaves production untouched for HOLD/REJECT;
14. writes the complete local evidence report beneath
    `.prism/runtime/evolution-experiments/`.

### Remaining non-fabricated boundary

The GitHub/CI environment does not have access to the user's local Ollama daemon
or physical NVIDIA GPU. Therefore no baseline score, training loss, VRAM/RAM
peak, local candidate artifact, candidate AtlasBench score, Shadow result, or
promotion verdict is claimed here. Those values must come from the real local
experiment report.

### Exact next task — supersedes the older next-task section above

On the actual PRISM host, from repository root, run:

```text
python tools/run_atlas_evolution_experiment.py
```

Inspect `.prism/runtime/evolution-experiments/experiment-*.json`. If the report
is blocked/failed, fix the concrete local issue and rerun; do not skip or
manufacture a gate. If it completes, record its real baseline, training,
candidate, Shadow, verdict, and rollback evidence here before continuing to
multimodal, voice, Desktop packaging, Cortex V2, flagship certification, or
Phase 11.

`PHASE_10_COMPLETE = NO`
`PHASE_11_UNLOCKED = NO`
