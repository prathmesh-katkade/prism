# Phase 3 · Unit 03 — parity, quality, and performance verification

**Evidence:** Python: 12 tests passed (full suite). Web: 4 component tests passed. Playwright:
2 visual/keyboard tests passed. TypeScript typecheck, ESLint, Ruff, mypy, generated-contract
freshness, dependency boundaries, and accessibility baseline passed.

**Performance baseline:** deterministic profile only, local Windows environment, 5 mixed columns:
1,000 rows 29 ms; 50,000 rows 641 ms; 500,000 rows 6,490 ms. The Phase 3 API rejects frames over
500,000 rows and uploads over 64 MB; rows are returned in pages capped at 100.

**Known gap:** the store is process-local, so an API restart requires re-upload. This is deliberate
Phase 3 scope, not a persisted-project implementation.
