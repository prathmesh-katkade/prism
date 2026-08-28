# Current migration phase

**Phase:** 5.1 — AI Analyst stabilization complete locally

**Enabled:** native Overview, native SQL Lab, and native AI Analyst. AI Analyst uses compact
server-held context, evidence/provenance records, deterministic execution with optional local
Ollama fallback, SSE state/token transport, causal-evidence refusal, and guarded SQL Lab hand-off.
SQL Lab includes typed connector capabilities,
DuckDB/SQLite/MySQL read execution, schema metadata, plans, cancellation/timeouts, durable run
metadata, provenance, virtualized paginated results, contextual Atlas actions, and legacy parity.

**Still forbidden:** Clean, Visualize, Stats, Forecasting, ML, full autonomous Atlas behavior,
governance, desktop, and publication work. Streamlit AI Analyst remains the parity/rollback reference.
Streamlit SQL Lab remains available as the parity and rollback reference.
