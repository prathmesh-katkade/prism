# Research — 2026-08-10, Run 9 (seventh independent session, same day)

Lightweight pass: this is the ninth cycle of the day. Runs 1-8 already ran
full four-source-class sweeps (industry practice, competitor tools,
ecosystem tech, agentic-EDA research) — see `.prism/research_2026-08-10-run8.md`
and earlier files for the full backlog table, which is still current
(confirmed against Run 8's own "Recommendation for next run" section).
Per this run's "use fewer tokens" directive, this pass reuses that
standing research rather than re-running web searches for ground already
covered today, and only adds what's new.

## Standing backlog (carried forward, still valid)

| Feature | Evidence | Depth | Effort | Risk | Theme |
|---|---|---|---|---|---|
| PyGWalker-style drag-and-drop chart builder | Hex/Deepnote parity, flagged 4 consecutive runs | 2 | L | Low | Competitor parity |
| DuckDB/polars path for Auto Cleaner on large samples | Follow-on to Run 8's ingestion fix | 3 | M | Low | Ecosystem tech |
| Light-theme dataframe repaint-lag | Cosmetic/timing, 3 sessions investigated | 1 | S | Low | Polish |
| Live-Gemini screenshot verification | No API key in sandbox, 8 consecutive runs | — | — | — | N/A (env-gated) |

## New candidate for Run 9

**Agentic Insight Orchestrator** — Prism now has *seven* independent
detector modules that each run and render standalone: `auto_insights`
(skew/correlation/missingness/outliers/imbalance), `anomaly`
(IsolationForest ensemble), `confounder_detection` (Simpson's Paradox),
`causal_inference` (ATT + CATE subgroup), `drift`, and `insight_verifier`
(numeric-claim fact-checking against the loaded frame). Each fires
independently; nothing cross-checks or ranks findings *across* detectors,
and nothing tells the user which of the dozen things Prism just found
actually matters most. This is the textbook next step in agentic-EDA
research (self-verifying multi-agent analysis pipelines, e.g. AutoGen/
LIDA-style "planner → executors → critic" patterns, and the "insight
prioritization" stage most auto-EDA tools — ydata-profiling, Sweetviz,
Julius AI — skip entirely, presenting a flat list instead).

- **Evidence**: direct extension of Prism's own `insight_verifier`
  precedent (self-verification is already a proven pattern in this
  codebase); matches the "self-verifying analysis agents" pillar of this
  cycle's required agentic-AI-analysis research area; addresses a real
  UX gap none of the 8 prior runs touched (cross-detector synthesis).
- **Technical-depth score**: 5 — orchestration logic, dedup/contradiction
  detection across statistically distinct methods (e.g. a confounder flag
  vs. a causal ATT on the same variable pair), and a severity-ranking
  synthesis step, reusing `insight_verifier`'s verification pattern rather
  than duplicating it.
- **Effort**: M (pure orchestration over existing modules + one new
  ranking/dedup module; no new external dependency).
- **Risk**: Low — read-only over existing detector outputs, additive UI
  section, fails silently (empty state) if fewer than 2 detectors have
  findings.
- **Roadmap theme**: agentic v2 (this cycle's required theme).

## Selection

Run 9 ships **one** feature — the Agentic Insight Orchestrator — per the
"use less tokens" directive for this cycle (narrower scope than Runs 5/8's
two-feature bundles). It directly satisfies the cycle's mandatory agentic-
AI-analysis theme and turns Prism's existing detector sprawl into a real
differentiator: an agent that runs its own sub-agents (the detectors),
notices when they disagree, and tells the user what to look at first.
PyGWalker and the Auto Cleaner DuckDB follow-on remain backlog for the
next run with spare budget for L-effort UI work.
