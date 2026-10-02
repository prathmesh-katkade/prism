# Correctness checkpoint, 2026-10-02

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
