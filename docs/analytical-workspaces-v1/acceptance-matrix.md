# Analytical workspaces v1 acceptance matrix

Snapshot: 2026-10-02, branch `prism/analytical-workspaces-v1` at `80d14d6` plus the preserved working-tree report changes. This matrix is updated as gates and UI evidence become available. “Implemented” describes code found; “verified” means a fresh gate or direct exercise in this worktree.

| Area | Actual starting state | Fresh verification / gap |
|---|---|---|
| Clean operations | Category mapping, duplicate survivorship, explicit date format, validation rules implemented | Backend baseline passed; full recipe editor and detailed review UI partial |
| Clean recipes | Durable versioned recipes; preview and one-use review ticket; data and provenance published in one transaction | Injected later-step failure and retry verified; multi-step editor and detailed row inspection pending |
| SQL Lab | Parsed join diagnostics, CTE inspection, declared-key comparison and result handoffs implemented | UI workflow and isolated integration verification pending |
| Visualize | Scatter/box/trend fixes and server mark drilldown implemented | Linked filters, shared scales, annotations, persisted chart UI and full visual matrix pending |
| Reports | Durable saved chart result versions, report charts/notes, refresh with explicit source identity, distinct acknowledgement, first report canvas | Backend refresh, missing-source and fresh-store restart tests pass; tables, reordering and browser proof pending |
| AI proposals | Existing Clean/Visualize deterministic Atlas action endpoints | Local-model typed proposal workflow pending; deterministic suggestions must not be presented as model output |
| Connected workflow | Prior screenshots show Clean/Visualize slices | End-to-end UI, recording, SQL/Reports screenshots and 100k measurements pending |
| Baseline web | 104 tests across 16 files | Passed fresh on this worktree |
| Baseline Python | `.venv` initially referenced missing Python 3.11.9 | Interpreter repaired, pinned dev dependencies installed; original baseline 1,293 passed / 7 skipped; current checkpoint 1,298 passed / 7 skipped / 43 warnings on a unique isolated SQLite database |
| Baseline lint/type | Web lint passed | Typecheck initially failed on a Visualize test mock signature; fixed locally and rerun passed. Current Ruff and mypy pass. |

The earlier 1,240 passed / 7 skipped and 95 web tests in `README.md` are historical evidence, not current verification. No release or landing claim is made by this matrix.
