# Atlas VNext design decisions

Source: `C:\Users\Admin\Documents\prism-context\prism-ui-ux-redesign.pdf`.
The PDF has 1,265 pages. Text extraction returned 1,720,101 characters and
found no pages with fewer than 20 non-whitespace characters. The entries below
are the 50 questionnaire answers that directly constrain the Atlas GUI, its
tokens, or what it shows by default. References use the PDF's locked Round and
Question labels; summaries preserve the selected answer's substance.

## Product identity and workspace

| Source | Locked decision | Implementation implication |
|---|---|---|
| R1 Q4 | PRISM should feel like professional analytics software, a scientific instrument, and a high-end power-user workspace. | Treat the command center as a working analytical surface with precise hierarchy and controls, not a promotional dashboard. |
| R1 Q5 | AI is a major part of PRISM's identity, without the usual neon-glass AI aesthetic. | Make Atlas visible through its actual work and state, not generic AI ornament. |
| R1 Q6 | Atlas is PRISM's operating intelligence layer, not merely a chatbot. | Present plan, execution, evidence, and actions as one workflow. |
| R1 Q7 | Atlas has persistent presence, command palette, contextual actions, inline intelligence, and a deeper expandable mode, without permanently taking workspace. | Keep Atlas easy to find while allowing the analytical canvas to retain space. |
| R1 Q8 | The default is serious and premium; cinematic moments are reserved for meaningful moments. | Keep ordinary command-center states restrained; larger visual emphasis needs a meaningful event. |
| R2 Q2 | Navigation uses a left rail, central analytical workspace, right contextual inspector, and Ctrl/Cmd+K command palette. | Keep the command center legible within the larger workspace hierarchy and avoid duplicating global navigation. |
| R2 Q3 | Panels should be resizable, collapsible, dockable, and saveable per project. | Preserve clear surface boundaries and compact controls compatible with future panel resizing. |
| R2 Q4 | The center remains tab/module-driven, with dedicated environments such as SQL, Visualize, Stats, Forecasting, ML, and AI. | Name Atlas functions as a focused analytical environment and use stable section labels. |
| R2 Q9 | The inspector adapts to selected datasets, columns, charts, queries, models, and findings, with properties, lineage, actions, warnings, and Atlas guidance. | Atlas context should follow selected analytical objects rather than show a fixed generic sidebar. |
| R2 Q10 | A persistent context bar communicates project, source, analysis, connection/execution state, unsaved changes, and quick switching. | Use explicit state labels and compact context indicators where the command center presents run context. |

## Visual language, density, and interaction

| Source | Locked decision | Implementation implication |
|---|---|---|
| R3 Q1 | Editorial precision is the base, with premium dark-tool depth and very selective spectrum moments. | Establish hierarchy with type, spacing, and neutral surfaces; reserve brand color for meaningful emphasis. |
| R3 Q2 | Chrome is neutral, status colors are semantic, charts carry richer palettes, and spectral effects are rare and meaningful. | Define separate semantic state and data colors; do not use chart colors as general decoration. |
| R3 Q3 | Typography combines editorial hierarchy, technical clarity, and tabular numerics, using one sans and one mono family. | Tokenize roles around one sans and one mono stack; enable tabular figures for counts and timings. |
| R3 Q4 | Analytical surfaces are sharp, controls have modest radii, and temporary overlays may be softer when tactility helps. | Use a small surface radius and reserve larger radii for actual overlays. |
| R3 Q5 | The selected answer asks for rich micro-interactions throughout PRISM. | This conflicts with the thesis's blanket rejection of decorative animation; see the conflict register below. |
| R3 Q6 | The selected answer asks for expressive hover behavior, cursor-aware effects, magnetic interactions, animated highlights, and previews. | This conflicts with the thesis's blanket rejection of decorative animation; the current pass's explicit no-decoration constraint still applies. |
| R3 Q7 | The selected answer combines context-sensitive cursor states with advanced behaviors such as chart inspection, drag feedback, magnetic targets, resize states, and subtle cursor-linked reactions. | Keep interaction feedback tied to a specific action and do not add cursor effects to the command center as ambient decoration. |
| R3 Q9 | Long analyses should show step progression, partial evidence, cancel/retry, and useful Atlas narration, without invented ETAs. | Use stable timeline rows and meaningful state tokens; never imply an unsupported time estimate. |
| R3 Q10 | Empty states should explain the surface, recommend next actions, offer sample/demo paths, and allow Atlas guidance. | Make empty command-center states instructional and specific to available actions. |
| R11 Q5 | Accessibility includes contrast modes, font scaling, reduced motion, sound controls, keyboard-first navigation, screen-reader support, and focus customization. | Tokens and components must remain legible under scaling and contrast changes; respect reduced-motion preferences. |
| R11 Q7 | Personalization includes intentionally curated dark/light themes, density, restrained accents, motion intensity, sound, and workspace presets. | Expose a shared semantic system that supports theme and density variants without changing interaction meaning. |
| R20 Q1 | Atlas is ambient rather than a permanent chat rail: compact persistent signature, command palette, contextual actions, inline intelligence, and expansion when needed. | Do not make chat the default command-center content; keep the persistent presence compact and task-led. |
| R20 Q2 | Atlas has a restrained geometric/spectral identity that compresses to an icon, expands into a state visualization, and responds to operational state without becoming a glowing orb. | State indicators should be recognizable and semantic, without glow effects. |
| R20 Q3 | A compact Execution Narrative shows intent, current/completed steps, tools/resources, evidence, verification, retries, and next action; full audit detail is expandable. | Put the concise run story first and keep detailed provenance inspectable on demand. |
| R20 Q4 | Atlas states use a restrained, consistent combination of geometry, motion, typography, sound, and semantic color. | Map state tokens to named states and provide non-color cues; only use motion where the state changes. |
| R20 Q5 | Attention is anchored to the affected object; prominence follows urgency and consequence, with routine insights queued quietly. | Keep secondary findings quiet and place high-value attention near the run or object it concerns. |
| R21 Q1 | Keyboard navigation is a global command system with contextual commands, chaining, fuzzy search, favorites, and object-aware actions. | Keep command-center controls keyboard reachable and avoid mouse-only actions. |
| R21 Q2 | Ctrl/Cmd+K is the universal command surface for navigation, objects, analyses, Atlas, and workflows. | Avoid competing shortcuts or command affordances inside this surface. |
| R21 Q4 | Navigation uses predictable focus zones and cross-pane keyboard movement while preserving spatial orientation. | Keep focus order stable across command-center sections and any expanded detail. |
| R22 Q1 | Density is adaptive, with global profiles and per-surface overrides for spacing, row heights, controls, labels, and inspector depth. | Use deliberate compact analytical rows and keep density adjustable independently of semantic hierarchy. |
| R22 Q2 | Dark and light themes are both intentionally designed, share semantic tokens and analytical grammar, and support system/project preferences. | Implement two designed themes from common semantic token names, not a mechanically inverted palette. |
| R22 Q3 | Typography uses one primary sans and one technical mono, with type roles, tabular numerics, analytical/editorial hierarchy, responsive sizing, and accessibility controls. | Provide named type roles and test large text without relying on arbitrary local font sizes. |
| R22 Q4 | Color uses neutral chrome, semantic status/risk/quality/evidence, accessible chart palettes, rare spectral identity, saturation budgets, contrast rules, and both theme equivalents. | Keep state colors distinct from brand accents, with tested light/dark values and restrained saturation. |
| R22 Q5 | Visual prominence follows analytical importance, active focus, evidence risk, and task context; secondary chrome recedes. | Use typography, spacing, and contrast to prioritize content rather than wrapping every item in a card. |
| R22 Q6 | Surface depth relies on spacing, tonal separation, hairline borders, and controlled elevation; decorative glassmorphism and glow-heavy cards are rejected as default UI. | Use flat neutral surfaces and borders; elevation only communicates layering or interaction. |
| R22 Q7 | Utility icons use a consistent base set; custom analytical symbols need governed stroke, size, motion, and accessible labels. | Avoid emoji or unlabeled decoration; use established icon components and accessible names. |
| R22 Q8 | Motion has tiers for feedback, navigation, workspace changes, analytical states, Atlas, and cinematic moments; intensity adapts, reduced motion is supported, and animation must not slow analysis. | The command center may use functional state transitions, but this pass adds no decorative animation. |
| R22 Q9 | Charts are recognizable by analytical rigor, uncertainty, evidence markers, typography, and interaction meaning, not decorative skin. | Keep chart palettes and chart presentation out of general command-center chrome. |
| R22 Q10 | PRISM's recurring motif is signal → separation → evidence, expressed sparingly through spectral traces, decomposition, precision markers, and evidence-link geometry. | If used later, motif elements must communicate a real transition or evidence relationship. |

## What Atlas shows by default

The locked answers favor a compact execution narrative: intent, current progress,
completed steps, tools/resources touched, evidence, verification, failures or
retries, and the next action. Detailed code, SQL, provenance, and the full
execution graph remain available through explicit inspection. Routine findings
stay quiet in context; high-value events may receive stronger attention at the
affected object. Ambiguity should remain visible as competing interpretations,
with evidence and a useful next test, rather than being silently collapsed.

## Conflicts and tensions with the working thesis

- **Motion:** the thesis says no decorative animation. The PDF answers R3 Q5–Q7
  request rich micro-interactions and expressive hover/cursor behavior. R22 Q8
  later requires tiers, reduced motion, and no animation that slows analytical
  work. The PDF therefore asks for more purposeful interaction feedback than
  the thesis summary. For this pass, the explicit implementation constraint
  forbidding decorative animation remains in force; functional state changes
  are the only motion considered.
- **Atlas presence:** the thesis calls Atlas contextual rather than a permanent
  centerpiece. R1 Q7 and R20 Q1 also require a compact persistent signature,
  alongside contextual and command-surface invocation. They reject a permanent
  space-hog chat rail, but the brief asks for more persistent visibility than a
  purely contextual assistant. The distinction is recorded here for Step 2b.

## Density decision for Step 2a

The command center is an analytical work surface, so the token foundation uses
a **34 px compact row** and a **40 px standard row**, with 8 px between related
rows and 16 px between sections. Compact rows make timelines and evidence lists
scannable without shrinking body text; standard rows preserve comfortable
pointer and keyboard targets. The scale can be overridden per surface as R22 Q1
requires. This is a starting policy, not a claim that every control should be
34 px high.

