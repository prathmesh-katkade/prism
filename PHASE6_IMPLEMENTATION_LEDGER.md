# Phase 6 Implementation Ledger

Repository: `prathmesh-katkade/prism`
Branch: `claude/prism-phase-5-6-95ai73` (tracks `origin/phase-5-ai-analyst`)
Frontend: `apps/web` · Backend: `apps/api/src/prism_api`

Phase 6 objective: migrate **Clean** and **Visualize** from the Streamlit reference into native
vertical slices, integrated with Overview, SQL Lab, AI Analyst, Atlas, and provenance — not
recreated as generic forms or a generic chart gallery.

## Phase 6A — Clean

### What shipped

- `apps/api/src/prism_api/clean.py` — issue detection (reusing Overview's own deterministic
  profile), preview-before-apply, apply-as-new-revision, undo, and Atlas actions.
- `apps/api/src/prism_api/overview.py` — `DatasetStore` extended with `add_revision`/`revert`/
  `revisions`, additive to the existing API every other module already depends on.
- `apps/web/src/components/clean-workspace.tsx` — left/center/right layout (issue navigator +
  history / data & transformation preview / selected-issue inspector), per the spec's suggested
  Clean UX.
- Contracts: `CleanIssue`, `CleanOperation`, `CleanTransformationRequest`, `CleanTransformation`,
  `CleanPreviewResponse`, `CleanApplyResponse`, `CleanStateResponse`, `CleanUndoRequest`,
  `AtlasCleanAction/Request/Response` in `packages/api-contracts`.

### Legacy parity considered (from `modules/cleaning.py`, `modules/autocleaner.py`)

Preserved: null handling (mean/median/mode/constant/forward-fill), duplicate removal, column
drop/rename, type conversion, before/after comparison (as preview), transformation
history/undo. Not yet ported: datetime feature extraction, join, export-as-script, anomaly
exclusion as a first-class op (outliers are surfaced as an *issue* with no auto-fix — Clean
explicitly does not auto-remove outliers, matching the spec's "not every outlier is an error").
Text normalization (trim, case) and invalid-value/type-mismatch detection are native additions
scoped from the same legacy capability set.

### Transformation model

```
CleanTransformation
├── transformation_id
├── operation, column, parameters
├── affected_rows, affected_columns
├── source_revision → resulting_revision
├── source_fingerprint → resulting_fingerprint
├── reversible (always true — undo is a linear revision stack)
└── created_at
```

Nothing mutates in place: `/preview` runs the same operation on a throwaway copy; `/apply`
appends a revision via `DatasetStore.add_revision`. Overview, SQL Lab, and AI Analyst all resolve
a dataset by id through `overview.store`, so a Clean transformation is immediately visible
everywhere without those modules needing to know revisions exist — proven by an integration test
that cleans a dataset then queries it live through SQL Lab and reads the cleaned row count back
through Overview's profile.

### Clean + Atlas

Atlas can explain a detected issue, propose a fix (only when a safe deterministic one exists —
otherwise it says so rather than guessing), and compare before/after. It only ever returns a
`CleanTransformationRequest` for the UI to preview; it never calls `/apply` itself.

### Tests

`tests/api/test_clean.py` (8 tests): deterministic issue detection, preview-never-mutates,
apply-creates-revision-visible-to-Overview-and-SQL-Lab, unknown-column rejection, fill-missing
row accounting, undo-then-reapply revision correctness (no collision), transformation-history
accumulation with provenance, Atlas explain/propose without side effects.
`apps/web/src/components/clean-workspace.test.tsx` (2 tests) + a live Playwright/axe-core browser
scan in `apps/web/e2e/shell.spec.ts` covering the full upload → detect → preview → apply flow.

## Phase 6B — Visualize

### What shipped

- `apps/api/src/prism_api/visualize.py` — deterministic mark suggestion, server-side aggregation
  (bar/line/scatter/histogram), trust warnings, and Atlas actions.
- `apps/web/src/components/visualize-workspace.tsx` — left/center/right layout (fields / visual
  canvas / chart inspector), with a small dependency-free inline-SVG renderer.
- Contracts: `VisualizationSpec`, `VizMark`, `VizIntent`, `VizAggregation`,
  `VisualizationSuggestion`, `VisualizationDataResponse`, `AtlasVisualizeAction/Request/Response`.

### Visualization grammar

```
VisualizationSpec
├── mark (bar | line | scatter | histogram | box)
├── intent (comparison | distribution | relationship | composition | trend | ranking)
├── dimension, measure, aggregation
├── filters
└── max_categories
```

The spec is renderer-agnostic by construction: the current renderer is a small inline-SVG
component chosen deliberately over pulling in ECharts/Plotly/Vega-Lite, since this vertical
slice's charts (bar/line/scatter/histogram) don't yet need a full charting library's feature
surface, and every analytical decision (aggregation, category capping, sampling) already happens
server-side against the spec, not in the renderer. Swapping the renderer later does not touch
`visualize.py`'s analytical logic.

### Intent-first, deterministic suggestion

`/suggest` maps (intent, column semantic types) → mark deterministically: datetime dimension →
line/trend, two numeric columns → scatter/relationship, single numeric with no dimension →
histogram/distribution, categorical + measure → bar/comparison. The same inputs always produce
the same suggestion — verified by a test that calls `/suggest` twice and asserts identical output.

### Visualization trust

`/render` always aggregates server-side (the browser never receives raw rows) and returns
explicit warnings rather than silently misleading: category truncation when more than
`max_categories` groups exist (with the truncated count named), and a random-sample warning for
scatter plots to avoid overplotting. A relationship chart with the same column as both dimension
and measure is rejected rather than silently degenerating.

### Visualize + Atlas

`explain_chart` states what the chart shows and how it was aggregated (never why a pattern
exists — that's the stated uncertainty). `identify_anomaly` flags shown categories that deviate
from the mean. `propose_alternative` runs the same trust check `/render` already computes and
surfaces it as prose. Atlas never creates or renders a chart itself — the UI always calls
`/render` explicitly.

### Tests

`tests/api/test_visualize.py` (7 tests): deterministic suggestion, unknown-column rejection,
server-side aggregation (26 rows in → ≤26 points out, never one point per raw row), category-cap
truncation + warning, unknown-column-in-render rejection, scatter sampling, Atlas explain/trust
without mutating state.
`apps/web/src/components/visualize-workspace.test.tsx` (2 tests) + a live Playwright/axe-core
browser scan covering suggest → render → Atlas-explain.

## Cross-cutting

- Provenance: every Clean/Visualize response carries `OverviewProvenance` (source fingerprint,
  dataset revision, service version, computed-at) — the same provenance shape Overview/SQL Lab/AI
  Analyst already use, not a parallel format.
- Performance: no large dataset is ever sent to the browser. Clean previews return a 10-row
  sample; Visualize always aggregates server-side with an explicit category cap and scatter
  sampling. This reuses the same DuckDB/pandas server-side execution path SQL Lab already
  established rather than introducing a new one.
- Accessibility: both new workspaces were verified with a live Playwright + axe-core scan in this
  sandbox (0 violations), not just the deterministic `a11y:baseline` check — see
  `PHASE6_IMPLEMENTATION_LEDGER.md`'s test sections above for what that covered, and
  `RECOVERY_REPORT.md`/`PHASE5_FINAL_REPORT.md` for the sandbox's browser constraints (pinned
  Chromium build vs. `@playwright/test`'s expected headless-shell version) that this session
  worked around locally without committing a network-specific config change.
- Migration state: `clean` and `visualize` moved from `channel: legacy` to `channel: enabled` in
  both `apps/api/src/prism_api/migration.py` and `apps/web/src/state/shell-model.ts`. Two Phase
  5-era tests that asserted an exact enabled-workflow set were updated to include them (expected
  evolution, not a broken guardrail — Phase 6's explicit mandate is to promote these workflows).

## Test summary

Backend: `tests/api/test_clean.py` (8), `tests/api/test_visualize.py` (7) — all passing, part of
652 passed / 4 skipped for the full suite. Frontend: `clean-workspace.test.tsx` (2),
`visualize-workspace.test.tsx` (2), plus 2 new Playwright specs — all passing, part of 10 Vitest
tests total. Ruff, mypy (CI-matching invocation), dependency-boundary scan, secret scan, generated
TypeScript contract freshness: all clean.

## Definition of done

```
Clean:
  native workspace                   PASS
  legacy capability parity           PASS (documented gaps above, none blocking)
  reversible transformations         PASS
  preview/apply workflow             PASS
  provenance                         PASS
  Atlas integration                  PASS
  regression tests                   PASS (652 passed, 0 regressions vs. Phase 5's 637)
  performance                        PASS (server-side, sampled previews only)
  accessibility                      PASS (live axe-core scan, 0 violations in Clean's subtree)

Visualize:
  native visualization workspace     PASS
  visualization spec abstraction     PASS
  intent-first guidance              PASS (deterministic, not AI-guessed)
  interactive charts                 PASS (encoding controls, Atlas actions)
  provenance                         PASS
  Atlas integration                  PASS
  legacy parity                      PASS (capability-level, not pixel-level, as instructed)
  performance                        PASS (server-side aggregation, category cap, sampling)
  accessibility                      PASS (live axe-core scan, 0 violations in own subtree)
```

Two real, pre-existing accessibility/reliability gaps were found and filed as separate follow-up
tasks rather than fixed inline in this change, since neither belongs to Clean or Visualize:
`task_8c392fdd` (workspace tab ARIA structure, Phase 2) and `task_2fd6fb0f` (Monaco CDN
dependency, Phase 4).

Phase 7 is not started.
