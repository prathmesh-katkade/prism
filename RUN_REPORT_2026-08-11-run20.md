# Prism Autonomous Improvement Routine — Run 20 (2026-08-11)

## 1. What shipped

### Explore Mode: PyGWalker-style auto-suggested chart encodings

**What it does.** A new "🧭 Explore Mode" panel in the Visualize tab
(between Auto-Generated Charts and the Manual Chart Builder) that ranks
candidate charts by how much signal they're likely to reveal, and renders
the top ones automatically — no clicking through axis pickers first. Four
deterministic signal sources feed a single ranked list:

| Signal | Metric | Chart |
|---|---|---|
| Numeric × numeric | \|Pearson correlation\| | Scatter |
| Categorical × numeric | ANOVA η² (eta-squared) effect size, gated to 2–15 distinct categories | Bar (group means) |
| Datetime × numeric | \|correlation with time ordinal\| | Line |
| Single numeric | \|skew\| ≥ 1.0 | Histogram |

Each suggestion carries a plain-English reason ("revenue varies strongly
across segment groups (η²=0.94)") and a 0–1 score, and is built via the
existing `build_manual_chart()` so every suggestion is guaranteed
renderable — a suggestion that fails to build (edge-case column
combination) is skipped silently rather than breaking the panel.

**Why it was chosen.** This was the single oldest item in the routine's
own backlog — first identified in Run 13's research pass and reused
unbuilt through seven consecutive runs (13–19), explicitly flagged as
"strongly recommended for Run 20" in the Run 19 log. Every prior run's
research repeatedly surfaced this gap against Hex/Deepnote/PyGWalker's
"suggested encodings on load" pattern; the app already had all the
building blocks (`build_manual_chart`'s grammar-of-graphics channels,
`get_top_correlations`, `describe_correlation`) and just never had a
ranking layer sitting in front of them.

**Technical-depth argument.** This isn't just UI polish — the ranking is
a small, principled feature-selection heuristic: η² is a real ANOVA
effect-size statistic (not just "count distinct values"), correlation
strength is signed and thresholded consistently with the existing
Overview/Auto-Insights correlation language, and skew detection reuses
`pandas.Series.skew()` the same way the app's other distribution-shape
logic does. It's the kind of "which of these 40 possible charts is
actually worth showing you" judgment call a data analyst makes manually —
now automated and explainable (every suggestion states *why* it ranked).
Zero extra Gemini calls: it's a deterministic statistics layer, so it
works even when the API is rate-limited or absent, which is exactly the
constraint this sandbox has hit for 20 consecutive runs.

## 2. Screenshots

Saved to `.prism/runs/2026-08-11-run20/`:
- `desktop_dark_full.png` / `desktop_dark_explore.png` — 1440×900, dark theme
- `mobile_dark_full.png` / `mobile_dark_explore.png` — 390×844 (PWA mobile width), dark theme

Both show the panel rendering cleanly: readable contrast, no
overflow/clipping, chart cards in a responsive 2-column grid that
collapses to 1 column on mobile, caption text stating the ranking reason
and score under each chart. Zero console/page errors beyond the expected
Gemini `ERR_CONNECTION_RESET` (no live `GEMINI_API_KEY` in this sandbox —
the same constraint every run since Run 9 has logged; Explore Mode makes
zero Gemini calls itself, so this is unrelated to the feature).

**Light theme not separately re-shot this run.** The panel reuses only
pre-existing Streamlit primitives already verified in light theme by
every prior run's Auto-Generated Charts section directly above it
(`st.subheader`, `st.caption`, `st.plotly_chart`, `ui.render_empty_state`,
`theme.apply_plotly_theme()`) — no new CSS was written. The sidebar theme
selector has documented automation flakiness (Runs 10/13/16–19); chasing
it added risk without new coverage, so it was skipped per that precedent.

## 3. Research findings NOT built (ranked backlog for future runs)

| Feature | Effort | Notes |
|---|---|---|
| Large Excel ingestion (out-of-core reader) | M | Unaddressed since Run 14 scoped it out of the DuckDB item. |
| Light-theme dataframe/chart repaint-lag | S | Cosmetic, logged since ~Run 10. |
| Mobile + light theme simultaneous screenshot coverage | S | Automation gap (sidebar selector), not a product bug. |
| Live-Gemini end-to-end verification | — | Structural sandbox constraint (no API key), 20 consecutive runs. |
| Categorical-pair confounder cross-check (two-way ANOVA / interaction) | M | Run 19's own follow-on idea for the confounder detector — Pearson-only today. |
| Explore Mode "load into Manual Builder" click-through | S | This run ships suggestions as direct renders; wiring a button that pre-fills the Manual Chart Builder's selectboxes with a suggestion's encoding is a natural, low-risk follow-up. |
| Atlas voice/HUD slice beyond current maturity | M | Mic input, dual-backend TTS, keyword fast path, and proactive HUD are already built (Runs 9–17); further depth needs a genuinely new capability, not incremental polish. |

No fresh Phase 2 web research sweep was run this cycle — the routine has
now reused the standing backlog for 13 consecutive runs, and the highest-
value, longest-open item was actionable without a new sweep. This is the
same token-efficiency reasoning logged since Run 9; a fresh research pass
is a reasonable candidate for the *next* run if the backlog above thins
out further.

## 4. Interview notes (STAR-style, verbatim-usable)

> **Situation/Task:** Prism's Visualize tab had auto-generated charts
> per column type and a full manual "pick your own X/Y/color/facet"
> builder, but nothing in between — a user still had to know which of
> dozens of possible column combinations were actually worth looking at.
>
> **Action:** I designed and shipped an "Explore Mode" ranking layer that
> scores every candidate chart by a metric matched to its type — Pearson
> correlation strength for numeric pairs, ANOVA eta-squared effect size
> for categorical-vs-numeric splits, trend correlation for time series,
> and skew for single-variable shape — then surfaces the top-ranked
> suggestions automatically, each with a plain-English "why" and a score.
> It runs entirely offline (no LLM calls), so it works under API rate
> limits, and I wrote 9 unit tests covering the ranking logic, cardinality
> gating, deduplication, and an end-to-end "every suggestion actually
> renders" check before writing any UI code.
>
> **Result:** Closed a backlog item that had been open for 7 consecutive
> development cycles, added a genuine statistical-reasoning layer (not
> just cosmetic UI) to the app's EDA experience, and kept the full test
> suite green (395/395) with zero regressions.

## 5. Recommendation for next run's focus

1. **Explore Mode → Manual Builder click-through** (S effort, low risk):
   let a suggestion pre-fill the Manual Chart Builder's selectboxes
   instead of only rendering statically — turns "here's what to look at"
   into "here's what to look at, and now tweak it," closer to the full
   PyGWalker interaction model.
2. **Two-way ANOVA / interaction confounder follow-on** (M effort): Run
   19 logged this as the natural next step for `confounder_detection.py`
   — extends confounder checking from Pearson numeric pairs to
   categorical group comparisons.
3. If neither lands cleanly, a fresh Phase 2 web research sweep is
   overdue (13 runs on the same backlog) and would likely surface new
   candidates beyond what's listed above.

---

*Routine run 20 of the Prism autonomous improvement loop. One feature
shipped, verified, merged to `main`, and pushed. No incidents.*
