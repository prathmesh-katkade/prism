# ADR 0008: Secure analytical sandbox boundary

## Decision

Future Python execution runs in a project-scoped worker with network disabled
by default, resource/time/concurrency limits, deterministic seeds, captured
output, registered artifacts, cancellation, and an allowlisted package policy.
No model-facing endpoint may execute arbitrary shell commands.

## Consequences

The initial Atlas slice exposes no Python executor. It uses only explicitly
registered PRISM tools until this boundary and its isolation tests exist.
