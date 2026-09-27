# Atlas Step 2a baseline audit

## Scope observed

The current `origin/main` tree has `atlas-command-center.tsx` at 934 lines, `atlas-inspector-drawer.tsx` at 354, `atlas-workspace.tsx` at 352, `atlas-cortex-ledger.tsx` at 101, and `apps/web/app/prism.css` at 286. These differ from the counts in the task brief for the command center, workspace, and stylesheet.

Nine screenshots are at the required 1440x900 viewport under `step2-before/`: empty workspace, command-center loading/ready/error, workspace with a run, inspector drawer, and Cortex core/group/node selection. The live capture used a new isolated SQLite database at `.prism/runtime/step2-before.sqlite`.

## Baseline styling inventory

Measured across the four Atlas components named in the brief plus `apps/web/app/prism.css`:

| Literal class | Count | Method |
|---|---:|---|
| Color literal occurrences | 160 | Hex, rgb/rgba, hsl/hsla, and named color tokens in source text |
| Font-size declarations | 185 | `font-size` or `font` declarations |
| Font-size length tokens | 188 | Lengths within those declarations |
| Spacing declarations | 499 | Margin, padding, gap, inset, and side-specific declarations |
| Spacing length tokens | 542 | Lengths within those declarations |
| Radius declarations | 45 | `border-radius` declarations |
| Radius length tokens | 33 | Lengths within those declarations |

The counts are source-literal occurrences, not unique values. The repo's current `prism.css` contains 45 custom-property definitions and 808 `var(--...)` references. This disproves the brief's statement that the file has exactly one custom property. Most of those variables belong to the existing app-wide theme system.

`packages/design-system/typescript/src/tokens.ts` currently exports six color values, six spacing values, and two radii. The web app has no direct import/use of `tokens` or `focusRing`; its `prism.css` uses its own CSS variables. The design-system token layer is therefore defined but not consumed by this app.

## Naming observed

- `Immersive Cortex` remains in `atlas-workspace.tsx:211`, outside the one-surface implementation scope for this phase.
- No `ATLAS · CORTEX` label exists in the inspected source. The ledger currently uses `ATLAS · RUN RECORD`.
- `System Cortex` appears in the command center. It names the model lineage section, so it is not a stale reference to the removed 3D rendering.

## Design-decision conflicts

`design-decisions.md` records the relevant source-backed conflicts: R3Q5–Q7 request rich interaction and cursor hover feedback, while the thesis rejects decorative motion; R22Q8 asks for motion tiers so work remains fast; and R1Q7/R20Q1 ask for a compact persistent Atlas signature, while the thesis describes Atlas as contextual only. The questionnaire wins. Any motion should communicate state without slowing work; the visual pass should preserve a compact Atlas identity while avoiding a permanent decorative centerpiece.
