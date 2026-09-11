# ADR 0001: Contract-first coexistence foundation

**Status:** Accepted

## Decision

Pydantic models exposed by `apps/api` define the canonical OpenAPI contract. The generated
TypeScript types and client are derived from that OpenAPI document and are consumed by web and
desktop boundaries. The existing Streamlit app and the historical `api/` prototype remain
unchanged, reference-only runtimes.

## Consequences

This removes the `sys.path` workaround from new code without attempting to rewrite the
Streamlit-coupled analytics in Phase 1. Feature endpoints remain intentionally absent until
their parity fixtures and extraction seams are approved.
