# Run 26 Report — 2026-08-12

## What shipped

**Run All Detectors** (`modules/detector_runner.py`, wired into `app.py`'s
Overview tab) — a single agentic entry point that auto-fires
`hypothesis_sweep.sweep_hypotheses()` (+ `annotate_power()` +
`cross_check_confounders()`) and `anomaly.find_anomalies()` together in
one click, reusing those functions verbatim and writing into the exact
`st.session_state` slots their own manual "Run Hypothesis Sweep" / "Find
Anomalies" buttons already populate.

## Why

`app.py`'s own code documented the gap this closes: `auto_insights` and
`confounder_detection.auto_scan_for_confounding` already run
automatically on upload, but `insight_orchestrator.orchestrate_insights()`
— the "Agent Summary" cross-detector synthesis panel — requires
`MIN_DETECTORS_FOR_OUTPUT = 2` before it says anything, and two of its
inputs (Hypothesis Sweep, Anomaly Detection) only populate after a user
separately visits Stats Lab and the Overview "Anomaly Detection"
expander and clicks their own button — even though both are fully
automatic, deterministic, dataset-wide checks needing no column or
target selection. In practice this meant most users never saw the Agent
Summary at all unless they happened to visit two unrelated tabs first.

Fresh research this cycle (`.prism/research_2026-08-12.md`) confirmed
this is the right call for the required agentic-AI-analysis theme: 2026
competitor tooling (Julius AI's one-prompt full EDA, Hex's Notebook
Agent, Anomalo's "Self-Driving Data") is converging on "one action,
multi-faceted result" as the baseline expectation — Prism already *has*
the detector bench, the gap versus competitors was that it stayed gated
behind manual per-tab clicks, not a missing detector. This was also Run
25's own logged option (b) recommendation.

**Deliberately excluded:** Causal Effect Estimator (ATT/CATE) and Drift.
Both require a user-chosen treatment/outcome column or a second
dataset — there's no defensible automatic default, so auto-firing either
would manufacture a claim nobody asked for.

## Technical depth

- **Size-aware guardrails** (`autorun_eligible()`,
  `MAX_AUTORUN_ROWS = 250_000`, `MAX_AUTORUN_COLUMNS = 150`) prevent a
  huge dataset from turning one click into an unresponsive multi-minute
  hang, with a clear fallback message pointing at running each detector
  individually (which has no such cap).
- **No new Gemini calls** — the existing "Generate Executive Summary"
  button is untouched, still an explicit separate click. Confirmed
  against this cycle's fresh Gemini-2.5-Flash-free-tier research
  (RPM/RPD, not TPM, is the binding constraint) that this stays within
  discipline regardless of how many times a user clicks "Run All
  Detectors".
- **Defensive input filtering** — `run_all_detectors()` filters
  `column_types` down to columns that actually exist in `df` before
  calling `sweep_hypotheses()`/`find_anomalies()`, since neither
  function validates that itself; this also closed a latent crash risk
  (a caller passing a stale `column_types` dict) that existed before this
  change, exercised by
  `test_run_all_detectors_never_raises_on_malformed_column_types`.
- **Never raises** — every detector failure mode (no numeric columns,
  too few rows, scikit-learn missing, no viable pairs) degrades to the
  same inline warning/skip its manual tab already shows.
- **Idempotent / re-run-safe** — `already_have_sweep`/
  `already_have_anomaly` flags skip a detector that's already run this
  session rather than re-computing (and the button hides itself once
  both have run), so repeated clicks are cheap and don't reset unrelated
  narration caches.
- Fixed a pre-existing gap as a side effect: `hypothesis_sweep_confounder_check`
  was never reset in `set_active_dataset()` on a new upload — now is,
  alongside the two new `detector_runner_last_ran`/`_last_skipped` state
  keys.

## Tests

16 new tests in `tests/test_detector_runner.py`:
- `autorun_eligible()`: normal dataset, `None`/empty df, over-row-cap,
  over-column-cap, exactly-at-cap boundary.
- `run_all_detectors()`: both detectors run fresh; each individually
  skipped when already computed; both skipped; blocked over the row cap
  runs nothing; no-viable-pairs dataset doesn't crash; too-few-rows for
  anomaly reports its own error instead of crashing; `None` df handled;
  malformed `column_types` (referencing a column not in `df`) doesn't
  raise.
- **Integration test** (`test_run_all_detectors_feeds_orchestrator_to_non_silent_result`):
  proves the actual point of the feature — feeding
  `run_all_detectors()`'s output into
  `insight_orchestrator.orchestrate_insights()` produces a non-silent,
  ranked result with 2+ detectors fired, on a planted-signal synthetic
  dataset.

Full suite: **486 → 502 passing, zero regressions.**

## Live verification (Playwright)

Screenshots in `.prism/runs/2026-08-12/`:
- `01-desktop-dark-overview-uploaded.png` — 1440px, dark theme, dataset
  just uploaded.
- `02-desktop-dark-after-run-all.png` — Agent Summary populated with 3
  detectors ("Confirmed by 2 detectors — revenue", 3× "High" chi-
  square/ANOVA findings) after one "Run All Detectors" click; Atlas also
  fired its existing proactive alert ("Quick flag — 2 independent checks
  now agree on revenue") unprompted, confirming the feature correctly
  feeds the pre-existing proactive-alert wiring too.
- `03-desktop-light-overview.png` — 1440px, Arctic (Light) theme, same
  Agent Summary rendering correctly with good contrast.
- `04-mobile-dark-overview-uploaded.png` — 390px, dark theme, freshly
  uploaded.
- `05-mobile-dark-after-run-all-detectors.png` — 390px, dark theme,
  Agent Summary populated after clicking "Run All Detectors" via
  JS-dispatch + `scrollIntoView()` (the sticky bottom Atlas command bar
  still intercepts real pointer clicks on mobile, same standing gap
  logged 8+ prior runs — JS dispatch + explicit scroll-into-view is what
  got a *visible-content* result this time, where prior runs' plain JS
  click alone did not).
- `06-mobile-light-overview.png` — 390px, **light theme, reached for the
  first time in this repo's run history.** Prior runs (7+) documented
  the mobile sidebar's collapsed "App Preferences" expander + theme
  selectbox as unreachable via automation; this run found the actual
  selector path (open sidebar → click the expander's leaf text node →
  click the `stSelectbox` → click the `<li>` option by text) and
  captured it successfully. Minor unrelated cosmetic note: the dataframe
  table and the sticky bottom Atlas bar keep a dark background in light
  theme — a pre-existing, app-wide styling quirk, not something this
  run's change touched or is in scope to fix.
- `12-desktop-dark-full-after-run.png` — full-page desktop view
  confirming the "Run All Detectors" section correctly disappears once
  both detectors have run (nothing left for it to do), and the Agent
  Summary panel renders its full ranked list below.

No tracebacks in the Streamlit server log across the whole session;
`curl` returned HTTP 200 throughout.

## Not built (backlog, ranked)

1. **Chi-square/ANOVA post-hoc power in `annotate_power()`** — Run 25's
   own flagged follow-on, still real and still requires threading the
   actual contingency-table shape through (not approximating from
   Cramer's V/eta-squared alone — flagged twice now as an easy way to
   produce silently-wrong estimates if rushed).
2. **Anomaly Drivers auto-run** — `anomaly.find_anomaly_drivers()` (SHAP-
   style feature attribution for *why* rows were flagged) was left out
   of this run's auto-run scope; it depends on the anomaly detector's
   own output and isn't independently gate-blocking the orchestrator the
   way Hypothesis Sweep/Anomaly Detection were, but would be a natural
   "Run All Detectors" extension.
3. **Mobile sidebar/theme-toggle automation** — now solved (see above),
   but the underlying app-wide cosmetic issue (dataframe/sticky-bar dark
   background persisting in light theme) remains open as a small design
   polish item.
4. **Atlas proactive "you haven't run X yet" nudge** — capped at one
   Atlas/JARVIS-track feature per run; this run's slot went to the core
   agentic-analysis capability instead per the brief's priority order.

## STAR bullet (interview-ready)

> **Situation:** Prism's insight-orchestration layer synthesized
> findings across five independent detector modules, but silently did
> nothing for most users because two of its inputs only populated after
> manually visiting separate tabs.
> **Task:** Close that gap without adding new detection logic, new
> Gemini API calls, or UI complexity that could hang on a large dataset.
> **Action:** Built a thin orchestration module (`detector_runner.py`)
> that reuses the existing deterministic detector functions verbatim,
> added dataset-size guardrails and idempotent re-run-skip logic, and
> wired one button into the existing session-state contract so results
> are indistinguishable from a user having triggered each tab manually.
> **Result:** One click now takes the "Agent Summary" panel from silent
> to a 3-detector ranked synthesis, verified end-to-end with an
> integration test and live Playwright screenshots across four viewport/
> theme combinations (plus a first-ever successful mobile-light-theme
> capture); 16 new tests, 486→502 suite green, zero regressions.

## Recommendation for Run 27

Two reasonable directions, roughly comparable in leverage:
- **Chi-square/ANOVA post-hoc power** (backlog #1 above) — the
  remaining, well-scoped stats-rigor follow-on from Run 25/26, now that
  `annotate_power()`'s t-test-only scope has been stable across two
  cycles.
- **Anomaly Drivers auto-run + light narration** (backlog #2) — a small,
  natural extension of this run's `detector_runner.py` that would let
  "Run All Detectors" also explain *why* the flagged rows are unusual,
  strengthening the agentic-AI-analysis theme further if it's kept as a
  required or high-priority theme again.

Either is small enough to ship in one cycle without needing a second
feature to fill the slot.
