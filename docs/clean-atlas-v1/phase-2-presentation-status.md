# Clean + Atlas presentation — Phase 2 status

Continues from `phase-1-capability-and-plan.md`. All source changes in
`apps/web/src/components/clean-workspace.tsx`, `clean-workspace.test.tsx`,
`prism-shell.tsx`, two new files (`atlas-character.tsx`, `atlas-dock-panel.tsx`),
and `apps/web/app/prism.css`. No files outside `apps/web` touched.

## Clean

| Requirement | Done | How |
|---|---|---|
| Mapping editing in the centre, operation-wide settings on the right | Yes | The value-chip selector, assign control and mapping summary moved from the right inspector into a new `.clean-centre-editor` block in the centre panel (rendered while building, before a preview exists); the right panel keeps only Operation/Column/simple fields, the always-visible Parameters switches, and the survivorship rule select - each with a one-line pointer to "the centre panel". Once a preview exists, the centre panel's pre-existing inline-editable review table (`updateMappingTarget`, unchanged) takes over - mapping editing stays in the centre either way. |
| Synchronized step selection across all three panes | Yes | `loadDraftStep` now calls `previewOperation(request)` after loading the step's fields, so selecting a step in the left list refreshes the centre panel's real preview for that exact step, not whatever a previously selected step left there. Regression test: `synchronizes step selection across panes…`. |
| Mark previews stale immediately after parameter changes; disable Apply until recomputed | Yes | A new `invalidateManualPreview()` clears `preview`/`pendingRequest` (and sets a `manualPreviewStale` flag) on every parameter change handler (operation, column, rename/convert/fill/case fields, category switches, mapping assign/remove, survivorship columns/rule/tiebreak). The apply bar only renders while `preview` is truthy, so it disappears the instant a parameter changes; the inspector shows "Preview is stale — recompute before applying." and the Preview button becomes "Recompute preview". Regression test: `marks a preview stale…`. |
| Counts derived from actual results | Already done | Carried over from the prior session's audit (exception-row vs. distinct-value relabelling); unchanged this phase. |
| Bounded resizing, scrolling, fixed actions, keyboard nav | Unchanged from Phase 1 | Still bounded/responsive via `clamp()`, not user-draggable - see Phase 1's capability table; not revisited this phase since nothing here regressed. |
| Light/dark + narrow layouts preserved | Yes | Re-verified at 1440×900 and 740px (narrow, single-column) after all changes - no new horizontal overflow, tab switcher and centre editor both render correctly narrow. Screenshots in `evidence/phase2/`. |

## Atlas

| Requirement | Done | How |
|---|---|---|
| One reusable character asset/component, small/large variants | Yes | `atlas-character.tsx` - a single SVG component (`AtlasCharacter`), `size="small" \| "large"`, stacked-card geometry matching reference #1/#2's data-tile direction. Fixed brand colours across both themes (same convention as the existing `.prism-mark` logo), not theme tokens. |
| Restrained poses for idle, working, presenting evidence, waiting for input | Yes | Four distinct `pose` values, each a small, deliberate geometry change (eye/brow/mouth shape, a held "evidence chip" for presenting, three small activity dots for working) - no pose exists without a real interaction state driving it. Screenshots of all four in `evidence/phase2/06-09`. |
| Respect reduced motion | Yes, via the existing site-wide rule | `prism.css` already has a blanket `@media (prefers-reduced-motion:reduce)` that zeroes all animation/transition durations; the character's `idle`/`working`/`waiting` keyframe animations fall under it automatically. No new per-component media query was needed or added. |
| Labelled launcher + docked assistant | Yes | The right inspector's top now has an "Atlas / Step settings" tab row (`.clean-inspector-tabs`), the Atlas tab itself carrying the small character as its icon (the "launcher"); selecting it renders the full `AtlasDockPanel` docked in the same pane. The pre-existing floating `.atlas-presence` bubble (shell-wide, all workspaces) is untouched. |
| Switch Atlas / Step settings without losing the selected step | Yes | The tab choice is separate UI state (`inspectorTab`); switching tabs never touches `editingStepIndex`/`manualMode`/form state. Regression test: `docks a real Atlas panel… switching to it never loses the selected step` asserts the Column field still reads the step's real value after a round trip through the Atlas tab. |
| Contextual chips + starter questions | Yes, on the real API | `AtlasDockPanel` shows real chips (dataset name, revision, the actual focused step/operation, the actual column) - no invented counts. Three starter questions pre-fill the same free-text intent the existing `/api/v1/workspace-proposals` endpoint already accepts (the same contract `WorkspaceProposalPanel` used elsewhere uses); no second, mocked endpoint was added. The character's pose in the dock reflects that request's real lifecycle (waiting → idle once text exists → working while in flight → presenting once a result returns). |

### A real accessibility regression found and fixed before it shipped

A direct axe-core scan (not just the repo's a11y-baseline snapshot, which
only tracks a fixed node count and would not have caught this) found two
*new* color-contrast violations from this phase's own additions: the new
tab buttons' unselected-state colour, and the new "select and map in the
centre panel" help text reused the existing `.clean-field-help` class. Both
used `--faint` (`#8C8575` in dark Palette A), the same token already flagged
as a contrast shortfall in this repo's CI run earlier today. Fixed by
switching both to `--muted` (`#B8B09F`), a lighter, already-used-elsewhere
token - re-scanned clean on both the Step-settings and Atlas tab views. Two
*pre-existing* violations (`.clean-current-mapping > .eyebrow`, the
`.good.health-pill` status pill, both untouched by this phase, used
throughout Clean since before this session) were left as-is, consistent with
not taking on unrelated, systemic a11y debt in this pass - see Phase 1's and
`release-status.md`'s own notes on scope discipline.

## Proof

Captured via the dev-server bundle (`npm run dev`, pointed at an isolated
API instance, port 8010, SQLite file `phase2-history.sqlite` - not the
production database) - **not** the packaged desktop binary. See "Desktop
rebuild blocked" below for why.

- `evidence/phase2/01-full-reference-3440x1369.png` - reference size (the
  owner's own reported ultrawide dimensions)
- `evidence/phase2/02-right-panel-3440.png` - right panel, Step settings tab
- `evidence/phase2/03-full-ordinary-1440x900.png` - ordinary laptop size
- `evidence/phase2/04-full-narrow-740.png` - narrow-layout check (740px,
  full page, single-column collapse, nav rail auto-collapsed)
- `evidence/phase2/05-atlas-tab-3440.png` - the Atlas tab itself
- `evidence/phase2/06–09-pose-*.png` - all four character poses, captured
  through real interaction (typing, submitting, awaiting a deliberately
  delayed mocked response, and the resolved result), not staged artwork

Measured, not assumed: `.clean-value-chips` confirmed to live inside
`.clean-preview` (centre) and not `.clean-inspector` (right) via DOM
containment check before any screenshot was taken; the stale-preview message
and the apply bar's disappearance were both confirmed via `page.evaluate`
element counts, not just visual inspection.

## Desktop rebuild blocked - named explicitly, not worked around

`npx tauri build --debug --no-bundle` was attempted from this exact tree and
failed: `error: failed to remove file ...\app.exe` / `Access is denied (os
error 5)`. Cause, confirmed rather than assumed: a Prism desktop instance
the owner had already launched (PID 23512, started 2026-10-10 19:17:54,
predating this phase) still holds `app.exe` open, and Windows will not let a
build overwrite a running executable. The foreground window at the time was
not Prism's, suggesting the owner was not actively interacting with it, but
it was still open, so it was left alone rather than closed without being
asked - closing another session's open window out from under it is exactly
the kind of action that needs a yes first, not an assumption. **The
packaged-binary screenshots and the production-build/startup/shutdown smoke
test for this phase's changes are the one piece of Phase 2 proof not yet
done** - everything else (gates, regression tests, dev-server visual
verification at all four sizes, the a11y fix) is real and complete. Once
that window is closed, the rebuild is a single command away.

## Remaining visual differences from the references (named explicitly, not implied clean)

- Reference #1/#5 show the detailed mapping table as inline editable
  dropdowns directly inside the same "Before/Changes/After" review table
  that also shows affected rows. The current build keeps the pre-preview
  chip-select-and-assign editor (`.clean-centre-editor`) as a visually
  distinct block above that table rather than merging them into one surface
  - functionally equivalent (both edit the same mapping, both live in the
    centre), but not pixel-identical to the reference's single unified
  table.
- The left panel still carries a `.clean-current-mapping` summary card
  (pre-existing, not part of this phase) that now partially duplicates
  information visible in the centre editor. Not a regression - it predates
  this phase - but it is a redundancy the references don't show, named here
  rather than left for someone else to notice first.
- Atlas's dock panel is a single-turn request/response (matching the real
  `/api/v1/workspace-proposals` contract), not the multi-turn threaded
  conversation reference #1/#2 depict - there is no multi-turn chat endpoint
  to build that against yet. Each "Ask Atlas" submission replaces the prior
  result rather than appending to a transcript.
- The character's stacked-card depth (three offset layers in the reference)
  renders correctly but reads as more subtle at the 28px "small"/tab-icon
  size than at 72px "large" - acceptable at both sizes on inspection, named
  because the reference's small-size variant has slightly more contrast
  between layers.
- No "Preview checks" scorecard (reference #1's "4/5 passed" panel) exists -
  that would require a real, as-yet-unbuilt checks/assertions backend behind
  it; building a static or fabricated version was explicitly out of scope
  ("their illustrative counts… are not proof that backend capabilities
  exist").

## Gates (this phase, full rerun after every source edit)

lint, typecheck, `test:web` (**123 passed**, 18 files, 0 failed - 3 new
tests in `clean-workspace.test.tsx` since Phase 1's checkpoint: stale-preview
invalidation, synchronized step selection, the Atlas dock), `build:web`,
`a11y:baseline`: all clean. A direct axe-core scan of
both inspector tabs (not just the baseline snapshot) found and fixed two new
contrast violations before this checkpoint, documented above. Backend gates
(pytest, ruff, mypy, boundaries, secrets, contracts) were not rerun this
phase since no Python source changed; Phase 1's `release-status.md` entry
has their last full-rerun results against this same branch.
