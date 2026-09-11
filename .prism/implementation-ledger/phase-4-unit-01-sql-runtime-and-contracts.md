# Phase 4 · Unit 01 — SQL runtime and typed contract boundary

**Delivered:** Framework-free DuckDB and server-configured SQLite runtimes preserving the legacy
`data` table convention for local reads; typed Pydantic/OpenAPI contracts for sources, capabilities,
schema, runs, paginated results, plans, snippets, history, provenance, and contextual Atlas actions.

**Safety:** SQL is classified conservatively. Only proven reads execute; mutating or unknown SQL
returns a governed-write failure. Credential-like parameter values are redacted from provenance.
No connection secret is returned by any SQL Lab response.

**Parity evidence:** representative DuckDB read results, dtypes, nulls, and deterministic ordering
match `modules/sql_lab.py`. The reference module was not edited.

**Runtime:** queued/running/terminal state runs behind an interruptible in-process job seam. Run
metadata and snippets are durable in a server-local SQLite store; capped result pages are intentionally
ephemeral and return an explicit rerun response after process restart.

**Connector boundary:** local/Overview, server-configured SQLite, and server-configured MySQL are
native. External source definitions contain only environment-variable references; connection URLs
remain server-side. PostgreSQL and SQL Server expose typed capability/degraded states but have no
representative legacy source in this repository, so they remain unverified rather than advertised
as parity-complete.
