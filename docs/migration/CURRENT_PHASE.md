# Current migration phase

**Phase:** 8C — Deterministic Dependency Graph / Lineage Traversal (**COMPLETE
— merged**)

**Merged via:** [PR #12](https://github.com/prathmesh-katkade/prism/pull/12)
at merge commit `79b059f40a85a3ce5dc71500ca23286178ce5948` into
`phase-6.5-integration-staging`, 2026-08-31.

**Canonical base for the next phase:** `phase-6.5-integration-staging` at
`79b059f40a85a3ce5dc71500ca23286178ce5948` (PR #12 — Phase 8C merge).

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

## Phase 8B — COMPLETE, merged

Phase 8B completed dataset-revision identity, direct-parent wiring across the
remaining native workflows (SQL Lab, Visualize, Forecasting, ML Lab, AI
Analyst), and a read-only lineage API (`GET /objects/{object_id}`, `GET
/datasets/{dataset_id}/objects`). Merged via
[PR #11](https://github.com/prathmesh-katkade/prism/pull/11) at
`670d670ee0cdaaff7a6a62f1281d2df8b6802cf8`. Gate record:
`.prism/checkpoints/phase-8b.md`.

## Phase 8C scope

Phase 8C makes the direct `parent_refs` graph 8A/8B already record walkable —
still entirely read-only, still built only from links producers already
record, never AI-inferred:

- **Reverse child index** — `AnalyticalObjectRegistry` now maintains
  `parent_object_id → [child_object_id, ...]` inline during `register()`, so
  a child lookup is a dict access, never a full-registry scan.
- **Direct parent/child lookup** — `GET /objects/{id}/parents` and
  `GET /objects/{id}/children`: the immediate relationship only, `[]` for a
  root/leaf, 404 for an unknown id.
- **Transitive ancestor/descendant traversal** — `GET
  /objects/{id}/ancestors` and `GET /objects/{id}/descendants`: iterative,
  cycle-safe BFS with per-node depth, deterministic `(depth ASC, object_id
  ASC)` ordering, and an optional bounded `max_depth` (1–100, typed 422
  outside that range) that reports whether it actually truncated real
  further history.
- **Compact graph view** — `GET /objects/{id}/graph`
  (`direction=upstream|downstream|both`): the one place the root itself is
  included, at depth 0, otherwise a thin composition of the same traversal
  used above.
- **Shortest path** — `GET /path?from_object_id=&to_object_id=`: deterministic,
  direction-agnostic, with a `found=false` (not an error) response when both
  objects exist but nothing connects them.
- **Fingerprint-aware identity, extended** — traversal walks `object_id`s,
  which already encode `(dataset_id, revision, source_fingerprint)`, so a
  revision-number-only identity bug (the class of gap 8B fixed) has no
  separate surface to regress into here.

No write route exists, or was added, anywhere under `/lineage`. No new
parent link is created by 8C — only the existing graph is walked. No
staleness/invalidation propagation, rerun/reproduction engine, Atlas lineage
reasoning, lineage/evidence frontend UI, database persistence, or Phase 9
work is part of this phase.

Existing Phase 3–7 HTTP contracts, and both pre-existing Phase 8B lineage
routes, remain backward compatible and byte-for-byte unchanged; all 8C
routes are additive.

The implementation ledger is `PHASE8_IMPLEMENTATION_LEDGER.md` (8C section);
the final gate record is `.prism/checkpoints/phase-8c.md`. Every gate passed,
including live CI on PR #12's only head (`125b3f9`, all 5 checks green, no
re-run needed) and no review comments raised before merge.

`PHASE_8A_COMPLETE = YES`, `PHASE_8B_COMPLETE = YES`, `PHASE_8C_COMPLETE =
YES`, `PHASE_8D_STARTED = NO`.

## Still forbidden in 8C

- staleness propagation / invalidation propagation
- rerun or reproduction execution engine
- Atlas lineage awareness
- lineage/evidence frontend UI
- database or persistence layer
- governance
- Phase 9 work

The exact 8D starting point (Versioning + Staleness Propagation) reuses the
descendant traversal 8C already built to answer "a dataset revision changed;
which downstream objects are now stale?" — it must not be started without a
fresh, explicit scope decision. See `PHASE8_IMPLEMENTATION_LEDGER.md`'s 8C
section and `.prism/checkpoints/phase-8c.md` for the exact starting point.
