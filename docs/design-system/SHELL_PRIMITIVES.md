# PRISM shell primitives — Phase 2

The Phase 2 shell uses sharp analytical surfaces, a neutral chrome, one sans (`Inter` fallback
stack), one mono stack, and sparse spectral signal accents. Components consume semantic CSS
variables rather than per-feature colors.

## Primitives

| Primitive | Purpose | Accessibility boundary |
|---|---|---|
| Top bar | Project identity, theme, universal command entry | Skip link; labelled command dialog trigger |
| Navigation rail | Migration-aware workspace entry | `nav`, visible native/bridged/legacy labels |
| Workspace tab group | Durable activity context | ARIA tablist/tab/tabpanel relationship |
| Inspector | Object state and contextual actions | Named complementary landmark; actions disabled until implemented |
| Command surface | Global keyboard action discovery | Modal dialog, focus on search, Escape restores trigger |
| Atlas presence | Ambient assistant affordance | Expandable button; no permanent sidebar allocation |
| Split group | Later multi-view docking target | Explicit empty/drop state, saved layout boundary |

## State grammar

`enabled → native`, `shadow → bridged`, and `legacy → legacy`. The UI never presents a second
implementation while a workflow stays legacy. The migration bridge points to the reference path
and the parity gate only.

## Layout persistence

`prism.shell.layout.v1` holds visual preference only: theme, density, panel widths and visibility,
Atlas expansion, and split-view state. No data, credentials, analytical state, or migration state
is stored in the browser.
