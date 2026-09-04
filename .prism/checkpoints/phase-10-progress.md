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

## Foundry wave checkpoint (2026-09-04, same session, continued autonomously)

User authorized continuing the Foundry wave. Delivered, one commit per
coherent unit, each pushed after a full local `ruff`/`mypy`/pytest/
boundaries/secrets/contract-freshness pass:

- `b0926ca` — 10N verified training-dataset generator (Atlas-run-sourced SFT).
- `4c6e8e4` — 10O DPO preference pairs from real Atlas-memory corrections.
- `856fb30` — 10M FoundryBackend/SoupFoundryBackend (Soup inspected live at
  https://github.com/MakazhanAlpamys/Soup, v0.73.3) + Resource Governor
  integration + Candidate Registry.
- `1af8562` — 10P AtlasBench: 90-task frozen corpus across all 10 categories,
  deterministic runner, durable append-only run history.
- `063de4d` — 10Q Shadow Brain comparison, locked promotion policy
  (PROMOTE_ELIGIBLE/HOLD/REJECT), atomic append-only promotion/rollback
  store, and an honest (all-unsupported) adapter-hot-swap capability report.

CI: green through `1af8562`; `063de4d` and `fb42013` (docs) both came back
green too. `phase-4-live-e2e` intermittently fails on unrelated, pre-existing
frontend Playwright flakiness (documented on the PR, not a regression from
this wave's Python-only diffs).

Deliberately not done, and not claimed at that point: KTO (no real feedback
signal to source it from), a live-wired AtlasBench subject (harness is
proven against reference subjects only), any REST/UI wiring for any of the
above, and any actual end-to-end Soup training run (the backend is real and
tested, but `soup` has never been installed anywhere this project has run).

## REST wiring + 10R checkpoint (2026-09-04, same session, continued autonomously)

- `61124f5` — wired the entire 10M–10Q backend surface onto FastAPI via a
  new `atlas_foundry_routes.py` (`/api/v1/atlas/foundry`, `/api/v1/atlas/bench`,
  `/api/v1/atlas/promotion`, `/api/v1/atlas/adapters`), deliberately narrower
  than the backend it wraps: no route ever returns an AtlasBench answer key,
  and there is no client-facing "promote" endpoint. 9 new integration tests.
  Full local `ruff`/`mypy`/pytest (297 passed)/boundaries/secrets/contract-
  freshness pass before pushing; frontend typecheck/lint/test:web (35 tests)
  also passed against the regenerated contract.
- CI run #131 (`61124f5`) failed `phase-4-live-e2e` on `history-live.spec.ts`
  — the same pre-existing timing flake already documented in the standing-down
  PR comment, now its third occurrence (after `b0926ca` and `4c6e8e4`), still
  on a spec unrelated to this wave's diff. Not re-diagnosed further per that
  comment's stated scope boundary.
- `779222b` — 10R Atlas Evolution UI: a native `EvolutionWorkspace` tab
  wired into the shell (`prism-shell.tsx`, `shell-model.ts`), consuming the
  routes above with honest empty states throughout (no candidate has ever
  been trained or promoted in any environment this project has run in).
  `npm run typecheck`/`lint`/`test:web` (38/38 across 11 suites)/
  `a11y:baseline`/`contract:check` all passed; no backend files touched.
  CI run #132 is this session's natural re-run of the `phase-4-live-e2e`
  flake (the standing-down comment said the next push would retry it
  naturally) — see the workflow-run status for its outcome as of this
  checkpoint.

This completes the build order specified for this session's Foundry wave:
10N, 10O, 10M, Candidate Registry, 10P, 10Q, Promotion/Rollback, Adapter
Foundation, 10R.

Full detail, module map, and the exact next task are in
`PHASE10_IMPLEMENTATION_LEDGER.md`. `PHASE_10_COMPLETE` remains `NO`;
Phase 11 remains locked.

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
