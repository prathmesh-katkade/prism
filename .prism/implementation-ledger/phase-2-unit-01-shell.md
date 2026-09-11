# Phase 2 · Unit 01 — application frame

**Objective:** Establish the production Next.js PRISM frame without implementing an analytical workflow.

**Delivered:** top bar, responsive left workspace rail, tabbed central workspace, contextual
inspector, theme/density controls, persistent visual layout preferences, and desktop-first CSS
visual language.

**Boundary:** All product areas remain migration bridges. The shell does not import `app.py`,
`modules/`, or any analytical service.

**Rollback:** Remove `apps/web/app`, `apps/web/src/components`, and shell-local state; the Phase 1
packages and legacy reference remain unchanged.
