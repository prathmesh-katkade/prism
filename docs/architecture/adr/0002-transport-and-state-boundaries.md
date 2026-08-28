# ADR 0002: Typed transport and layered frontend state

**Status:** Accepted

## Decision

The web boundary keeps transport, server/cache state, workspace state, and ephemeral UI state
as separate interfaces. REST and SSE share an `ApiTransport` abstraction; the browser is not
allowed to call `fetch` outside that boundary. Feature flags and migration states are
contract-defined, default-safe, and do not expose a migrated workflow in Phase 1.
