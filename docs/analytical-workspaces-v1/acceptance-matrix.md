# Analytical workspaces v1 acceptance matrix

Snapshot: 2026-10-02, branch `prism/analytical-workspaces-v1` at pushed checkpoint `5503a6b` plus the current working tree. â€œVerifiedâ€ means a fresh gate or direct exercise against this worktree and an isolated database.

| Area | Implemented | Verification and remaining scope |
|---|---|---|
| Clean operations | Category mapping, duplicate survivorship, explicit date/numeric formats, missing-value choices, validation, changed/exception source-row identity, Before/Changes/After and Affected/Exceptions/Validation tabs | Focused backend tests pass. Current layout and connected browser flow still need real visual proof. |
| Clean recipes | Durable versioned recipes, one-use review tickets, atomic data and provenance, multi-step draft editor with add/edit/reorder/disable and downstream preview | Injected later-step failure and retry verified. Editor still needs live browser acceptance. |
| SQL Lab | Schema-aware editor, typed parameters and JSON, saved SQL/parameters, parsed join diagnostics, guarded CTE materialization, declared-key comparison, result handoffs | CTE mutation regression passes. Full live workflow and MySQL integration remain open. |
| Visualize | Server filters shared by render and drilldown, histogram bin controls and mark inspection, axes/units, reference line, annotation, scatter/box/trend fixes | Focused API tests pass. Shared-scale small multiples, fuller chart-specific warnings and live UI proof remain open. |
| Reports | Durable chart/table snapshots and notes, persisted cross-content order, explicit chart refresh with retained versions, stale/missing source status | Focused API and fresh-store restart tests pass. Connected browser proof and table refresh versioning remain open. |
| AI proposals | Existing deterministic Clean/Visualize Atlas actions | Local-model typed proposal workflow remains open; deterministic suggestions must not be labeled model-generated. |
| Connected workflow | Earlier real Clean/Visualize screenshots | New Clean/SQL/Visualize/Reports light/dark, desktop/mobile, state screenshots and one connected recording remain open. |
| 100k rows | No current measurement | Reproducible fixture, timing, responsiveness and hardware disclosure remain open. |
| Python | Python 3.11.9 and dev dependencies repaired | Original baseline 1,293 passed / 7 skipped. Current working tree: **1,304 passed / 7 skipped / 43 warnings** in 105.93s, unique isolated SQLite database. |
| Web and static gates | Current worktree | **104 passed across 16 files** on full rerun. Lint, typecheck, build, a11y baseline, Ruff, mypy, boundaries, secrets and generated-contract check pass. |
| Landing | Branch checkpoint `5503a6b` pushed | Current working tree not yet pushed. Main, CI at landed SHA, smoke URL and release tag remain open until mandatory criteria pass. |

The earlier 1,240 passed / 7 skipped and 95 web tests in the historical README are not current verification. No complete release claim is made here.
