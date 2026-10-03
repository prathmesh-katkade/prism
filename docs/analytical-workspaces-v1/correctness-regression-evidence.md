# Correctness checkpoint, 2026-10-02

## Current working-tree follow-up

- Clean draft recipe preview now accepts edited ordered steps, including disabled steps. A schema mismatch names the failing step; changing an earlier step recomputes downstream results. Preview returns bounded changed and exception row samples with source-row identities and exact totals. Validation exposes violation source rows. Focused Clean and validation run: **43 passed**.
- CTE list and materialization reject mutating and multi-statement SQL before parsing. Focused CTE run: **7 passed**.
- Visualize applies saved spec filters on the server for both render and drilldown. Histogram bins carry numeric bounds and resolve to the same contributing rows. Focused Visualize run: **17 passed**.
- Reports save bounded table snapshots with selected source revision/fingerprint, persist order across charts, tables and notes, and disclose stale or unavailable table sources. A fresh store connection restores table rows and item order. Focused Reports run: **11 passed**.
- The current full isolated Python run: **1,304 passed, 7 skipped, 43 warnings in 105.93s**. Full web rerun: **104 passed across 16 files**. One preceding full web run had one intermittent Atlas command-center failure (103/104); the test passed alone (15/15) and the full suite passed on rerun. Both outputs are retained in the raw log.

Source branch: `prism/analytical-workspaces-v1`. Tests below used a unique temporary SQLite database via `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`; production data was not used.

## Clean review and publication

- A Clean preview returns the reviewed dataset revision and fingerprint and a one-use ticket bound to the full typed operation. Apply rejects a missing ticket, changed parameters, an intervening dataset revision, or a duplicate submission with HTTP 409.
- Recipe preview runs enabled steps in order and returns the projected result and per-step affected counts. Its ticket binds the recipe ID, version and full step list to the dataset identity. A recipe edit or intervening dataset change invalidates it.
- Recipe apply computes every step first. It then inserts the resulting dataset revisions, dataset-revision objects, cleaning-plan objects, lineage edges and audit entries in one database transaction. A later-step injected storage exception rolled back both data and provenance; a new preview and retry succeeded.
- Single-operation revision insertion now checks the expected source revision and fingerprint inside the database transaction, closing the stale-read window between review and publication.

Focused gate: `tests/api/test_clean.py tests/api/test_analytical_object_integration.py tests/api/test_reports.py -q` — **48 passed, 1 warning**. Full suite after the review change: **1,298 passed, 7 skipped, 43 warnings** in 100.94 seconds. Raw full output is appended to `C:\Users\Admin\Documents\prism-workspaces-upgrade-log.txt`.

## Report source refresh

- Saving a chart now persists its actual aggregated result and source revision/fingerprint. A fresh store connection recovers both the report reference and rendered data.
- The report reports stale status when either revision or fingerprint differs. A missing source is shown as unavailable and refresh returns HTTP 409.
- Refresh requires an explicitly selected revision and fingerprint for each chart. It recomputes/validates the spec against that source, saves a new chart result, and updates the report reference. The prior chart result remains available by chart ID. An acknowledgement route remains distinct and leaves the frozen result unchanged.

Focused gate: `tests/api/test_reports.py -q` — **10 passed, 1 warning**. The report canvas UI is present but its full chart/table/note composition, reordering and connected browser proof remain open acceptance items.

## Gate note

The first full Python run after enforcing review tickets had **1 failed, 1,295 passed, 7 skipped**: the explicit stored-plan rerun called the now guarded user apply function. That internal rerun was changed to use its own stored-plan commit path. Its focused test passed, and the subsequent full run above passed. The earlier failure remains in the raw log rather than being erased.
# Current working-tree verification, 2026-10-03

The earlier counts below document prior checkpoints. The current full isolated SQLite run is **1,309 passed, 7 skipped, 43 warnings in 129.67s**. Focused Clean is **35 passed** after fixing the numeric missing-value explanation to include the required fill strategy. Optional local-model proposal cases are **4 passed** (disabled, valid Clean preview, invalid SQL/chart, timeout). Web is **104 passed across 16 files**; lint, typecheck, build, a11y, Ruff, mypy, boundaries, secrets and generated-contract check passed.

Live Chromium connected proof passed with chart/table/note add, reorder and removal through cross-origin PUT/DELETE, stale-source warning and actual chart refresh. The 100k live browser run passed; it observed 100 returned rows from the default `LIMIT 100` SQL query and did not mistake that for a 100k scan. Raw current logs are appended to the Documents upgrade log. The seven skips are four unconfigured MySQL parity cases and three Atlas environment-specific checks. Release scope still remains open as described in the acceptance matrix.
