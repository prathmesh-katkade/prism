# Run 27 Report — 2026-08-12

## What shipped

**Chi-square and ANOVA post-hoc power**, extending
`hypothesis_sweep.annotate_power()` (Run 25's t-test-only version)
to the other two test families `sweep_hypotheses()` already runs
automatically — `modules/experiment_design.py` (new functions),
`modules/hypothesis_sweep.py` (row assembly + `annotate_power()`),
`app.py` (two label-text tweaks, no logic changes needed).

## Why

Run 25 shipped t-test post-hoc power; Run 25's own report and Run 26's
own report both explicitly flagged chi-square/ANOVA power as the
"real but separate" remaining follow-on, twice — describing it as
needing "the contingency table's actual shape" or "group count"
threaded through, not approximated from Cramer's V/eta-squared alone.
This run's fresh Phase 2 research (`.prism/research_2026-08-12-run27.md`)
confirmed it's still the single most consistently-named statistics topic
across 2026 data-analyst interview-prep sources, explicitly naming
chi-square alongside t-tests in the same "power analysis" sentence — the
highest-evidence, most concretely-scoped candidate available, ahead of
role-specific dashboards or a new detector (neither of which had
supporting evidence this cycle) and ahead of correlation/Fisher-z power
(a genuinely different distribution family, logged as the next
follow-on rather than rushed into this cycle alongside two others).

**Theme fit:** satisfies this cycle's required agentic-AI-analysis theme
the same way Run 25 justified the theme fit for the t-test half of this
same feature — it's an automatic follow-up question the already-agentic
Hypothesis Sweep now asks about its own significant findings, across two
more test families, with zero new user action and zero new Gemini calls.

**One correction to Run 26's own backlog note** (see
`.prism/audit_2026-08-12-run27.md`): Run 26's report listed "Anomaly
Drivers auto-run" as unbuilt backlog, but `app.py`'s Anomaly Detection
expander already computes `find_anomaly_drivers()` unconditionally
whenever `anomaly_result_df` is populated — and `detector_runner.
run_all_detectors()` (Run 26's own feature) already writes into that
exact slot. That item turned out to already be effectively resolved,
which further supported this run's chi-square/ANOVA choice as the
higher-leverage remaining move.

## Technical depth

- **Cohen's w derived from the raw statistic, not Cramer's V**
  (`cohens_w_from_chi2(chi2_statistic, n) = sqrt(chi2/n)`). This is the
  part both prior runs' backlog notes assumed would need the contingency
  table's row/column shape threaded through separately — V's relationship
  to w does need that shape (`min(rows, cols) - 1`), and the same degrees
  of freedom can come from more than one table shape, so recovering w
  from V and dof alone is genuinely ambiguous. Going through the raw
  chi-square statistic and n sidesteps the ambiguity entirely and needs
  nothing beyond what `stats_lab.run_chi2()` already computes and
  returns (statistic, n, dof) — a cleaner solution than what was assumed
  necessary, not a shortcut around the concern.
- **Cohen's f derived from eta-squared**
  (`cohens_f_from_eta_sq(eta_sq) = sqrt(eta_sq / (1 - eta_sq))`, clamped
  below 1.0 to avoid a divide-by-zero on a near-perfect fit), combined
  with the ANOVA test's *actual* per-group sizes — `run_anova()`'s own
  `groups` dict, now threaded through `sweep_hypotheses()`'s row assembly
  the same way t-test's `group_sizes` already was — for `k_groups` and
  total `nobs`, not approximated from eta-squared and total n alone.
- **Reference-value verified, not just self-consistent**: tests cross-
  check `achieved_power_chi2`/`achieved_power_anova` against Cohen's
  (1988)/G*Power's own canonical textbook numbers — w=0.3, df=1, α=.05 →
  n≈87 for 80% power; f=0.25, k=3 groups, α=.05 → total n≈159 (~53/group)
  — reproduced via statsmodels' `GofChisquarePower`/`FTestAnovaPower`
  before writing a single line of the wrapping code, confirming the
  approach against the literature rather than trusting the library blind.
- **`interpret_power_check()` became a dispatcher**, not three separate
  public functions, keyed on each check dict's own `"test"` field
  (defaulting to `"ttest"` for backward compatibility with any caller
  built before that key existed). This meant `app.py`'s existing call
  site — the "Power" badge in the Hypothesis Sweep results table and the
  underpowered-findings expander — needed **zero logic changes** to cover
  all three families; only two label strings changed ("t-test result" →
  "result", since the expander now legitimately covers all three). Run
  26's `detector_runner.run_all_detectors()` calls `annotate_power()`
  unchanged and inherits the extension automatically — verified via the
  existing `test_run_all_detectors_feeds_orchestrator_to_non_silent_result`
  integration test still passing unmodified.
- **Correlation (Pearson) power deliberately excluded**, documented in
  both `experiment_design`'s module docstring and `annotate_power()`'s
  docstring: it needs a Fisher z-transform noncentral distribution
  family, genuinely different from the noncentral-chi-square family the
  other three share — a real follow-on, not approximated here.
- Hardened `experiment_design._round_up()` against
  `statsmodels.stats.power.solve_power()` occasionally returning a
  size-1 numpy array instead of a plain float (surfaced as a
  `DeprecationWarning` under the new chi2/ANOVA solve-power paths; the
  t-test path just never happened to trigger the array-return branch —
  a pre-existing risk this run's testing exposed, not introduced).

## Tests

26 net new tests:
- **`tests/test_experiment_design.py`** (25 new): `cohens_w_from_chi2`
  (definition check, zero-n guard), `achieved_power_chi2`/
  `power_check_chi2` (reference-value match, monotonic in n, degenerate
  inputs, underpowered/well-powered/zero-effect-size flows),
  `cohens_f_from_eta_sq` (definition check, perfect-fit guard),
  `achieved_power_anova`/`power_check_anova` (same coverage pattern),
  and `interpret_power_check`'s dispatch (chi2 text, anova text, and a
  regression test confirming a ttest-shaped dict *without* the new
  `"test"` key still interprets correctly — the backward-compat path).
- **`tests/test_hypothesis_sweep.py`**: updated `test_non_ttest_rows_
  have_no_group_sizes` (now outdated by design — ANOVA rows do carry
  `group_sizes`) into `test_pearson_and_chi2_rows_have_no_group_sizes` +
  `test_anova_rows_carry_group_sizes`; added `test_chi2_rows_carry_dof`/
  `test_non_chi2_rows_have_no_dof`; updated `test_annotate_power_skips_
  nonsignificant_and_nonttest_rows` (also now outdated — chi2/anova
  significant rows *do* get a power check) into `test_annotate_power_
  skips_nonsignificant_rows` + explicit `test_annotate_power_covers_
  significant_anova_row`/`_chi2_row` + `test_annotate_power_still_skips_
  pearson_rows`; added an **end-to-end integration test**
  (`test_annotate_power_end_to_end_covers_all_three_families_with_
  readable_prose`) proving a full `sweep_hypotheses()` → `annotate_power()`
  → `interpret_power_check()` pass on a planted-signal fixture produces
  readable prose for all three families without raising, the same
  pipeline `app.py` and `detector_runner` actually run.

Full suite: **502 → 528 passing, zero regressions.**

## Live verification (Playwright)

Screenshots in `.prism/runs/2026-08-12-run27/`:
- `01-desktop-dark-overview-uploaded.png` — 1440px, dark theme, a
  synthetic dataset with planted ANOVA/chi-square/t-test signals
  (region→revenue, region↔tier, segment→spend) just uploaded.
- `02-desktop-dark-hypothesis-sweep-results.png` — Hypothesis Sweep
  results table showing **all three test families in the "Power"
  column simultaneously** (two ANOVA rows, one chi-square row, one
  t-test row, each "✅ 100%") — the core proof the extension works
  live, not just in unit tests.
- `04-desktop-light-hypothesis-sweep.png` — same results, Arctic
  (Light) theme, correct contrast.
- `08-desktop-dark-underpowered-chi2-expanded.png` — a deliberately
  small-n, weak-effect dataset (25 rows) expanded to show the real
  underpowered-chi-square callout: **"region vs tier — ⚠️ Underpowered:
  with 25 rows, this chi-square test had only 69% power to detect an
  association this strong — a follow-up should collect ~33 rows total to
  reach 80% power."** — matching a standalone Python reference
  computation of the same dataset exactly before the UI run.
- `09-mobile-dark-hypothesis-sweep-results.png` / `10-mobile-dark-
  underpowered-expanded.png` — 390px, dark theme, same underpowered
  chi-square finding reachable and correctly rendered on mobile via the
  "Advanced Tools" popover → "Stats Lab" flow.
- `11-mobile-light-hypothesis-sweep-results.png` / `12-mobile-light-
  underpowered-expanded.png` — 390px, **light theme**, same finding.
  Mobile light theme has been logged as a hard-to-reach automation gap
  across many prior runs (Run 26 first cracked it); this run found and
  documented the exact reliable path: click `[data-testid=
  "stExpandSidebarButton"]` (not the generic `button[kind="header"]`
  query used in earlier attempts, which matched the wrong header
  button and left the sidebar off-canvas at `x:-256`), then the "⚙️ App
  Preferences" expander leaf, then the theme `stSelectbox` **via a real
  Playwright pointer click** (`locator.click()`, not a raw DOM
  `element.click()` — BaseWeb's Select listens for `mousedown`, which a
  synthetic DOM click doesn't fire, so the dropdown silently never
  opened until switched to a real click), then the `<li>` option by text.

No tracebacks in the Streamlit server log across the whole session;
`curl` returned HTTP 200 throughout, including after every interaction.

## Not built (backlog, ranked)

1. **Correlation (Pearson) post-hoc power via Fisher z-transform** — the
   natural fourth test family, deliberately excluded this run (see
   Technical depth). A genuinely different noncentral distribution
   family than the other three, needing its own careful reference-value
   validation pass rather than a quick bolt-on; real effort, low risk if
   done carefully, real risk of a subtly-wrong CI/z-transform if rushed.
2. **Role-specific / persona dashboards** (CFO vs. ops view) — a 2026
   dashboard-trend candidate from this run's research, but a real UX
   redesign (effort L), not a small module; doesn't serve the required
   agentic-AI-analysis theme either.
3. Standing items unchanged this run: mobile-viewport sidebar/theme-
   toggle automation is now **fully solved** (see Live verification
   above — this closes a gap logged across 7+ prior runs). Light-theme
   repaint lag (cosmetic, app-wide) remains open, low priority.
   Live-Gemini verification remains structural (no API key in this
   sandbox — 27th consecutive run without one).

## STAR bullet (interview-ready)

> **Situation:** Prism's automated Hypothesis Sweep already self-checked
> its own significant t-test findings for statistical power (Run 25),
> but ANOVA and chi-square findings — two of the sweep's three test
> families — had no equivalent check, flagged as a real gap across two
> consecutive prior development cycles.
> **Task:** Close the gap without approximating the standardized effect
> size from insufficient information — the exact trap both prior
> attempts had flagged (Cramer's V alone can't be converted back to
> Cohen's w without the contingency table's shape, which isn't
> recoverable from degrees of freedom alone).
> **Action:** Derived Cohen's w directly from each chi-square test's own
> raw statistic and sample size instead of back-computing it from
> Cramer's V, sidestepping the shape-ambiguity problem entirely; threaded
> ANOVA's actual per-group sizes through the sweep's row assembly for
> Cohen's f; validated both against Cohen's (1988) canonical textbook
> power tables before integrating; refactored the existing interpretation
> function into a small dispatcher so the calling UI code needed zero
> changes to inherit the new coverage.
> **Result:** All three test families now get an automatic, statistically
> rigorous power self-check with no new user action and no new API calls;
> 26 new tests, 502→528 suite green, zero regressions; verified live
> end-to-end across four device/theme combinations, including closing a
> mobile-light-theme automation gap that had been open for 7+ prior
> development cycles.

## Recommendation for Run 28

With chi-square/ANOVA power now shipped, Hypothesis Sweep's power
self-check is complete for every test family with a well-defined,
non-approximated power formula available (t-test, chi-square, ANOVA).
Two reasonable directions:
- **Correlation/Fisher-z power** (backlog #1) — closes the set fully,
  but is a small, self-contained stats-rigor item on its own; may be
  worth combining with a second, more agentic-theme-forward feature in
  the same cycle rather than shipped alone, since Run 27's own research
  found no fresh gap versus competitor tooling this time.
- **A genuinely new agentic-AI-analysis angle** — worth another fresh
  Phase 2 research pass rather than assuming the same searches will
  surface something new; this run's competitor-tooling research (Julius
  AI/Hex/Deepnote) found nothing Prism doesn't already cover in some
  form, suggesting the next real gap (if any) may require looking at a
  different data source (e.g. recent HN/Reddit data-tooling discussion,
  or a specific underserved workflow like time-series/forecasting
  interview prep) rather than the same "AI analysis tool comparison"
  searches this run and Run 26 both ran.
