# Prism Improvement Routine — Run Report
**Date:** 2026-08-12 · **Run 29**

## 1. What shipped

### Bootstrap confidence intervals on Auto-Insights' correlation findings

**What it does:** Prism's on-upload, zero-click Auto-Insights scan flags
strongly correlated column pairs (e.g. "'revenue' and 'cost' are strongly
correlated, r=0.87"). That number now ships with a 95% bootstrap confidence
interval — e.g. *"(95% CI: 0.81 to 0.91.)"* — and, when the interval is wide
despite a high point estimate (a real risk on small or noisy samples), an
explicit caveat: *"wide interval, treat with caution on this sample size."*

**Why it was chosen:** The audit (`.prism/audit_2026-08-12-run29.md`) found
that this was the one auto-surfaced insight category in the entire app that
shipped a number with zero uncertainty signal — every other numeric finding
surface (Hypothesis Sweep's post-hoc power badges, built across Runs 25-28)
eventually got one. Two targeted searches confirmed the gap was worth
closing now: 2026 agentic-analytics coverage repeatedly names "confidence
interval" / "bootstrap" output as the signal that separates a point-estimate
dashboard from a genuinely agentic analysis tool, and it's the one candidate
this run's research turned up that satisfies the cycle's required
agentic-AI-analysis theme (it strengthens the zero-click, on-upload pipeline
itself — not a manually opened tab).

**Technical-depth argument:** A point estimate with no confidence signal is
exactly the failure mode a data-science interview panel is trained to probe
("how sure are you?"). The fix isn't a lookup-table formula — Pearson r's
sampling distribution isn't simple to derive in closed form for an arbitrary
population, so this uses the standard nonparametric answer: percentile
bootstrap, resampling **row pairs** (not each series independently, which
would silently break the x/y linkage the correlation depends on) 500 times
and reading the 2.5th/97.5th percentile of the resampled r's. Cost is bounded
three separate ways so it can't become the slow path on a real upload:
bootstrapping only fires for "strong" (r≥0.85) pairs, a hard cap of 20 pairs
per scan, and a 5,000-row subsample ceiling per pair. A stress test (50K rows
× 25 mutually near-duplicate columns — the worst case a wide, redundant
dataset could produce) completes in ~1.4s, inside the module's documented
"<2s on upload" budget. The whole thing is pure numpy/pandas — zero new
dependencies, zero new Gemini calls, so it costs nothing against the
free-tier rate limit regardless of how many times a dataset is re-scanned.

## 2. Screenshots

All four captured live via Playwright against the running app (Chromium
1194, launched with an explicit `executable_path` — this sandbox couldn't
`playwright install` a fresh browser, matching the workaround Run 28 already
logged), driven with a planted `r=0.999` correlation
(`revenue`/`cost`, n=400):

- Desktop (1440×900) dark — `.prism/runs/2026-08-12-run29/desktop-dark-auto-insights.png`
- Desktop (1440×900) light — `.prism/runs/2026-08-12-run29/desktop-light-auto-insights.png`
- Mobile PWA width (390×844) dark — `.prism/runs/2026-08-12-run29/mobile-dark-auto-insights.png`
- Mobile PWA width (390×844) light — `.prism/runs/2026-08-12-run29/mobile-light-auto-insights.png`

All four show the new `(95% CI: 0.998 to 0.999.)` text rendering inline with
the existing correlation message — readable contrast in both themes, no
overflow/clipping, glass panel styling consistent, sidebar/Atlas HUD
unaffected. No new loading or empty state was needed: this is a text-only
addition to an existing, already-tested rendering path (`app.py` reads
`insight["message"]` verbatim — no UI wiring changed).

## 3. Research findings NOT built (backlog for future runs)

| Feature | Evidence | Depth | Effort | Why deferred |
|---|---|---|---|---|
| K-fold cross-validation for ML Lab (`mllab.run_baseline_models()`) | Search: "what interviewers look for" confirms CV is a standing screening topic; audit found only a single 80/20 split with no variance estimate | 4/5 | M | Doesn't touch the zero-click agentic pipeline this cycle required at least one feature to serve; not a dead end, just not this run's pick. `sklearn.model_selection.cross_validate` + `StratifiedKFold`/`KFold` (already a dependency), reporting mean±std per metric *alongside* the existing single-split numbers, is the direct next-run path. |

Full detail: `.prism/research_2026-08-12-run29.md`.

## 4. Interview notes (STAR-style, verbatim-usable)

**Bootstrap confidence intervals:**
> "In Prism's automated data-quality scanner, I noticed every auto-detected
> correlation reported a bare point-estimate r with no sense of how reliable
> that estimate actually was — a strong correlation on 20 rows looked
> identical to one on 20,000 rows. I implemented a percentile bootstrap:
> resampling row pairs with replacement 500 times to build the sampling
> distribution of r and surfacing the 95% interval alongside the point
> estimate, with cost controls (severity gating, a pair cap, row
> subsampling) so it stays well under the tool's 2-second scan budget even
> on a 50K-row, 25-column stress case. When the interval came out wide
> despite a high r, I made the tool say so explicitly, rather than let a
> lucky small sample read as a confident finding — that's the whole point of
> reporting a CI instead of a point estimate."

## 5. Recommendation for next run's focus

The strongest, most concrete backlog item is k-fold cross-validation for ML
Lab (table above) — it directly answers a top screening question this run's
research confirmed, is low-risk (sklearn already a dependency, additive not
replacing the existing single-split display), and gives the next run a clear
agentic-theme-independent slice if that cycle's priority theme shifts. Beyond
that: after 5 consecutive runs (25-29) of web research increasingly failing
to surface new competitor-gap features against this codebase's now very wide
feature surface, it may be worth a run that does a deliberate "wire audit"
instead — checking for detector modules with logic that exists in
`modules/` but isn't yet reachable from any `app.py` tab, rather than
continuing to search externally for net-new capability ideas.

---

*Run 29 summary appended to `.prism/routine_log.md`. Branch
`feature/correlation-bootstrap-ci` merged into `main` (`--no-ff`), pushed to
`origin/main` and to the designated dev branch
`claude/adoring-meitner-3nd7sz`. Fresh clone of `main` verified to launch
cleanly (`streamlit run app.py` → HTTP 200). Full suite: 550 → 559 passing,
zero regressions.*
