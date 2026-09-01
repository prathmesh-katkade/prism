# Phase 9 Final Report — Durable Analytical History and Productization

**Date:** 2026-09-01
**Repository:** `prathmesh-katkade/prism`
**Canonical base:** `phase-6.5-integration-staging` at `4b0a271061603db75d2350f8f951652c84dabd3d`
**PR:** [#14](https://github.com/prathmesh-katkade/prism/pull/14) (`phase-9-productization` → `phase-6.5-integration-staging`)

## Executive summary

Phase 8 gave PRISM a complete, deterministic analytical-history system that
reset on every API process restart — a known, explicitly accepted limitation
carried in every 8A–8H checkpoint. Phase 9 makes that history durable without
touching a single Phase 8 contract: `DatasetStore` stays the sole authority
for active revision identity, `AnalyticalObject` stays fully immutable, and
every read/traversal/freshness/rerun/Atlas behavior from Phase 8 is
unchanged — only the storage underneath the registry and the dataset store
changed, from process memory to a configured SQL database. On top of that
durable foundation, Phase 9 wires the Evidence Inspector through every
remaining native workflow, adds a native History workspace, adds a
lightweight append-only audit trail, and expands safe reproduction where an
async-safe design actually exists.

This work landed as 14 commits on `phase-9-productization`, continuing a
prior interrupted session's real, already-pushed work (verified against git
and GitHub directly rather than assumed) plus this session's own CI
diagnosis, fixes, and a new live-e2e suite for the History workspace. All 5
CI checks are green on the final head `4a1b68e`.

## What Phase 9 delivered

### Durable analytical history
`DurableAnalyticalObjectRegistry` (`apps/api/src/prism_api/durable_registry.py`)
subclasses the Phase 8 `AnalyticalObjectRegistry` and persists immutable
object snapshots and direct lineage edges through SQLAlchemy Core to a
configured database — managed MySQL in staging/production
(`PRISM_ANALYTICAL_HISTORY_DATABASE_URL`), an isolated local SQLite file
under `.prism/runtime/` otherwise. `PRISM_REQUIRE_DURABLE_HISTORY` turns a
missing URL into a startup failure so staging can never silently fall back
to an ephemeral file. `create_history_registry()` is the one factory the
real app singleton uses; passing `database_url=None` directly still gives
the old in-memory, per-instance isolation every existing Phase 8 test
pattern (`registry.__class__()`) depends on — no Phase 8 test needed to
change.

`DurableDatasetStore` (`apps/api/src/prism_api/durable_dataset_store.py`)
persists `DatasetStore`'s revision frames in the same configured database,
so a same-revision rerun survives a restart without ever trusting a
registry snapshot as a substitute for source data. `DatasetStore` itself
stays the sole authority for active-revision identity and branch semantics;
the durable adapter only makes its storage outlive the process.

Decision record: `docs/architecture/adr/0005-durable-analytical-history.md`.
Operations: `docs/operations/durable-analytical-history.md` (safe additive
schema upgrade, rollback/recovery procedure).

### Restart survival, proven
`tests/api/test_durable_registry.py` opens two independent registry/store
instances against the same database URL and proves history, direct lineage
edges, redaction, and primary-key idempotency all survive a process
boundary — the strongest proof available without a live redeploy. One test
(`test_configured_mysql_history_survives_registry_restart`) runs for real
against the CI MySQL service via `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`,
not just SQLite.

### Evidence Inspector everywhere
The shared `newestAnalyticalObjectId(datasetId, kind)` bridge
(`apps/web/src/components/analytical-history.ts`) wires SQL Lab, Clean, AI
Analyst, Visualize, Forecasting, Stats, and ML Lab results into the one
Evidence Inspector architecture Phase 8E built — a single shared component,
not a per-workflow reimplementation.

### Native History workspace
`history-workspace.tsx`: a searchable, kind-filterable, bounded read of the
durable history with live-computed current/stale counters (freshness is
still always computed live against `DatasetStore`, never stored — Phase 8D's
invariant, untouched) and direct navigation into the Evidence Inspector.
Covered by a unit/a11y test (`history-workspace.test.tsx`) and, added this
session, a real-browser live-e2e test
(`apps/web/e2e-live/history-live.spec.ts`) that uploads a dataset, runs a
SQL query, confirms the durably registered result shows up in History via
search, and opens its Evidence Inspector.

### Reproducibility expansion, where safe
Safe current-revision Clean reapply is supported. Same-revision Clean rerun
and SQL Lab rerun remain explicitly unsupported — SQL Lab's async
submit/poll execution model isn't safe to replay deterministically yet, and
this phase documents that rather than forcing it. Every rerun, as in Phase
8F, only ever creates a new object; nothing is ever overwritten.

### Lightweight governance, no RBAC
Append-only creation/rerun audit events (`AnalyticalAuditEvent`,
`GET /objects/{id}/audit`) record an explicit `system` actor — PRISM has no
identity/session boundary to attribute anything more specific to, and this
phase does not invent one. Authenticated actor/session correlation is
intentionally deferred until that boundary exists, consistent with this
phase's "no RBAC" scope.

### Security
Secret sanitization is enforced a second time at the persistence boundary
(`sanitize_provenance_parameters` runs again immediately before every
durable write, independent of producer-side sanitization) and verified to
survive a full database round trip
(`test_creation_audit_survives_restart_without_storing_secrets`). Every
query goes through parameterized SQLAlchemy Core, never string-built SQL.
There is no generic mutation API anywhere in the durable layer — only typed,
append-only writes and read-only routes; `/rerun` remains the one Phase 8F
write endpoint and still accepts only `mode`.

### Operations hardening
Schema version 1 is additive: startup creates the object, edge, audit,
DatasetStore-revision, and version tables only if absent and never
rewrites or deletes an existing row. `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`
+ `PRISM_REQUIRE_DURABLE_HISTORY=true` are correctly declared in
`render.yaml` for the native staging service (`sync: false` — the actual
credential is set in the Render dashboard, never in the file).
`/api/v1/platform/ready` reports an `analytical_history` provider readiness
entry. CI seeds a real `prism_history` MySQL database and runs
`test_durable_registry.py` against it before the live-e2e suite.

## CI diagnosis, this session

PR #14 arrived with two failing checks. Both are now green on head
`4a1b68e`, with the reasoning kept in each commit message and in
`.prism/checkpoints/phase-9-final.md`:

- **`phase-1-python`:** the checked-in generated TypeScript contract was
  stale (missing two fields on a validation-error interface). Regenerated
  and committed.
- **`phase-4-live-e2e`:** three rounds of genuine root-causing, not blind
  retries:
  1. `sql-lab-live.spec.ts` and `clean-visualize-live.spec.ts` share one
     real FastAPI backend and its single global
     `overview_store.latest()` pointer by design. Parallel Playwright
     workers raced concurrent dataset uploads against that shared
     pointer — a pre-existing hazard the durable store's added DB-write
     latency widened into a reliable failure. Fixed by pinning
     `workers: 1`.
  2. A second failure on the identical assertion, with server logs proving
     the backend responded in under 20ms every time and local reruns never
     reproducing it, pointed to CI-runner render latency rather than a
     logic bug. Timeout widened 10s → 20s.
  3. A third failure, in the newly added `history-live.spec.ts`, exhausted
     even the widened timeout. Replaced "click, then wait an unknown mix of
     network plus render time" with "wait for the actual results response,
     then wait a bounded, render-only 15s" across all three live spec
     files — confirmed green on the next run.

## Verification

- `pytest tests/api tests/contracts tests/migration tests/overview
  tests/sql_lab`: 222 passed, 4 skipped locally (MySQL-only tests skip
  without a local MySQL server; all run for real in CI).
- `ruff check`, `mypy --follow-imports=skip --allow-subclassing-any
  --allow-untyped-decorators --no-warn-return-any`: clean.
- `npm run lint`, `npm run typecheck`: clean.
- `npm run test:web` (vitest): 33/33 passed.
- `python tools/check_boundaries.py`, `python tools/check_secrets.py`:
  passed.
- `npm run test:e2e:live` (all 6 live browser tests, single worker,
  matching CI): passed three times in a row locally with the final
  response-synchronized version.
- CI on PR #14, head `4a1b68e`: all 5 checks green
  (`secret-scan`, `phase-1-web`, `phase-1-python`, `legacy-regression`,
  `phase-4-live-e2e`).

## Known limitations, by design (not blockers)

- **Authenticated actor/session correlation** is deferred until PRISM has
  an identity boundary; every durable audit event currently records an
  explicit `system` actor rather than inventing an identity layer this
  phase was never scoped to build.
- **Deterministic SQL rerun** is deferred until an async-safe design
  exists — SQL Lab's submit/poll execution model isn't safe to replay yet.
  Documented in the API's own rerun response for `query_result`, not
  silently dropped.

## Deployment status

`BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` — checked directly this session, not
assumed from Phase 8's prior finding. This session has no Render API
credentials, and additionally confirmed the sandbox's egress proxy rejects
outbound connections to `*.onrender.com` under organization policy
(`connect_rejected`), so even the unauthenticated public-endpoint probe
Phase 8 relied on is not reachable here. `render.yaml` correctly declares
the durable-history environment variables for the native staging service,
so the infrastructure-as-code side is ready; only the live deploy and the
"restart the API and prove history survives" production proof remain
undone, pending Render access this session does not have.

**Distinguishing status honestly:**
- **Engineering complete:** YES — all Phase 9 code on `phase-9-productization`.
- **CI complete:** YES — all 5 checks green on PR #14's head `4a1b68e`.
- **Live deployment / restart proof:** NOT VERIFIED — blocked by both
  missing credentials and network egress policy in this session. Restart
  survival is proven at the strongest level available without it: two
  independent process instances (including one against the real CI MySQL
  service) sharing one database, per `test_durable_registry.py`.

Consistent with the release bar this repository has applied since Phase
6.5/7 and reaffirmed in Phase 8: engineering + CI completeness, not a live
deployment no session in this environment has credentials to perform.

## Release status

**COMPLETE — merged.** [PR #14](https://github.com/prathmesh-katkade/prism/pull/14)
merged into `phase-6.5-integration-staging` at merge commit
`2013f41faa8a515b039b6a37a493abc2c05c7b23` on 2026-09-01. All 5 CI checks
passed on the final head `4a1b68e`. See `PHASE9_IMPLEMENTATION_LEDGER.md` for
the full completed/remaining checklist and `.prism/checkpoints/phase-9-final.md`
for the detailed gate record.

## Phase 10 handoff

Not started, not scoped beyond the pointer already on record. See
`PHASE10_HANDOFF.md`.

## Final Phase 9 flags

```
PHASE_9_COMPLETE = YES (engineering + CI; deployment verification blocked externally)
PHASE_10_UNLOCKED = YES
```
