# ADR 0014: Atlas experience projects durable facts and keeps execution bounded

## Decision

The Phase 11 Atlas interface is a presentation and navigation layer over durable
server records. Cortex nodes, relationships, specialists, steps, evidence,
certification state, and shareable run links must resolve to stored identifiers.
Animation and 3D layout may clarify those facts but cannot manufacture activity,
reasoning, tools, evidence, or completion.

Run admission is bounded before a durable run is accepted for execution.
Unexpected worker exits and process-restart leftovers transition atomically to a
recorded failure. They are never left indefinitely running and never relabeled as
completed. History links are additive URL state; an optional focused node is
honored only after the run-scoped Cortex proves that node exists.

The API remains local-only until real external identity, sessions, resource
ownership, and RBAC exist. Public staging and production configurations fail at
startup rather than placing privileged routes behind a shared secret.

## Consequences

- A screenshot or animation is presentation evidence, not execution evidence.
- Every operator-visible state can be traced to a run-scoped backend record.
- Saturation returns a retryable refusal instead of creating unbounded threads.
- Stale or crashed work leaves an explicit durable terminal reason.
- Phase 11 can improve the interface without weakening Phase 10 trust gates.

This ADR extends ADR 0010 from graph projection to the full Phase 11 experience
and its execution/recovery boundary.
