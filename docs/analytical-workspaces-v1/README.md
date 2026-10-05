# Analytical workspaces v1 delivery status

Last updated 2026-10-03. Branch `prism/analytical-workspaces-v1`; last pushed checkpoint before this working tree: `3fb26c4`. **The complete release has not landed.** Atlas development, model bindings, promotion policy, production data and released orchestration remain outside this work.

## What exists now

Clean has revision and fingerprint bound review tickets, explicit Apply/Discard, atomic recipe data plus provenance publication, and an editable multi-step recipe UI. It offers Before/Changes/After, affected source rows, exceptions and validation results. Date and numeric parsing, missing values, category mapping and deterministic duplicate survivorship are typed operations.

SQL Lab has a schema-aware editor, typed parameters and saved query/parameter pairs. SQL parsing supports guarded CTE inspection, join diagnostics, declared-key comparisons, handoffs with lineage, cancellation and bounded read-only execution. MySQL parity is not currently live-verified because the isolated MySQL test URL is absent.

Visualize has intent/field-driven chart controls, server-side filtering shared with mark inspection, histogram bins, axis labels and units, reference line, annotation, chart-specific warnings and persisted chart specifications. Server-generated bar/line small multiples use a shared value scale; selecting a panel mark inspects rows with that panel's server filter.

Reports save charts, bounded table snapshots and notes, with durable content order and remove controls. The UI exposes the exact source revision/fingerprint, stale and unavailable sources, and explicit chart/table refresh that recomputes and retains previous versions. A separate API-process restart browser run reopened the saved report and source.

Optional local-model Clean/chart/SQL proposals are typed and validated by the same operation rules as manual work. Clean proposals only return a preview ticket; data mutation still requires reviewed Apply. Provider timeout, invalid output or unavailability retains the manual controls. The installed `qwen2.5:3b` model returned valid SQL and chart drafts; a live browser run reviewed the SQL draft without executing it. Existing deterministic suggestions are not represented as model-generated.

## Current evidence

- [Acceptance matrix](acceptance-matrix.md) and [correctness regression evidence](correctness-regression-evidence.md).
- Fresh full Python run: **1,309 passed, 7 skipped, 43 warnings in 129.67s** with an explicitly isolated SQLite history database. Four skips require an unconfigured MySQL source; three are Atlas environment-specific checks. The previously reported 1,240/7 and 1,304/7 runs are historical.
- Web: **104 passed across 16 files**. Lint, typecheck, build, accessibility baseline, Ruff, mypy, dependency boundaries, secret scan and generated-contract check passed on this working tree. Exact raw output is appended to `C:\Users\Admin\Documents\prism-workspaces-upgrade-log.txt`.
- Live Chromium connected flow: upload, Clean preview/apply, SQL query, Visualize facets/mark inspection/save, report chart/table/note/reorder/remove, changed source, stale warning and explicit chart/table refresh. A separate API process then reopened the saved report. Screenshots in [screenshots](screenshots) show real results in light and dark at 1440x900 and 400x900, plus empty/loading/error states. [Workflow recording](connected-workflow.webm).
- [100k backend measurement](performance-100k.json) and [100k browser measurement](performance-100k-ui.json) include the fixture definition, limits, hardware and elapsed times. They are observations without a retrospective pass threshold.

## Remaining release work

Run the full final gates on this latest worktree and the applicable isolated MySQL integration gate when a source is available. No MySQL URL, local listener on ports 3306/3307 or Docker CLI is available in the current environment. Then push the branch, integrate from a clean checkout only when the mandatory gate is verified, verify CI at the exact landed SHA, smoke-test the running app, and tag only if the full release is verified. There is no release SHA, main push, CI result, running-app URL or release tag yet.
