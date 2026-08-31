# Current migration phase

**Phase:** 8B — Analytical Object Registry + Read-Only Retrieval (**locally
complete, PR pending**)

**Working branch:** `phase-8b-registry-read-model`.

**Canonical base:** `phase-6.5-integration-staging` at
`4912610be584e2b3e9902500bd6585aeebb8a506` (PR #10 — Phase 8A merge).

Phases 1–7 remain complete. Overview, SQL Lab, AI Analyst, Clean, Visualize,
Stats, Forecasting, and ML Lab stay native and enabled; their Streamlit
implementations remain the parity/rollback references.

## Phase 8A — COMPLETE, merged

Phase 8A made `packages/analytical-schemas` the canonical, framework-free
analytical-object and provenance model: an append-only process-local
registry, and Stats/Clean as representative producers, every object tied to
`DatasetStore`'s own dataset id/revision/fingerprint. Merged via
[PR #10](https://github.com/prathmesh-katkade/prism/pull/10) at
`4912610be584e2b3e9902500bd6585aeebb8a506`. Gate record:
`.prism/checkpoints/phase-8a.md`.

## Phase 8B scope

Phase 8B turns that foundation into a useful, read-only canonical
analytical-history model:

- **Dataset-revision objects** — `ensure_dataset_revision` idempotently
  mirrors each `DatasetStore` dataset/revision/fingerprint identity into the
  registry (deterministic id, exactly one object per identity), with the
  immediately preceding revision linked as its direct parent whenever it is
  already registered.
- **Producer coverage completed** — SQL Lab (local dataset connection only),
  Visualize, Forecasting, and ML Lab (baseline/feature-selection/SHAP as
  three independent objects) now register alongside 8A's Stats/Clean. AI
  Analyst registers only a completed, evidence-grounded `ANSWERED` outcome.
  Deliberate exclusions (Overview, ML Lab's `apply-feature`/`imbalance`, SQL
  Lab against non-dataset connections, AI Analyst's other two outcomes) are
  documented with reasons in `PHASE8_IMPLEMENTATION_LEDGER.md`, not silently
  skipped.
- **Direct-parent semantics only** — every object points at the one
  dataset-revision object it actually ran against; no transitive graph
  exists or is inferred.
- **Read-only lineage API** — `GET /api/v1/lineage/objects/{object_id}` and
  `GET /api/v1/lineage/datasets/{dataset_id}/objects` (optional `revision`/
  `kind` filters, deterministic newest-first ordering, immutable snapshots).
  No write route exists under `/lineage`.

Existing Phase 3–7 HTTP contracts remain backward compatible: every touched
producer route's own response model and status code are unchanged.

The implementation ledger is `PHASE8_IMPLEMENTATION_LEDGER.md`; the current
gate record is `.prism/checkpoints/phase-8b.md`. All locally-verifiable gates
pass (full Python suite, ruff/mypy under CI's exact flags, boundaries,
secrets, fresh TypeScript contracts, full frontend gate, legacy regression);
CI itself is pending a PR from `phase-8b-registry-read-model`.

## Still forbidden in 8B

- dependency graph traversal or visualization
- staleness propagation / invalidation propagation
- rerun or reproduction execution engine
- Atlas lineage awareness
- lineage/evidence frontend UI
- database or persistence layer
- Phase 9 work

The exact 8C starting point (Deterministic Dependency Graph / Lineage
Traversal) builds ancestor/descendant traversal on top of the direct
`parent_refs` links 8A and 8B already record. It must not expand into
staleness, rerun, Atlas, UI, or persistence work without a new scope
decision.
