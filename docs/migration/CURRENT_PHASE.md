# Current migration phase

**Phase:** 6A/6B — Clean and Visualize vertical slices complete locally

**Enabled:** native Overview, native SQL Lab, native AI Analyst, native Clean, and native Visualize.
Clean and Visualize both operate on the same server-held `overview.store` dataset that Overview,
SQL Lab, and AI Analyst already share — a Clean transformation is a new dataset revision, visible
immediately to every other native workspace under the same `dataset_id`, with no dataset ever
mutated in place. Clean issue detection reuses Overview's own deterministic quality profile (no
recomputation), offers preview-before-apply for every transformation, and undo as a linear
revision stack. Visualize suggests a chart mark deterministically from column types and intent,
aggregates data server-side (the browser never receives raw rows), and flags trust issues
(category truncation, overplotting) as warnings rather than silently misleading. Both expose
Atlas as contextual, evidence-grounded actions — explain an issue/chart, propose a fix,
identify anomalies — never as autonomous unattended mutation.

**Still forbidden:** Stats, Forecasting, ML, full autonomous Atlas orchestration, governance,
desktop, and publication work. Streamlit Clean/Visualize (`modules/cleaning.py`,
`modules/visualization.py`, `modules/autocleaner.py`) remain the parity/rollback reference.
Streamlit AI Analyst and SQL Lab remain available as parity/rollback references from Phase 5.
