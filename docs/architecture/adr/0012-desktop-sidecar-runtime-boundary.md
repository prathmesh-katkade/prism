# ADR 0012: Desktop shell and sidecar boundary

## Decision

PRISM retains its web UI while runtime contracts stabilize. A future thin desktop
shell supervises explicit FastAPI, model, sandbox, memory, voice, and Foundry
sidecars with least privilege. It is not a rewrite of the analytical UI.

## Consequences

Desktop packaging is architecture-only in this wave; no desktop runtime is
introduced before service supervision and permission contracts are testable.
