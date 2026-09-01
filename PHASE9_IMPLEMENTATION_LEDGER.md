# Phase 9 Implementation Ledger — Durable Analytical History and Productization

**Branch:** `phase-9-productization`
**Status:** IN PROGRESS — do not certify or merge as Phase 9 complete from this record.

## Completed in this checkpoint

- [x] Recovered Phase 8 canonical state and preserved an unrelated dirty local
  Phase 8B worktree by using an isolated Phase 9 worktree.
- [x] Recorded the truthful Phase 8 deployment probe: public health, readiness,
  and web root are available, but authenticated Render deployment identity is
  unavailable.
- [x] Added ADR 0005 selecting the existing SQLAlchemy boundary. Managed MySQL
  is the intended staging store; SQLite is a local/test fallback.
- [x] Added transactionally persisted immutable object snapshots and direct
  lineage edges, indexed by object id, dataset, revision, fingerprint, kind,
  and creation time.
- [x] Added restart, lineage, primary-key idempotency, and redaction tests.
- [x] Made DatasetStore revisions durable in the same configured store, retaining
  its authority for active revision and fingerprint-aware branch semantics.
- [x] Added the reusable client-side read-only bridge and wired Evidence
  Inspector selection through SQL Lab, Clean, AI Analyst, Visualize,
  Forecasting, Stats, and ML baseline results.
- [x] Added a native History workspace with bounded global-history reads,
  search, kind filtering, current/stale counters, and direct Evidence Inspector
  navigation.
- [x] Added safe Clean current-revision reapply; same-revision Clean remains
  explicitly unsupported because it would otherwise change the active branch.
- [x] Added append-only creation/rerun audit events with service/version and an
  explicit `system` actor (there is no authenticated identity layer to invent),
  plus a read-only audit endpoint.
- [x] Added durable-history readiness reporting, managed-MySQL CI restart
  coverage, explicit Render configuration requirements, and an operational
  migration/backup/rollback procedure.
- [x] Wired ML feature-selection and SHAP results into the shared Evidence
  Inspector context.

## Remaining before Phase 9 certification

- [ ] Authenticated actor/session correlation (out of scope until PRISM has an
  identity boundary; creation records explicitly show `system` meanwhile).
- [x] Dedicated deployed History browser suite: `apps/web/e2e-live/history-live.spec.ts`
  drives a real browser against the live API - upload, run a SQL query,
  confirm the durably registered result appears in the History workspace,
  and open its Evidence Inspector.
- [ ] Deterministic SQL rerun design where asynchronous execution context can
  be preserved without permitting credential reuse or arbitrary execution.
- [ ] Full repository gate on CI, PR review/merge, authenticated staging deploy,
  and live smoke matrix.

```
PHASE_8_COMPLETE = YES
PHASE_9_COMPLETE = NO
PHASE_10_UNLOCKED = NO
```
