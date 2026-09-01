# ADR 0005: Durable analytical history uses the existing SQLAlchemy boundary

**Status:** Accepted (Phase 9)

## Context

Phase 8 deliberately kept analytical objects and direct lineage edges in one
process-local registry. It gave PRISM deterministic provenance but lost all
history on API restart. `DatasetStore` remains the sole authority for dataset
revision content and identity; history must never reinterpret or replace it.

## Decision

Persist immutable analytical-object snapshots and direct parent-to-child edges
through SQLAlchemy, which is already a runtime dependency used by PRISM's SQL
integration. A managed database URL is supplied only through
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL`; the Render blueprint declares the
secret reference but never a credential. MySQL is the intended managed staging
target because it is already exercised in CI. SQLite is an explicit local/test
fallback, not a production substitute.

The schema has primary-key object identity, transactionally written direct
edges, and indexes for dataset, revision, fingerprint, kind, and creation time.
Freshness stays derived at read time against `DatasetStore`; historical
snapshots, provenance, and edges are append-only. DatasetStore revision frames
are persisted by its own adapter and remain its authoritative source for
revision identity and content. The history tables never store a fitted model,
raw credential, or hidden reasoning.

## Consequences

Restart-safe history and lineage are available when a durable database URL is
configured. Retries are idempotent at the object-id primary key. Migrations use
the version table plus additive SQLAlchemy schema creation; incompatible future
changes require a numbered migration and a tested rollback before release.
The version-1 rollout is additive and documented in
`docs/operations/durable-analytical-history.md`; managed database backups are
required before future destructive schema changes.
