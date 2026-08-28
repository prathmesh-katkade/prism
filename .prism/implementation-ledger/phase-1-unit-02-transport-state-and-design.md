# Phase 1 · Unit 02 — transport, state, and design primitives

**Objective:** Establish frontend-facing interfaces without building a workflow.

**Delivered:** generated TypeScript OpenAPI contract/client, REST/SSE transport abstraction,
separated server/workspace/UI state interfaces, release-channel feature flags, and renderer-agnostic
design tokens/primitives.

**Decision:** Browser network traffic goes through `ApiTransport`; feature availability is false
unless a contract migration state is explicitly `enabled`.

**Validation:** TypeScript lint/type check, generator freshness check, and accessibility baseline passed.

**Parity:** All product routes remain unavailable in the new UI by design.

**Rollback:** These are unused additive interfaces; no legacy runtime imports them.
