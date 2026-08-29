# Phase 8 Handoff

**Status: Phase 8 has NOT been started.** This document exists only to give a
future session minimal orientation — it is not a Phase 8 brief or plan, and
no Phase 8 code, contracts, or components exist anywhere in this repository.

## Where things stand

- Branch: `phase-7-advanced-analytics`, head `ec2a22a`.
- Phase 7 (Stats Lab, Forecasting, ML Lab) is complete — see
  `PHASE7_FINAL_REPORT.md` for the full summary and `PHASE_8_UNLOCKED = YES`.
- Every workflow in `apps/web/src/components/prism-shell.tsx`'s navigation
  (Overview, SQL Lab, AI Analyst, Clean, Visualize, Stats, Forecasting, ML)
  now opens a native surface and is `ReleaseChannel.ENABLED` in both
  `apps/api/src/prism_api/migration.py` and
  `apps/web/src/state/shell-model.ts`. There is no remaining Streamlit
  analytical module left to migrate as a vertical slice in the pattern
  Phases 3–7 followed.

## What Phase 8 is not yet defined to be

Unlike Phase 7 (which had a detailed `PHASE7_BRIEF.md` prepared in the
prior session before implementation started), **no equivalent brief for
Phase 8 exists**. Every phase checkpoint since Phase 1
(`.prism/checkpoints/phase-1.md` through `phase-6.md`) has carried the same
boilerplate "still forbidden" line — *"full autonomous Atlas orchestration,
governance, desktop, and publication work"* — without ever elaborating what
those mean concretely. That phrase is the only signal in this repository
about what comes after the vertical-slice migration work Phases 3–7
completed. Do not treat it as a spec.

Four candidate directions it points toward, purely as orientation (not a
commitment, priority order, or scope decision):

1. **Full autonomous Atlas orchestration** — every native workflow's Atlas
   integration so far (Clean/Visualize/Stats/Forecasting/ML Lab) is
   explicitly *contextual and evidence-grounded*: Atlas explains a
   deterministic result or proposes a single reviewable action, never
   executes multi-step plans unattended. A "full orchestration" phase would
   presumably mean Atlas chaining multiple tool calls/workflows toward a
   goal — a materially different trust model than anything built so far,
   and one every phase to date has explicitly deferred.
2. **Governance** — no access control, audit trail, or multi-user concept
   exists anywhere in the native stack today (the `DatasetStore` is
   process-local, single-session). Undefined what "governance" means
   concretely — data governance, user/role governance, and model-governance
   (relevant given ML Lab now exists) are all plausible readings.
3. **Desktop** — `apps/web/src/components/prism-shell.tsx`'s own project-grid
   copy ("Desktop ready … Layout state is local and browser-native, ready
   for future Tauri ownership") and ADR 0001
   (`docs/architecture/adr/0001-phase-1-contract-first-foundation.md`)
   both name Tauri as the placeholder direction, but no Tauri scaffolding,
   dependency, or build target exists in the repo yet.
4. **Publication** — undefined; could mean anything from exporting an
   analysis/report to deploying the native stack as the production default
   (still Streamlit today) to something else entirely.

## Before starting Phase 8

A future session should get an explicit scope decision from the user/product
owner — analogous to how Phase 7's own master prompt named Stats/
Forecasting/ML Lab explicitly — rather than inferring a plan from the
"still forbidden" phrase above. Do not begin implementing any of the four
candidate directions without that explicit instruction.

## Files worth reading first, once Phase 8's actual scope is known

- `docs/architecture/adr/0001-phase-1-contract-first-foundation.md` — the
  original architectural boundaries (web / API / desktop-shell placeholder
  / legacy Streamlit) this project has held since Phase 1.
- `PHASE7_IMPLEMENTATION_LEDGER.md` and `PHASE7_FINAL_REPORT.md` — the
  complete, current state of every native workflow, useful for
  understanding what Atlas/governance/desktop work would build on top of.
- `apps/api/src/prism_api/migration.py` /
  `apps/web/src/state/shell-model.ts` — the `ReleaseChannel` mechanism, if
  Phase 8 introduces new workflows following the same pattern.
