# Atlas VNext token foundation

`packages/design-system/typescript/src/tokens.css` is the canonical value source. It defines semantic CSS custom properties for dark and light themes; `tokens.ts` exports typed `var(...)` references to those names. The web root loads the package stylesheet, and the specimen imports the typed references through `@prism/design-system/tokens`.

The scale follows the locked questionnaire decisions in `design-decisions.md`: one sans and one mono family, editorial display headings, tabular data, neutral surfaces and borders, and separate state colors for completed, blocked, running, and recorded. Analytical panels use a 2px radius, controls 4px, and overlays 8px. Borders use 1px hairlines, 2px emphasis, and a 3px focus outline.

Dark and light values are explicitly authored. Compact and standard analytical rows are 34px and 40px high. Related rows use an 8px gap, sections 16px. This keeps activity and evidence lists compact while preserving a larger interactive row for ordinary pointer and keyboard use.

The specimen route is `/design-tokens`. It renders both themes and displays color roles, type roles, spacing, radii, and density without changing any existing surface styling.

For the command center, the scale also includes a responsive hero role and a metric role so headline and score sizing stay separate from display and section text.
