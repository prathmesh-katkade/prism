# Prism Autonomous Improvement Routine — Run 21 (2026-08-11)

## 1. What shipped

### Hypothesis Sweep: group-difference confounder cross-check

**What it does.** Run 19 wired Hypothesis Sweep's strongest significant
*correlation* pairs into `confounder_detection`'s Simpson's-Paradox check —
"does this Pearson r hold up once you control for a third variable?" That
check only covered numeric/numeric pairs. This run closes the matching gap
for significant *group differences*: when the sweep finds a significant
Welch's t-test (a binary categorical column vs. a numeric column — e.g.
"treatment" vs. "outcome"), it now runs the same paradox/attenuation check,
stratifying by every other categorical column and asking whether the group
difference reverses sign or weakens once you control for it.

New in `modules/confounder_detection.py`:

| Function | Role |
|---|---|
| `stratified_mean_difference()` | Cohen's d for the two groups, computed per stratum + n-weighted pooled average, verdict vs. the plain overall d |
| `detect_group_diff_confounders()` | Runs the above against every categorical candidate confounder |
| `auto_scan_for_group_diff_confounding()` | Agentic entry point — no pair needs to be hinted; also accepts a caller's already-computed pairs (Hypothesis Sweep's own effect sizes) without recomputing |
| `narrate_group_diff_confounder_finding()` | Gemini plain-English explanation, same non-blocking contract as the rest of the module |

`hypothesis_sweep.cross_check_confounders()` now scans both significant
Pearson pairs *and* significant t-test pairs, tagging each result
`"relationship": "correlation"` or `"group_diff"`. The existing "🕵️
Confounder cross-check" panel in `app.py` renders both kinds side by side —
group-diff findings get a pooled-vs-adjusted Cohen's d caption and a
per-stratum mean-diff table instead of a correlation table, same
expander/badge/"Explain this" UI, zero new CSS.

**Why it was chosen.** This was Run 19's own logged follow-on candidate
for its confounder cross-check work, and it directly serves this cycle's
required agentic-AI theme: it's a fully automatic, no-user-request
statistical follow-up question ("but does that hold up?") applied to a
category of finding (group differences) the app could already detect but
never re-questioned. No paid APIs, no extra Gemini calls — pure
deterministic statistics, same as the correlation half of this feature.

**Technical-depth argument.** Simpson's Paradox is usually taught with a
correlation example, but it's a property of confounding, not of Pearson r
specifically — a t-test can reverse under a confounder exactly the same
way, and the textbook real-world case (a drug that wins in every hospital
individually but loses pooled) is a group-difference paradox, not a
correlation one. Reusing Cohen's d as the effect-size analog of r is not
a hand-wave: the 0.2/0.5/0.8 thresholds this module already uses for
paradox/attenuation detection *are* Cohen's own small/medium/large
conventions for d, so the same verdict logic applies without retuning.
One genuine design decision surfaced during TDD, not after shipping: the
correlation module's extra "do the strata even disagree with each other"
heterogeneity check (a fixed 0.5 spread threshold) doesn't transfer to d,
because r is bounded to [-1, 1] but d is unbounded and its per-stratum
sampling variance scales with 1/√n — applying that same fixed threshold
flagged an intentionally-robust test fixture as "confounded" purely from
ordinary sampling noise in a large, genuine effect. A failing test caught
this before it shipped; the fix was to drop that extra check for the
d-based path and rely solely on the sign-flip/attenuation-ratio logic,
which is scale-relative and doesn't have the problem — documented inline
so a future run doesn't reintroduce it.

## 2. Screenshots

Saved to `.prism/runs/2026-08-11-run21/`:
- `01_dataset_loaded.png`, `02_stats_lab.png`, `03_hypothesis_sweep_result.png` — desktop 1440px, dark theme, real sample data (`samples/hr_data.csv`); the sweep runs and correctly stays silent on the confounder panel (no significant t-test pair in this dataset to flag — the honest, common case).
- `04_confounder_crosscheck_panel.png`, `05_confounder_finding_expanded.png` — desktop 1440px, dark theme, a synthetic planted-Simpson's-Paradox dataset (binary `treatment`, numeric `outcome`, `severity` confounder — generated for this run only, not committed): renders "🔴 Paradox — **treatment** differs by **outcome**, controlling for **severity**", pooled Cohen's d = ‑2.60 vs. adjusted d = +1.79 (correct sign flip), and the per-stratum mean-diff/d table.
- `06_light_desktop_paradox.png` — same paradox finding, light theme (Arctic), same dataset. Contrast and glass-panel styling both read clean.
- `07_mobile_dark_loaded.png` — 390×844 (PWA mobile width), dark theme, dataset loaded and dataframe preview readable. Driving further into the sweep panel on mobile hit the same sticky-bottom-Atlas-bar-intercepts-clicks issue every prior run's mobile automation has run into (pre-existing app layout, not introduced by this change) — not re-chased past one retry.

Zero console/page errors beyond the expected Gemini `ERR_CONNECTION_RESET`
(21st consecutive run with no `GEMINI_API_KEY` in this sandbox — narration
itself was never exercised live for the same reason every prior run
documents, but the deterministic detection/rendering path — the actual
new logic — was fully exercised live, not just in unit tests).

## 3. Research findings NOT built (ranked backlog for future runs)

| Feature | Effort | Notes |
|---|---|---|
| Large Excel ingestion (out-of-core reader) | M | Unaddressed since Run 14 scoped it out of the DuckDB item. |
| Light-theme dataframe/chart repaint-lag | S | Cosmetic, logged since ~Run 10. |
| Mobile-viewport navigation automation gap | S | Sticky bottom bar intercepts Playwright clicks — now observed across 6+ runs. A real fix is a test-harness workaround (force-scroll or JS-level click), not an app change; the layout itself is intentional. |
| Live-Gemini end-to-end verification | — | Structural sandbox constraint (no API key), 21 consecutive runs. |
| Explore Mode "load into Manual Builder" click-through | S | Run 20's own logged follow-on — still open. |
| Atlas voice/HUD slice beyond current maturity | M | Mic input, dual-backend TTS, keyword fast path, and proactive HUD are already built (Runs 9–17); further depth needs a genuinely new capability. |

No fresh Phase 2 web research sweep this cycle — the routine has now
reused the standing backlog for 14 consecutive runs, and the highest-value
actionable item (this run's) came straight from the backlog without a new
sweep. A fresh sweep is a reasonable candidate once the list above thins
to cosmetic-only items.

## 4. Interview notes (STAR-style, verbatim-usable)

> **Situation/Task:** Prism's Hypothesis Sweep already flagged
> statistically significant relationships after multiple-comparisons
> correction, and a prior version of mine had taught it to re-question its
> own significant *correlations* for Simpson's Paradox — but a
> significant *group difference* (a t-test result) got no such scrutiny,
> even though the same confounding failure mode applies to it.
>
> **Action:** I extended the confounder-detection module with a
> Cohen's-d-based stratification check — the group-difference analog of
> the existing partial-correlation approach — reusing the same
> paradox/attenuation verdict thresholds (which are literally Cohen's own
> small/medium/large effect-size conventions, so no retuning was needed).
> I wrote the tests first, including a "genuinely robust effect should
> stay robust" case, which caught a real design flaw: a heterogeneity
> threshold tuned for a bounded correlation coefficient doesn't transfer
> to an unbounded effect size like d, and I fixed that before shipping
> rather than after a false positive reached a user.
>
> **Result:** Closed a gap the team's own prior work had explicitly
> flagged as open, added a second full statistical-rigor path (23 new
> tests, 413/413 total green) to the app's automated EDA pipeline, and
> live-verified it correctly distinguishes a real planted paradox from a
> dataset with nothing to flag — with zero additional LLM API calls.

## 5. Recommendation for next run's focus

1. **Explore Mode → Manual Builder click-through** (S effort, low risk,
   open since Run 20): let a suggestion pre-fill the Manual Chart
   Builder's selectboxes instead of only rendering statically.
2. **Large Excel ingestion** (M effort): the oldest surviving backlog item
   by run-count once this cycle's pick is excluded; worth scoping properly
   rather than deferring again.
3. If neither lands cleanly, a fresh Phase 2 web research sweep is
   overdue (14 runs on the same backlog) and would likely surface new
   candidates beyond what's listed above — competitor tools (Hex,
   Deepnote) and current job-description skim haven't been re-checked
   since early August.

---

*Routine run 21 of the Prism autonomous improvement loop. One feature
shipped, verified (413/413 tests, live Playwright pass, fresh-checkout
launch check), merged to `main`, and pushed. No incidents.*
