# Prism Improvement Routine — Run Report, 2026-08-10 (Run 7)

Fifth independent same-day session of the Prism autonomous improvement
routine. `origin/main` was at Run 6's tip (`d7bb1d1`) with no drift; full
history of all six prior runs is in `.prism/routine_log.md`.

## What shipped

### Causal Effect Estimator (propensity score matching)

**What it does:** a new "🔬 Causal Effect Estimator" panel in Overview,
directly below the existing Confounder Check panel. The user picks a
binary treatment column (e.g. `ticker`), which value counts as "treated,"
a numeric outcome column, and covariates to adjust for. It then:

1. Fits a logistic-regression propensity model — P(treated | covariates).
2. Greedily matches each treated row to its nearest untreated row in
   propensity-logit space, within a caliper, without replacement.
3. Reports covariate balance (standardized mean difference) before and
   after matching — the check that matching actually worked.
4. Estimates the Average Treatment Effect on the Treated (ATT) as the
   mean outcome difference across matched pairs, with a bootstrap 95%
   confidence interval.

Verified live end-to-end via Playwright against the Stocks sample dataset
(`ticker` as treatment, `open` price as outcome): ATT = 0.477, 95% CI
[-0.829, 1.67], 172 of 200 treated units matched (86%), and it correctly
flagged a remaining-imbalance warning on the `volume` covariate rather
than presenting an untrustworthy number as clean.

**Why it was chosen:** it's the direct next question after Run 6's
Confounder/Simpson's-Paradox detector. That panel diagnoses "this
correlation might not be the real story"; this one answers "okay, then
what IS the real effect, once you correct for the confound." Same
diagnose-then-treat arc a senior analyst actually walks through, not two
unrelated features bolted together. It's also this cycle's required
agentic-AI-analysis pick — an automated causal-inference pipeline the
user doesn't need to know how to code themselves.

**Technical-depth argument (why this reads well in an interview):**
propensity score matching is a standard checkpoint question for causal-
inference maturity — "how do you know a correlation is causal" is a
common data-scientist interview probe, and "I ran a naive group
comparison" is the wrong answer. This feature is the textbook, auditable
version: every intermediate number (propensity scores, standardized mean
differences, which rows got matched to which) is inspectable, not a
black-box call to a causal-ML library. It also demonstrates statistical
honesty — the balance-check warning fires automatically when the match
quality doesn't support the estimate, instead of always returning a
confident-looking number.

**Small fix caught in Phase 5 (not shipped as a bug):** the panel's four
result values initially all sat in `st.metric` tiles; the 95% CI and
matched-pairs strings were long enough to truncate at 1440px width.
Caught in screenshot review before merge, fixed by moving the longer
values into a caption under two short metric tiles.

**Backlog item investigated and closed:** Run 6 left an open question
about dark canvas-row styling appearing on Overview's dataframe tables
under the light theme. Tested both the in-session theme-toggle path and
a genuine browser reload while light theme is active — the finding does
not reproduce; `sync_native_theme()` (shipped Run 4) works correctly.
Closed in the backlog.

## Screenshots

- `.prism/runs/2026-08-10-run7/01_causal_estimator_desktop_dark.png` —
  panel + column pickers, desktop dark
- `.prism/runs/2026-08-10-run7/02_causal_estimator_balance_narrate_dark.png` —
  full result: metrics, warning, balance table, graceful no-API-key
  narration fallback
- `.prism/runs/2026-08-10-run7/03_causal_estimator_desktop_light.png` —
  full result, Arctic (Light) theme
- `.prism/runs/2026-08-10-run7/04_causal_estimator_mobile_dark.png` —
  ~390px PWA viewport, no overflow/clipping
- `.prism/runs/2026-08-10-run7/05_light_theme_dataframes_check.png` —
  the closed backlog item, confirmed correct

## Research findings not built (ranked backlog for future runs)

| Feature | Depth | Effort | Notes |
|---|---|---|---|
| polars/DuckDB large-file path | 4 | L | Architecture-adjacent, seven consecutive runs now agree it needs a dedicated session rather than another deferral |
| CATE / uplift modeling (heterogeneous treatment effects) | 5 | L | Natural next step after this run's ATT estimator — "does the effect vary by subgroup" |
| PyGWalker-style drag-and-drop chart builder | 2 | L | Competitor-parity with Hex/Deepnote, lower technical depth |
| Live-Gemini screenshot verification | — | — | Seventh consecutive run with no API key in the sandbox; every narrate_* helper verified via unit tests + the graceful-fallback screenshot instead |

## Interview notes (STAR-style, verbatim-usable)

> **Situation:** Prism's automated correlation/confounder detector could
> tell a user a relationship might be confounded, but stopped short of
> quantifying the actual effect.
> **Task:** Build a causal-inference layer that estimates a real
> treatment effect instead of leaving the user with just a flagged
> correlation.
> **Action:** Implemented propensity score matching from scratch —
> logistic-regression propensity scores, greedy nearest-neighbor caliper
> matching, standardized-mean-difference balance checks before and after
> matching, and a bootstrap confidence interval — with every failure
> mode (non-binary treatment, too few units, zero matches, imbalanced
> covariates) surfaced explicitly instead of silently returning a
> misleading number.
> **Result:** Shipped with 23 passing tests, including a synthetic
> confounded-assignment fixture that proves the matched estimate is
> measurably closer to the true injected effect than a naive group-mean
> comparison — and verified the balance-check correctly flags real
> imbalance on a live dataset rather than just on synthetic data.

## Recommendation for next run

Two options, both defensible:
1. **polars/DuckDB large-file path** — the item every run since Run 1
   has correctly deferred as architecture-adjacent. Seven deferrals is
   enough evidence it's real and worth a dedicated session rather than
   an eighth "not this run either."
2. **CATE/uplift modeling** as a second causal-inference slice — extends
   this run's ATT estimator to answer "for whom is the effect biggest,"
   which is the natural next question a stakeholder asks after seeing an
   average effect.

Recommend (1) if the next run has a full session to dedicate to it
uninterrupted; recommend (2) if it's another same-day short session,
since it composes cleanly with what's already shipped.

---

*Full technical detail, failure-mode discussion, and the closed
backlog investigation are in `.prism/audit_2026-08-10-run7.md` and
`.prism/research_2026-08-10-run7.md`.*
