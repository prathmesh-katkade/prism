# Phase 3 · Unit 01 — analytical core and contracts

**Objective:** Establish a framework-free, deterministic Overview profile and canonical HTTP contract.

**Delivered:** `prism-overview-analytics` provides semantic typing, missingness, duplicate and IQR
signals, explainable health, column profiles, distributions, correlations, suggestions, and a
legacy-equivalent privacy health deduction. FastAPI exposes typed dataset, profile, rows, provenance,
and Atlas models; TypeScript contracts are generated from OpenAPI.

**Parity:** `tests/overview/test_overview_parity.py` compares legacy `data_engine` and `profiling`
outputs with the new analytical service on a representative frame, PII health deduction, low-signal,
empty-column, duplicate, missing, date, and outlier cases. Exact equality is required for legacy
quality/profile/health values; correlation output uses six-decimal rounding.

**Rollback:** Remove the new package and Overview endpoints/contracts. Legacy Streamlit behavior is
unchanged.
