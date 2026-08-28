# Research — 2026-08-10, Run 6

Light, targeted web pass this run — five prior sessions already did a full
four-source-class sweep across 2026-08-07 and Runs 3-5 today, and the
standing conclusion (agentic-AI-analysis theme is well-aimed, no pivot
needed) still holds. This run's search was aimed at validating the two
specific candidates selected, not re-surveying the whole landscape.

## Ranked candidates (this run's additions)

| Feature | Evidence | Depth (1-5) | Effort | Risk | Roadmap theme |
|---|---|---|---|---|---|
| Confounder / Simpson's Paradox detector | Active 2026 research area — arXiv papers on automated Simpson's Paradox detection and non-redundant confounder discovery ([arXiv:2511.00748](https://arxiv.org/pdf/2511.00748), [De-paradox Tree, arXiv:2603.02174](https://arxiv.org/pdf/2603.02174)); 2026 data-analyst/data-scientist interview guides explicitly flag confounding-variable detection and "correlation vs. causation" as the line between junior and senior candidates ([wecreateproblems](https://www.wecreateproblems.com/interview-questions/data-analysis-interview-questions), [datainterview.com statistics guide](https://www.datainterview.com/blog/statistics-interview-questions)) | 5 | M | Low (pure pandas/numpy/scipy arithmetic, no new dependency) | Agentic AI analysis (required this cycle) |
| `google-generativeai` -> `google-genai` migration | Google's own deprecation notice (raised as a `FutureWarning` on every import in this repo); four consecutive prior routine runs flagged it as needing a dedicated session | n/a (reliability/debt, not a feature) | M | Low — contained to 2 files once traced (see audit) | Free-tier reliability (all themes depend on Gemini staying callable) |

## Carried forward from prior runs (still open, not re-researched this run)

- polars/DuckDB large-file path — architecture-adjacent, six runs now.
- PyGWalker-style drag-and-drop chart builder — competitor parity
  (Hex/Deepnote), effort L, UI-breadth over statistical depth.
- Advanced causal-inference tooling beyond this run's confounder check
  (e.g. propensity-score matching, diff-in-diff) — the 2026 interview
  research above suggests this is a legitimate deeper follow-on to this
  run's pick, not a duplicate of it (this run ships *detection*; matching/
  diff-in-diff would be the next layer, *correction*). Logged as a new
  backlog candidate, effort L, depth 5.

## Selection

Two features (not three) — the Gemini SDK migration was the standing
"needs a dedicated run" item four prior runs deferred, and turned out
small enough in scope (once actually traced — see audit) to pair with one
real feature in the same run rather than consuming the whole session on
its own. Confounder detection was picked as the required agentic-AI-
analysis pick: it runs unprompted on every dataset load, same as Auto-
Insights/Ensemble Anomaly Consensus/Hypothesis Sweep before it, extending
the same "detect, don't wait to be asked" pattern to a genuinely new
statistical dimension (relationship *validity*, not just presence).

Full reasoning and outcome logged in `.prism/routine_log.md`.
