# Phase 4 · Unit 03 — gate remediation

**Delivered:** An interruptible SQL job seam, queued/running/terminal contracts, cancellation and
timeout behavior, live SSE run-state events, durable secret-free run/snippet metadata, idempotent
execution requests, startup reconciliation, explicit post-restart result expiry, server-configured
SQLite/MySQL connectors, result export/promotion, and a virtualized paginated result grid. Query caps
apply before a result frame is materialized.

**Security:** SQLite paths and external connection URLs are configured only on the API host and are
never returned through contracts, provenance, Atlas evidence, logs, or browser state. Conservative
classification now rejects stacked statements and mutating CTEs while allowing mutation words in
quoted literals. Production dependency audit is zero-vulnerability after the Next 16.3.3 upgrade.

**Verification:** 30 Python tests, 5 web component/integration tests, 3 Playwright visual/keyboard
tests, 1 unmocked live browser/API test, type/lint/build/contract/boundary/secret/a11y checks, and
the production dependency audit pass. A real isolated MySQL 8 source verifies schema, results,
types/nulls/order, plans, API secrecy, cancellation, and timeout behavior against the legacy helper.

**Remaining boundary:** PostgreSQL and SQL Server have typed connector/capability seams but no
representative legacy source or live parity environment in this repository, so they remain clearly
degraded/unverified. Deployment is not claimed; this checkpoint verifies the local migration slice.
