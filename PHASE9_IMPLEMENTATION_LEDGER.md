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
- [x] Added the reusable client-side read-only bridge and wired Evidence
  Inspector selection through Visualize, Forecasting, and ML baseline results.

## Remaining before Phase 9 certification

- [ ] Production migration/rollback tooling and managed-MySQL configuration.
- [ ] Persisted audit fields and request/session correlation.
- [ ] SQL Lab, Clean, AI Analyst, and all remaining ML result coverage in the
  Inspector; dedicated History workspace and its accessibility/E2E suite.
- [ ] Deterministic SQL/Clean rerun design and implementation where safe.
- [ ] DatasetStore restart semantics and a real managed-store restart test.
- [ ] Full repository gate on CI, PR review/merge, authenticated staging deploy,
  and live smoke matrix.

```
PHASE_8_COMPLETE = YES
PHASE_9_COMPLETE = NO
PHASE_10_UNLOCKED = NO
```
