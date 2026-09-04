# Phase 10 Progress Checkpoint

Date: 2026-09-04

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`
`CONTINUATION_SAFE = YES`

## Canonical status

Phase 10 has advanced through the Atlas runtime, agents/specialists, secure
Python worker foundation, memory/RAG foundation, Researcher, Resource Governor,
Foundry/Soup abstraction, verified training-data generation, AtlasBench,
Shadow/promotion policy, Evolution UI, and the software activation path for the
first real self-improvement experiment.

PR #15 remains open against `phase-6.5-integration-staging`; do not merge it yet.

Activation code head before documentation-only commits:
`5ee368e8df911c65c1121be346b0f8c9ccef504f`.

PR #15 CI run #166 (`33904258400`) is fully green at that code head:

- `phase-1-python`: PASS
- `phase-1-web`: PASS
- `phase-4-live-e2e`: PASS (real MySQL 8.0 + browser-to-API)
- `legacy-regression`: PASS
- `secret-scan`: PASS

The earlier lifecycle head also passed all five jobs on run #163; the History
live-E2E root fix independently passed all five on run #152.

## Evolution activation delivered

- History live-E2E now binds to its own uploaded dataset and synchronizes on
  real API state; no timeout inflation workaround.
- Duplicate AI Analyst evidence React keys fixed.
- Live Ollama AtlasBench subject uses production provider/model configuration,
  receives benchmark prompt/choices only, and probes `/api/tags` before any
  baseline can exist.
- Configured-but-unprobed Ollama cannot create a production pointer.
- Verified model digest bootstraps the pre-Foundry production rollback anchor
  once; restart rehydrates an existing pointer.
- Candidate→Ollama runtime bindings are durable/append-only and model names are
  validated.
- Foundry API and experiment runner train on TRAIN split only; zero-TRAIN
  versions fail closed.
- Promotion requires a durable evaluator-owned `PROMOTE_ELIGIBLE` decision, a
  real candidate artifact, and a verified runtime binding; it changes Atlas's
  active Ollama model.
- Rollback verifies the target binding before pointer mutation and restores the
  previous model as a new append-only event.
- Soup activation contract currently pinned to `soup-cli==0.74.0`, Python
  3.10–3.12, with `Qwen/Qwen2.5-0.5B-Instruct` as the first trust-locked smoke
  base model.
- `tools/run_atlas_evolution_experiment.py` now performs the real production
  baseline → verified TRAIN corpus → Soup LoRA/QLoRA → candidate deploy →
  candidate AtlasBench → locked verdict → eligible-only promotion → mandatory
  rollback drill sequence and writes an inspectable JSON report.

## Remaining physical gate

No GPU/Soup training result is claimed in this checkpoint because this
GitHub/CI execution environment cannot reach the user's local Ollama daemon or
physical NVIDIA GPU.

The only accepted evidence for the first real experiment is the report produced
on the actual PRISM host by:

```text
python tools/run_atlas_evolution_experiment.py
```

Expected report location:
`.prism/runtime/evolution-experiments/experiment-*.json`.

That report must supply the real hardware snapshot, Ollama/model identity,
production baseline, training dataset counts/hash, Soup job metrics, candidate,
candidate benchmark, Shadow comparison/verdict, and promotion/rollback result.
HOLD or REJECT is valid; do not force promotion.

## Next task

Run the physical Evolution experiment on the local Windows PRISM host, inspect
and preserve its JSON evidence, then update
`.prism/checkpoints/phase-10-evolution-activation.md` and
`PHASE10_IMPLEMENTATION_LEDGER.md` with those real values.

Do not start multimodal, voice, Desktop packaging, Cortex V2, Phase 10 final
certification, merge PR #15, or Phase 11 before that evidence exists.
