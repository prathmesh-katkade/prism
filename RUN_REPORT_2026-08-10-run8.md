# Prism Improvement Routine — Run Report, 2026-08-10 (Run 8)

Sixth independent same-day session of the Prism autonomous improvement
routine. `origin/main` was at Run 7's tip (`f585a54`) with no drift (local
`main` in this sandbox was stale and fast-forwarded before any branch work
started — see the routine log for detail). Full history of all seven prior
runs is in `.prism/routine_log.md`.

## What shipped

### 1. CATE by subgroup — heterogeneous treatment effects

**What it does:** extends the existing Causal Effect Estimator panel with
a "Does the effect vary by subgroup?" section. After estimating a pooled
Average Treatment Effect, the user can pick a categorical column (2-10
groups) and Prism re-runs the identical propensity-score-matching estimate
within each subgroup level, then compares:

- **Sign reversal** — the treatment helps one segment and actively hurts
  another. Surfaced as a hard "⚠️ Sign reversal detected" callout, since a
  blanket rollout would be the wrong call.
- **Statistically meaningful heterogeneity** — subgroup confidence
  intervals that don't overlap the pooled estimate's CI, even without a
  sign flip.
- Otherwise, an explicit "effect looks consistent across subgroups" —
  staying silent about heterogeneity that isn't there is as important as
  flagging heterogeneity that is.

Results render as a red/green bar chart (subgroup ATT, colored by sign)
with 95% CI error bars against a dashed pooled-ATT reference line.

Verified live end-to-end via Playwright against a synthetic campaign
dataset with an injected opposite-signed effect across three regions
(Metro +8, Rural -6, Tier2 +1 on `monthly_revenue`) — the panel correctly
matched, detected, and called out the sign reversal, with a covariate
balance table showing the match improved `tenure_months`'s standardized
mean difference from -1.20 to 0.10.

**Why it was chosen:** this cycle's required agentic-AI-analysis pick, and
the most direct, lowest-risk extension of Run 7's causal work — it reuses
`estimate_causal_effect()` per subgroup rather than introducing new
statistical machinery (no S/T/X-learner build-out was needed; matching was
already built and tested).

**Technical-depth argument:** a single pooled ATT is a genuinely dangerous
number to act on if the underlying effect is heterogeneous — this is the
uplift-modeling / uplift-decision question ("who should actually get the
treatment?") that separates "ran a t-test" from "understands treatment
effect heterogeneity," a standard checkpoint in causal-ML interview loops.
The sign-reversal case is the sharpest version of this: a stakeholder
looking only at the pooled number would make the wrong call.

### 2. DuckDB out-of-core ingestion for large CSV uploads

**What it does:** for CSV uploads at or above 15MB, Prism now routes
ingestion through DuckDB's `read_csv_auto()` instead of reading the whole
file into pandas memory first. DuckDB counts the file's total rows and
pulls a random reservoir sample directly from disk — pandas only ever sees
the (already right-sized) sample, not the full file. Below the threshold,
or on any DuckDB failure, behavior is unchanged via silent fallback to the
pre-existing pandas path.

Verified end-to-end via Playwright: uploaded a synthetic 500,000-row,
16.6MB transactions CSV. Prism's existing "Smart Sampling" flow correctly
reported the full 500,000-row count (served by the new DuckDB path), and
choosing a 50,000-row random sample loaded cleanly into Overview — the
sampled `transaction_id` values were visibly shuffled (e.g. 54736, 381891,
440354, ...) rather than sequential, confirming a genuine random draw
across the whole file rather than the old "keep the first N rows"
behavior.

**Why it was chosen:** closes the single longest-standing backlog item in
this routine's history — flagged in every run since 2026-08-07 (seven
consecutive) as needing dedicated attention, and correctly deferred each
time as "architecture-adjacent." This run found a framing that respects
the routine's no-rewrite guardrail: DuckDB only replaces *how* the file is
read, not what the rest of the app receives (still a plain pandas
DataFrame) — so it shipped as a scoped, additive ingestion path rather
than the dedicated architecture session prior runs assumed it would need.

**Technical-depth argument:** recognizing when an in-memory, single-
threaded read is the wrong tool and reaching for an out-of-core engine —
without destabilizing everything downstream that depends on the existing
interface — is exactly the kind of judgment a senior data engineer is
expected to exercise on a real large-file pipeline, not just "I imported
pandas."

**Bug caught and fixed during build (not shipped as a separate item):**
DuckDB's `ignore_errors=true` CSV reader doesn't always fail loudly on
malformed input — on a banner-row CSV it mistook the banner text for the
real header and silently produced a "successful" all-null one-row
DataFrame (which then vanished entirely after the existing
`dropna(how="all")` step, returning an empty-but-"ok" result instead of an
error). Caught by a test before it ever reached the UI; fixed by treating
an all-null DuckDB parse as a failure and falling back to pandas, which
already has dedicated banner-row recovery logic.

## Screenshots

- `.prism/runs/2026-08-10-run8/01_causal_result_desktop_dark.png` —
  pooled Causal Effect Estimator result, desktop dark
- `.prism/runs/2026-08-10-run8/02_cate_heterogeneity_desktop_dark.png` —
  CATE panel: sign-reversal callout + per-subgroup bar chart, desktop dark
- `.prism/runs/2026-08-10-run8/03_cate_heterogeneity_mobile_dark.png` —
  ~390px PWA viewport, no overflow/clipping
- `.prism/runs/2026-08-10-run8/04_cate_heterogeneity_desktop_light.png` —
  Arctic (Light) theme, theme switched before panel interaction (see the
  audit file for the repaint-lag caveat when switched *after*)
- `.prism/runs/2026-08-10-run8/05_large_file_duckdb_ingest.png` —
  Smart Sampling correctly reporting a 500,000-row upload
- `.prism/runs/2026-08-10-run8/06_large_file_loaded_overview.png` —
  the resulting 50,000-row random sample loaded into Overview

## Research findings not built (ranked backlog for future runs)

| Feature | Depth | Effort | Notes |
|---|---|---|---|
| PyGWalker-style drag-and-drop chart builder | 2 | L | Competitor-parity with Hex/Deepnote, lower technical depth — now the longest-standing unaddressed item |
| DuckDB/polars-backed Auto Cleaner path for very large samples | 3 | M | New candidate — today's fix covers the *read* path only; post-load cleaning still runs purely in-memory pandas on the sampled-down frame |
| Live-Gemini screenshot verification | — | — | Eighth consecutive run with no API key in the sandbox; both new narration helpers verified via unit tests + the graceful-fallback path |

## Interview notes (STAR-style, verbatim-usable)

> **CATE by subgroup:**
> **Situation:** Prism's causal-effect estimator reported a single pooled
> treatment effect, which can hide a treatment that helps one segment and
> hurts another.
> **Task:** Extend the estimator to test whether the effect actually holds
> across subgroups, not just on average.
> **Action:** Re-ran the existing propensity-score-matching estimator
> within each subgroup level (a lightweight T-learner-style approach reused
> from the pooled estimator, not a from-scratch build), then compared
> subgroup confidence intervals against the pooled estimate to flag sign
> reversal and non-overlapping-CI heterogeneity.
> **Result:** Shipped with 8 passing tests, including a synthetic-data
> fixture with an injected opposite-signed effect that the estimator
> correctly recovered and flagged end-to-end in a live Playwright run —
> catching exactly the "average effect looks fine, but the real story is
> two segments moving in opposite directions" failure mode a naive pooled
> analysis would miss.

> **DuckDB large-file ingestion:**
> **Situation:** Prism's file loader read an uploaded CSV fully into pandas
> memory before any size check, which doesn't scale to real large-file
> uploads and had been flagged as a gap for seven consecutive prior
> improvement cycles.
> **Task:** Add out-of-core ingestion for large files without rewriting the
> app's core data pipeline.
> **Action:** Added a size-gated DuckDB path that counts rows and pulls a
> random sample directly from disk, with the rest of the app still
> receiving a plain pandas DataFrame — and, after catching a real bug where
> DuckDB's own error-tolerant CSV parser silently produced a garbage
> all-null result on malformed input, added a validity check with a clean
> fallback to the existing pandas recovery logic.
> **Result:** Shipped with 10 passing tests and a live 500,000-row/16.6MB
> upload verified end-to-end — confirmed the resulting sample was a true
> random draw across the whole file (non-sequential IDs), not the old
> biased "first N rows" truncation, with zero behavior change for files
> under the size threshold.

## Recommendation for next run

1. **PyGWalker-style drag-and-drop chart builder** is now the longest-
   standing unaddressed backlog item (competitor-parity gap vs. Hex/
   Deepnote) — reasonable next pick if the theme allows cosmetic/UX-adjacent
   work, though it should be paired with a genuinely agentic feature per
   this cycle's priority rule.
2. **DuckDB/polars path for Auto Cleaner on very large samples** — the
   natural follow-on to this run's ingestion fix; worth testing against an
   actually huge (500MB+) file rather than the 16.6MB fixture used here to
   see whether post-load cleaning operations need the same treatment.
3. Continue re-checking the light-theme repaint-lag finding (now precisely
   reproducible — see the audit file) if a run has spare capacity; it's
   cosmetic/timing-only and has already absorbed three sessions'
   investigation, so it shouldn't block higher-depth feature work.

---

*Full technical detail, the light-theme repaint-lag repro, and the local-
`main`-staleness incident note are in `.prism/audit_2026-08-10-run8.md` and
`.prism/research_2026-08-10-run8.md`.*
