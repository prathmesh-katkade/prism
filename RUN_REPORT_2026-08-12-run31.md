# Prism Improvement Routine — Run Report
**Date:** 2026-08-12 · **Run 31**

## 1. What shipped

### Association interaction check (Hypothesis Sweep)

**What it does:** Run 30 shipped a two-way ANOVA interaction check that asks
"does a significant group difference (numeric ~ categorical) actually hold
the same way for everyone, or does a third categorical column change its
size?" That check only applies when the outcome is numeric. Stats Lab's
Hypothesis Sweep also runs chi-square tests for categorical/categorical
pairs, and had no equivalent follow-up question for those. This run adds it:
for the sweep's significant chi-square findings, `cross_check_categorical_
interactions()` fits a log-linear (Poisson GLM) model over the full
`cat_a x cat_b x other_col` contingency table and runs a likelihood-ratio
test comparing the saturated model (with the three-way interaction term)
against the model with only two-way terms. A significant result means the
strength of the `cat_a`/`cat_b` association genuinely differs across levels
of a third categorical column — not just an additive shift in counts. New
"🔗 Association interaction check" panel in Stats Lab, directly below the
existing ANOVA interaction panel, showing per-level Cramer's V so the size
of the swing is visible, not just its p-value.

**Why it was chosen:** this was Run 30's own explicit recommendation —
"extend the interaction-check pattern to chi-square (categorical/
categorical) findings" — logged as the top backlog item precisely because
it's a smaller, well-scoped follow-on in the same statistical family Run 30
just built out. Satisfies this cycle's mandatory agentic-AI-analysis theme
as a genuinely new automated follow-up question fired on the sweep's own
results, not a new standalone detector.

**Technical-depth argument:** eta-squared and Cramer's V both lack a sign
to "flip" the way a correlation coefficient does, which is exactly why
Run 6's confounder-flip pattern doesn't generalize to either case. Run 30
solved this for the numeric-outcome case with a genuine ANOVA interaction
term; this run solves the analogous problem for two categorical variables
with the standard tool from categorical data analysis — a log-linear model
and a likelihood-ratio test on its three-way term — rather than forcing a
sign-based check onto a quantity that doesn't have one. That's the kind of
"pick the statistically correct tool for the question, not the tool that's
already lying around" judgment a hiring panel is specifically listening
for. FDR correction is applied across every third-column candidate tested,
same multiple-comparisons discipline as every other check in this module.

**Verified live** (not just unit-tested) against a synthetic 420-row planted
dataset: `cat_a`/`cat_b` are near-perfectly matched within `region == north`
(95% agreement) and independent within `region == south`. The panel
correctly reported `interaction_p_adj = 1.29e-30` and per-level Cramer's V
of **0.923 (north)** vs. **0.0 (south)** — the exact planted asymmetry,
end-to-end through the real Streamlit UI, not just the unit test fixture.

### Bundled fix: "Run All Detectors" never computed either interaction check

**What was wrong:** while wiring the new panel into `detector_runner.py`
(the "⚡ Run All Detectors" one-click entry point), a grep of every
`hypothesis_sweep_*` session-state key against every place it gets written
turned up a real gap: `run_all_detectors()` already computed the confounder
cross-check, but never called `cross_check_interactions()` (Run 30's ANOVA
check) or the new categorical one — so a user who used "Run All Detectors"
instead of clicking "Run Hypothesis Sweep" directly would see either an
empty panel or, worse, a stale result carried over from a previously loaded
dataset (`app.py`'s new-dataset reset block had the same omission for the
ANOVA interaction check since Run 30 — the categorical one is new this run
so it couldn't have been stale before now, but it needed the same reset
entry going forward).

**Fix:** both interaction checks are now computed inside
`run_all_detectors()` (same try/except-per-detector pattern the confounder
check already uses) and both session-state keys are cleared in the
new-dataset reset block alongside every other detector-result key.

**Why this matters for the demo:** a portfolio app where the one-click
"run everything" button silently produces a different (weaker) result than
clicking each tab manually is the kind of inconsistency a technical
interviewer notices immediately if they try both paths — this closes that
gap before anyone finds it live.

Full suite: 573 → 579 green (7 new tests for the interaction check, 2 new
assertions on the bundled fix), zero regressions.

## 2. Screenshots

Captured live via Playwright (Chromium 1194, explicit `executable_path` —
same sandbox workaround Runs 28-30 logged) against a synthetic dataset
planting both interaction signals at once (`value`/`group`/`region` for the
existing ANOVA check, `cat_a`/`cat_b`/`region` for the new one), uploaded
through the running app:

- Desktop (1440×1100) dark — `.prism/runs/2026-08-12-run31/01_desktop_dark_association_interaction.png`
- Desktop (1440×1100) light — `.prism/runs/2026-08-12-run31/02_desktop_light_association_interaction.png`
- Mobile PWA width (390×844) dark — `.prism/runs/2026-08-12-run31/03_mobile_dark_association_interaction.png`

All three show correct rendering: readable contrast in both themes, no
overflow/clipping on the expanded finding's Cramer's V table, glass panel
styling consistent with the rest of the app, sidebar/Atlas HUD unaffected.
The expanded finding correctly shows the planted asymmetry (Cramer's V:
north 0.923, south 0) with `interaction_p_adj = 1.292e-30`. Mobile+light
theme together wasn't captured — same standing sidebar-theme-selector
automation gap logged since Run 10 (a real mouse click at fixed sidebar
coordinates is needed; a JS-dispatched `.click()` doesn't open BaseWeb's
`Select` component). No live-Gemini screenshot this run either — 14th
consecutive run with no `GEMINI_API_KEY` configured in the execution
sandbox; this feature makes zero Gemini calls anyway, so that's not a
verification gap here specifically.

## 3. Research findings NOT built (backlog for future runs)

Reused Run 30's standing backlog and research rather than a fresh
four-source-class web sweep — same token-efficiency reasoning every run
since Run 9 has logged, and nothing in the app's structure changed enough
this run to warrant re-deriving it. See `.prism/research_2026-08-12-run30.md`
for the full table.

| Feature | Evidence | Depth | Effort | Why deferred |
|---|---|---|---|---|
| PyGWalker-style chart builder's remaining interaction model (draggable pills, true auto-suggested encodings) | Long-standing, no new evidence this run | 3/5 | L | Architecturally risky in Streamlit without a custom JS component — out of scope per the no-architecture-rewrite guardrail. |
| Light-theme dataframe/chart repaint-lag | Cosmetic, timing-only; several prior sessions already invested | 1/5 | S | Diminishing returns on further investigation. |
| Live-Gemini screenshot verification | No `GEMINI_API_KEY` configured in this execution sandbox | — | — | Structural sandbox constraint, not actionable from inside a run. |
| `google.genai` follow-up: unify `ai_analyst.get_model()`/`get_sql_model()`/`atlas._client()` into one client factory | Noted while reading `ai_analyst.py` this run — three separate construction sites for what should be one client, minor duplication, not a bug | 2/5 | S | Cosmetic refactor, not evidenced as broken; new candidate, not previously logged. |

## 4. Interview notes (STAR-style, verbatim-usable)

**Association interaction check:**
> "Our automated hypothesis sweep already flagged significant chi-square
> associations between categorical columns, but a pooled association can
> hide the fact that it only holds within certain segments. Cramer's V has
> no sign to flip the way a correlation does, so I couldn't reuse the
> confounder-check pattern — I fit a log-linear Poisson model over the full
> three-way contingency table instead and ran a likelihood-ratio test on
> the three-way interaction term, FDR-corrected across every candidate
> third variable tested. I verified it end-to-end on a planted dataset
> where two categories were 95%-matched in one segment and independent in
> another, and the model correctly recovered that exact asymmetry with a
> per-level Cramer's V of 0.92 vs. 0.0."

**"Run All Detectors" consistency fix:**
> "While wiring a new panel into the app's one-click 'run everything'
> entry point, I grepped every place a related piece of session state got
> read and written and found the one-click path silently skipped two
> analyses the manual per-tab buttons already ran — meaning the same
> dataset could show different results depending on which button a user
> clicked. I closed the gap and added test assertions so it can't silently
> regress again. Catching that kind of 'two paths through the same feature
> quietly disagree' bug before a demo, rather than during one, is exactly
> the kind of engineering discipline that doesn't show up in a screenshot
> but matters in production."

## 5. Recommendation for next run

The chi-square interaction-check backlog item Run 30 flagged is now closed,
and the "Run All Detectors" consistency gap it (accidentally) exposed is
fixed. The strongest remaining item is the PyGWalker chart builder's
interaction model — L-effort and architecturally constrained, worth a
dedicated run rather than another slice. Absent that, the new small
candidate found this run (unifying Gemini client construction across
`ai_analyst.py`/`atlas.py` into one factory) is a well-scoped S-effort
cleanup that could ride alongside any future feature pick.

## Process note

This run's trigger again asked for the full 8-phase loop to repeat "until
the session is 100% used" while also saying "don't use credits" / "use less
tokens" — the same contradiction every run since Run 10 has flagged and
resolved the same way: ran one complete, safely verified cycle (full test
suite green before and after merge, live Playwright screenshots reviewed,
fresh-boot HTTP 200 with no traceback, both `main` and the session branch
pushed) and stopped, per the hard guardrails, which take precedence over
the scheduling prompt's phrasing. An open-ended repeat of research/build/
verify against an already-thin backlog would be diminishing-returns
busywork, not token efficiency.
