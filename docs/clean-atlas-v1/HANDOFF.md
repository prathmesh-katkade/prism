# Clean + Atlas presentation — handoff

One durable file, updated at every checkpoint rather than left to scatter
across phase docs. Read this first in any new session.

## State as of this entry

- Branch: `prism/clean-pattern-review-v1`
- HEAD: Phase 3 checkpoint, about to be committed/pushed (see git log for
  the exact SHA - this file is updated in the same commit)
- Working tree: clean except pre-existing, unrelated modified
  screenshots/recordings (`docs/analytical-workspaces-v1/screenshots/*`,
  `docs/atlas/investigation-collaboration/*`,
  `docs/clean-pattern-review-v1/reference-comparisons/*`,
  `docs/clean-pattern-review-v1/evidence/sql-join-*`) and untracked
  `.prism/*` scratch files from an unrelated prior Pattern Review task -
  none of this is mine to touch; preserved, not discarded.
- PR #18 open against `main` (unmodified at `c9472ca`); direct `git push`
  to `main` is blocked by this environment's own "Merge Without Review"
  permission gate - landing goes through the PR.
- A desktop instance the owner launched themselves (PID 23512 at last
  check, started 2026-10-10 19:17:54) may still be running, locking
  `app.exe` - check before any `tauri build`.

## Completed acceptance items

**Phase 1** (`phase-1-capability-and-plan.md`): capability table, reference
folder (`references/`, 6 images), implementation checklist, before
screenshots.

**Phase 2** (`phase-2-presentation-status.md`): mapping editor moved to the
centre panel; right panel holds only operation-wide settings; synchronized
step selection across all three panes; stale-preview invalidation; Atlas
character component (4 poses, 2 sizes); docked Atlas/Step-settings tab
switcher that preserves selection; real context chips + starter questions
on the existing `/api/v1/workspace-proposals` contract; a real new
colour-contrast regression found via direct axe scan and fixed. 123 web
tests passing (3 new). CI on PR #18: legacy-regression, phase-1-python,
phase-1-web, secret-scan all passed; phase-4-live-e2e pending/expected to
fail for a pre-existing, already-documented reason (see
`release-status.md`'s 2026-10-10 entry) unrelated to this work.

**Phase 3** (`phase-3-connected-workflow-status.md`): the minimum complete
workflow (select → ask → inspect → review → approve → inspect revision) is
real end-to-end. Multi-turn, revision-bound conversation state that
survives Atlas/Step-settings tab switches (both tabs now stay mounted,
hidden not unmounted); stale-revision marking per turn; the real
`clean_preview` (deterministic, same engine manual ops use) now rendered
distinctly from the model's own text; genuine request cancellation via
`AbortController`, proven via the request's own `AbortSignal`, not just a
hidden spinner; a bounded, honest ambiguity signal from real exception
counts. **Investigated and intentionally not built**: cross-reload
persistence (the only durable store, `ObjectKind.CLEANING_PLAN`, already
means "applied transformation," not "proposal"; a new ObjectKind is a
shared-schema change out of scope this pass) and true interactive
clarification (the richer primitive for this, `AtlasClarification`,
belongs to the separate, much larger Atlas investigation runtime -
wiring the docked Clean assistant onto it is real, separate integration
work, named not faked). Desktop extension (detachable Atlas, screen
viewing) not attempted, per the brief's own bounding. 125 web tests
passing (3 new this phase). No `apps/api` source changed this phase.

## Exact failed or unrun checks

- `phase-4-live-e2e` (CI): expected red, root cause documented, not this
  work's regression - stale UI-text assertions from commit `5f9f528`
  onward, 14 commits before this branch's starting point.
- `test:visual`/`test:e2e:live` locally: same pre-existing failures,
  investigated and attributed, not re-fixed (separate body of work).
- Desktop packaged-binary rebuild for Phase 2: blocked by the owner's open
  app instance holding `app.exe`; not yet done. Check if that window is
  closed before the next desktop build attempt.
- mypy: blocked by a pre-existing environment issue (anyio needs Python
  3.10+, repo pins 3.9) - unrelated, not fixed.
- Backend gates (pytest/ruff/boundaries/secrets/contracts): last run clean
  at Phase 1/2's start; not rerun since, since no Python source has changed
  yet. Must rerun once Phase 3 touches `apps/api`.

## Reference-image paths

`docs/clean-atlas-v1/references/01` through `06` (indexed in
`phase-1-capability-and-plan.md`'s table). `01`/`02` are the current Atlas
mascot direction; `03`'s layout still informs design but its mascot (the
cat) is superseded; `04` (detached assistant) is explicitly deferred
per the brief; `05` is the primary Clean layout reference; `06` is the
already-matched palette.

## Next concrete actions (Phase 4 — verify, land, open the release)

1. Full repository gates appropriate to changed code. Python gates
   (pytest/ruff/mypy/boundaries/secrets/contracts) have been idle since
   Phase 1's checkpoint - no `apps/api` source has changed in Phase 2 or 3,
   so rerunning them is a confirmation pass, not expected to surface
   anything new; still run them for real rather than assume.
2. Isolated SQLite/MySQL checks required by the project (`test:e2e:live`
   locally against an explicit isolated SQLite DB; CI's `phase-4-live-e2e`
   job against real MySQL). Both are expected to still show the
   pre-existing, already-documented failures from `release-status.md`'s
   2026-10-10 entry (stale UI-text assertions predating this branch) -
   confirm that's still the full extent of it, don't assume.
3. Desktop smoke test: rebuild `apps/desktop-shell` (check the owner's
   instance, PID noted above, isn't still holding `app.exe` locked first),
   launch, verify Clean's restructured panels and the Atlas dock render
   correctly in the real packaged app (not just the dev server, which is
   all Phases 2-3 verified against so far), close cleanly.
4. Restart proof: since this phase's own conversation state is
   intentionally in-memory only (see Phase 3's "Investigated, not built"),
   the "restart proof for persisted conversations and pending decisions"
   requirement should verify and honestly state *that* boundary - a
   restart clearing the Atlas conversation is the documented, correct
   behaviour here, not a bug to paper over.
5. Regression checks already exist for stale previews (Phase 2 test),
   duplicate application (pre-existing Clean apply-gate, unchanged), and
   cancellation (Phase 3 test) - confirm they still pass; don't re-derive
   from scratch.
6. One short recording of the real workflow: open PRISM → select a Clean
   step → open Atlas → ask why → inspect the real computed evidence →
   (the ambiguity signal, if the fixture has exceptions) → review → apply
   → inspect the new revision. Use a real dataset and, if available, a real
   local Ollama instance - if none is available in this environment, use
   the same honest "unavailable" path and say so, rather than mock the
   model response and present it as the real recording.
7. Landing: commit only intended files (the established pattern this whole
   effort has followed - preserve the pre-existing unrelated modified
   screenshots/`.prism/` scratch files, don't touch them). Push checkpoints
   throughout. A direct `git push` to `main` is blocked by this
   environment's "Merge Without Review" gate - land through PR #18 (or its
   current equivalent), not a workaround. Check CI at the exact resulting
   SHA. Tag only after mandatory checks pass - `phase-4-live-e2e`'s
   pre-existing failure is a real open question for whether "mandatory
   checks pass" is satisfied; if it's still red for the same pre-existing
   reason, name that explicitly rather than tag anyway or silently skip
   tagging.
8. Rebuild and open the packaged application being tested; report the
   executable path, build SHA, and remaining limitations - the same
   standard every phase in this effort has held to.
