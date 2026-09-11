# Phase 1 · Unit 01 — boundaries and canonical contracts

**Objective:** Establish coexistence boundaries without altering Streamlit.

**Delivered:** `apps/api`, `apps/web`, `apps/desktop-shell`, and the documented legacy boundary;
Pydantic API contracts, analytical schemas, Atlas interfaces, configuration, and test utilities.

**Decision:** New apps cannot import `app.py`, `modules/`, or the legacy API prototype. OpenAPI is
served at `/api/v1/openapi.json` from the new API only.

**Validation:** API contract tests passed; static dependency-boundary check passed.

**Parity:** Overview, SQL Lab, and AI Analyst remain `legacy` only.

**Rollback:** Delete the additive `apps/` and `packages/` paths; legacy entry points are unchanged.
