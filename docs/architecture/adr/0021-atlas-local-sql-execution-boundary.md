# ADR 0021: Atlas local SQL execution boundary

Status: Accepted for the first production investigation slice, 2026-09-28.

## Context

Atlas previously planned SQL steps but never executed them. SQL Lab already
owns a server-resolved local dataset connection, a guarded DuckDB executor,
query history, idempotency, cancellation, and provenance. The Atlas planner's
model output contains step labels, not trustworthy SQL or column references.

## Decision

The initial Atlas SQL tool accepts a typed aggregate declaration supplied by
the local user: count, sum, average, minimum, or maximum, with optional group
and equality filter. Atlas resolves the dataset ID and every column against
the active server-held revision, constructs the SQL from a fixed grammar,
quotes identifiers, and binds the filter value. Raw model SQL is never
dispatched by this tool. The model cannot propose its executable tool name.

The SQL runs through SQL Lab's existing local connection and job runtime. The
Atlas journal stores the exact query, bound parameters, source and revision,
execution-policy version, SQL run ID, result fingerprint, bounded result rows,
and terminal outcome. SQL Lab's own query metadata remains durable. Atlas
checks the revision and source fingerprint after execution before citing the
result. Recorded originals are immutable; SQL Lab receives an editable draft.

Atlas checks a server-owned execution policy before each dispatch. Profile-only
mode and per-tool disable block new work while retaining prior evidence. If
policy changes during SQL execution, the adapter requests cancellation and
records the outcome. The local desktop launch binds the API to loopback; Atlas
run creation and SQL Lab routes require the local-owner authorization boundary.

## Consequences

This is a deliberately narrow descriptive calculation. It does not infer a
join, causal result, statistical design, or arbitrary SQL from natural
language. Missing or invalid columns fail closed. SQL Lab remains the sole
execution service. Hosted use remains blocked by the existing deployment
security boundary until real user identity and authorization are implemented.
