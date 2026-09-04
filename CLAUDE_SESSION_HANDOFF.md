# PRISM Claude Session Handoff

## Read this first — Phase 10 Evolution activation (2026-09-04)

This file is intentionally reset to the current continuation state. Historical
Phase 7/8/9/early-Phase-10 detail remains in the phase reports, implementation
ledgers, and `.prism/checkpoints/`; do not use an older handoff paragraph to
infer current capability.

### Repository truth

- Repository: `prathmesh-katkade/prism`
- Active branch: `phase-10-atlas-local-intelligence`
- PR: #15 → `phase-6.5-integration-staging`
- Canonical Phase 10 base: `ab75b5a08f03a553fe4d6229c100d0be4c1dc158`
- Activation code head certified before documentation-only commits:
  `5ee368e8df911c65c1121be346b0f8c9ccef504f`
- PR #15 CI run #166 (`33904258400`) at that code head: all five jobs PASS,
  including the real MySQL 8.0 + browser-to-API flow.
- Current head: `07d549a` (Atlas System Seed Corpus V1); CI green through the
  Trusted Evolution wave (Candidate Artifact Trust Registry, System Seed
  Corpus V1, and three real CI-discovered bugs fixed -- see
  `.prism/checkpoints/phase-10-progress.md` for the full list).
- Do not merge PR #15 yet.

```text
PHASE_9_COMPLETE = YES
PHASE_10_UNLOCKED = YES
PHASE_10_IN_PROGRESS = YES
PHASE_10_COMPLETE = NO
PHASE_11_UNLOCKED = NO
CONTINUATION_SAFE = YES
```

### What is actually implemented now

Phase 10's earlier runtime foundation remains intact: durable Atlas runs/events,
dynamic declared-tool planning, visible specialists/Council, constrained Python
sandbox, memory/RAG foundation, allowlisted Researcher, Resource Governor,
observable Atlas workspace, and truthful Cortex V1.

The Foundry/Evolution software path is now also operational rather than only
scaffolded:

- verified SFT training-data builder and real-correction DPO pairs;
- `SoupFoundryBackend` with Resource-Governor job admission;
- frozen ten-category AtlasBench and durable run history;
- real Ollama AtlasBench subject using the same provider/model configuration as
  production Atlas;
- `/api/tags` reachability/model check before any live baseline can exist;
- no production rollback anchor may be created from configuration alone — a
  verified live model digest is required;
- server-owned durable promotion decisions under the locked
  `PROMOTE_ELIGIBLE` / `HOLD` / `REJECT` policy;
- durable append-only candidate → Ollama runtime bindings;
- promotion requires an eligible evaluator decision + real candidate artifact
  + verified runtime binding and changes Atlas's active model immediately;
- rollback verifies its target runtime before changing the production pointer,
  then restores the previous bound model as a new append-only event;
- Foundry trains on TRAIN split only; validation/test-only datasets fail closed;
- native Evolution UI reads real durable state; no synthetic candidate/promotion
  values are injected;
- recurring History live-E2E dataset-ordering race is fixed and green in the
  real browser/MySQL job;
- duplicate AI Analyst evidence React key warning is fixed.

### Current Soup activation contract

The physical experiment runner pins the first activation to:

- Soup: `soup-cli==0.74.0`
- Python: 3.10–3.12
- first trust-locked smoke base model: `Qwen/Qwen2.5-0.5B-Instruct`
- default method: QLoRA/SFT, deliberately small to prove the complete evolution
  loop before scaling model size.

Canonical runner:

```text
python tools/run_atlas_evolution_experiment.py
```

It performs, in order:

1. rehydrate an existing durable production pointer when present;
2. genuine production Ollama AtlasBench;
3. verified production rollback-anchor bootstrap on the first run;
4. durable verified training-data build and TRAIN-only export;
5. isolated pinned Soup environment setup if needed;
6. Resource-Governor-admitted LoRA/QLoRA smoke training;
7. real adapter/candidate registration;
8. Soup GGUF export + candidate-only Ollama deployment;
9. durable candidate runtime binding and `/api/tags` verification;
10. candidate AtlasBench on the identical frozen corpus version/hash;
11. locked server-side promotion decision;
12. if `PROMOTE_ELIGIBLE` only: real production switch, runtime verification,
    mandatory rollback drill, and exact starting-model restoration;
13. no promotion for HOLD/REJECT;
14. JSON evidence report beneath
    `.prism/runtime/evolution-experiments/experiment-*.json`.

### What is NOT proven yet

The actual Windows host is accessible and was checked on 2026-09-05: Ollama
0.33.3, Qwen3 4B Q4_K_M, and an NVIDIA GTX 1650 Max-Q are available. `soup` is
not installed, so the experiment must stop before training. Therefore do not
claim values for:

- local OS/CPU/RAM/GPU/VRAM at experiment time;
- Ollama version/model inventory;
- real production AtlasBench scores;
- real local training-dataset counts;
- Soup loss/elapsed/VRAM/RAM/checkpoint hash;
- candidate ID/model;
- candidate AtlasBench/Shadow result;
- final promotion verdict;
- physical promotion/rollback drill.

A HOLD or REJECT result is a valid successful experiment outcome. Never force a
promotion to make the demo look successful.

### Exact next task

Continue the approved Memory/RAG V2 through Cortex V2 data-architecture wave.
Treat Soup installation as a separate physical-runtime dependency decision;
without it, the canonical evolution experiment must remain blocked and no
candidate evidence can exist.

If the report is `blocked` or `failed`, diagnose that concrete local runtime
failure and rerun. Do not start another Phase 10 product wave to avoid the
physical gate.

### Stop boundary

Do not begin multimodal, voice, Desktop packaging, Cortex V2/dense 3D, flagship
workflow/final certification, merge PR #15, or Phase 11 until the first physical
Evolution experiment has coherent evidence and the user explicitly advances
scope.

Canonical current records:

- `docs/migration/CURRENT_PHASE.md`
- `PHASE10_IMPLEMENTATION_LEDGER.md`
- `.prism/checkpoints/phase-10-evolution-activation.md`
- `.prism/checkpoints/phase-10-progress.md`
- `PHASE10_ARCHITECTURE.md`
