# Phase 10 — Evolution Activation checkpoint

Date: 2026-09-04

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`
`CONTINUATION_SAFE = YES`

This checkpoint supersedes the earlier Evolution-activation checkpoint text.
The software path required for PRISM's **first real Atlas evolution experiment**
is now implemented and CI-certified. It must still not be misread as evidence
that a physical Soup/GPU training experiment has run on the user's local
machine: that evidence does not exist in this execution environment.

## Authoritative code gate

Activation code head before documentation-only commits:
`5ee368e8df911c65c1121be346b0f8c9ccef504f`.

PR #15 CI run **#166** (`33904258400`) is fully green at that code head:

- `phase-1-python` — PASS
- `phase-1-web` — PASS
- `phase-4-live-e2e` — PASS, including real MySQL 8.0 + browser-to-API flow
- `legacy-regression` — PASS, including compile check for every Python file
- `secret-scan` — PASS

The repeated `history-live.spec.ts` failure is closed at its root, not hidden by
larger timeouts. SQL Lab is bound to the exact dataset created by the live test,
and the test synchronizes on real API state before asserting `3 returned / 3
total rows`. The duplicate AI Analyst `overview-profile` React-key warning was
also removed.

## Live AtlasBench production baseline

`atlas_bench_live.py` now exposes a genuine non-mutating Ollama benchmark
subject. It receives benchmark prompt + choices only; evaluator answer key,
rationale, category scores, thresholds, and promotion policy remain entirely
server-owned.

A production baseline is fail-closed:

- `PRISM_AI_PROVIDER=ollama` configuration alone creates no benchmark and no
  production pointer.
- the subject must reach Ollama `/api/tags` and find the exact configured model;
- the model digest from that successful probe is required before PRISM may
  persist the configured model as the initial production rollback anchor;
- unreachable/missing Ollama therefore produces no fabricated 0-score baseline
  and no fabricated production state.

## Soup / Foundry activation path

Current verified Soup contract is pinned in the experiment runner to
`soup-cli==0.74.0` (Python >=3.10,<3.13). The first smoke experiment is
trust-locked to `Qwen/Qwen2.5-0.5B-Instruct` to prove the full evolution loop
before attempting a larger model.

`tools/run_atlas_evolution_experiment.py` now performs one coherent physical
experiment through existing Phase 10 boundaries:

1. restore an already-durable production pointer if one exists;
2. run genuine production AtlasBench against the reachable configured Ollama
   model;
3. if this is the first experiment, persist that verified model/digest as the
   immutable rollback anchor;
4. build a durable verified training-dataset version from eligible Atlas run
   history;
5. export **TRAIN split only** — validation/test examples never enter Soup;
6. create/use the isolated pinned Soup training environment;
7. run a Resource-Governor-admitted SFT LoRA/QLoRA smoke job;
8. persist real job metrics/checkpoints/candidate artifact from actual adapter
   output;
9. export/deploy that candidate to Ollama under a candidate-only runtime name;
10. persist an append-only candidate → Ollama runtime binding and verify the
    deployed model is visible in `/api/tags`;
11. run candidate AtlasBench against the exact same frozen corpus version/hash;
12. compute and durably store the locked server-owned promotion verdict;
13. if and only if the verdict is `PROMOTE_ELIGIBLE`, append a real production
    promotion event, activate the candidate runtime, verify Atlas resolves to
    that candidate, then perform the mandatory rollback drill and verify the
    exact starting production model is restored;
14. leave production unchanged for `HOLD` or `REJECT`;
15. write an inspectable JSON experiment report under
    `.prism/runtime/evolution-experiments/`.

The runner does **not** force an eligible result. A HOLD or REJECT is a valid
successful test of the evaluator.

## Durable runtime-effective promotion

The former gap where promotion could be an auditable pointer without changing
Atlas's actual runtime is closed.

- `atlas_candidate_runtime.py` adds append-only candidate runtime bindings.
- runtime model names are validated and command-shaped names are rejected.
- `DurableAtlasPromotionStore.bootstrap()` creates the pre-Foundry rollback
  anchor once without pretending it was an evaluated candidate promotion.
- a new anchor requires a verified live model digest; startup configuration by
  itself cannot create one.
- existing pointers are rehydrated on restart.
- `POST /api/v1/atlas/promotion/promote` requires a durable evaluator-owned
  eligible decision, a real candidate artifact, and a verified candidate
  runtime binding before changing the pointer; Atlas's live Ollama model is
  activated immediately afterward.
- rollback verifies the target runtime binding **before** mutating production,
  appends a rollback event, and activates the restored model.
- no production or rollback event is edited in place.

## Training-data isolation

The normal Foundry REST path and the one-command experiment runner both train on
`AtlasTrainingSplit.TRAIN` only. A dataset version with zero TRAIN examples is
rejected rather than silently training on validation/test examples. Existing
redaction, deduplication, project/run grouping, split isolation, and hidden-CoT
exclusion remain intact.

## Regression coverage added in this activation

Coverage now includes:

- durable append-only candidate runtime bindings;
- runtime model-name injection rejection;
- configured-but-unprobed Ollama cannot create a production pointer;
- verified production bootstrap is durable and idempotent;
- promotion activation changes Atlas to the bound candidate model;
- rollback restores the exact bound starting model and preserves append-only
  history;
- Foundry refuses validation/test-only datasets;
- dead/missing Ollama cannot create a fake AtlasBench baseline;
- History live-E2E deterministic dataset binding;
- unique AI Analyst evidence keys.

## What is deliberately NOT claimed

This GitHub/CI execution environment cannot access the user's local Ollama
daemon, NVIDIA GPU, or a locally installed Soup training stack. Therefore the
following values are **not invented and remain physically unproven**:

- local OS/CPU/RAM/GPU/VRAM snapshot for the experiment;
- Ollama version and currently installed local models;
- genuine production AtlasBench score/category breakdown;
- actual `atlas-training-v0001` example counts produced from the user's local
  durable history;
- Soup training job ID, loss trajectory, elapsed time, VRAM/RAM peak, and
  checkpoint hash;
- real candidate ID/runtime model;
- candidate AtlasBench score;
- Shadow comparison result;
- final `PROMOTE_ELIGIBLE` / `HOLD` / `REJECT` result;
- a physical promotion/rollback drill.

Those facts must come from the runner's generated local report; test doubles or
GitHub Actions CPU runners cannot substitute for them.

## First real local execution (2026-09-04)

- Machine observed: Windows 11, Intel i5-9300H, 16 GiB RAM, NVIDIA GTX 1650
  Max-Q (4 GiB VRAM; 3.94 GiB free before the run), and 190.23 GiB free disk.
- Ollama 0.33.3 was healthy. The installed model selected explicitly for this
  isolated execution was `qwen3:4b-q4_K_M` (Qwen3 4B GGUF Q4_K_M,
  digest `2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`).
- A configuration defect was found before scoring: AtlasBench defaulted to a
  different model than Atlas. Commit `80f13e7` makes the live subject inherit
  `PRISM_OLLAMA_BASE_URL` and `PRISM_OLLAMA_MODEL`, with the old
  AtlasBench-specific names retained only as explicit compatibility overrides.
- Production baseline persisted in an isolated durable SQLite runtime:
  `benchrun_e22b23a14daa4590bc917922113f6547`, subject
  `atlas_ollama_24b0e61eb95e`, corpus `atlasbench-v1`, hash
  `f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`.
  It scored **71/90** in **235.6 seconds**. Category results: agentic 8/10,
  causal safety 5/8, evidence 6/8, forecasting 6/8, general 10/10, ML 9/10,
  personality 6/8, Python sandbox 7/8, SQL 7/10, statistics 7/10.
- The first real 10N/10O build truthfully produced zero eligible SFT examples
  and zero DPO pairs. This runtime contains no completed evidence-backed Atlas
  operations or real corrections; AtlasBench data is not training data.

## Remaining operational blockers

1. No verified real Atlas-run corpus or clearly-labelled system seed corpus
   exists yet, so a training job must not start.
2. Soup is not installed. Upstream was re-checked at commit
   `f07e07ed7edd548a4d1d9143f77af9027b1b7036` (v0.74.0 source): Python
   3.10-3.12, `soup profile --config`, `soup train --config`, and GGUF/Ollama
   export remain supported. A separate pinned training environment is required.
3. Candidate-artifact trust verification and an adapter-capable inference
   runtime are not yet implemented. No candidate may be trained, registered,
   benchmarked, or promoted until those gates exist.

## Exact next task

On the actual Windows PRISM host with the configured local Ollama model and
Python 3.10–3.12, run from repository root:

```text
python tools/run_atlas_evolution_experiment.py
```

Then inspect the generated
`.prism/runtime/evolution-experiments/experiment-*.json` and promote its real
IDs/metrics into this checkpoint/ledger. If the report is `blocked` or
`failed`, fix the concrete local runtime issue and rerun; do not fabricate or
skip a failed gate.

Do **not** start multimodal, voice, Desktop packaging, Cortex V2/dense 3D,
Phase 10 final certification, or Phase 11 until that first physical experiment
has coherent evidence.

`PHASE_10_COMPLETE = NO`
`PHASE_11_UNLOCKED = NO`
