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

## Remaining before Phase 9 certification

- [ ] Production migration/rollback tooling and managed-MySQL configuration.
- [ ] Persisted audit fields and request/session correlation.
- [ ] Remaining ML feature-selection/SHAP Inspector selection and dedicated
  History accessibility/E2E suite.
- [ ] Deterministic SQL rerun design where asynchronous execution context can
  be preserved without permitting credential reuse or arbitrary execution.
- [ ] Real managed-MySQL restart test.
- [ ] Full repository gate on CI, PR review/merge, authenticated staging deploy,
  and live smoke matrix.

```
PHASE_8_COMPLETE = YES
PHASE_9_COMPLETE = NO
PHASE_10_UNLOCKED = NO
```
