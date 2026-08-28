# Prism Research — 2026-08-10, Run 4

Light targeted web pass (two searches) rather than a full four-source sweep —
this run's scope was already well-defined by Run 3's own "recommendation for
next run" list plus the routine's standing backlog, so research here mainly
validated the ensemble-anomaly pick rather than open-ended discovery.

## Ranked candidates

| Feature | Evidence | Depth | Effort | Risk | Roadmap theme |
|---|---|---|---|---|---|
| **Ensemble anomaly consensus (LOF + DBSCAN + IsolationForest)** | Ensembles of multiple anomaly detectors are described as standard practice in production fraud-detection systems (Stripe/PayPal-style); hybrid IsolationForest+DBSCAN papers show accuracy gains over single-method detection ([ScienceDirect hybrid iForest-DBSCAN](https://www.sciencedirect.com/science/article/abs/pii/S0957417425020007), general search synthesis) | 5 | M | Low | Agentic AI (self-verifying/consensus pattern) + Hell Mode-adjacent statistical rigor |
| Self-verifying LLM data-science agents (general pattern) | Recent survey of LLM-based data-science agents documents function-calling + code-interpreter + verification loops as the emerging standard shape for agentic EDA tools ([arXiv 2510.04023](https://arxiv.org/html/2510.04023v1)) | — | — | — | Confirms the anomaly-narration/ensemble-narration pattern already used across 3 runs is well-aimed, not a pivot signal |
| polars/DuckDB large-file backend | Still the highest-depth open backlog item per every prior run's research; not re-researched this run (no new evidence needed — decision to defer was already made 3x) | 5 | L | Med | Ecosystem tech |
| Feature Selection Engine (mutual info/RFE/L1) | Standing backlog item, ML Lab-adjacent | 4 | M | Low | ML capability |
| `google-generativeai` → `google-genai` migration | Standing backlog item — old SDK's `FutureWarning` still fires on every test run | 2 (hygiene) | M | Med (touches 4 call sites) | Maintenance |

## Why ensemble anomaly consensus over the other open items

1. **Required this cycle:** the routine mandates at least one selected
   feature serve the agentic-AI theme. Ensemble consensus + Gemini
   disagreement-narration is a direct implementation of the "self-verifying
   analysis agent" pattern research keeps surfacing (cross-check a claim
   against independent methods before trusting it) — a stronger fit for
   that theme than a pure UI feature would be.
2. **Genuinely new, not a rebuild:** confirmed via `modules/anomaly.py`
   before starting — only IsolationForest existed. `data_engine.py`
   already has a comprehensive "Data Health Score" (0-100, 5-component
   breakdown, already exportable via `report_writer.generate_pdf_report`/
   `generate_cleaning_certificate`) — the backlog's "Data Quality Score
   with exportable scorecard" item turned out to already be shipped in
   substance under a different name; building it again would have
   violated the routine's "never rebuild a shipped feature" rule. Caught
   this before writing any code, not after.
3. **Bounded, well-scoped effort:** three sklearn models over the same
   numeric columns, no new external dependency (scikit-learn already a
   requirement), reuses the existing narration/caching/fingerprint
   plumbing from `anomaly.py` rather than inventing a parallel system.

## Not built (carried forward)

Same as Run 3's list minus the two items this run's small fixes closed
(mobile Atlas overlap, light-theme dataframe styling): polars/DuckDB
backend, Feature Selection Engine, `google-generativeai` migration, Data
Quality Score scorecard (**now known to already exist** — see finding
above, remove from future backlogs as a "not built" item; if anything is
still missing it's a dedicated *scorecard export UI entry point*, not the
scoring logic itself).
