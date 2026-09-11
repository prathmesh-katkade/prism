# PRISM Phase 4 checkpoint

**Status:** **PASS — READY FOR PHASE 5 locally.** Deployment/publication is not claimed.

## Starting state

- Workspace: `C:\Users\prath\prism`
- Branch: `main`, behind `origin/main` by 153 commits
- Base HEAD: `89094c6 Fix real visual bugs and add two premium themes, found via screenshot audit`
- Phase 1–3 were already uncommitted local work. Phase 3's checkpoint marked Overview PASS, but
  deployment was not verified. Phase 4 was layered onto that exact workspace without pulling,
  resetting, committing, or overwriting the inherited changes.
- `modules/sql_lab.py` remains the legacy Streamlit parity/rollback implementation. Its working-tree
  modification predates this Phase 4 slice; Phase 4 did not rewrite it.

## Native SQL Lab delivered

- Monaco-backed PRISM Query Studio with schema completion, multi-cursor behavior, formatting,
  uppercase-selection refactor, parameters, snippets, history, plans, result tabs, dialect display,
  status/cancel states, and native Ctrl/Cmd+Enter execution.
- Typed FastAPI/OpenAPI contracts for connections, capabilities, schema, execution, SSE run state,
  cancellation, paginated results, export, result promotion, plans, history, snippets, provenance,
  and contextual Atlas SQL actions.
- Pure DuckDB/SQLite/MySQL execution services behind connector/capability boundaries; source URLs,
  paths, credentials, and secret references stay on the API host.
- Durable, secret-free run/snippet/idempotency metadata with startup reconciliation; intentionally
  ephemeral capped result materialization with explicit rerun behavior after restart.
- Virtualized/paginated PRISM Data Grid with typed columns, selection, safe current-page filtering
  and sorting, copy, CSV/JSON export, result metadata, and promotion into an Overview dataset.
- Reproducible provenance records source identity/state fingerprint, SQL text/version, dialect,
  redacted parameters, timestamps, schema/result fingerprints, warnings, execution metadata, and
  downstream promoted objects.
- Conservative query safety rejects stacked statements, mutating CTEs, writes, and DDL. The future
  governed-write system is not simulated; unapproved mutation remains blocked.
- Atlas provides inspectable, editable SQL actions for explain, optimize, debug, plan inspection,
  generation, comparison, result-region explanation, lineage, and result conversion. It does not
  execute generated SQL or invent unsupported schema/capabilities.

## Connector capability and parity state

| Source | Phase 4 state | Evidence / difference |
| --- | --- | --- |
| Local/Overview dataset | Native | DuckDB schema, parameterized safe reads, EXPLAIN, capped results, cancellation/timeout seam, exact legacy values/types/null/order parity. |
| SQLite | Native when server configured | Schema, parameterized reads, EXPLAIN QUERY PLAN, interruption; file paths remain server-only. |
| MySQL | Native when server configured | Live isolated MySQL 8 parity for values, schema, numeric/null/order behavior, plans, API secrecy, cancellation, and timeout against the legacy helper. |
| PostgreSQL | Degraded/unverified | Typed capability and server-secret boundary exist; no representative legacy source/driver in this repository was available for parity certification. |
| SQL Server | Degraded/unverified | Typed capability and server-secret boundary exist; SHOWPLAN is explicitly degraded because it is permission-sensitive, and no representative legacy source was available. |

## Files changed for Phase 4

- Backend/runtime: `apps/api/src/prism_api/sql_lab.py`, `sql_jobs.py`, `main.py`, `migration.py`,
  `packages/sql-lab-runtime/python/prism_sql_lab_runtime/{service.py,external.py,__init__.py}`.
- Contracts/configuration: `packages/api-contracts/python/prism_api_contracts/{models.py,__init__.py}`,
  generated TypeScript contracts, API/runtime requirements, root requirements, and package metadata.
- Frontend: `apps/web/src/components/{query-editor.tsx,query-studio.tsx,query-studio.test.tsx}`,
  shell/model/transport integration, styles, package scripts, and lockfile.
- Verification: SQL Lab API/parity/performance tests, static and live Playwright specs/snapshots,
  cross-platform live configuration, CI MySQL/live-E2E job, secret and boundary checks.
- Records: this checkpoint, four Phase 4 ledger units, migration parity/current-phase records, and
  ADR 0004.

## Acceptance evidence

| Gate | Result |
| --- | --- |
| Backend, connector, contract, parity, security, cancellation, timeout, performance | PASS — 30 tests |
| Frontend components/integration | PASS — 5 tests |
| Static visual/keyboard regression | PASS — 3 Playwright tests |
| Unmocked browser → FastAPI analytical flow | PASS — upload, Monaco run, results, plan, promotion |
| Python typing/lint | PASS — mypy and Ruff |
| TypeScript/ESLint/production build | PASS |
| Generated contracts, dependency boundaries, secret scan | PASS |
| Accessibility baseline and keyboard operation | PASS |
| Production dependency security | PASS — 0 npm production vulnerabilities |
| CI workflow structure and whitespace validation | PASS |

Performance evidence: the 500,000-row local schema/aggregate/cap test completed in 0.43 seconds on
this workstation, below its 1.5/2.0-second gates; an unbounded 500,000-row read was capped at 1,001
rows before browser delivery. The live test requires Monaco startup below 8 seconds and passed. These
are local regression baselines, not remote database SLAs.

UX evidence:

- `apps/web/e2e/shell.spec.ts-snapshots/sql-lab-dark-desktop-chromium-win32.png`
- `apps/web/e2e-live/sql-lab-live.spec.ts-snapshots/sql-lab-live-results-live-chromium-win32.png`

## Known risks and technical debt

- The job executor is in-process and the metadata store is server-local. A later distributed Job
  Runtime can replace the seam without changing the Phase 4 API states.
- Result rows intentionally expire on restart; metadata and reproducibility survive, and the query
  can be rerun. Cross-user ownership and durable result retention remain later platform concerns.
- PostgreSQL and SQL Server cannot be parity-certified without representative environments; the UI
  reports this honestly instead of pretending support.
- Writes/DDL remain blocked until governed-write/risk-preview contracts are implemented in their
  own approved phase.
- The workspace is uncommitted, `main` is behind origin, and no deployment was verified. Those are
  publication/integration risks, not unexplained SQL Lab analytical drift.

## Rollback path

Set SQL Lab's migration channel back to `legacy` in `apps/api/src/prism_api/migration.py` and
`apps/web/src/state/shell-model.ts`, then remove the additive Phase 4 runtime/routes/components/tests
and generated contract additions. The Streamlit SQL Lab remains available throughout, so rollback
does not require reconstructing the legacy workflow or its saved-connection behavior.

## Verdict

**PASS — READY FOR PHASE 5 locally.** Phase 5 has not been started. Commit/rebase review and
deployment verification should occur as a separate controlled step before claiming a released build.
