# Phase 4 · Unit 02 — native Query Studio

**Delivered:** Native SQL Lab workspace with lazy Monaco through the PRISM Query Editor boundary,
SQL completion populated from verified schema metadata, multi-cursor Monaco behavior, formatting
action, parameter JSON, keyboard execution, source dialect display, plan/history/snippet/result
tabs, selectable result cells, contextual Atlas actions, and connector capability reporting.

**Data handling:** the browser receives only source metadata and result pages capped at 100 rows per
request. The server caps the query before result materialization, and the Query Studio renders each
page with the PRISM virtual-grid boundary.

**UX evidence:** component integration tests cover schema loading, pagination, page filtering/sort,
promotion, and execution state. Playwright covers the static keyboard-first surface plus an
unmocked browser-to-FastAPI flow: upload, Monaco Ctrl/Cmd+Enter execution, result rendering, plan,
and promotion into an Overview dataset.

**Result handling:** the grid uses `@tanstack/react-virtual` inside the PRISM Data Grid boundary.
It provides safe current-page sort/filter/copy actions and server-produced CSV/JSON export without
loading hidden result data into browser state. Cross-result server-side sort/filter remains a future
durable result-store concern.
