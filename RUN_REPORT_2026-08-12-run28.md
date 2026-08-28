# Run 28 Report — 2026-08-12

## What shipped

**Correlation (Pearson) post-hoc power via Fisher z-transform**,
extending `hypothesis_sweep.annotate_power()` (Run 25's t-test-only
version, Run 27's chi-square/ANOVA extension) to the fourth and final
test family Hypothesis Sweep runs automatically —
`modules/experiment_design.py` (new functions), `modules/
hypothesis_sweep.py` (one new `elif` branch, no row-assembly changes
needed), `app.py` (two label-text tweaks, no logic changes).

## Why

Run 27's own report logged two options for Run 28: correlation/Fisher-z
power (closing the power-check backlog set fully), or a fresh agentic-AI
angle from a differently-sourced research pass. This run's fresh Phase 2
research (`.prism/research_2026-08-12-run28.md`) tried the second path
first — two community-discussion searches (Hacker News, then a different
subreddit, a genuinely new source class per Run 27's specific suggestion)
both came up empty for a concrete new gap, matching Run 26/27's
competitor-tooling research outcome. The industry-practice search
reconfirmed the Fisher z-transform correlation-power technique for the
third consecutive research pass across three prior runs — strong,
repeated evidence, closed-form technique, low implementation risk. Per
this run's own instructions ("pick ONE feature that satisfies the
required agentic-AI-analysis theme OR is the correlation-power backlog
closer"), correlation power was the clear, evidence-backed choice this
cycle.

**Theme fit:** satisfies the agentic-AI-analysis theme the same way Runs
25/27 justified it for the other three families — it's an automatic
follow-up question the already-agentic Hypothesis Sweep now asks about
its own significant correlation findings too, with zero new user action
and zero new Gemini calls.

## Technical depth

- **Exact two-term normal-CDF power formula**, not an approximation:
  under H0 (rho=0), Fisher's z of the sample r is approximately
  Normal(0, 1/sqrt(n-3)) — a variance that (unlike r itself) doesn't
  depend on the true correlation. Achieved power is evaluated at the
  noncentrality the *observed* r implies for a given n:
  `power = 1 - Φ(z_crit - ncp) + Φ(-z_crit - ncp)`, where
  `ncp = fisher_z(r) * sqrt(n-3)`. This is algebraically identical to R's
  `pwr.r.test` internals (`Φ(sqrt(n-3)*z_r - z_alpha/2) +
  Φ(-sqrt(n-3)*z_r - z_alpha/2)`) — verified by hand before writing the
  wrapping code, not assumed from a library call.
- **`fisher_z(r) = arctanh(r)`**, clamped to `r ∈ [-0.999999, 0.999999]`
  first so a (near-)perfect correlation doesn't blow arctanh up to
  infinity — same defensive-clamping convention as
  `cohens_f_from_eta_sq()`'s eta-squared clamp in Run 27's work.
- **Recommended sample size is verified, not just computed.** The
  standard closed-form approximation (Cohen 1988; the same formula R's
  `pwr.r.test` uses) — `n ≈ ((z_alpha/2 + z_beta) / fisher_z(r))² + 3`
  — is a good starting point but *drops* the exact formula's small
  second (opposite-tail) term, which means the naive `ceil()` of that
  estimate can fall a hair short of actually reaching the target power.
  Confirmed this empirically: for r=0.5, alpha=.05, target=80%, the
  closed-form gives n≈28.99 → naive ceil = 29, but
  `achieved_power_correlation(0.5, 29)` = 79.98%, genuinely just under
  80%. `_n_needed_for_correlation_power()` starts from the closed form
  then nudges n upward (bounded, max 50 steps) until plugging it back
  into the exact `achieved_power_correlation()` formula actually clears
  `target_power` — for that example, n=30. A dedicated test
  (`test_power_check_correlation_recommended_n_actually_reaches_target`)
  locks this in. This is a genuine correctness improvement over the
  textbook closed-form approximation most calculators stop at, not a
  shortcut around it.
- **Reference-value verified against the literature**: r=0.3, alpha=.05,
  power=.80 → n≈85 (Cohen's (1988) canonical correlation power table,
  reproduced by G*Power's "Correlation: bivariate normal model" and R's
  `pwr.r.test`) — reproduced independently in a standalone script before
  writing the wrapping test, matching to the exact integer.
- **`interpret_power_check()`'s dispatcher gains one more branch**
  (`"pearson"`), no restructuring — `app.py`'s "Power" badge and
  underpowered-findings expander (and therefore `detector_runner`'s "Run
  All Detectors", which calls `annotate_power()` unchanged) inherit
  correlation coverage automatically. Only two comment/label tweaks in
  `app.py`, matching Run 27's precedent exactly.
- **No new row-assembly wiring needed in `hypothesis_sweep.py`** (unlike
  t-test's `group_sizes` or chi-square's `dof`, which needed new fields
  threaded through `sweep_hypotheses()`'s row dict) — a Pearson row's
  `effect_size` (already exactly `r`, per `stats_lab.run_pearson()`) and
  `n` were already present on every row from day one. The new branch in
  `annotate_power()` is a straight call to `power_check_correlation(row
  ["effect_size"], row["n"], ...)`.
- **Also added the planning-side counterpart**, `sample_size_correlation()`
  / `interpret_sample_size_correlation()`, symmetric with the existing
  `sample_size_two_proportions()`/`sample_size_two_means()` — completes
  the module's stated "two audiences, one set of formulas" pattern for
  all four test families instead of leaving correlation's "before an
  experiment" planning question asymmetric with its own post-hoc check.

## Tests

22 net new tests:
- **`tests/test_experiment_design.py`** (20 new): `fisher_z` (definition
  check, ±1 clamp guard), `achieved_power_correlation` (reference-value
  match, monotonic in n, zero-effect-equals-alpha, sign symmetry,
  degenerate n<4 guard, r=±1 saturates to 1.0), `power_check_correlation`
  (underpowered/well-powered/zero-effect flows, and the dedicated
  "recommended n actually reaches target power when verified" test
  described above), `sample_size_correlation`/
  `interpret_sample_size_correlation` (reference-value match, smaller
  effect needs more n, higher power needs more n, sign doesn't matter,
  rejects zero/out-of-range r), and `interpret_power_check`'s new
  `"pearson"` dispatch branch (both underpowered and well-powered text).
- **`tests/test_hypothesis_sweep.py`**: replaced the now-outdated
  `test_annotate_power_still_skips_pearson_rows` with
  `test_annotate_power_covers_significant_pearson_row` (well-powered,
  using the existing strong-correlation `_correlated_df()` fixture) and
  `test_annotate_power_flags_underpowered_significant_pearson_row` (a
  new small-n/modest-r fixture); updated the end-to-end integration test
  (renamed to `..._all_four_families_...`) to assert all four test
  families — not three — get readable power prose with zero raises on a
  planted-signal fixture, the same pipeline `app.py` and
  `detector_runner` actually run.

Full suite: **528 → 550 passing, zero regressions.**

## Live verification (Playwright)

Chromium wasn't downloadable via `playwright install` in this sandbox
(proxy blocks `cdn.playwright.dev`), but a pre-installed, version-
mismatched Chromium binary was found at `/opt/pw-browsers/chromium-1194/`
— launched successfully by passing `executable_path` directly instead of
relying on Playwright's own version-matched download. Screenshots in
`.prism/runs/2026-08-12-run28/`:

- `01_desktop_dark_wellpowered_pearson_table.png` — 1440px, dark theme,
  `samples/stock_data.csv` (400 rows of OHLC data), Hypothesis Sweep run:
  **6/6 significant findings are all Pearson correlation rows**, each
  showing "✅ 100%" in the new Power column — the core proof the
  extension works live, not just in unit tests.
- `02_desktop_dark_scrolled_experiment_design.png` — same run, scrolled
  down to confirm the confounder cross-check and Experiment Design
  calculator below still render correctly, no traceback.
- `03_desktop_light_wellpowered_pearson_table.png` — same dataset/run,
  Arctic (Light) theme, correct contrast, no dark-canvas banding.
- `04_desktop_dark_underpowered_pearson_badge.png` — a deliberately
  small, weak-signal synthetic dataset (`underpowered_correlation.csv`,
  20 rows, planted r≈0.53) showing the sweep results table with
  **"⚠️ 68%"** in the Power column.
- `05_desktop_dark_underpowered_expanded.png` — the expanded
  underpowered-findings callout: **"metric_a vs metric_b — ⚠️
  Underpowered: with 20 paired observations, this correlation test had
  only 68% power to detect a relationship this strong — a follow-up
  should collect ~26 paired observations to reach 80% power."** —
  matching a standalone Python reference computation
  (`power_check_correlation(0.5300, 20)` → 68.2% achieved,
  `recommended_n=26`) exactly before the UI run.
- `06_mobile_dark_underpowered_chart.png` / `07_mobile_dark_underpowered_
  expanded.png` — 390px, dark theme, same underpowered correlation
  finding reachable and correctly rendered on mobile (via the
  "Advanced Tools" popover → "Stats Lab" flow, `force:true` real
  pointer-click clicks plus an explicit Escape + off-target click to
  close the popover before hitting "Run Hypothesis Sweep" — the same
  sticky-bottom-bar click-interception gap 8+ prior runs have logged).

No tracebacks in the Streamlit server log across the whole session;
`curl` returned HTTP 200 throughout. Mobile **light** theme was not
attempted this run — the exact working selector path Run 27 documented
(`stExpandSidebarButton` + real pointer clicks) wasn't re-verified here
since this feature adds no new UI surface (same "Power" badge/expander
mechanism Run 27 already screenshotted in that exact combination);
budget went to confirming the new *math* renders correctly across the
combinations that matter for a non-visual backend extension instead.

## Not built (backlog, ranked)

1. **Standing items unchanged this run:** mobile-viewport sidebar/theme-
   toggle automation has a documented working path (Run 26/27) but each
   run still re-derives the exact click sequence from scratch — a small
   reusable Playwright helper/fixture (first suggested by Run 2) would
   save real time in a future run that needs the full 4-way matrix again.
   Light-theme repaint lag (cosmetic, app-wide) remains open, low
   priority. Live-Gemini verification remains structural (no API key in
   this sandbox — 28th consecutive run without one).
2. **A genuinely new agentic-AI-analysis angle** — this is now the
   fourth consecutive run (25, 26, 27, 28) where web research for a
   *new* standalone-detector-style feature came up short; the
   power-check set, confounder detection, causal inference (ATT/CATE),
   ensemble anomaly detection, and the Agent Summary orchestrator between
   them now cover most of what 2026 competitor tooling and interview-prep
   research surfaces. The next run may need to look somewhere genuinely
   different than "web search for a gap" — e.g. a fresh top-to-bottom
   audit of what's in `modules/` vs. what's actually wired into
   `app.py`'s UI (Run 27 found one such gap — "Anomaly Drivers auto-run"
   turned out to already be resolved — the inverse, an unwired module,
   may also exist), or accept that the app's detector/orchestrator
   surface has reached a natural plateau and pivot toward UX
   consolidation, performance, or the Gemini SDK's evolving surface
   instead of another new statistical check.

## STAR bullet (interview-ready)

> **Situation:** Prism's automated Hypothesis Sweep self-checked its own
> significant findings for statistical power across three test families
> (t-test, chi-square, ANOVA) — but correlation, the sweep's most common
> finding type in numeric-heavy datasets, had no equivalent check,
> flagged as the standing backlog item across three consecutive prior
> development cycles.
> **Task:** Close the gap using the correct distribution family — Fisher
> z, not the noncentral chi-square family the other three share — and
> make sure the "how many more samples do you need" recommendation is
> actually correct, not just a textbook approximation trusted blindly.
> **Action:** Implemented the exact two-term normal-CDF power formula
> (verified algebraically identical to R's `pwr.r.test` internals before
> writing the wrapping code); discovered empirically that the standard
> closed-form sample-size approximation can fall a hair short of its
> stated target power once rounded to an integer (r=0.5, target 80% →
> naive ceil gives 29, which only achieves 79.98%); fixed it by nudging
> the recommendation upward until the exact power formula confirms it
> actually clears the target, then locked that behavior in with a
> dedicated regression test.
> **Result:** All four test families now get an automatic, statistically
> rigorous power self-check with no new user action and no new API
> calls — closing a backlog item three consecutive development cycles
> had flagged; 22 new tests, 528→550 suite green, zero regressions;
> verified live end-to-end (desktop dark/light, mobile dark) with the
> underpowered-correlation callout's exact wording matching a standalone
> reference computation.

## Recommendation for Run 29

The statistical power-check set built across Runs 25/27/28 is now
complete for all four test families Hypothesis Sweep runs. Two
reasonable directions, in order of what this run's research actually
supports:

1. **A different research method than "web search for a competitor
   gap"** — four consecutive runs (25-28) have tried variations on this
   and increasingly come up empty. Worth trying a structural self-audit
   instead: systematically diff every module in `modules/` against what
   `app.py` actually renders, looking for the *inverse* of Run 27's
   finding (a computed-but-never-surfaced result), or read through
   `insight_orchestrator.py`'s detector adapters for one that's stale
   relative to its source module's current output shape.
2. **If neither surfaces a real gap**, it may be honest to say in that
   run's report that Prism's detector/orchestrator/stats-rigor surface
   has reached a natural plateau for this repeating-cycle format, and
   pivot the "required feature" theme toward something orthogonal —
   performance/scale testing of the existing DuckDB large-file path
   under a genuinely large (500MB+) file, or a documentation/portfolio-
   presentation pass (a single page that narrates the *set* of features
   built across all 28 runs as one coherent interview story) rather than
   forcing another marginal statistical check into the codebase.
