# Phase 9 Handoff

**Phase 8 is complete** (8A through 8H — provenance, lineage traversal,
freshness/staleness, reproducibility/safe rerun, Atlas lineage awareness,
hardening). This document points at what comes next; it implements none of
it.

## What Phase 8 leaves in place

- A canonical, immutable `AnalyticalObject`/`AnalyticalProvenance` model
  (`packages/analytical-schemas`), tied to `DatasetStore`'s
  `(dataset_id, revision, source_fingerprint)` identity.
- A process-local, in-memory `AnalyticalObjectRegistry` with a maintained
  reverse child index, deterministic BFS ancestor/descendant traversal, and
  a read-only lineage API (`/api/v1/lineage/...`).
- Live, per-read freshness assessment (`current`/`stale`/`superseded`/
  `unknown`).
- Safe, non-destructive rerun (`same_revision`/`current_revision` modes)
  for Stats/Forecast/ML/Visualize.
- A dedicated Evidence Inspector UI wired through Stats Lab, and a
  deterministic Atlas lineage-awareness layer wired through it.

## Explicitly not built in Phase 8

- Any persistence layer. The registry is process-local and in-memory;
  every history reset on process restart is a known, accepted limitation
  throughout Phase 8A–8H.
- Automatic staleness *mutation* — freshness is always computed live, never
  written onto an object.
- Automatic rerun / invalidation propagation — a stale object is only ever
  identified and recommended, never rerun without an explicit user action.
- Full per-workspace Evidence Inspector wiring — only Stats Lab is wired;
  SQL Lab/Visualize/Forecasting/ML Lab follow the same one-line pattern
  (documented in `PHASE8_IMPLEMENTATION_LEDGER.md`'s 8E section) but were
  deliberately left for a follow-up pass.
- SQL Lab and Clean rerun support (each has a documented, structural reason
  in `PHASE8_IMPLEMENTATION_LEDGER.md`'s 8F section).

## Candidate Phase 9 directions (unscoped — pick one deliberately, do not assume)

1. **Persistence architecture decision.** The registry's process-local
   nature is Phase 8's most-repeated known limitation. A Phase 9 slice
   could write the ADR this needs (database choice, migration strategy for
   existing in-memory-only history, whether history needs to survive a
   restart at all vs. being explicitly ephemeral) — deliberately scoped as
   *decision*, not implementation, unless the ADR itself calls for a small
   spike.
2. **Complete Evidence Inspector coverage** across SQL Lab, Visualize,
   Forecasting, and ML Lab, using the exact pattern Stats Lab already
   demonstrates.
3. **Governance / access control** — explicitly out of scope for all of
   Phase 8 (see the mega-run task's own STRICT PHASE 8 BOUNDARY), never
   touched.
4. **Rerun coverage expansion** — SQL Lab's async run/poll flow and Clean's
   apply/undo mechanism, if a rerun UX distinct from their existing actions
   is ever actually wanted.

## Explicit non-goals carried forward

Nothing in Phase 9 should retroactively relax any Phase 8 invariant:
`DatasetStore` stays the sole revision authority; historical evidence stays
immutable; no secret is ever exposed through any lineage-family response;
Atlas stays grounded in recorded fact, never inference, unless a future
phase makes a deliberate, documented decision to attach a real model to it
(which Phase 8's Atlas never was).

## Whoever picks this up

Read `PHASE8_FINAL_REPORT.md` first for the full picture, then
`PHASE8_IMPLEMENTATION_LEDGER.md`'s 8A–8H sections for implementation
detail on whichever sub-phase's territory the Phase 9 work touches. Do not
restart or duplicate any Phase 8 sub-phase.
