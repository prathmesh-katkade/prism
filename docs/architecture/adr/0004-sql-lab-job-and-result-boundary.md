# ADR 0004: SQL Lab separates durable run metadata from ephemeral result materialization

## Status

Accepted for Phase 4.

## Context

SQL Lab needs cancellation, timeout state, reproducible history, and paginated results without
persisting potentially sensitive result values or shipping an unbounded table to the browser.
The platform-wide Job Runtime and governed-write system are later-phase work.

## Decision

Phase 4 uses an interruptible in-process job seam for safe read queries. Run state, provenance,
and snippets are persisted in a server-local SQLite metadata store. Result frames stay only in
process memory, are capped before materialization, and are exposed as small pages. A restart keeps
the reproducible run record but returns an explicit expired-materialization response instead of
silently pretending that result data remains available.

Server-configured SQLite paths are discovered from `PRISM_SQLITE_SOURCES_JSON`. External source
registrations are discovered from `PRISM_EXTERNAL_SQL_SOURCES_JSON` and reference a separate
environment variable containing the connection URL. Paths, URLs, and secret references never form
part of an API response, Atlas evidence, provenance payload, or browser state.

## Consequences

- Long-running connector implementations can attach a driver interrupt callback without changing
  the REST contracts.
- A later durable Job Runtime can replace the in-process seam behind the same run states.
- Result retention and cross-user project ownership are still intentionally out of scope.
- MySQL is native-ready when registered through the server-only source boundary and has live parity
  evidence. PostgreSQL and SQL Server remain degraded until a representative source and driver can
  exercise their capability seams.
