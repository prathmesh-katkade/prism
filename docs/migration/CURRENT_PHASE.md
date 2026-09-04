# Current migration phase

**Phase:** 10 — IN PROGRESS (Atlas Local Intelligence Foundry)

**Phase 10 integration branch:** `phase-10-atlas-local-intelligence`, based on
`phase-6.5-integration-staging` at `ab75b5a08f03a553fe4d6229c100d0be4c1dc158`.

Phase 10 now has the contract-first Atlas runtime, durable run/event state,
dynamic declared-tool planning, specialist/Council visibility, constrained
Python execution, local memory/RAG foundations, allowlisted Researcher,
Resource Governor, Atlas operations UI, and truthful Cortex V1 built in the
earlier waves.

The Foundry/Evolution stack (10M–10R) is also implemented end-to-end at the
software boundary. It includes versioned verified SFT data, real-correction DPO
pairs, a typed Soup backend, Resource-Governor-admitted training jobs, durable
candidate artifacts, the frozen ten-category AtlasBench corpus, live Ollama
AtlasBench subjects, Shadow Brain comparison, server-owned promotion decisions,
append-only promotion/rollback history, and the native Evolution workspace.
KTO remains deliberately absent because PRISM still has no genuine binary
accept/reject signal to train from.

The activation hardening completed on 2026-09-04 adds the pieces required for a
real first evolution experiment rather than a simulated one:

- the recurring History live-E2E race was fixed by binding SQL Lab to the exact
  dataset created by the test and synchronizing on durable API state; the real
  MySQL/browser CI flow is green;
- the duplicate AI Analyst evidence React key was removed;
- live AtlasBench refuses to persist a baseline unless the configured Ollama
  daemon is reachable and the requested model is present in `/api/tags`;
- the pre-Foundry production rollback anchor is created only after that live
  probe yields a model digest — configuration alone cannot manufacture a
  production pointer;
- candidate-to-Ollama runtime bindings are durable and append-only;
- Foundry exports TRAIN split only and refuses validation/test-only datasets;
- promotion requires both a durable evaluator-owned `PROMOTE_ELIGIBLE`
  decision and a verified candidate runtime binding, then changes the model
  Atlas resolves at runtime;
- rollback verifies the target runtime binding before changing the pointer and
  restores the previous bound model as a new append-only event;
- `tools/run_atlas_evolution_experiment.py` is the one-command physical
  activation path. It pins the first smoke experiment to Soup 0.74.0 and
  `Qwen/Qwen2.5-0.5B-Instruct`, records a real production AtlasBench baseline,
  builds TRAIN-only verified data, performs Soup LoRA/QLoRA training through
  the existing Foundry backend, exports/deploys the candidate to Ollama,
  benchmarks the identical frozen corpus, computes the locked verdict, and —
  only if eligible — performs a real production switch followed by a mandatory
  rollback drill ending on the exact model that started the experiment.

No real GPU/Soup experiment result is claimed by this document yet. The current
GitHub/CI environment cannot execute the user's local Ollama daemon or GPU, so
loss, VRAM/RAM peak, candidate score, Shadow result, promotion verdict, and the
rollback drill remain evidence that must come from the generated local
experiment report. A HOLD or REJECT first candidate is a valid successful test
of the evaluator; PRISM must not force promotion.

Phase 10 is therefore **software-ready for the first physical Evolution
experiment, but not Phase-10-complete**. Multimodal, voice, desktop packaging,
Cortex V2/dense 3D, flagship workflow certification, and Phase 11 remain locked
behind that evidence and the remaining Phase 10 gates.

See `PHASE10_ARCHITECTURE.md`, `PHASE10_IMPLEMENTATION_LEDGER.md`,
`.prism/checkpoints/phase-10-progress.md`, and
`.prism/checkpoints/phase-10-evolution-activation.md`.

```
PHASE_9_COMPLETE = YES
PHASE_10_UNLOCKED = YES
PHASE_10_IN_PROGRESS = YES
PHASE_10_COMPLETE = NO
PHASE_11_UNLOCKED = NO
```

**Phase:** 9 — COMPLETE (durable analytical history and productization,
**PHASE_10_UNLOCKED**)

**Canonical base for the next phase:** `phase-6.5-integration-staging` at
`2013f41faa8a515b039b6a37a493abc2c05c7b23` (PR #14 — Phase 9 merge).

Phase 9 made Phase 8's analytical history durable (SQLAlchemy-backed registry
and DatasetStore, proven to survive a restart), wired the Evidence Inspector
through every native workflow, added a native History workspace, expanded
safe reproduction where an async-safe design exists, and added a lightweight
append-only audit trail — without changing any Phase 8 contract. Full detail:
`PHASE9_FINAL_REPORT.md`. Deployment verification remains
`BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` (no Render credentials in this
environment, and this session's egress policy also rejects `*.onrender.com`).
Next phase: `PHASE10_HANDOFF.md` (unscoped pointer only).

## Phase 8 — COMPLETE (all sub-phases 8A–8H merged)

Canonical base at the time: `phase-6.5-integration-staging` at
`4b291898d38e4397a335aef761ab13b3be197d68` (PR #13 — Phase 8D–8H merge).

Phases 1–7 remain complete. Overview, SQL Lab, AI Analyst, Clean, Visualize,
Stats, Forecasting, and ML Lab stay native and enabled; their Streamlit
implementations remain the parity/rollback references.

## Phase 8A–8H — COMPLETE, all merged

- 8A: [PR #10](https://github.com/prathmesh-katkade/prism/pull/10) at `4912610be584e2b3e9902500bd6585aeebb8a506`.
- 8B: [PR #11](https://github.com/prathmesh-katkade/prism/pull/11) at `670d670ee0cdaaff7a6a62f1281d2df8b6802cf8`.
- 8C: [PR #12](https://github.com/prathmesh-katkade/prism/pull/12) at `79b059f40a85a3ce5dc71500ca23286178ce5948`.
- 8D–8H: [PR #13](https://github.com/prathmesh-katkade/prism/pull/13) at `4b291898d38e4397a335aef761ab13b3be197d68`.

Gate records: `.prism/checkpoints/phase-8a.md` through `phase-8-final.md`.
Full report: `PHASE8_FINAL_REPORT.md`.

## Phase 8D–8H scope

- **8D — Versioning + Staleness Propagation.** Contextual freshness
  (`current`/`stale`/`superseded`/`unknown`/`invalid`), computed live
  against `DatasetStore`'s active identity — `AnalyticalObject` stays fully
  immutable. `GET /objects/{id}/freshness`, `GET /datasets/{id}/freshness`.
- **8E — Evidence + Lineage Inspector UI.** A dedicated `EvidenceInspector`
  React component, integrated additively into the existing shell/Inspector
  architecture, wired through Stats Lab.
- **8F — Reproducibility + Safe Rerun.** `POST /objects/{id}/rerun`
  (`same_revision`/`current_revision`) — never overwrites, always creates a
  new object. Supported: analysis/forecast/ml_model/visualization;
  deliberately unsupported kinds each carry a documented reason.
- **8G — Atlas Lineage Awareness.** Six deterministic Atlas actions
  (`explain_provenance`/`explain_staleness`/`explain_lineage`/
  `compare_versions`/`recommend_reruns`/`explain_evidence`), grounded
  entirely in recorded data — Atlas here is a rule-based explainer, not an
  LLM call, exactly like every other native workspace's existing Atlas
  actions.
- **8H — Hardening + release gate.** End-to-end integration audit (5 real
  HTTP flows), self-code-review, full regression, full repo-standard gate
  suite, `PHASE8_FINAL_REPORT.md`, this checkpoint.

No new graph engine, no dependency-graph redesign, no database/persistence
layer, no governance, no Phase 9 work. Full detail:
`PHASE8_IMPLEMENTATION_LEDGER.md` (8D–8H sections), gate records
`.prism/checkpoints/phase-8d.md` through `phase-8-final.md`.

A post-push automated review found three real gaps in 8D–8H's own new code
(a React state-reset bug and a race-guard gap in the Evidence Inspector,
and a missing `dataset_id` comparison in Atlas's `compare_versions`) — all
fixed and regression-tested in PR #13's final head before merge.

```
PHASE_8A_COMPLETE = YES   PHASE_8E_COMPLETE = YES
PHASE_8B_COMPLETE = YES   PHASE_8F_COMPLETE = YES
PHASE_8C_COMPLETE = YES   PHASE_8G_COMPLETE = YES
PHASE_8D_COMPLETE = YES   PHASE_8H_COMPLETE = YES

PHASE_8_COMPLETE = YES
PHASE_9_UNLOCKED = YES
```

## Still forbidden until a fresh scope decision

- database or persistence layer
- automatic staleness mutation or invalidation propagation
- automatic rerun without an explicit user action
- Atlas inventing a dependency, version, or stale reason (structurally
  prevented, not just policy — see `atlas_lineage.py`)
- governance / access control
- Phase 9 work

See `PHASE9_HANDOFF.md` for candidate Phase 9 directions (unscoped).
