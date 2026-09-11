# Migration parity status

| Workflow | Legacy reference | Current state | New parity evidence |
|---|---|---:|---|
| Overview | `app.py:Overview` | native, legacy retained | deterministic quality/profile/health parity; typed API profile/rows/Atlas tests |
| SQL Lab | `modules/sql_lab.py` | native, legacy retained | DuckDB/local exact parity; live MySQL result/schema/type/null/order/error/plan/cancel/timeout parity; typed API and unmocked browser flow |
| AI Analyst | `modules/ai_analyst.py` | native, legacy retained | compact-context/evidence/provenance contract; SQL Lab-only execution hand-off; causal refusal; SSE token/state/fallback/cancellation coverage; live browser/API SQL-evidence round trip |

Overview, SQL Lab, and AI Analyst are native workflows at the Phase 5.1 checkpoint. Every later
workflow remains legacy-only. A bridge identifies the reference and parity gate; it is not a
second mental model or an implementation substitute.
