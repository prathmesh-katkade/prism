# ADR 0007: Atlas orchestration and Council

## Decision

Atlas owns structured plans, typed tool invocation, cancellation, retries, and
the public answer. Specialists are named, visible execution units that return
evidence-backed conclusions. Council mode preserves conclusions, evidence, and
objections only; it never exposes hidden reasoning traces.

## Consequences

Plans can be inspected and replayed against compatible deterministic tools while
the interface remains truthful about unknowns, tool limitations, and objections.
