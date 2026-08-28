# Run 28 research — 2026-08-12

Quick, real web research pass (per routine Phase 2), following Run 27's own
recommendation to evaluate both logged options with fresh evidence before
picking.

## Searches run

1. `correlation Pearson power analysis Fisher z-transform data analyst
   interview 2026` (industry-practice / interview-prep source class)
2. `Hacker News discussion data analysis tool AI agent 2026 what's missing`
   (community-discussion source class)
3. `reddit dataisbeautiful OR r/datascience 2026 what data analysis tool
   feature do you wish existed` (community-discussion source class,
   different community)

## Findings

**Search 1 (industry-practice):** confirms the Fisher z-transform is the
standard, well-established technique for correlation power/CI work —
`z = 0.5 * ln((1+r)/(1-r))`, approximately normal with SE = `1/sqrt(n-3)`,
independent of the true correlation. This is exactly the "genuinely
different noncentral distribution family" both Run 25/26/27 correctly
flagged as needing its own dedicated treatment rather than a quick bolt-on
— but it's a *closed-form, well-documented* transform (unlike, say,
chi-square/ANOVA power which needed careful effect-size derivation
choices), meaning the implementation risk is genuinely low if reference-
value-verified before shipping, matching this run's guardrail ("technical
depth over cosmetic polish... low risk"). Sources: MetricGate's power-
analysis-for-correlation and Fisher's-Z-transformation docs, UCLA's SAS
FAQ on the Fisher z test for a single correlation.

**Search 2 & 3 (community-discussion source class, two different
communities — HN and Reddit data subs):** neither search surfaced any
concrete, actionable, Prism-relevant feature gap. Search 2 returned mostly
meta-commentary about the AI-agent hype cycle in general (infra/reliability/
pricing discourse), nothing about data-analysis tooling gaps specifically.
Search 3 returned no actual discussion threads at all — general software
directory listings only, no real community sentiment captured. This
reconfirms Run 26/27's finding that the "competitor tooling / community
research" angle has been thoroughly mined this week and isn't producing
new evidence-backed candidates from a web search alone, even after
switching source (HN, then a different subreddit) as Run 27 suggested
trying.

## Ranked candidates

| Feature | Evidence | Depth | Effort | Risk | Theme |
|---|---|---|---|---|---|
| Correlation (Pearson) post-hoc power via Fisher z | Strong — confirmed again this run (3rd consecutive research pass naming it), closed-form technique, well-documented reference formulas | High (completes rigorous power-check set for all 4 test families Hypothesis Sweep runs) | S | Low (closed-form transform, easy to reference-value-verify) | Extends existing self-verifying-agent pattern (Hypothesis Sweep asking itself "was this significant correlation even well-powered?") — same theme fit Run 25/27 argued for t-test/chi2/ANOVA |
| New agentic-AI angle (community-discussion source) | Weak — two different community-discussion searches (HN, Reddit) both returned no concrete gap this run | — | — | — | Required theme, but no real candidate surfaced |

## Decision

**Selected: correlation (Pearson) post-hoc power via Fisher z-transform**,
extending `modules/experiment_design.py` / `hypothesis_sweep.
annotate_power()` to the fourth and final test family Hypothesis Sweep
runs (Pearson correlation — t-test, chi-square, and ANOVA are already
done). This is explicitly sanctioned by this run's own instructions
("pick ONE feature that satisfies the required agentic-AI-analysis theme
OR is the correlation-power backlog closer") — chosen over forcing a
fresh agentic feature this run because two independent community-
discussion searches (a new source class, per Run 27's specific
suggestion) produced no real evidence-backed alternative, while the
correlation-power item has three consecutive runs' worth of confirming
evidence and a low-risk, well-scoped path to completion. Closes the
power-check backlog set fully — no more "we can check t-test/chi2/ANOVA
power but not correlation power" gap.
