# Current migration phase

**Phase:** 8A — Unified Provenance Foundation (**in progress**)

**Working branch:** `phase-8-provenance-lineage`.

**Canonical base:** `phase-6.5-integration-staging` at
`2741c2ef3c242d3edff7a46beda2acd437da25ac` (Phase 7 release closeout).

Phases 1–7 remain complete. Overview, SQL Lab, AI Analyst, Clean, Visualize,
Stats, Forecasting, and ML Lab stay native and enabled; their Streamlit
implementations remain the parity/rollback references.

## Phase 8A scope

Phase 8A makes `packages/analytical-schemas` the canonical, framework-free
analytical-object and provenance model. It adds an append-only process-local
registry and integrates Stats and Clean as representative producers. Every
object is tied to the existing `DatasetStore` dataset id, exact revision, and
source fingerprint. `DatasetStore` remains the authoritative revision system.

Existing Phase 3–7 HTTP contracts remain backward compatible: the registry is
an internal foundation and is not yet a public lineage graph endpoint.

The implementation ledger is `PHASE8_IMPLEMENTATION_LEDGER.md`; the current
gate record is `.prism/checkpoints/phase-8a.md`.

## Still forbidden in 8A

- dependency graph traversal or visualization
- staleness propagation
- rerun engine
- Atlas lineage awareness
- database or persistence layer
- Phase 9 work

The exact 8B starting point is a separately authorized design for read-only
registry retrieval semantics. It must not expand into graph, staleness, rerun,
Atlas, or UI work without a new scope decision.
