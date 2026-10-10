# Clean + Atlas presentation — Phase 1: implementation contract

Branch: `prism/clean-pattern-review-v1`. Starting commit for this phase: `729f6f5`
(PR #18 open against `main`, which remains unmodified at `c9472ca` — a direct
push to `main` is blocked by this environment's own permission gate; see
`release-status.md` for the full account). Desktop services were already
running when this phase began (a packaged `app.exe`/`prism-api.exe` pair the
owner had started themselves after the prior report) — not touched, not
restarted, to avoid interrupting a live session.

**This document is Phase 1 only: inspection, capability table, reference
index and implementation checklist. No Clean or Atlas implementation code
was changed in this phase.**

## Reference folder

`docs/clean-atlas-v1/references/`, copied read-only from
`C:\Users\Admin\.codex\generated_images\01a0d7b5-f591-7a11-8bb5-6e52554e0414\`:

| # | File | What it shows | Status |
|---|---|---|---|
| 1 | `01-data-tile-atlas-in-clean.png` | Data-tile Atlas docked inside Clean: compact top-bar launcher badge + full right-panel drawer with Atlas/Step-settings tabs, context chips, a chat thread, a preview-checks scorecard, and suggested next-step chips. | **Current mascot and docked-panel direction** |
| 2 | `02-atlas-character-interaction-study.png` | "Atlas — The Little Analyst": the data-tile character itself (small/large use), four interaction patterns — understand context, bring evidence forward, ask when meaning is unclear (disambiguation via radio choices, "Nothing applied" until decided), hand approved work back to PRISM (Inspect → Preview → Approval → Apply tracker). | **Current mascot + interaction patterns** |
| 3 | `03-cleaning-plan-review-concept-superseded-mascot.png` | A multi-step "plan review" screen: a 4-stage process rail (Inspect data → Draft recipe → Review decisions → Apply changes), per-step cards with Include toggles/why-this-step/example/affected-counts, a plan-wide ready/review/needs-input status bar, a "What will stay unchanged" summary, an "Ask Atlas" box with quick-action chips. | **Interaction layout still informs design; mascot (the cat) is superseded by #1/#2** |
| 4 | `04-detached-assistant-concept-deferred.png` | Atlas as a separate OS window observing shared app windows (PRISM + a spreadsheet), with Explain/Guide/Act modes, an explicit "Guide mode · no clicks or typing performed" disclosure, and a "window text may be incomplete" caveat. | **Explicitly deferred** — matches the brief's own "general desktop automation is deferred; screen viewing, detached-window support, voice and cloud support are conditional on verified infrastructure" instruction. Not attempted in Phase 1 or 2. |
| 5 | `05-clean-workspace-substantial-panels.png` | The target Clean layout without Atlas expanded: left recipe list, **centre panel carrying the category-mapping edit table itself** (inline "Proposed value" dropdown per source row), right panel holding only operation-wide settings/impact/review/handoffs, an explicit "Recompute preview" action with a "Preview is up to date with revision N" staleness line. | **Primary layout reference for Phase 2** |
| 6 | `06-approved-palette-a-charcoal-brass.png` | Palette swatch strip: Canvas `#141310`, Panel `#1C1A16`, Raised `#25221C`, Border `#423B2D`, Text `#EEE9DC`, Secondary `#B8B09F`, Brass/Action `#D6AE50`, Selected Row `#3B301A`, Success `#5A7F4E`, Warning `#B58B3C`, Error `#9C4B4B`. | **Already implemented and verified identical** in `apps/web/app/prism.css` and `packages/design-system/typescript/src/tokens.css` (confirmed by direct hex comparison — no palette work needed). |

All six carry a `DESIGN CONCEPT`/`DESIGN PREVIEW · ILLUSTRATIVE DATA` badge in
the image itself. Row counts, percentages, check scores and exception counts
in them (24,800 rows, 1,240 changed, 4/5 checks, etc.) are illustrative only
and are **not** read as proof that any specific backend computation already
exists at that precision — each capability below was checked against actual
source, not against the mockup's numbers.

**Mascot precedence, as instructed:** data-tile Atlas (#1, #2) is current.
The cat/"Miss Minutes"-era character in #3 is superseded for identity; #3's
*layout* (plan-wide review, Include toggles, status bar) still informs
Phase 2/3 design.

## Capability table

Checked against the actual current source and this morning's rebuilt desktop
binary, not assumed from the references.

### Clean

| Capability | State | Evidence |
|---|---|---|
| Three-pane layout (recipe / review / inspector), responsive, capped on ultrawide | **Working** | `prism.css` `.three-pane` grid; verified today at 1024/1600/3440px, no overflow, no exposed grid-gap colour (see `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/`). |
| Right-inspector hierarchy (identity → operation/params → impact → review → commit) | **Working** | Finished this session (commit `729f6f5`); real-browser-verified disclosure collapse, Impact-before-commit-button ordering. |
| Mapping editing kept in the centre, operation-wide settings on the right | **Missing** | Current build keeps detailed mapping editing (value chips, assign, summary) in a **right-panel** collapsible disclosure (`clean-workspace.tsx` ~L957). Reference #5 puts an editable "Proposed value" dropdown directly in the centre review table instead. These are two different interaction models — not yet reconciled. |
| Synchronized step selection across all three panes | **Partial** | Selecting a draft step in the left list (`loadDraftStep`) correctly loads that step's operation/params into the right inspector (verified by this session's and prior sessions' tests). It does **not** also re-trigger a centre-panel preview for that step — the centre panel keeps showing whatever `preview`/`pendingRequest` was last computed, which can be for a different step, until the user clicks Preview again. Confirmed by reading `loadDraftStep` (clean-workspace.tsx ~L348) — it sets form state only, never calls `previewOperation`. |
| Stale-preview invalidation (mark stale on parameter change, disable Apply until recomputed) | **Missing** | Every parameter `onChange` handler (`setManualOperation`, `setManualColumn`, `setCategoryCaseSensitive`, `setCategoryPreserveUnmatched`, `setManualTargetType`, `setManualFillStrategy`, `setManualCase`, …) is a plain state setter — none call `setPreview(null)`. A preview computed before a parameter edit stays displayed, and Apply stays enabled against it. Confirmed by grep across every one of these handlers; none clears `preview`. |
| Counts derived from actual results (not interchanging rows/distinct-values/exceptions) | **Working** | Audited and fixed this session: `exception_rows_total` was mislabelled "unresolved value(s)" (a distinct-value phrasing), relabelled to "exception row(s)"; `columnValues.total_distinct` and `preview.unresolved_values.length` (genuinely distinct-value counts) left as-is. |
| Bounded resizing, scrolling, fixed actions, keyboard nav | **Partial** | Column widths are bounded/responsive (`clamp()`), not catastrophic on ultrawide (fixed this session + earlier sessions); the apply bar is fixed and correctly aligned at every width (fixed this session, see footer/Atlas-drift fix). Panels are **not** user-draggable-resizable the way the generic shell's rail/inspector are (`ResizeHandle` exists for those, not for Clean's three-pane columns). Keyboard: real `<button>`/`<label>`/`<select>`/switch-role inputs throughout; not separately walked end-to-end this phase. |
| Light/dark theme | **Working** | `.theme-light`/`.theme-dark` token sets already defined identically in `prism.css` and the shared design-system tokens (prior-session work, reconfirmed present). |
| Usable narrow layout | **Working** (for Clean's own content) | `@container` single-column collapse exists for the three-pane (prior-session fix). Not re-verified against Atlas's docked-panel content this phase, since that panel doesn't exist yet. |
| "No report linked" / report association | **Honest, not actionable** | No `report_id`/association field exists anywhere in `clean-workspace.tsx`, its props, or the wider frontend (checked by grep this and a prior session). The static "No report linked." text is accurate, not a hardcoded lie over real data — but it's also not the actionable "Link a report" button shown in reference #6; that would need a real backend association endpoint, which doesn't exist. |

### Atlas (as a Clean-docked assistant matching references #1/#2)

| Capability | State | Evidence |
|---|---|---|
| A reusable Atlas character asset/component | **Missing** | No character/mascot asset exists anywhere in `apps/web/src` or `packages/design-system`. `find src -iname "*atlas*"` turns up only the **Atlas investigation workspace** (`atlas-workspace.tsx`, `atlas-investigation.tsx`, `atlas-inspector-drawer.tsx`, `atlas-cortex-ledger.tsx`, …) — a full page for inspecting an AI agent run's plan/council/evidence/memory. That is a different feature from a small docked assistant character and was not touched. |
| Launcher + docked assistant panel | **Partial, wrong shape** | `prism-shell.tsx` already renders an `.atlas-presence` floating pill ("Atlas · Watching workspace context") that expands to an `.atlas-drawer` — but that drawer is static marketing copy ("What should we investigate?" + a button to the full Atlas workspace), not a chat thread, not contextual to the current Clean step, and not tabbed against "Step settings". |
| Switch Atlas / Step settings without losing selected step | **Missing** | No such tab exists; the right inspector *is* "Step settings" today with no Atlas-tab sibling. |
| Idle / working / presenting-evidence / waiting-for-input poses, reduced motion | **Missing** | No character exists yet to pose. `prism.css` already has a `@media (prefers-reduced-motion: reduce)` pattern used elsewhere (e.g. Atlas investigation's pulse animations), so the convention to extend is established even though the asset isn't. |
| Contextual chips + starter questions | **Partial** | The existing `WorkspaceProposalPanel` (`workspace-proposal-panel.tsx`, already wired into Clean) is a real, working "ask a local model for a proposal" flow: free-text intent → `POST /api/v1/workspace-proposals` → an honest `ollama` vs. `provider unavailable` result, with evidence bullets and a "Review in workspace" handoff. It has no chips, no dataset/step context chips, no character, and is labelled "OPTIONAL LOCAL MODEL" rather than "Atlas" — but it is the real backend path Atlas's chat should drive, not a placeholder. |

### Explicitly out of scope this pass (per the brief)

Detached/floating assistant window, live screen-sharing/observation, voice
input, and cloud-model routing (reference #4) are not implemented and are
not planned for Phase 2 — the brief itself defers these pending verified
infrastructure, and nothing in the current codebase provides screen capture,
a second native window, or voice I/O to build on.

## Implementation checklist (Phase 2 scope, linked to screen + verification)

| # | Requirement | Screen | Verification |
|---|---|---|---|
| 1 | Move mapping editing to the centre panel's review table (inline proposed-value editing); right panel keeps only operation-wide settings | Clean → centre review panel, right inspector | Unit test asserting the value-chip/assign UI renders under `.clean-preview`, not `.clean-inspector`; visual match to reference #5 at 3440/1600/1024px |
| 2 | Synchronize step selection: selecting a step in the recipe list also refreshes the centre preview for that step | Clean → left recipe list → centre panel | New test: select step B while step A's preview is showing; assert centre panel now reflects step B (or an explicit "not yet previewed" state), not stale step-A data |
| 3 | Stale-preview invalidation: any parameter change after a preview exists clears/marks it stale and disables Apply until recomputed | Clean → right inspector | New test: preview an operation, change a parameter, assert Apply is disabled and a "stale, recompute" state is shown instead of the old impact numbers |
| 4 | Reusable Atlas character component, small/large variants, 4 states, reduced-motion respected | New `atlas-character.tsx` (or similar) + CSS | Component test rendering all 4 states; `prefers-reduced-motion` CSS guard present and tested the same way existing reduced-motion rules are |
| 5 | Labelled launcher + docked assistant panel (Atlas/Step-settings tabs) in Clean | `prism-shell.tsx` launcher, new Clean-scoped Atlas panel | Test: switching to the Atlas tab and back preserves `selectedStepId`/`editingStepIndex` |
| 6 | Contextual chips + starter questions wired to the real `WorkspaceProposalPanel`/`workspace-proposals` API (not a new mocked endpoint) | Atlas tab inside Clean | Test using the existing proposal-panel fetch contract; no fabricated proposal data |
| 7 | Comparable screenshots at reference size (3440×1369), ordinary laptop size, ultrawide, and a narrow-layout check | Desktop app | Section 3/4-style evidence capture, same methodology as `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/` |

Items 1–3 are Clean-only and independent of Atlas; items 4–6 are the new
Atlas surface. Item 7 is the Phase 2 checkpoint proof.

## Fresh "before" screenshots

Captured today (2026-10-10), from the actual packaged desktop build
(`apps/desktop-shell/src-tauri/target/debug/app.exe`, built from commit
`729f6f5`) and the identical dev-server bundle, **before** any Phase 2 work:

- `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/01-full-ultrawide-3440x1369.png`
- `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/02-left-panel-full.png`
- `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/03-right-panel-full-reordered.png`
- `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/04-full-ordinary-1600x900.png`
- `docs/clean-pattern-review-v1/evidence/2026-10-10-inspector-hierarchy/06-packaged-desktop-app-clean-workspace.png` (the real packaged app, not the dev server)

Not duplicated into this folder to avoid storing the same binaries twice;
referenced here as the Phase 1 baseline. No narrow-layout (≤780px) or
Atlas-panel screenshots exist yet, since neither a narrow pass nor the Atlas
panel itself has been built — these are named gaps for Phase 2's own proof
step, not silently skipped.

## Blockers identified now, per the checkpoint instruction

1. **Reference #5 contradicts this session's own just-shipped work**: mapping
   editing was deliberately placed in the right panel's collapsible
   disclosure a few hours ago (commit `729f6f5`), and reference #5 wants it
   in the centre table instead. Phase 2 will move it again rather than leave
   two inconsistent patterns live — flagging so this isn't read as thrash
   nobody decided on.
2. **No backend report-association endpoint** exists for the "Link a report"
   button in reference #6 — building that button without one would be
   exactly the "invented control" the brief warns against. Recommend Phase 2
   leaves "No report linked." as-is (honest) unless a real association
   endpoint is in scope.
3. **Direct `git push` to `main` is blocked** by this environment's own
   "Merge Without Review" permission gate (hit for real this session, not
   theoretical) — landing anything, including this phase's checkpoint, goes
   through a PR (#18 already open) rather than the fast-forward pattern
   prior sessions used.
4. **A desktop instance was already running** when this phase started,
   under what looks like the owner's own active use — Phase 1 did not
   restart it or capture new screenshots from it, to avoid interrupting a
   live session; Phase 2's proof screenshots will use a freshly, separately
   launched instance once that one is confirmed free.
