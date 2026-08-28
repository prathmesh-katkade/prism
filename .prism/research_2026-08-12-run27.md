# Run 27 Research — 2026-08-12

Five real web searches (WebSearch tool), summarized with candidate
ranking below.

## Searches run
1. "data analyst interview questions 2026 statistics A/B testing
   chi-square ANOVA power analysis"
2. "agentic EDA AI data analysis tool 2026 automatic anomaly narration
   insight generation"
3. "Julius AI Hex Notebook Agent Deepnote 2026 new features autonomous
   data analysis"
4. "Gemini 2.5 Flash free tier rate limits 2026 RPM RPD quota"
5. ""data storytelling" OR "narrative generation" automatic data analysis
   dashboard 2026 trend"

## Findings

**A/B testing / power analysis is still the single most consistently
named statistics topic** across every 2026 data-analyst interview-prep
source surveyed (LockedInAI, Dataquest, GeeksforGeeks, DataInterview,
GUVI) — explicitly including chi-square and ANOVA, not just t-tests:
"calculating required sample size using power analysis... analyzing
results by running a two-sample t-test **or chi-square test**." Prism
already shipped the t-test half of this in Run 25; chi-square/ANOVA power
was the explicitly-logged remaining gap in both Run 25's and Run 26's own
backlog notes, flagged twice as "a real follow-on, not approximated."

**Competitor tooling (Julius AI, Hex, Deepnote) in 2026** continues
converging on "one action → autonomous multi-step analysis" as table
stakes (confirms Run 26's read, nothing new to react to this cycle) —
Julius AI's plain-English conversational analysis, Hex's Notebook Agent,
Deepnote's real-time collaborative AI threads. No single competitor
feature surfaced that Prism's existing detector/orchestrator/hypothesis-
sweep/anomaly-driver surface doesn't already cover in some form; the
differentiator search results kept surfacing was less "which detector"
and more "how automatically does it fire and how rigorously does it
self-check" — which is exactly the axis Run 25/26/this run's feature
keeps extending (power self-checks, confounder cross-checks, narration
verification).

**Gemini 2.5 Flash free-tier limits**: sources disagree in specifics
(10 RPM/250 RPD vs 1,500 RPD/1M TPM depending on source/date), confirming
Run 26's own note that Google no longer publishes one universal table —
actual quota is project-specific, visible only in the AI Studio console.
No actionable change versus Run 26's existing caching/no-new-calls
discipline; this run's feature adds zero new Gemini calls regardless.

**Data storytelling / narrative generation**: "75% of data stories
will be generated automatically by AI" by 2026 per one industry source —
confirms narrative generation is a mainstream expectation, but Prism
already has extensive narration coverage (`narrate_sweep`,
`narrate_anomalies`, `narrate_anomaly_drivers`, `narrate_insights`,
`story_mode.py`, all narration-verified against ground-truth numbers via
`insight_verifier`/each module's own `verify_narration`). No fresh gap
surfaced here worth building against this cycle.

**Agentic-EDA-specific search (query 2)** mostly returned electronic
design automation (EDA the chip-design discipline) rather than
exploratory data analysis — a naming collision in 2026's search index,
not a useful signal either way; treated as a null result, not
re-attempted with different phrasing since queries 1/3/5 already covered
the relevant ground from other angles.

## Ranked candidate table

| # | Feature | Evidence | Technical depth (1-5) | Effort | Risk | Theme |
|---|---|---|---|---|---|---|
| 1 | **Chi-square + ANOVA post-hoc power in `annotate_power()`** | Query 1 — A/B testing prep guides explicitly name chi-square alongside t-tests; Run 25/26's own twice-logged backlog item | 4 — needs deriving Cohen's w directly from the raw chi-square statistic (not approximated from Cramer's V + table shape, the exact trap both prior runs flagged) and Cohen's f from eta-squared, verified against Cohen's (1988)/G*Power canonical reference tables (w=.3,df=1→n≈87; f=.25,k=3→n≈159) | M | Low — pure statsmodels, additive to an existing, already-tested pipeline; zero new Gemini calls | Agentic-AI-analysis (extends Hypothesis Sweep's automatic self-critique, same pattern Run 25 used to justify the theme fit) |
| 2 | Anomaly Drivers auto-narration bundling into `detector_runner` | Run 26's own backlog #2 | 2 | S | Low | Agentic-AI-analysis |
| 3 | Correlation (Pearson) post-hoc power via Fisher z-transform | Natural fourth test family, but a genuinely different noncentral distribution (not chi-square family) — would need its own careful validation pass, not a quick bolt-on | 3 | S–M | Low–Med (easy to get the CI/z-transform math subtly wrong without dedicated reference-value testing) | Stats-rigor, not agentic-theme |
| 4 | Role-specific / persona dashboards (CFO vs ops view) | Query 5 — 2026 dashboard trend | 2 | L | Med (real UX redesign, not a small module) | Neither required theme |
| 5 | New EDA/anomaly detector beyond current five | No fresh gap found; competitors aren't ahead here | — | — | — | — |

## Decision going in
Candidate #1 selected — see `.prism/routine_log.md` for the full
reasoning entry, written before implementation started per this run's
required order of operations. #2 turned out to be already effectively
resolved as a side effect of Run 26 (see `audit_2026-08-12-run27.md`),
which further supports #1 as the highest-remaining-leverage move rather
than something already covered. #3 (Pearson/Fisher-z power) is the
natural next backlog item, explicitly logged as such below.
