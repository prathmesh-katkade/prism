# ADR 0015: Present Atlas Cortex as structured records

## Decision

Atlas Cortex continues to project stored runs, plans, steps, evidence, and their recorded relations as required by ADR 0010. The web client presents that projection as grouped records, an atomic node list, and a relation list. Selection keeps the existing context-inspector contract for the run core, nodes, groups, and pipeline stages.

Remove the 3D scene and its rendering dependencies. Spatial coordinates, camera movement, glow, particles, and rotation are presentation effects; none is a source of run truth. The data helpers that map persisted state to tone, plan-step links, and grounded groups remain independent of the renderer.

## Consequences

An analyst can read node state, group membership, identifiers, and relation types without a WebGL surface. The replacement is intentionally plain pending the separate VNext design review. Existing ADRs remain unchanged.
