# Research — 2026-08-12 (Run 29)

Two targeted web searches this run (kept tight per this run's "use fewer
tokens" instruction — prior runs' broader competitor/community sweeps
(Runs 25-28) have all come up empty for new gaps against this codebase's
existing breadth, so this run searched for confirmation of the two gaps the
audit already surfaced rather than re-running a full four-source sweep).

1. **"data scientist interview 2026 cross-validation k-fold model evaluation
   what interviewers look for"** — confirms k-fold CV (esp. stratified) is a
   standing, frequently-asked screening topic: interviewers probe for
   understanding of *why* a single split is insufficient (bias/variance in
   the metric estimate), stratified-fold class-balance handling, and the
   k-size speed/variance trade-off. Prism's ML Lab currently has none of
   this (single 80/20 split only).
2. **"2026 AI data analysis tool confidence interval bootstrap automated EDA
   agent trend"** — 2026 agentic-analytics coverage (Gartner-cited 40%
   enterprise adoption figure) repeatedly pairs "proactive insight
   generation" with "confidence intervals" / "bootstrap" as the maturity
   signal that separates a point-estimate dashboard from an agentic
   analysis tool: outputs are expected to carry a confidence signal, not
   just a number.

## Ranked candidates

| Feature | Evidence | Depth (1-5) | Effort | Risk | Roadmap theme |
|---|---|---|---|---|---|
| Bootstrap CI on auto-insights' correlation findings | Search 2; audit gap (zero-click insights ship no uncertainty signal anywhere in the app) | 4 | S | Low — pure numpy resampling, no new deps, bounded cost via subsample+cap | Agentic AI analysis (auto-EDA) |
| K-fold cross-validation for ML Lab baseline models | Search 1; audit gap (single-split evaluation) | 4 | M | Low — sklearn `cross_validate`/`StratifiedKFold` already a transitive dep via existing sklearn usage | ML Lab / interview-signal, not agentic |

## Selection

**Built this run:** bootstrap CI on auto-insights' correlation findings.
Chosen over cross-validation because (a) it is the one candidate that
satisfies this run's required agentic-AI-analysis theme — CV strengthens
ML Lab but does not touch the zero-click auto-insight pipeline — and (b) it
is the smaller, more self-contained slice, appropriate given this run's
explicit "use fewer tokens" instruction. Full rationale and technical
design logged in `.prism/routine_log.md` before the branch was merged.

**Deferred to next run's backlog:** k-fold cross-validation for
`mllab.run_baseline_models()`. Not a dead end — no approach was attempted
and failed; simply not selected this cycle. `StratifiedKFold`/`KFold` +
`cross_validate` from sklearn (already an installed dependency) is the
obvious path: report mean ± std of each metric across k=5 folds alongside
(not instead of) the existing single-split numbers, so the "held-out test
set" story ML Lab already tells stays intact.

Not an Atlas/JARVIS-track feature this run (no voice/HUD work touched).
