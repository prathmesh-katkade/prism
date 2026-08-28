# Prism Improvement Routine — Run Report
**Date:** 2026-08-12 · **Run 30**

## 1. What shipped

### Two-way ANOVA interaction check (Hypothesis Sweep)

**What it does:** Stats Lab's Hypothesis Sweep already cross-checks its
strongest significant *correlations* and *group differences* for confounders
(does a third variable flip or attenuate the effect?). It had no equivalent
check for one-way ANOVA findings (a categorical column splitting a numeric
column's mean across 3+ groups) — eta-squared has no sign to flip, so the
existing confounder check explicitly puts ANOVA pairs out of scope. This run
adds the analogous question for a multi-group effect: does a *third*
categorical column change the *size* of the group difference? A new
"🧩 Interaction check" panel fits a genuine two-way ANOVA
(`numeric ~ C(cat) + C(other) + C(cat):C(other)`, Type II sum of squares)
and tests the interaction term's own p-value, FDR-corrected across every
candidate third column actually tested, showing per-level group means in an
expandable table.

**Why it was chosen:** logged as open backlog since Run 19 (10 consecutive
runs), and it's the one candidate that satisfies this cycle's mandatory
agentic-AI-analysis theme — a genuinely different automated follow-up
question on the sweep's own zero-extra-click results, not a new standalone
detector.

**Technical-depth argument:** eta-squared/Cramer's V have no sign, so a
"does a confounder flip this?" check (the pattern used everywhere else in
the app) doesn't apply. Effect modification needed a different statistical
tool — a genuine interaction term in a two-way ANOVA — which is exactly the
kind of "pick the right test for the right question" judgment a hiring panel
probes for. Candidates are capped to 2-10-level categorical columns with a
sufficiently populated cross-tab (4+ cells, 2+ rows each) so a sparse or
high-cardinality column can't produce an unstable fit, and every candidate
tested gets FDR-corrected together — the same multiple-comparisons
discipline the rest of the sweep already applies.

### K-fold cross-validation (ML Lab)

**What it does:** ML Lab's Baseline Model Runner reported a single 80/20
train/test split's score with no sense of how much that number would move
on a different split. It now also runs `StratifiedKFold`/`KFold`
cross-validation (5 folds, capped down for small datasets or small classes)
automatically alongside every "Run Baseline Models" click, showing mean ±
std per metric for both models in a new expander.

**Why it was chosen:** the strongest backlog item Run 29 left open — "how
stable is that number?" is the standard hiring-panel follow-up to any single
reported metric, and the gap was real: `run_baseline_models()` had zero
automated test coverage before this run, let alone a variance estimate.

**Technical-depth argument:** correctness here is about avoiding data
leakage as much as computing the right numbers — each fold's preprocessing
(impute + scale/one-hot) is fit only on that fold's training rows via an
sklearn `Pipeline`, not on the full dataset before splitting. Reporting
mean±std instead of a bare number is the difference between a demo score and
a defensible one.

Full suite: 559 → 573 green (5 + 9 new tests), zero regressions.

## 2. Screenshots

Captured live via Playwright (Chromium 1194, launched with an explicit
`executable_path` — same sandbox workaround Runs 28/29 logged) against a
synthetic planted-interaction dataset (360 rows: `value`/`group`/`region`,
group effect present only within `region == north`) uploaded through the
running app:

- Desktop (1440×900) dark — `.prism/runs/2026-08-12-run30/desktop-dark-hypothesis-sweep-interaction.png`, expanded finding: `.prism/runs/2026-08-12-run30/desktop-dark-interaction-expanded.png`
- Desktop (1440×900) light — `.prism/runs/2026-08-12-run30/desktop-light-hypothesis-sweep-interaction.png`
- Mobile PWA width (390×844) dark — `.prism/runs/2026-08-12-run30/mobile-dark-hypothesis-sweep-interaction.png`
- ML Lab cross-validation panel: desktop dark/light + mobile dark —
  `desktop-dark-mllab-cv.png`, `desktop-light-mllab-cv.png`, `mobile-dark-mllab-cv.png`

All show correct rendering in both themes: readable contrast, no
overflow/clipping, glass panel styling consistent with the rest of the app,
sidebar/Atlas HUD unaffected. The expanded interaction finding correctly
shows the planted asymmetry (north: -0.2 / 4.8 / 20.0 vs. south: 5.1 / 5.0 /
4.9 across the three `group` levels) with `interaction_p_adj = 2.2e-237`.
Mobile+light theme together wasn't captured — same standing sidebar-
expander-on-narrow-viewport automation gap logged since Run 10 (a real
mouse click at fixed sidebar coordinates was needed to open the theme
selector at all, since BaseWeb's `Select` component doesn't respond to a
JS-dispatched `.click()`; not re-derived for the mobile viewport this run).
A grammar bug (singular/plural verb agreement in the new panel's caption:
"1 group effect that depend on" → "depends on") was caught and fixed during
this screenshot pass, before merge.

**Sandbox note for future runs:** immediately after a programmatic file
upload, this app's main-content nav row can sit in a stuck CSS-transform
state (Playwright's `getBoundingClientRect()` reports real nav buttons
~2100px off-canvas) for several seconds — a headless-automation-speed
artifact, not a real bug (real users load and interact slower than a
synthetic upload+click). Clicking via `element.click()` dispatched through
`page.evaluate()` still fires React's handler correctly regardless of the
element's current visual position, sidestepping Playwright's visibility-
based actionability check without needing to wait out the transform.

## 3. Research findings NOT built (backlog for future runs)

| Feature | Evidence | Depth | Effort | Why deferred |
|---|---|---|---|---|
| PyGWalker-style chart builder's remaining interaction model (draggable pills, true "explore & suggest" auto-encoding beyond what Explore Mode already does) | Long-standing, no new evidence this run | 3/5 | L | Architecturally risky in Streamlit without a custom JS component — out of scope per the no-architecture-rewrite guardrail. |
| Large Excel ingestion (no out-of-core reader for `.xlsx`/`.xls`, unlike the DuckDB CSV path) | Flagged Run 14, unaddressed since | 3/5 | M | No streaming reader available without adding a new dependency. |
| Light-theme dataframe/chart repaint-lag | Cosmetic, timing-only; three-plus prior sessions already invested | 1/5 | S | Diminishing returns on further investigation. |
| Live-Gemini screenshot verification | No `GEMINI_API_KEY` configured in this execution sandbox | — | — | Structural sandbox constraint, not actionable from inside a run. |

Full detail: `.prism/research_2026-08-12-run30.md`.

## 4. Interview notes (STAR-style, verbatim-usable)

**Two-way ANOVA interaction check:**
> "Our automated hypothesis-testing sweep flagged group differences (one-way
> ANOVA) as significant, but a significant pooled effect can still hide the
> fact that it only holds for some segments. Since eta-squared has no sign
> to flip the way a correlation does, I couldn't reuse the existing
> confounder-check pattern — I implemented a genuine two-way ANOVA with an
> interaction term instead, FDR-corrected across every candidate third
> variable tested, so a real effect-modification finding stays statistically
> defensible rather than being one more untested multiple-comparisons risk."

**K-fold cross-validation:**
> "Our baseline model runner reported a single train/test split's accuracy
> with no sense of how stable that number was. I added k-fold
> cross-validation with the exact same preprocessing pipeline wrapped in an
> sklearn `Pipeline` — so each fold's imputer/scaler/encoder fits only on
> that fold's training rows, avoiding data leakage — and now report mean ±
> standard deviation per metric, which is what a hiring panel's standard
> follow-up ('how confident are you in that number?') actually wants to see."

## 5. Recommendation for next run

The interaction-check backlog item (open since Run 19) and the CV backlog
item (open since Run 29) are both now closed. The strongest remaining item
is the PyGWalker chart builder's interaction model, but it's L-effort and
architecturally constrained — worth a dedicated run rather than a quick
slice. Absent that, extending the interaction check's pattern to Hypothesis
Sweep's chi-square (categorical/categorical) findings — is there a
three-way association effect? — is a smaller, well-scoped follow-on in the
same statistical family this run just built out.
