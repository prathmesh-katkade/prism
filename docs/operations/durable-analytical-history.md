# Durable analytical-history operations

## Configuration

Production and staging must set `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` to a
managed MySQL-compatible SQLAlchemy URL. `PRISM_REQUIRE_DURABLE_HISTORY=true`
turns a missing URL into a startup failure; it is deliberately enabled in the
native Render service so PRISM never substitutes an ephemeral local file for
durable evidence. Local development may omit both values and uses an isolated
SQLite file under `.prism/runtime/`.

## Safe schema upgrade

Schema version 1 is additive: startup creates the object, direct-edge,
append-only audit, DatasetStore revision, and version tables if absent, then
records version 1. It never rewrites or deletes an existing snapshot, lineage
edge, audit event, or DatasetStore revision. Take a managed-database backup
before deploying a future schema version; future incompatible changes require
a numbered migration and a release-specific rollback test.

The staging CI service starts MySQL and proves that an object written by one
registry instance is visible to a fresh instance using the same configured
database URL. `/api/v1/platform/ready` reports the analytical-history
dependency as `ready` or `unavailable`.

## Rollback and recovery

For a code rollback within schema version 1, redeploy the previous compatible
API build. The tables are additive and the historical snapshots are immutable,
so no data rollback is needed. If a future migration is destructive, restore
the managed-database backup before rolling back the application; never drop
the history tables as an incident response shortcut.

If readiness reports `unavailable`, stop certifying new durable evidence,
restore database reachability, then use the read-only history and audit routes
to confirm prior objects and lineage are present. No API route can mutate an
existing object, lineage edge, or audit entry.
