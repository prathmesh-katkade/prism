# Rollback — Native Stack (Phase 5 / 6 / 6.5)

This document describes how to roll back the native Next.js + FastAPI stack
without deleting data and without touching the legacy Streamlit application.

## 1. Code rollback

- **Previous stable migration commit** (last commit before Phase 6.5's
  changes, i.e. the state right after PR #6 merged Phase 5 + Phase 6):
  `a203eea` — "Merge #6: Phase 5 verification + Phase 6 Clean/Visualize
  vertical slices" on `phase-5-ai-analyst`.
- **Current release tag**: `prism-native-v0.6` at `349943f`.
- To roll the native stack's *code* back to pre-6.5 behavior:
  `git revert` the Phase 6.5 commits (`3b4d89c`..`349943f`) on top of
  `phase-5-ai-analyst`, or redeploy from commit `a203eea` directly. No schema
  or data migration is tied to any Phase 6.5 commit, so this is a pure code
  rollback.

## 2. Deployed service rollback

No live staging deployment exists yet in this environment (deployment is
blocked on hosting credentials — see `PHASE6_5_RELEASE_REPORT.md`). Once a
real deployment exists on Render (or any host), rollback is:

- **Render**: use the dashboard's "Rollback to previous deploy" on
  `prism-native-api-staging` and `prism-native-web-staging` independently —
  each service redeploys from its last successful build without affecting
  the other, and without affecting the `prism` (Streamlit) service.
- If a rollback target commit is needed explicitly, redeploy each service
  pinned to commit `a203eea` (pre-6.5) or an earlier tagged commit.

## 3. Feature-flag / migration-map rollback

Each native workflow's release channel is tracked independently and can be
individually rolled back without a deploy of new code, by changing the
`channel` field to `ReleaseChannel.SHADOW` or `ReleaseChannel.LEGACY`:

- Backend: `apps/api/src/prism_api/migration.py` → `PHASE_1_MIGRATIONS`
  tuple. Currently all five workflows (`overview`, `sql-lab`, `ai-analyst`,
  `clean`, `visualize`) are `ReleaseChannel.ENABLED`.
- Frontend: `apps/web/src/state/shell-model.ts` → `phaseTwoMigrations`
  array, which must be kept in sync with the backend list.
- Rolling a single workflow back to `LEGACY` routes the shell's navigation
  for that workflow back to the legacy bridge/reference notice instead of
  the native vertical slice, with no data loss — the native `DatasetStore`
  and its revision history are unaffected and resume serving that workflow
  the moment the channel is flipped back to `ENABLED`.

## 4. Legacy Streamlit service

The legacy Streamlit application (`app.py`, `modules/*`) is untouched by
Phase 5/6/6.5 and requires no rollback action. It is deployed as the `prism`
service in `render.yaml` (unchanged), independent of the two new native
staging services. It remains the production-default surface; the native
stack is staging/integration-only per Phase 6.5's explicit scope.

## 5. Disabling native workflow channels entirely

To fully disable the native stack (e.g. if a defect is found post-release)
without deleting any code or data:

1. Set every entry in `PHASE_1_MIGRATIONS` (backend) and
   `phaseTwoMigrations` (frontend) to `ReleaseChannel.LEGACY`.
2. Optionally stop the two `prism-native-*-staging` services in the hosting
   dashboard — this does not affect the `prism` Streamlit service.
3. No database migration, data deletion, or destructive action is required
   at any point in this rollback path — the native stack's `DatasetStore`
   is in-memory/session-scoped and holds no persistent state to unwind.

## 6. What rollback does *not* require

- No deletion of uploaded datasets, revisions, or saved queries — the native
  stack currently persists none of these outside the running process.
- No secret rotation — no new secrets were introduced by Phase 6.5 beyond
  what `apps/api/.env.example` / `apps/web/.env.example` already document as
  optional and unset by default.
- No coordination with the legacy Streamlit deployment — the two stacks are
  fully independent services.
