# ADR 0010: Atlas Cortex derives from runtime records

## Decision

Atlas Cortex is a projection of stored runs, plans, steps, evidence, analytical
objects, memories, models, and benchmark records. Nodes and edges must refer to
real identifiers and relation types. Rendering effects are presentation only.

## Consequences

The initial API emits a data-model projection, not speculative 3D visuals. This
lets the future graph remain auditable, accessible, and truthful.
