# Prism Research — 2026-08-10, Run 8 (sixth independent session, same day)

Targeted pass, same rationale as Run 7: the broad four-source sweep
(industry practice, competitor tools, ecosystem tech, agentic-EDA research)
has been run repeatedly today and its findings are stable — this run
validates the two highest-priority carried-forward backlog items rather
than re-surveying from scratch.

## Candidate table

| Feature | Evidence | Depth | Effort | Risk | Roadmap theme |
|---|---|---|---|---|---|
| **CATE / subgroup heterogeneity (uplift-style)** | Direct extension of Run 7's ATT estimator — S/T-learner-style heterogeneous treatment effects are a standard follow-up question in causal-ML interview loops and uplift-modeling literature (Athey & Imbens); flagged as a new candidate by Run 7's own research | 5 | M | Low (reuses `estimate_causal_effect()` per subgroup — no new statistical machinery, no new dependency) | Agentic AI analysis (this cycle's required theme) |
| **polars/DuckDB large-file path** | Hex/Deepnote both default to a columnar/out-of-core engine for large files; flagged in every routine run since 2026-08-07 (7 consecutive) as needing a dedicated session; `duckdb` was already a Prism dependency (SQL Lab) but never wired into ingestion | 4 | M | Low (additive ingestion path, size-gated, silent fallback to the existing pandas path on any failure — not a rewrite of the analysis engine) | Ecosystem tech |
| PyGWalker drag-and-drop chart builder | Competitor-parity with Hex/Deepnote's visual query builders | 2 | L | Low | Competitor tools |
| Live-Gemini screenshot verification | Still blocked — no API key in this sandbox, eighth consecutive run | — | — | — | — |

## Selection

Both picked. **CATE by subgroup** satisfies this cycle's required agentic-AI-
analysis theme and is the most direct, lowest-risk way to extend Run 7's
causal work without re-deriving new statistical machinery (the subgroup
estimates are just `estimate_causal_effect()` re-run per level — the "hard
part," propensity matching, was already built and tested). **DuckDB
large-file ingestion** was re-scoped from "L / architecture-adjacent" (Run
7's assessment) down to **M / additive**: rather than replacing pandas as
the analysis engine (a rewrite the routine's guardrails correctly forbid),
it adds a size-gated ingestion path that produces the exact same pandas
DataFrame the rest of the app already expects — DuckDB only replaces *how*
the file gets read, not what downstream code receives. That reframing is
what finally made it safe to build after seven consecutive runs of correctly
deferring it as too large/risky to attempt.

## Not pursued (backlog, carried forward)

- PyGWalker-style drag-and-drop chart builder (still lower technical depth,
  cosmetic-adjacent — correctly deprioritized against depth-scoring features
  for another consecutive run).
- Live-Gemini screenshot verification (eighth consecutive run with no API
  key in the sandbox — both new narration helpers verified via unit tests +
  the graceful "No Gemini model available" fallback, same documented
  limitation as every prior run).
- **New candidate for next run:** now that DuckDB handles large-file
  *reads*, the natural next step is a DuckDB-backed (or polars-backed)
  path for the Cleaning/Auto Cleaner operations themselves on the sampled-
  down large-file case — today Auto Cleaner still operates purely on the
  in-memory pandas DataFrame post-sample, which is fine at 50k rows but
  worth re-checking once a genuinely huge (500MB+) file is tested against
  the new ingestion path.
