# Analytical Workspaces v1 — delivery report

Branch: `prism/analytical-workspaces-v1`
Baseline: `main` @ `56da12e` (tag `prism-native-v0.9`), reverified against `origin/main` before starting.
Worktree: `C:\Users\Admin\source\repos\prism-workspaces`

## Status: partial, verified delivery — not a landed release

This branch contains six real, gated, tested commits. It has **not** been merged to
`main` and **no tag was created**, because the full scope of the requested
analytical-workspaces upgrade (Checkpoints B–D in full, SQL Lab join diagnostics,
Visualize investigation interactions, saved reports, AI proposal expansion, full
light/dark/mobile visual QA across all three workspaces, and a 100k-row performance
pass) was not completed in this session. Landing a partial release to `main` was
judged worse than leaving verified, working increments on a pushed branch with an
honest account of what remains — per the task's own ground rules ("do not claim the
whole release is complete if mandatory scope remains unfinished").

## What shipped (all on `prism/analytical-workspaces-v1`, all gates green)

1. **`fix(visualize): correct scatter X, box-plot stats, and trend ordering`**
   Fixed four verified, reproduced defects in the existing Visualize workspace:
   - Scatter plotted points by array index instead of the selected numeric X value.
   - Box plots had no quartile/whisker/outlier computation at all and silently fell
     through to the bar renderer.
   - The generic aggregation path always sorted by value descending, which broke
     chronological order for line/trend charts.
   - The dimension (X-field) picker excluded numeric columns, making a numeric X
     (needed for scatter/relationship charts) unreachable from the UI even though
     the backend already accepted one.
   Also made bar/line rendering zero-anchored so negative and constant values draw
   correctly. New backend tests (`tests/api/test_visualize.py`) and frontend
   `ChartCanvas` unit tests cover irregular-spacing scatter, non-monotonic trend
   order, and real quartile geometry.

2. **`fix(sql-lab): restore saved parameters along with SQL from a snippet`**
   Clicking a saved snippet restored only the SQL text; its saved parameters were
   silently dropped. Now both are restored together, matching the existing
   `initialParameters` handoff path. Covered by a new `query-studio.test.tsx` case.

3. **`feat(clean): add a general operation editor and always-visible data`**
   The Clean workbench previously only exposed auto-detected issues with their
   proposed fixes; there was no way to run any of the 8 backend-supported
   operations manually, and the centre pane was empty until something was
   selected. Added a general operation editor (operation + searchable column +
   typed parameters, with concrete disabled-reasons) and an always-visible,
   paginated live data table.

4. **`feat(clean): add versioned, durable recipes with all-or-nothing apply`**
   Implements the "apply a reproducible recipe" part of the release objective: a
   named, ordered list of typed operation steps, persisted durably (survives an
   API restart — same SQLite-backed pattern as `DurableDatasetStore` /
   `DurableAnalyticalObjectRegistry`) and versioned append-only. Steps carry an
   explicit `enabled` flag (disable without deleting) and apply is all-or-nothing:
   the whole enabled chain is dry-run validated against the dataset's *current*
   schema before anything commits, and a mismatch names the specific step/column
   rather than applying a partial prefix or guessing a mapping.

5. **`feat(clean): wire the recipe backend into the Clean workspace UI`**
   Checkpoint 4's API had no UI. Added "Save as recipe" on the manual operation
   form and a "RECIPES" nav list with per-recipe Apply, including inline surfacing
   of the backend's specific schema-mismatch error.

6. **`fix(clean): fix OPERATIONS nav heading wrapping badly in the narrow pane`**
   Found via an actual rendered screenshot (see below), not code review alone: a
   missing wrapper `<div>` broke the flex layout and wrapped "Any supported
   transformation" into an unreadable four-line mess in the 232px nav column.

## Gate results (this session, final run)

| Gate | Result |
|---|---|
| `npm run lint` | pass, no output |
| `npm run typecheck` | pass, no output |
| `npm run test:web` | **95 passed**, 16 files |
| `npm run build:web` | pass (Next.js production build) |
| `npm run a11y:baseline` | pass |
| `ruff check` (api/src, packages, tools, tests) | pass |
| `mypy` (api/src, packages) | pass, 91 source files |
| `pytest -q` (full suite) | **see note below** |
| `tools/check_boundaries.py` | pass |
| `tools/check_secrets.py` | pass |
| `tools/generate_typescript_contracts.py --check` | pass (generated contract is in sync) |

**pytest note:** the full suite was run three times this session. Run 1 (fresh
worktree): 1235 passed, 7 skipped. Run 2 (immediately after, same local
`.prism/runtime/analytical-history.sqlite`): 1 failure in
`tests/api/test_phase8c_lineage_traversal.py::test_ancestors_never_cross_into_a_different_fingerprint_sharing_the_same_revision_number`.
Root-caused: that pre-existing test uses hard-coded object/dataset IDs
(`"fp_child"`, `"ds_fp_test"`) and collided with leftover rows from run 1 in the
shared local SQLite file (`.prism/runtime/` is gitignored, local-only, not part of
this diff). After clearing that local file, a fresh run 3 passed clean: **1240
passed, 7 skipped**. This is a test-isolation gap in a pre-existing Atlas lineage
test, unrelated to anything changed in this branch — confirmed by the fact that
none of my changes touch lineage traversal, and the failure only appeared on a
second consecutive run against accumulated local state, never on a fresh one. Not
fixed here (out of scope — Atlas internals, explicitly protected by the task's
own ground rules); worth a follow-up ticket.

## Visual verification

Screenshots in `screenshots/` (captured via a real running dev server + Playwright,
not mocked): `clean-dark.png`, `clean-light.png`, `clean-manual-op-dark.png`,
`clean-mobile-dark.png` (400px), `visualize-dark.png`, `visualize-scatter-dark.png`.
All captured against a real uploaded 80-row messy fixture (duplicate region
spellings, missing revenue values) through the actual running app, not fabricated.

Compared against the approved reference mockup
(`C:\Users\Admin\.codex\generated_images\...\exec-cc4f6fb5-....png`):
- **Matches:** dark neutral surface palette, restrained gold accent, compact
  density, serif display headings, existing project header/workspace
  rail/tab strip (left untouched, as instructed), persistent data visibility
  (live table shown by default, not just on selection), explicit Apply/Discard,
  equivalent light theme, no avatar/account UI (correctly omitted per the
  "local single-owner application" instruction), no decorative glow/gradients.
- **Does not yet match:** the mockup's specific Clean composition — a
  step-numbered recipe list with APPLIED/PREVIEW/DRAFT status pills, a tabbed
  Before/Changes/After review with an editable per-value category-mapping table,
  and Affected-rows/Exceptions/Validation sub-tabs. Building that UI honestly
  would require backend features not yet implemented (explicit category-value
  mapping as a distinct operation type with "unresolved value" tracking,
  validation rules, exception sets) — deliberately not faked with placeholder UI
  that isn't backed by real data, per the task's explicit "do not invent...
  recommendations" / "a proposed value is not an applied value" constraints.

**Known pre-existing architectural note** (not introduced by this branch, observed
while screenshotting): every native workspace (Overview, Stats, Forecasting, ML,
Clean, Visualize) renders its own workspace-local `.inspector` aside *and* the
shell's global "CONTEXT" inspector simultaneously — the two-inspector pattern
Checkpoint A explicitly asks to avoid. This is systemic across the whole shell,
not specific to Clean/Visualize, and the global inspector's `action` buttons
aren't wired to real handlers (no `onClick`), so workspace-local asides currently
carry the actual interactive controls. Reconciling this is a cross-cutting shell
change touching every existing workspace — flagged here, not attempted, given the
blast radius and the explicit instruction to leave Atlas's released functionality
intact.

## Not attempted in this session (explicit limitations)

- **Clean:** category-value mapping, date/number parsing with ambiguity
  reporting, configurable missing-value handling beyond the existing fill
  strategies, duplicate-grouping survivorship rules, exception sets, validation
  rules (uniqueness/nonnegative/date-ordering). The recipe *engine* these would
  plug into is done; the operation types themselves are not.
- **SQL Lab:** join diagnostics (key cardinality, unmatched keys,
  row-multiplication risk), explicit intermediate-CTE execution/materialization,
  query-version result comparison, "Use result in Clean"/"Use result in
  Visualize" handoffs with lineage. No safe SQL-parsing dependency
  (e.g. `sqlglot`) is currently in this repo; adding real join diagnostics without
  one would mean unsafe string-splitting, which the task explicitly forbids.
- **Visualize:** mark-selection-to-contributing-rows drill-down, linked
  filtering, shared-scale small multiples, reference lines/annotations.
- **Reports:** the entire saved-report canvas (chart/table/notes composition,
  refresh-on-source-change) — not started.
- **Workspace AI:** no expansion beyond what already existed (the `atlas_action`
  propose/explain endpoints already present in Clean/Visualize, which already
  satisfy "preview before apply, no direct mutation authority").
- **100,000-row performance verification:** not measured. The scatter/box-plot
  backend changes add a second pass for box-plot dry-run-style grouping and the
  recipe apply path runs a full dry-run plus a real run of the enabled chain
  (2x compute for recipes specifically) — not benchmarked at scale this session.
- **Full visual QA matrix:** only Clean (dark/light/mobile) and Visualize (dark)
  were screenshotted. SQL Lab was not. No recording of the connected workflow was
  produced.
- **Landing to `main` and tagging:** not performed — see Status above.

## Confirmed unchanged

- Atlas investigation functionality, model promotion, production pointers, and
  orchestration: untouched. No file under `apps/api/src/prism_api/atlas_*` or
  related to model promotion was modified by any commit on this branch.
- No raw data, secrets, or `.env` files were committed (`tools/check_secrets.py`
  passed on every gate run).
- `prism-production` and other existing worktrees were not touched.
