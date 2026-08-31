# Current migration phase

**Phase:** 8 (D–H) — Freshness, Inspector UI, Reproducibility, Atlas Lineage
Awareness, and Hardening (**locally complete, PR pending**)

**Working branch:** `phase-8-completion`.

**Canonical base:** `phase-6.5-integration-staging` at
`79b059f40a85a3ce5dc71500ca23286178ce5948` (PR #12 — Phase 8C merge + docs
commit `68377c7`).

Phases 1–7 remain complete. Overview, SQL Lab, AI Analyst, Clean, Visualize,
Stats, Forecasting, and ML Lab stay native and enabled; their Streamlit
implementations remain the parity/rollback references.

## Phase 8A/8B/8C — COMPLETE, merged

- 8A: [PR #10](https://github.com/prathmesh-katkade/prism/pull/10) at `4912610be584e2b3e9902500bd6585aeebb8a506`.
- 8B: [PR #11](https://github.com/prathmesh-katkade/prism/pull/11) at `670d670ee0cdaaff7a6a62f1281d2df8b6802cf8`.
- 8C: [PR #12](https://github.com/prathmesh-katkade/prism/pull/12) at `79b059f40a85a3ce5dc71500ca23286178ce5948`.

Gate records: `.prism/checkpoints/phase-8a.md`, `phase-8b.md`, `phase-8c.md`.

## Phase 8D–8H scope (this working branch)

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

## Still forbidden until a fresh scope decision

- database or persistence layer
- automatic staleness mutation or invalidation propagation
- automatic rerun without an explicit user action
- Atlas inventing a dependency, version, or stale reason (structurally
  prevented, not just policy — see `atlas_lineage.py`)
- governance / access control
- Phase 9 work

See `PHASE9_HANDOFF.md` for candidate Phase 9 directions (unscoped).
