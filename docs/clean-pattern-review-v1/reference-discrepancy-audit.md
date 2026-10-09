# Reference discrepancy audit — 2026-10-08, second pass (read first)

Capture SHA: `5be551bd80e3db26b446cdd6bdad0a2e2601d978` plus uncommitted
Phase-3-review fixes on `prism/clean-pattern-review-v1` (ownership
enforcement, progress monotonicity, stale-revision rejection, Visualize bar
thickness/margins, a real stale-subtitle bug fix - see below). Viewport
1586×992 (the references' own size), dark and light, plus 400×844 narrow.
Fixture: the same 8-row `reference-customers.csv` this audit has used
throughout (`tools/capture_pattern_reference_audit.mjs`), captured against a
disposable local dev server (not the stable or preview app, no user data
touched). Comparisons regenerated with
`tools/build_pattern_reference_comparisons.py`; raw images in
`reference-comparisons/*-side-by-side.png`.

**This pass's functional finding, not merely cosmetic:** inspecting the
Visualize side-by-side surfaced a real bug, not just a styling gap - the
chart's descriptive subtitle (the "Distribution question → ... chart of
..." line) was frozen at whatever the initial auto-suggestion computed and
never updated again, even after the user changed mark/category/measure via
the inspector. The chart itself re-rendered correctly; only the sentence
describing it went stale, so a user who switched from a suggested histogram
to a horizontal bar of revenue-by-region would keep seeing "Distribution
question → histogram chart of revenue." under a chart that no longer
matched that description. Fixed by deriving the subtitle from the live spec
on every render (`describeSpec` in `visualize-workspace.tsx`), mirroring
the backend's own rationale formula exactly, instead of freezing the
server's one-time suggestion string. Reproduced before the fix and
confirmed corrected after it, with console-logged before/after text in this
session's verification (not just a visual glance).

**Still-open, named visual discrepancies found this pass (not fixed, not
claimed as acceptable):**
- Visualize: no "Sort by" control exists in Chart settings, unlike the
  reference; the reference's gold-highlighted bar is explicitly the
  "sorted-first" (largest) category, which the current implementation can
  only coincidentally match depending on data order, not by an actual sort
  setting. No inline filter-chip row above the chart matching the
  reference's "Region: All ×  [+ Add filter]" pattern - filtering exists
  but only via the right-panel "Server filters" field/equals form, a
  different interaction pattern than the reference. The settings panel has
  extra controls the reference doesn't show (Small multiples by, X/Y axis
  label, Unit) and is missing "Axis starts at" and a currency-specific
  control (a generic "Unit" field stands in for it).
- Clean: the reference's top progress stepper (1 Clean → 2 Query →
  3 Visualize → 4 Report) has no equivalent in the current shell. This is
  believed to be an intentional difference, not an oversight - an earlier
  instruction in this same effort states Clean→SQL→Visualize→Report are
  optional handoffs, not a compulsory wizard, and a numbered stepper
  strongly implies the latter. Recorded here as a deliberate, explained
  deviation rather than a silently-dropped reference element.
- Clean: this pass's capture shows a genuinely-built 1-step draft recipe
  (`DRAFT RECIPE · 1 STEP(S)`, built via the real "+ New manual operation"
  → "Preview" → "Add step to draft" flow, not a fabricated entry) plus a
  second operation under active review in the center panel. This is closer
  to the reference's populated 4-step hierarchy than earlier captures (which
  showed only one operation with no draft list at all) but is still short
  of a 4-step, mixed-status (Applied/Preview/Draft) hierarchy. The
  underlying UI genuinely supports numbered badges with Applied/Preview/
  Draft/Disabled status pills (confirmed directly, not assumed) - building a
  capture fixture that exercises all four states remains open, not done.
- SQL Lab and Clean typography/control density: unchanged from the prior
  pass's findings below - still smaller/denser than the references.

None of the above are content fabrications. They are named, open items.

# Reference discrepancy audit — 2026-10-07

Starting feature SHA: `19ddfb3e22a9a552d73e2c9f80ed23638b5f8807`.
Remote feature SHA was identical after fetch; `origin/main` was `e5903c85b9ce733488dc0970e3318df124757cb5`.
The feature worktree contained regenerated screenshot and performance files, a Next-generated type file, and an unrelated untracked Atlas recording. These were preserved.

References: `references/clean-approved.png`, `references/sql-lab-concept.png`, `references/visualize-concept.png`. Each is 1586 × 992 pixels. Illustrative values in the references are not acceptance data.

This initial audit compares the supplied images with the current repository screenshots (`docs/analytical-workspaces-v1/screenshots/*-dark-1440.png`) and the live component structure at the starting SHA. The repository screenshots are 1440 × 900 and therefore are **not** pixel matched captures. A live 1586 × 992 comparison remains required before visual acceptance.

| Surface | Reference | Current discrepancy | Required correction |
|---|---|---|---|
| Shell | 180px navigation, 43px top bar, 43px workspace tabs; content begins immediately below tabs | 238px navigation, 56px top bar, 44px tabs; workspaces sit inside up to 56px padding | Scope a compact shell to Clean, SQL Lab, Visualize and Reports without changing Atlas. |
| Typography | Compact sans headings, approximately 14px body, clear muted labels | Oversized serif headings and tiny monospace labels dominate | Use the shared design tokens for compact hierarchy and readable controls. |
| Clean geometry | Recipe about 23% of remaining width, centre about 48%, inspector about 20%; full-height panels | 200px/auto/260px grid is inset; at 1440px it collapses to one column | Keep three panes at reference and 1440 desktop widths; stack near narrow width. |
| Clean recipe | Numbered steps dominate, each with Applied/Preview/Draft state; issues and suggestions are secondary | Draft or preview list appears only when present; saved-recipe and issues sections are equally prominent | Show a truthful active recipe hierarchy, accessible steps and relevant suggestions. |
| Clean review | Mapping table, quantitative summary, readable affected rows, sticky Apply/Discard footer | Generic affected-row diff with raw JSON cells; Apply/Discard inside inspector | Add operation-specific mapping review and structured row cells, keep one-use server flow. |
| SQL geometry | Source/schema/saved queries left, large editor/results centre, Join evidence right, all above fold | Hero and toolbar consume most first viewport; schema/editor appear lower, results lower still; no right join pane | Recompose into three simultaneous panes while preserving all existing actions. |
| SQL evidence | Keys, cardinality, matched/unmatched, grain, result handoff | Join diagnostics are a result tab and require an explicit action | Surface contextual join evidence at right with unknown/unsupported state when necessary. |
| Visualize geometry | Fields and saved views left, chart and contributing rows centre, settings right | Chart is small and inset; field controls and inspector are sparse; at 1440px panes stack | Give the chart a dominant pane and keep settings visible at desktop sizes. |
| Visualize chart | Horizontal bars, legible axis labels, selection-linked rows | Current chart offers vertical bars, lines, scatter and box; horizontal bars are absent | Implement a bounded horizontal bar mark or keep an explicit residual discrepancy. |
| Reports | No approved reference | Existing two-pane screen has the earlier serif/card treatment | Apply the shared system without asserting pixel equivalence. |
| Pattern Review | No dedicated reference; must fit Clean | Pattern panel exists and has discovery, families, decisions and extraction, but retains current Clean layout and only bounded example rows | Preserve semantics; audit pagination and exception identities in the live workflow. |

Visual acceptance is **open**. No pixel-match claim is made from this audit.

## Current correction note

The later CSS and UI pass removed the duplicate Clean inspector Apply/Discard
controls; the review footer now owns those actions. The typed manual editor
now occupies the inspector and the active unsaved preview appears as a
numbered Preview step in the left recipe. The validation-rule editor is
collapsed until requested, leaving the Pattern section visible sooner.
Pattern exceptions have source-bound, bounded paging and aligned row/value
pairs. Captures now include dark/light desktop and 400 × 844 narrow views for
Clean, SQL Lab, Visualize, Reports, and Pattern Review. These are in
`reference-comparisons/`. The three reference/current side-by-side images
were regenerated after the changes.

Remaining visual discrepancies: the reference Clean recipe is a populated
four-step hierarchy while the deterministic mapping fixture has one unsaved
reviewed step (saved recipes now show their numbered steps); SQL's toolbar
and result actions are denser than the reference; Visualize's
bars and axis typography remain smaller than pictured; saved-view composition
is still sparse. Reports has no approved image. Visual acceptance remains
open, so these captures are evidence of progress rather than a ditto claim.

## Live reference-size comparison after the first visual pass

The captures in `reference-comparisons/` use a deterministic eight-row customer
fixture uploaded through the browser to the isolated development API at
`http://127.0.0.1:8101`. Playwright set the viewport to the references' exact
1586 × 992 pixels. The side-by-side images preserve both source images
unaltered. The current captures are feature-preview evidence, not a release
claim.

| Workspace | Side-by-side | Current outcome and remaining discrepancy |
|---|---|---|
| Clean | [Compare](reference-comparisons/clean-side-by-side.png) | The full-width three-pane layout, mapping count strip, reviewed-value table, structured affected rows and always-reachable Apply/Discard footer now appear. The left pane still has only one preview step in this fixture; saved recipes now expose numbered steps. Typed parameters moved to the right inspector and its duplicate Apply control was removed after this comparison capture, so a fresh capture is required. Typography and tab/control dimensions remain smaller than the reference. |
| SQL Lab | [Compare](reference-comparisons/sql-lab-side-by-side.png) | Source/schema, editor/results, and join inspector now occupy simultaneous panes above the fold. This fixture has a single source, so the inspector truthfully shows an unknown state rather than fictional join counts. A separate [two-source join capture](evidence/sql-join-dark-1586x992.png) now shows actual join counts. The toolbar is still denser than the reference, the saved-query list is empty, and the result grid's type labels and action row are visually busy. |
| Visualize | [Compare](reference-comparisons/visualize-side-by-side.png) | The horizontal-bar mark is now a durable spec type with server aggregation and matching drilldown. The live capture uses source values as-is, so Bangalore variants remain separate. The canvas, field search, chart/data/small-multiple tabs, settings, and selected contributing row are visible. The chart still has wider margins and thinner bars than the reference; settings order, saved views, warning placement, units and date formatting need further alignment. |

The reference Clean image uses unreconciled illustrative totals. Its status
styling cannot justify auto-approval of ambiguous mappings. The SQL image
also illustrates a multi-source query that the eight-row single-source
fixture does not reproduce. These are content differences, not visual
acceptance exceptions.
