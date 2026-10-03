# Analytical workspaces v1 delivery status

Last updated 2026-10-03. Branch `prism/analytical-workspaces-v1`; last pushed checkpoint before this working tree: `3fb26c4`. **The complete release has not landed.** Atlas development, model bindings, promotion policy, production data and released orchestration remain outside this work.

## What exists now

Clean has revision and fingerprint bound review tickets, explicit Apply/Discard, atomic recipe data plus provenance publication, and an editable multi-step recipe UI. It offers Before/Changes/After, affected source rows, exceptions and validation results. Date and numeric parsing, missing values, category mapping and deterministic duplicate survivorship are typed operations.

SQL Lab has a schema-aware editor, typed parameters and saved query/parameter pairs. SQL parsing supports guarded CTE inspection, join diagnostics, declared-key comparisons, handoffs with lineage, cancellation and bounded read-only execution. MySQL parity is not currently live-verified because the isolated MySQL test URL is absent.

Visualize has intent/field-driven chart controls, server-side filtering shared with mark inspection, histogram bins, axis labels and units, reference line, annotation, chart-specific warnings and persisted chart specifications. Shared-scale small multiples and linked multiple-view filtering are still missing.

Reports save charts, bounded table snapshots and notes, with durable content order and remove controls. The UI exposes the exact source revision/fingerprint, stale and unavailable sources, and an explicit chart refresh that recomputes and retains the previous version. Table refresh versioning and a separate API-process restart browser proof remain open.

Optional local-model Clean/chart/SQL proposals are typed and validated by the same operation rules as manual work. Clean proposals only return a preview ticket; data mutation still requires reviewed Apply. Provider timeout, invalid output or unavailability retains the manual controls. This route is covered by mocked-provider tests; successful live model execution remains unverified. Existing deterministic suggestions are not represented as model-generated.

## Current evidence

- [Acceptance matrix](acceptance-matrix.md) and [correctness regression evidence](correctness-regression-evidence.md).
- Fresh full Python run: **1,309 passed, 7 skipped, 43 warnings in 129.67s** with an explicitly isolated SQLite history database. Four skips require an unconfigured MySQL source; three are Atlas environment-specific checks. The previously reported 1,240/7 and 1,304/7 runs are historical.
- Web: **104 passed across 16 files**. Lint, typecheck, build, accessibility baseline, Ruff, mypy, dependency boundaries, secret scan and generated-contract check passed on this working tree. Exact raw output is appended to `C:\Users\Admin\Documents\prism-workspaces-upgrade-log.txt`.
- Live Chromium connected flow: upload, Clean preview/apply, SQL query, Visualize chart/save, report chart/table/note/reorder/remove, changed source, stale warning and explicit refresh. Screenshots in [screenshots](screenshots) show real results in light and dark at 1440x900 and 400x900. [Workflow recording](connected-workflow.webm).
- [100k backend measurement](performance-100k.json) and [100k browser measurement](performance-100k-ui.json) include the fixture definition, limits, hardware and elapsed times. They are observations without a retrospective pass threshold.

## Remaining release work

Implement and verify shared-scale small multiples and linked views; finish table refresh versioning; prove true API restart/reopen in the browser; complete empty/loading/error, keyboard and overflow visual checks; perform a successful live local-model proposal; run the applicable isolated MySQL integration gate when a source is available. Then rerun all gates, push the branch, integrate from a clean checkout, verify CI at the exact landed SHA, smoke-test the running app, and tag only if the full release is verified. There is no release SHA, main push, CI result, running-app URL or release tag yet.
