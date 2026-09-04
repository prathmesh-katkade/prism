# Current migration phase

**Phase:** 10 — IN PROGRESS (Atlas Local Intelligence Foundry)

**Phase 10 integration branch:** `phase-10-atlas-local-intelligence`, based on
`phase-6.5-integration-staging` at `ab75b5a08f03a553fe4d6229c100d0be4c1dc158`.

The first two internal waves establish Atlas's contract-first runtime foundation:
provider capabilities, typed plan/step/event/evidence contracts, durable
SQLAlchemy run/event records, deterministic tool-registry planning, visible
Scout/Curator/Stat/Auditor state, constrained Python execution, SSE replay, an
operational Atlas workspace, and a Cortex V1 projection backed only by durable
real state; SQL-backed scoped memory, lexical local project knowledge, an
explicit allowlisted Researcher, compact-metadata Ollama plan proposals, a
resource-lease governor, and a native-worker sandbox health boundary.

The Foundry wave (10M–10Q) adds, backend-only so far (no REST/UI wiring yet):
a verified training-dataset generator (SFT) and a real-correction-sourced DPO
preference-pair generator; a typed `FoundryBackend` abstraction with a real
`SoupFoundryBackend` (inspected against the actual upstream Soup CLI) and a
`MockFoundryBackend`, Resource-Governor-integrated job admission/preemption,
and a candidate-artifact registry; a 90-task AtlasBench corpus across all ten
required categories with a deterministic runner and durable append-only run
history; and Shadow Brain comparison plus the locked promotion policy
(PROMOTE_ELIGIBLE/HOLD/REJECT) with an atomic, append-only promotion/rollback
store. It does not implement a general shell, package installation,
unrestricted web access, KTO, Cortex 3D UI, voice, desktop packaging, or the
Atlas Evolution UI (10R — needs the still-missing REST endpoints first).
Windows CPU/memory quotas remain explicitly unsupported without a configured
container worker. No candidate has ever actually been trained or promoted;
`soup` has never been installed in any environment this project has run in.
See `PHASE10_ARCHITECTURE.md`, `PHASE10_IMPLEMENTATION_LEDGER.md`, and
`.prism/checkpoints/phase-10-progress.md`.

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
