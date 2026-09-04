# Phase 10 Progress Checkpoint

**Date:** 2026-09-04
**Branch:** `phase-10-atlas-local-intelligence`
**Base:** `ab75b5a` (`phase-6.5-integration-staging`)

## Repository truth

Phase 9 is complete and merged (PR #14). No existing Phase 10 branch or work
was present. The original `C:\Users\prath\prism` checkout was a dirty,
unrelated Phase 8 worktree, so it was left untouched. Phase 10 is isolated in
`C:\Users\prath\prism-phase10`.

## CI recovery checkpoint (2026-09-04, continuation session)

A follow-up session was asked to recover interrupted Codex Foundry work and
fix PR #15's red CI before continuing. This session's checkout is a fresh
clone (not the Windows worktree above); `git status`/`diff`/`stash list`/
`ls-files --others` were all empty and no branch anywhere carried a
Foundry/Soup/AtlasBench-named commit — there was nothing local to recover.
The pushed HEAD (`351f299`) matched the last known-good state exactly.

Fixed and pushed (`9134f99` platform portability, `eb3a12b` MySQL-safe
run-store indexes, `65faec8` the 204/response_model import crash +
regenerated TS contract, `27923a4` a second MySQL key-length failure in the
memory store found only once the live-MySQL job got that far — see
`PHASE10_IMPLEMENTATION_LEDGER.md` for detail). Local evidence: `ruff`/`mypy`
clean using the exact CI invocation, `pytest tests/api tests/contracts
tests/migration tests/overview tests/sql_lab` → 246 passed / 4 skipped,
boundaries/secrets/contract-freshness all pass.

**CI on PR #15 confirmed green at `27923a4`** (all 5 checks, including the
real MySQL 8.0 job, passed; `mergeable_state: clean`). The Foundry wave
(10M–10R) begins now, starting with 10N.

## Completed in this checkpoint

- Created architecture record and ADRs 0006–0012 for providers, orchestration,
  sandbox, memory/RAG, Cortex, Foundry trust, and desktop sidecars.
- Defined typed public contracts for providers, structured runs/plans/steps,
  specialists, Council conclusions, events, evidence, memory, Cortex graph,
  model trust, benchmarks, and resource priority.
- Implemented a safe first vertical slice: unknown uploaded CSV → deterministic
  Overview profile → visible Scout/Stat/Auditor Council → Atlas grounded answer.
- Added stored event replay through SSE and a Cortex graph projection sourced
  only from run/step/specialist/evidence records.
- Added direct API regression tests for the demonstrator, SSE/Cortex truthfulness,
  deterministic fallback, and Atlas-only speaking identity.

## Gates

| Gate | Result |
| --- | --- |
| targeted API regression | PASS — 19 tests |
| broader API regression | BLOCKED_LOCAL_INTERPRETER — 42 passed, then pre-existing Forecasting `zip(..., strict=True)` failed under local Python 3.9; CI Python 3.11 is required |
| ruff | PASS |
| targeted mypy | PASS |
| TypeScript contract freshness | PASS |
| full Phase 10 certification | NOT READY — Phase 10 is intentionally in progress |

## Deliberately not implemented

No arbitrary Python/shell execution, web research, memory persistence/RAG,
model download, Foundry training, promotion, AtlasBench execution, voice,
multimodal pipeline, Cortex 3D visual UI, or desktop packaging was added. Their
contracts/ADRs do not imply implementation.

## Exact continuation

### Second-wave implementation (in progress)

- Atlas runs, plans, Council conclusions, evidence, cancellation intent, and
  append-only events now use Phase 9's SQLAlchemy/database policy in distinct
  Atlas tables. Restart/replay and deterministic sequence tests use independent
  store instances; Phase 8/9 analytical objects remain untouched.
- The planner validates every declared tool against a registry. It can choose
  quality, SQL, forecasting, ML, visualization, history, and Python intents,
  but safely blocks an action without the explicitly required context rather
  than generating a hidden command or model run.
- A typed project-scoped Python sandbox now exists. It has no shell/package
  surface, clears user environment values, blocks direct network/import escapes,
  contains ordinary file APIs to its workspace, captures output, terminates on
  timeout/cancellation, and collects allowlisted artifacts. Windows cannot
  honestly enforce CPU/memory quotas in this implementation; that needs a later
  worker/container boundary and is not certified here.
- Native Atlas operations UI and Cortex V1 consume real backend contracts/SSE.
  Cortex draws only durable run, dataset, step, specialist, tool, and evidence
  records; it contains no private thoughts or decorative fake nodes.

## Exact continuation

### Third foundation increment (in progress)

- SQL-backed Atlas memory now supports session/project/workspace/global scope,
  dedupe reinforcement, supersession, deletion policy, provenance, and an
  append-only audit trail. It rejects credential-shaped content.
- Local project knowledge has project-isolated lexical retrieval with chunk
  source/version/location, reindex/delete semantics, and prompt-injection
  flags. Embedding retrieval and analytical-history ingestion are not yet done.
- Researcher is a separate server-side allowlisted HTTPS boundary with bounded,
  citation-backed, untrusted results and clean offline behavior.
- Resource Governor exposes typed priority leases and hardware snapshots without
  assuming a GPU. The sandbox now declares native-worker capabilities and kills
  worker process trees, but Windows CPU/memory quotas still require container
  execution for enforcement.
- Ollama can propose a strict JSON plan only from capped compact metadata;
  malformed output falls back deterministically and cannot execute a tool.

### Current local evidence

- Focused Atlas runtime/sandbox/memory/research/resource suite: **16 passed**.
- Web typecheck, lint, and Vitest: **35 passed**.
- Boundaries, local secret scan, and contract freshness: **PASS**.
- Full API regression: **NOT READY locally** — the first failure after 55 tests
  is the known Python 3.9-only Forecasting `zip(..., strict=True)` issue.
- Web production build: **BLOCKED_LOCAL_WORKTREE** by an existing Next/Turbopack
  out-of-root `node_modules` symlink. Browser/CI certification still needs a
  supported normal checkout and Python 3.11.

Run supported Python 3.11/CI and browser certification for this increment, then
add a container-worker adapter, embedding provider, durable research records,
and run-integrated guarded Python only if their gates remain coherent. Preserve
all Phase 8/9 invariants and do not start Phase 11.
