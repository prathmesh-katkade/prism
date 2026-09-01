# Phase 9 checkpoint — Durable Analytical History and Productization

**Branch:** `phase-9-productization` → `phase-6.5-integration-staging`
**PR:** [#14](https://github.com/prathmesh-katkade/prism/pull/14)
**Status:** IN PROGRESS — CI is being driven to green on head `702c78f`; do not
certify or merge as Phase 9 complete from this record until the "CI on PR #14"
section below is updated to confirm all checks pass on the actual merged head.
Deployment verification is `BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` regardless.

## What Phase 9 delivered

- **Durable analytical history.** `DurableAnalyticalObjectRegistry` (SQLAlchemy)
  persists immutable object snapshots and direct lineage edges to a configured
  database — managed MySQL in staging/production, an isolated local SQLite
  file otherwise. `DatasetStore` stays the sole authority for active revision
  identity and content; `DurableDatasetStore` persists its revision frames in
  the same configured database so same-revision reruns survive a restart
  without trusting a registry snapshot as a substitute for source data.
  ADR: `docs/architecture/adr/0005-durable-analytical-history.md`.
  Ops: `docs/operations/durable-analytical-history.md`.
- **Restart survival, proven.** `tests/api/test_durable_registry.py` opens two
  independent registry/store instances against the same database URL and
  proves history, lineage, redaction, and idempotency all survive a process
  boundary; one test runs for real against the CI MySQL service via
  `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`.
- **Evidence Inspector coverage across every native workflow.** The shared
  `newestAnalyticalObjectId` bridge (`analytical-history.ts`) wires SQL Lab,
  Clean, AI Analyst, Visualize, Forecasting, Stats, and ML Lab results into
  one Evidence Inspector architecture (`evidence-inspector.tsx`).
- **Native History workspace.** `history-workspace.tsx`: searchable,
  kind-filterable, bounded reads of the durable history with live-computed
  current/stale counters and direct Evidence Inspector navigation. Unit
  (`history-workspace.test.tsx`) and a real-browser live suite
  (`apps/web/e2e-live/history-live.spec.ts`) both cover it.
- **Reproducibility expansion where safe.** Safe current-revision Clean
  reapply is supported. Same-revision Clean rerun and SQL Lab rerun remain
  explicitly unsupported — SQL Lab's async submit/poll execution model isn't
  safe to replay deterministically yet, and this phase does not force it.
  Every rerun still only ever creates a new object; nothing is overwritten.
- **Lightweight governance, no RBAC.** Append-only creation/rerun audit events
  (`AnalyticalAuditEvent`, `GET /objects/{id}/audit`) record an explicit
  `system` actor — there is no identity boundary in PRISM to invent one from.
  Authenticated actor/session correlation is intentionally deferred until
  that boundary exists.
- **Security.** Secret sanitization is enforced a second time at the
  persistence boundary (`sanitize_provenance_parameters` before every
  durable write, independent of producer-side sanitization), verified to
  survive a DB round trip. All queries are parameterized through SQLAlchemy
  Core. There is no generic mutation API — only typed, append-only writes and
  read-only routes.
- **Operations hardening.** Additive schema versioning (version-1 table
  creation is idempotent and non-destructive), managed-MySQL CI restart
  coverage, `/api/v1/platform/ready` reports `analytical_history` readiness,
  and a documented migration/backup/rollback procedure.

## Verified locally (this session)

- `pytest tests/api tests/contracts tests/migration tests/overview tests/sql_lab`:
  222 passed, 4 skipped (MySQL-only tests skip without a local MySQL server;
  they run for real in CI).
- `ruff check`, `mypy --follow-imports=skip ...`: clean.
- `npm run lint`, `npm run typecheck`: clean.
- `npm run test:web` (vitest): 33/33 passed.
- `python tools/check_boundaries.py`, `python tools/check_secrets.py`: passed.
- `npm run test:e2e:live` (all 6 live-e2e tests, single worker, matching CI):
  passed twice in a row.

## CI on PR #14 — IN PROGRESS

Driving to green across several rounds, all in `phase-4-live-e2e`'s live
browser suite (`secret-scan`, `phase-1-web`, `phase-1-python`, and
`legacy-regression` have been green since the first push this session):

1. `sql-lab-live.spec.ts` and `clean-visualize-live.spec.ts` share one real
   FastAPI backend and its single global `overview_store.latest()` pointer by
   design. Running the two spec files across parallel Playwright workers
   raced concurrent dataset uploads against that shared pointer — a
   pre-existing hazard the durable store's added DB-write latency widened
   into a reliable CI failure. Fixed by pinning `workers: 1` in
   `playwright.live.config.ts`.
2. A second failure on the same assertion after that fix, with server logs
   proving the backend responded in under 20ms every time and local reruns of
   the full suite never reproducing it, pointed to CI-runner render latency
   (Monaco itself logs a main-thread fallback there) rather than a logic bug.
   Widened the two live assertions checking that exact text from 10s to 20s.
3. A third failure on the same assertion, now in the newly added
   `history-live.spec.ts` and exhausting the full 20s, meant the timeout bump
   alone wasn't the fix. Replaced "click, then wait an unknown mix of network
   plus render time" with "wait for the actual results response, then wait a
   bounded, render-only 15s" across all three spec files (commit `702c78f`),
   removing the network half of the uncertainty rather than continuing to
   guess at a bigger number.

CI is currently running on `702c78f`; this checkpoint will be updated with the
confirmed result rather than left claiming green ahead of that confirmation.

## Deployment verification — BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS

Unchanged from Phase 8: this session has no Render API credentials. This
session additionally confirmed the sandbox's egress proxy rejects outbound
connections to `*.onrender.com` under organization policy (`connect_rejected`),
so even the unauthenticated public-endpoint probe Phase 8 relied on is not
possible here. `render.yaml` correctly declares
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` (`sync: false`, set manually in the
Render dashboard) and `PRISM_REQUIRE_DURABLE_HISTORY=true` for the native
staging API service, so the infrastructure-as-code is ready — deployment and
the live "restart the API and prove history survives" proof remain undone
pending Render access. Restart survival is proven at the strongest level
available without it: two independent process instances (including one
against the real CI MySQL service) sharing one database.

## Remaining, by design (not blockers)

- Authenticated actor/session correlation — deferred until PRISM has an
  identity boundary.
- Deterministic SQL rerun — deferred until an async-safe design exists;
  documented, not silently dropped.

```
PHASE_8_COMPLETE = YES
PHASE_9_COMPLETE = PENDING (CI being driven to green on PR #14, head 702c78f)
PHASE_10_UNLOCKED = NO
```
