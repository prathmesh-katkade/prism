# Research — 2026-08-12, Run 30

Given the explicit token-efficiency instruction this run's trigger carries
(same as every run since Run 9), and given Run 29's own recommendation
("four consecutive runs found web research for a new competitor-gap
feature increasingly unproductive — try a structural self-audit of
`modules/` vs. `app.py` wiring instead"), this run skipped a fresh
four-source-class web sweep and instead relied on the structural audit
above, which surfaced two concrete, already-well-evidenced gaps.

| Feature | Evidence | Depth | Effort | Risk | Theme |
|---|---|---|---|---|---|
| Two-way ANOVA interaction check (Hypothesis Sweep) | Run 19 logged this exact follow-on ("categorical-pair-aware... two-way ANOVA / interaction check") as open backlog for 10 consecutive runs; `cross_check_confounders()`'s own docstring explicitly excludes ANOVA/chi2 pairs | 4/5 — genuine interaction-effect statistics (Type II ANOVA), FDR-corrected across candidates | M | Low — pure statsmodels, deterministic, additive UI | Agentic AI analysis (required this cycle) |
| K-fold cross-validation (ML Lab) | Run 29 named this "the natural next-run slice" after shipping bootstrap CIs elsewhere; a single 80/20 split with no variance estimate is a standing, frequently-asked interview screening topic | 4/5 — variance estimation via resampling, a core ML-evaluation-rigor skill | S–M | Low — sklearn `cross_validate` already available, no new deps | ML capability / reproducibility |

**Selected: both.** The interaction check satisfies this cycle's mandatory
agentic-AI-analysis theme (it extends the sweep's zero-click, on-upload-
adjacent automated statistical pipeline with a genuinely different
follow-up question than the existing confounder check). K-fold CV is the
depth-over-breadth companion pick — closing the single strongest backlog
item the last run left open, at low implementation risk since it reuses
`run_baseline_models()`'s existing preprocessing pipeline verbatim inside
an sklearn `Pipeline`.

**Not selected / still open:** PyGWalker-style chart builder's remaining
interaction-model gap (long-standing, no new evidence this run), large
Excel ingestion (no out-of-core reader), light-theme dataframe/chart
repaint-lag (cosmetic, three-plus sessions already invested), live-Gemini
screenshot verification (structural sandbox constraint — no
`GEMINI_API_KEY` configured here, 20th+ consecutive run). Not an
Atlas/JARVIS-track feature this run (no voice/HUD work touched).
