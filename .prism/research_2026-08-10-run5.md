# Research — 2026-08-10 (Run 5)

Web research synthesized across the four required source classes. Full-depth
live browsing wasn't exhaustive this run (token-budget guardrail from the
routine brief) — searches targeted the two candidate features hardest,
since the audit already narrowed the gap to a specific pair.

## Ranked candidate table

| Feature | Evidence | Depth (1-5) | Effort | Risk | Roadmap theme |
|---|---|---|---|---|---|
| **Hypothesis Sweep** (auto-run every viable pairwise stat test + Benjamini-Hochberg FDR correction) | Multiple-testing correction is standard practice for exploratory analysis with many simultaneous tests ([ScienceDirect: to adjust or not to adjust](https://www.sciencedirect.com/science/article/pii/S0895435625000216), [arXiv 2411.10647 FDR overview](https://arxiv.org/html/2411.10647v1)); "agentic EDA" tooling research explicitly connects automated hypothesis generation to needing FDR-aware selective inference in 2026 online-testing work ([arXiv 2605.13916](https://arxiv.org/html/2605.13916v1)) | **5** — directly demonstrates the difference between "ran a test" and "ran science correctly"; almost no portfolio project does this | M | Low (pure stats/pandas, no new deps — statsmodels already vendored) | **Agentic AI analysis (required this cycle)** |
| **Feature Selection Engine** (mutual info + L1/Lasso + RFE consensus) | Confirmed as core, frequently-asked ML interview material across current guides ([ProjectPro 100+ DS interview Qs](https://www.projectpro.io/article/100-data-science-interview-questions-and-answers-for-2021/184), [Medium: 10 sklearn feature-selection techniques](https://medium.com/@bhagyarana80/10-feature-selection-techniques-built-into-scikit-learn-that-every-data-scientist-should-know-f63bc5fb77d7), [Infermatic: RFE + MI in ensembles](https://infermatic.ai/ask/?question=How+do+recursive+feature+elimination+%28RFE%29+and+mutual+information+%28MI%29+contribute+to+feature+selection+in+ensemble+models%3F)) | **4** — extends ML Lab's existing feature-engineering assistant with the natural next step; reuses the ensemble-consensus pattern Run 4 already validated for anomaly detection, so it also demonstrates *pattern reuse discipline* | M | Low (sklearn only, already a dependency) | ML Lab depth |
| polars/DuckDB large-file pandas replacement | Competitor tools (Hex, Deepnote) lean on DuckDB/polars for large files; SQL Lab already uses DuckDB | 4 | L | **High** — architecture-adjacent, touches `data_engine.py`'s core pipeline | Ecosystem tech |
| `google-generativeai` → `google-genai` SDK migration | Old SDK deprecated, `FutureWarning` on import | 2 (maintenance, not a capability) | M | Medium — touches every Gemini call site, needs full regression pass | Maintenance |
| Standalone exportable Data Quality Scorecard entry point | Run 4 confirmed the underlying scoring/export logic already exists; only a dedicated UI entry point would be new | 2 | S | Low | Portfolio polish |
| PyGWalker-style drag-and-drop chart builder | Competitor tools (Hex, Deepnote) offer visual/no-code chart building | 3 | L | Medium — new dependency, large UI surface | Ecosystem tech / competitor parity |

## Selection reasoning

Both **Hypothesis Sweep** and **Feature Selection Engine** are picked —
depth over breadth, matching Run 1's precedent when a run's two best
candidates are both real technical-depth adds with low risk rather than
diluting effort across three. Hypothesis Sweep satisfies this cycle's
mandatory agentic-AI-analysis theme (automatic hypothesis generation +
testing, statistically self-correcting via FDR — the "self-verifying
analysis agent" pattern applied to classical stats instead of ML anomaly
detection). Feature Selection Engine is not an Atlas-copilot-track feature
(no voice/HUD/proactive-surface component), so it doesn't count against
this run's one-Atlas-feature cap — that cap stays unspent this run, which
is fine; the brief requires *at most* one Atlas slice per run, not one every
run. polars/DuckDB and the SDK migration are deferred again per the
guardrail against architecture rewrites in an unattended run — five
consecutive runs of research agreeing they need a dedicated session is
itself now a signal for the human to schedule that session deliberately
rather than an autonomous run picking it up piecemeal.
