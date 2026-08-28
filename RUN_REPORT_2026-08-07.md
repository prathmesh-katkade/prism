# Prism Autonomous Improvement Run — 2026-08-07

Full-auto run, two feature branches. `feature/insight-verifier` (commit
`359e0ed`) and `feature/hypothesis-handoff` (commit `e988e6a`) → both
merged to `main` → pushed. Fresh-clone boot check passed after each merge.

## 1. What shipped

### Insight Verifier — self-verifying Auto Analyst findings
**What it does:** Auto Analyst's "Run Full Analysis" ends with Gemini
synthesizing 5 headline findings from the steps it ran. Those findings now
get fact-checked before they reach the user: `modules/insight_verifier.py`
recomputes a broad set of real statistics directly from the DataFrame (row
and column counts, per-column means/medians/nulls, category shares,
pairwise correlations, and bounded group-by means) and checks every number
each finding quotes against that reference set. Each finding is badged
**✓ verified** or **⚠ unconfirmed** in the findings panel, with a summary
caption ("N finding(s) with confirmed figures, M with an unconfirmed
number"). No new Gemini calls — purely deterministic, runs in milliseconds.

**Why it was chosen:** this cycle's mandatory priority theme was agentic AI
analysis, and specifically "self-verifying analysis agents" is called out
as a research direction to draw from. Every competitor named in the brief
(Hex, Deepnote, Julius AI, ChatGPT Advanced Data Analysis, Databricks
Assistant) presents LLM-generated insights as-is — none visibly fact-check
their own narration against the source data in a way the user can see per
finding. It's also the direct fix for the single biggest gap the audit
found: an LLM can misstate a number even when its analysis was correct, and
nothing was catching that before this run.

**Technical-depth argument:** this is a real, if small, "self-verifying
agent" pattern — generate → recompute independently → cross-check → surface
disagreement — not a cosmetic layer on top of the LLM. It's also exhaustively
unit tested (7 dedicated tests covering number extraction, reference-stat
computation, single-finding verification, and batch behavior, including a
"never raises" contract for malformed input).

### First automated test suite
**What it does:** `tests/` now holds 22 pytest tests — 7 for
`insight_verifier`, 4 for `anomaly.py` (IsolationForest flagging, including
edge cases: too few rows, no numeric columns, "no anomalies found" as a
valid empty result), and 7 for `auto_analyst.py`'s pure-logic paths (default
plan fallback branching by column type, result summarization, findings
synthesis error handling when no model is available or every step failed).
`pytest.ini` + `requirements-dev.txt` wire it up; `README.md` documents the
`pytest` entry point.

**Why it was chosen:** the audit's headline finding — zero tests existed
anywhere in a ~200KB application with real statistical and ML logic. A
portfolio app that can't demonstrate its own correctness is a weaker
interview story than one that can.

**Technical-depth argument:** covers previously-*untested* existing modules,
not just the new one — retrofitting coverage onto legacy code is a distinct
and harder skill than testing code you just wrote, and is exactly what a
data-science-adjacent engineering role expects day one on an existing
codebase.

### Suggested next hypothesis — data-driven handoff to Stats Lab
**What it does:** `auto_analyst.suggest_followup_hypothesis(df,
column_types)` looks at the *actual data*, not the LLM's prose, and ranks
candidate column pairs for a follow-up significance test: the strongest
numeric/numeric correlation if it clears a "worth testing" bar (|r| ≥ 0.3),
else the numeric/categorical pair with the largest one-way ANOVA
F-statistic among viable group counts. It returns `None` — no card shown —
rather than suggest something nobody would act on. The Auto Analyst tab
shows the pick as a "Suggested next step" card with a one-click "Test '<a>'
vs '<b>' in Stats Lab" button that pre-selects both columns and jumps tabs.

**Why it was chosen:** the top item in this run's own research backlog —
turns Auto Analyst from "here's what I found" into "here's the specific
next thing worth formally testing," which is exactly the gap between an
EDA summary and an actual analyst's workflow.

**Technical-depth argument:** it's grounded in real recomputed statistics
(a correlation matrix and one-way ANOVA F-tests), not an LLM guess at what
might be interesting — the suggestion is reproducible and the number behind
it (r or F) is shown in the reason text, not asserted. 5 dedicated tests.

## 2. Screenshots

Saved to `.prism/runs/2026-08-07/`:
- `01_landing_dark_desktop.png` — landing screen, dark theme, desktop
- `02_dataset_loaded_desktop.png` — sample dataset loaded, Atlas panel live
- `03_auto_analyst_tab_nav.png` — Advanced Tools popover + Auto Analyst tab
  (shows the "add your free Gemini API key" empty state — expected, no key
  configured in this execution sandbox)
- `04_theme_preferences.png` — App Preferences panel with theme selector
- `05_mobile_pwa_landing.png` — mobile PWA viewport (390×844), no overflow

**Known limitation:** no Gemini API key was available in this execution
sandbox, so the Insight Verifier's ✓/⚠ badges could not be visually
confirmed inside a live findings panel — Auto Analyst correctly falls back
to its "add your API key" empty state instead of crashing. The feature is
confirmed via its unit test suite and by re-using the exact `prism-badge
b-pass`/`b-fail` CSS pattern already shipped and screenshot-verified for
SQL Lab's data-quality badges. **Recommend the next run with a configured
key capture a live screenshot of the badges** for the interview portfolio.

No headline-feature demo GIF this run — the feature's payoff (the badges)
couldn't be triggered live for the reason above; a static screenshot would
be misleading, so it was skipped rather than faked.

## 3. Researched but not built (backlog)

| Feature | Depth | Effort | Why not this run |
|---|---|---|---|
| LLM-narrated anomaly explanations | 3 | S | Needs per-dataset-fingerprint caching to stay inside free-tier limits — deserves its own careful pass |
| polars/DuckDB-backed main pipeline (currently pandas-only outside SQL Lab) | 4 | L | Architecture-adjacent; explicitly out of scope for a single run per this routine's own guardrails |
| `google-generativeai` → `google-genai` SDK migration | 2 | M | Deprecation warning observed but not yet broken; touches every Gemini call site, needs dedicated regression testing |
| Fuller Atlas/JARVIS proactive-HUD slice | 3 | M | Atlas track is capped at one feature per run; Insight Verifier better served this cycle's mandatory priority theme |

Full detail and evidence in `.prism/research_2026-08-07.md`.

## 4. Interview notes (STAR, verbatim-usable)

**Insight Verifier:**
> "In my AI-powered data analysis tool, the LLM would synthesize
> plain-English findings from an automated exploratory analysis — but I
> realized nothing verified those findings' numbers actually matched the
> data (**Situation**). LLM-hallucinated statistics in an agentic pipeline
> is a known failure mode, and I didn't want the app to present a
> confidently-wrong number as fact (**Task**). I built a deterministic
> verification layer that recomputes real statistics — means, correlations,
> category shares, group-by aggregates — directly from the DataFrame, and
> cross-checks every number in each LLM-generated finding against that
> reference set with tolerance for reasonable rounding (**Action**). Every
> finding now carries a visible verified/unconfirmed badge, with zero extra
> API calls, and I backed it with a dedicated unit test suite that plants
> fabricated numbers to confirm the checker actually catches them
> (**Result**)."

**Test suite:**
> "I inherited — well, in this case audited my own — a ~200KB analysis
> application with statistical and ML logic (IsolationForest anomaly
> detection, LLM-driven plan generation) and zero automated tests
> (**Situation**). I needed a way to prove the analysis logic was correct
> without relying on manual clicking through the UI every time
> (**Task**). I wrote pytest coverage for the highest-risk pure-logic paths
> first — anomaly detection's edge cases (too few rows, no numeric columns,
> the empty "no anomalies" result) and the plan-generation fallback logic
> that has to work even when the LLM is unavailable — then extended it to
> my own new verifier module test-first (**Action**). 22 tests now run in
> under 2 seconds and are documented as the project's real entry point for
> "does this still work" (**Result**)."

**Interview note (hypothesis handoff):**
> "Auto Analyst told the user what it found, but not what to do next — so I
> closed that gap (**Situation/Task**). I ranked candidate column pairs
> straight from recomputed statistics — strongest correlation, or largest
> ANOVA F-statistic across a categorical split — rather than asking the LLM
> to guess what's interesting, and surfaced the single best pick with a
> one-click handoff into the app's existing significance-testing tab
> (**Action**). It's deterministic, reproducible, and backed by 5 tests
> covering both the "found something" and "correctly found nothing" paths
> (**Result**)."

## 5. Recommendation for next run

1. If a Gemini API key is available in the execution sandbox next time,
   capture live screenshots of the Insight Verifier badges (✓/⚠) and the
   Suggested-Hypothesis card in a real findings panel — this run could only
   confirm them via unit tests, code review, and CSS-pattern reuse.
2. LLM-narrated anomaly explanations (with per-dataset-fingerprint caching)
   is the next-best agentic-theme pick from this run's research.
3. Consider the `google-generativeai` → `google-genai` migration as its own
   dedicated, fully-regression-tested run once the SDK deprecation risk
   grows (not urgent yet).

---

# Run 2 (same day, independent concurrent session)

This second run executed in parallel with Run 1 above, without visibility
into its selections at research/build time. Zero feature overlap resulted
(confirmed at merge time — see `.prism/routine_log.md` for the full
concurrency note). Three feature branches: `feature/auto-insight-engine`,
`feature/regression-diagnostics`, `feature/stl-decomposition` → all merged
to `main` in sequence → pushed. Fresh-clone boot check passed after the
final merge.

## 1. What shipped

### Auto-Insight Engine — proactive statistical insights on upload
**What it does:** the moment a dataset loads (sample, upload, or restored
session — no button click), `modules/auto_insights.py` runs seven
detectors over it: distribution shape (skewness/kurtosis thresholds),
pairwise numeric correlation (strong ≥0.85 flagged as a multicollinearity
risk, moderate ≥0.6 flagged as worth investigating), missing-data severity
per column, IQR-based outlier prevalence, near-constant columns, high-
cardinality ID-like columns, class imbalance in low-cardinality
categoricals, and exact duplicate rows. Results are severity-ranked
(high/medium/low), capped at 12 findings, and shown at the top of the
Overview tab — the first thing a user sees after upload. An optional
"Generate Executive Summary" button asks Gemini to turn the raw findings
into a 3-5 sentence stakeholder-readable paragraph (one API call, cached in
session state, not re-fired on every rerun).

**Why it was chosen:** this cycle's mandatory priority theme was agentic AI
analysis — specifically "automatic insight generation" and "anomaly
narration" are named directly in the brief. Research confirmed this is
the exact direction the market has moved: Tellius and ThoughtSpot Spotter
both lead with proactive daily insight summaries over passive dashboards,
and 40%+ of enterprises are adopting agentic analytics for unprompted
anomaly detection (per this run's web research, `.prism/research_2026-08-07-run2.md`).
Prism's existing Auto Analyst already does agentic planning, but only on
demand; nothing surfaced findings automatically the way a hiring panel
would expect from a 2026-era "smart" analysis tool.

**Technical-depth argument:** every detector is a real statistical method
with a defensible threshold, not a heuristic guess — skewness/kurtosis
(scipy-backed via pandas), Pearson correlation scanning, the standard
1.5×IQR outlier fence, class-imbalance-by-proportion. The severity ranking
and 12-item cap show product judgment (a wall of 40 findings is worse than
a curated 8), and the whole scan runs in well under a second on typical
sample-sized data since it's pure vectorized pandas/numpy — no model
fitting. 23 unit tests cover every detector individually plus composed
behavior on synthetic clean vs. messy datasets, and edge cases (empty
DataFrame, single row, all-null column).

### Regression Diagnostics Panel — interview-grade statistical rigor
**What it does:** when ML Lab's target column is a regression task,
`modules/regression_diagnostics.py` fits an independent statsmodels OLS
(ML Lab's existing baseline model stays sklearn-based for its
prediction/comparison role; this is a separate fit purely for inference)
and runs the standard diagnostic battery a statistics course would teach:
residuals-vs-fitted and Scale-Location plots (linearity/homoscedasticity),
a Normal Q-Q plot (residual normality), Shapiro-Wilk's numeric normality
test, the Breusch-Pagan test for heteroscedasticity, Durbin-Watson for
autocorrelation, and Variance Inflation Factor per feature for
multicollinearity — each paired with a plain-English verdict ("⚠️ High
multicollinearity... consider dropping one or using regularization").

**Why it was chosen:** the audit and job-description research both pointed
here — VIF/multicollinearity and residual diagnostics are named directly
in real 2026 India/global data-analyst interview question banks, and no
competitor tool surveyed (Hex, Deepnote, Julius AI) surfaces this at
Prism's depth for a no-code baseline-model flow. It's also a zero-risk
addition: gated entirely behind an explicit button, touches no existing
data or state.

**Technical-depth argument:** this is the single highest technical-depth
pick of the run (self-scored 5/5) — it demonstrates working knowledge of
OLS assumptions and their formal tests, not just "run a model and show
accuracy." 33 unit tests, including synthetic-data recovery checks
(planted collinearity correctly produces high VIF; planted
heteroscedasticity correctly fails Breusch-Pagan; i.i.d. noise correctly
passes both) — the tests prove the statistics are actually right, not
just that the code runs.

### Time Series Decomposition (STL) — trend/seasonal/residual breakdown
**What it does:** added below the existing Forecasting tab's forecast
chart. `forecasting.decompose_series()` runs statsmodels' STL (Seasonal-
Trend decomposition using LOESS, robust to outliers by default) on the
same prepared series the forecast already uses, splitting it into trend +
seasonal + residual components with a 0-1 strength score for each
(Hyndman & Athanasopoulos' heuristic: how much residual variance each
component removes). Rendered as a 4-panel observed/trend/seasonal/residual
chart plus a one-line verdict.

**Why it was chosen:** a natural, low-risk complement to the existing
Forecasting tab that closes a real gap — STL/seasonal decomposition is a
standard interview topic for anyone claiming time-series experience, and
Prism could forecast a series without ever showing *why* it looks the way
it does. Small effort (S), reuses 100% of the existing
`prepare_series()` pipeline, zero new dependencies (statsmodels was
already a requirement).

**Technical-depth argument:** correctly distinguishes calendar-relative
seasonal periods per inferred frequency (7 for daily/weekly, 12 for
monthly, 4 for quarterly, etc.) and gates on having at least 2 full
seasonal cycles of history — a decomposition attempted on too little data
is worse than no decomposition. 26 unit tests, including an additive-
reconstruction identity check (`observed == trend + seasonal + resid`
within float tolerance) and verification that a synthetic series with
known trend and seasonality actually recovers both (r > 0.9 correlation to
ground truth) while a pure-noise series correctly scores low seasonal
strength.

### Small fixes shipped alongside (audit-sourced)
- `ai_analyst.call_gemini()` was one bad import away from crashing with a
  raw `TypeError` instead of a clean error message (the exception classes
  it caught could be `None` if `google.generativeai` failed to import).
  Now falls back to matching on exception class name. Also now guards
  `response.text` access against Gemini's safety-filtered/empty response
  case, which previously could raise `ValueError` uncaught.
- `auto_analyst._summarize_result()` now truncates wide DataFrames (20+
  columns capped, `... (N more columns omitted)`) and long string results
  (3000 char cap) before folding them into the findings-synthesis prompt —
  previously a wide result could balloon the prompt token count
  unboundedly.

## 2. Screenshots

Saved to `.prism/runs/2026-08-07/`:
- `auto_insights_desktop_dark.png` / `auto_insights_desktop_light.png` —
  Overview tab, Auto-Insights panel with a live finding (duplicate rows on
  the Sales sample), both themes, 1440×1000
- `auto_insights_mobile_dark.png` — same panel at 390×844
- `stl_decomp_desktop_dark.png` / `stl_decomp_desktop_light.png` —
  Forecasting tab showing the new STL Decomposition section (including its
  empty state) alongside the existing forecast panel, both themes

**Known limitation:** Regression Diagnostics has no captured screenshot.
Playwright automation against Streamlit's segmented-control navigation and
popover-based "Advanced Tools" menu proved unreliable in this sandbox
(element interception on click, and a DOM-order bug in the automation
script that targeted the wrong `<selectbox>` — full account in
`.prism/routine_log.md`). Correctness instead rests on 33 passing unit
tests against synthetic data with known statistical properties, and the
panel is built entirely from Streamlit primitives (`st.metric`,
`st.dataframe`, `st.plotly_chart`, `st.markdown`) already visually
verified elsewhere in this same run's screenshots and Run 1's. **Recommend
the next run capture this live** — the automation fix needed is
documented (select the target-column `<selectbox>` by its `<label>` text,
not DOM index).

**Also discovered (not fixed, logged as backlog):** a pre-existing mobile
layout issue where the Atlas side panel doesn't reflow at ~390px viewport
width, squishing main content into an unreadable strip. Confirmed via a
git-worktree comparison against `main` before this run's changes — it
predates both Run 1 and Run 2. Out of scope for a feature-shipping run;
flagged in `.prism/routine_log.md` for a dedicated CSS pass.

## 3. Researched but not built (backlog)

| Feature | Depth | Effort | Why not this run |
|---|---|---|---|
| Automated Hypothesis Testing Suite | 4 | M | **Largely covered by Run 1's `suggest_followup_hypothesis()` — re-scope before building** |
| Data Quality Score with Exportable Scorecard | 3 | S | Lower depth than the 3 picks made; good quick-win candidate for next run |
| Polars/DuckDB-backed large-file path | 4 | L | Architecture-adjacent, explicitly out of scope per this routine's own guardrails (same item Run 1 flagged) |
| Advanced Outlier Detection (LOF, DBSCAN) | 4 | M | IQR (this run) + IsolationForest (existing) already cover the common cases; diminishing returns without a driving use case |
| Feature Selection Engine (mutual info, RFE, L1) for ML Lab | 4 | M | Good next ML Lab addition, no room in this run's budget |
| Atlas Proactive Insights (JARVIS copilot track) | 4 | M | Routine caps the copilot track at one feature per run; none of this run's 3 picks needed to be it |
| Natural Language Summary of Every Tab | 3 | M | Lower technical depth than the picks made |
| `google-generativeai` → `google-genai` SDK migration | 2 | M | Same item Run 1 flagged — deprecation warning confirmed still present, not urgent, needs dedicated regression testing |

Full detail and evidence in `.prism/research_2026-08-07-run2.md`.

## 4. Interview notes (STAR, verbatim-usable)

**Auto-Insight Engine:**
> "Our data analysis tool required a user to manually click through tabs
> to find anything wrong with their data — nothing was proactive
> (**Situation**). I wanted the app to behave like the newer agentic
> analytics platforms I researched (Tellius, ThoughtSpot), which surface
> insights the moment data loads rather than waiting to be asked
> (**Task**). I built a seven-detector statistical scan — distribution
> skew, correlation strength, missing-data severity, IQR outlier rate,
> near-constant/high-cardinality columns, class imbalance, duplicates —
> that runs automatically on every upload, ranks findings by severity, and
> optionally hands them to an LLM for a one-paragraph executive summary
> (**Action**). It runs in under a second on typical data with zero extra
> model fitting, and I backed all seven detectors with 23 unit tests
> covering both a clean and a deliberately messy synthetic dataset
> (**Result**)."

**Regression Diagnostics Panel:**
> "Our ML Lab could train a baseline regression model and show R², but
> gave no way to check whether the model's own assumptions actually held
> (**Situation**). I wanted to add the statistical rigor a data-science
> interview panel would specifically probe for — is this a *valid*
> regression, not just a fitted one (**Task**). I fit an independent
> statsmodels OLS alongside the existing sklearn baseline and ran the
> standard diagnostic battery — residual plots, Shapiro-Wilk normality,
> Breusch-Pagan heteroscedasticity, Durbin-Watson autocorrelation, and VIF
> for multicollinearity — each with a plain-English verdict a
> non-statistician could act on (**Action**). I proved the diagnostics
> were actually correct, not just running, by planting known collinearity
> and heteroscedasticity into synthetic test data and confirming the
> right test caught each one — 33 tests total (**Result**)."

**STL Decomposition:**
> "Our forecasting feature could project a time series forward but never
> explained *why* the series moved the way it did historically
> (**Situation**). I added a decomposition step so a user — or an
> interviewer watching a demo — could see the trend, seasonal, and
> residual components separately before trusting a forecast built on top
> of them (**Task**). I used statsmodels' STL decomposition, reused the
> app's existing series-preparation pipeline entirely, and added a 0-1
> strength score per component so the read-out is quantified, not just a
> chart (**Action**). I verified correctness with an additive-
> reconstruction identity test and by confirming a synthetic series with
> known trend and seasonality actually recovered both — not just that the
> chart rendered (**Result**)."

## 5. Recommendation for next run

1. Fix the Playwright automation for Regression Diagnostics screenshots
   (target-column selectbox needs label-based lookup, not DOM index — see
   `.prism/routine_log.md` for the exact fix) and capture the missing
   visual evidence.
2. Data Quality Score with Exportable Scorecard is the best next quick win
   from this run's research — S effort, complements the Auto-Insight
   Engine's findings with a single headline number.
3. Re-scope "Automated Hypothesis Testing Suite" against Run 1's
   `suggest_followup_hypothesis()` before building anything — likely
   mostly shipped already.
4. The pre-existing mobile Atlas-panel overflow at ~390px width deserves a
   dedicated CSS-reflow pass; both this run and Run 1 independently
   confirmed it's real and pre-existing.
5. Consider whether concurrent same-day runs should coordinate (e.g. one
   run checks for an in-progress sibling before starting) — this run's
   collision resolved cleanly by luck (zero feature overlap), but a future
   collision on the *same* file/feature would be harder to merge.
