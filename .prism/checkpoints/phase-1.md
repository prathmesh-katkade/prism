# PRISM Phase 1 checkpoint

**Status:** Complete, pending architecture review.

## Delivered scope

- Modular boundaries for web, new FastAPI API, desktop-shell placeholder, and legacy Streamlit.
- Shared API contracts, analytical object schemas, Atlas interfaces, configuration, testing utilities,
  and TypeScript design tokens/primitives.
- Pydantic/OpenAPI canonical platform contract with generated TypeScript types/client.
- Typed REST/SSE transport plus layered frontend state, migration-state, and feature-flag interfaces.
- CI gates for lint/type, contract generation/tests, boundaries, secret scanning, accessibility baseline,
  and migration parity hooks.

## Explicitly not delivered

Overview, SQL Lab, AI Analyst, Atlas behavior, persistence, and Streamlit changes. Every migrated
workflow flag remains `legacy` and unavailable to the new web boundary.

## Validation

- Python contract/framework-boundary suite: 5 passed.
- Legacy deterministic Auto Cleaner reference suite: 8/8 passed.
- Python lint/type, TypeScript lint/type, generated-contract freshness, dependency-boundary,
  secret-pattern, and accessibility baseline checks: passed.

## Remaining gates

Architecture review must approve the contract naming/versioning and the API ownership/lifecycle
model before any workflow endpoint or screen begins. CI must pass on clean GitHub runners,
including Python 3.11 and gitleaks history scanning.

## Rollback

Phase 1 is additive except for CI and `.gitignore`; deleting the new foundation paths and reverting
the CI workflow restores the prior legacy-only runtime. No data or legacy product code was changed.
