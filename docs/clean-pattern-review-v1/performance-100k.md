# Pattern Review 100k-row performance

Hardware: single local Windows machine, Chromium, SQLite-backed default
history store (`.prism/runtime/analytical-history.sqlite`), no MySQL
involved. Fixture: 100,000-row synthetic CSV (`invoice_id`, `amount`), 1 in
500 rows malformed, 1 in 300 `amount` values unparseable, mixed `kg`/`lb`
units. No warmup, single run - these are observations, not a pass/fail
threshold invented after the fact.

## A real regression found and fixed

The first run measured **32.6s** for extraction preview and **33.5s**
(end-to-end, including a client-side reload) for apply. Profiling
`_extract_identifier_components` in isolation showed it completes a full
100k-row extraction in **278ms** - the function itself was never the
problem. The actual cost was in `_row_inspection` (shared Clean machinery,
not new to this feature): it built a full `CleanRowInspection` detail object
- a `.loc[]` lookup plus a `.to_dict()` conversion - for *every* affected row,
then sliced the result down to the first 100 for display. Extraction is the
first operation in this codebase that routinely marks nearly all 100,000
rows "changed" in one call (every row gets new column values), which exposed
this at a severity existing operations (duplicates, missing-value fills on a
minority of rows) rarely hit.

Fix: slice the affected-row index list to `INSPECTION_LIMIT` (100) **before**
building any row-detail objects, not after. Verified with the full pytest
suite (1353 passed, 0 regressions) and re-measured:

| Step | Before fix | After fix (isolated, warm) | After fix (full browser run) |
|---|---|---|---|
| Extraction preview (server) | 32,060ms | 2,479ms | 17,681ms |
| Extraction apply (server) | n/a (not isolated) | 5,848ms | 9,144ms |

The isolated and full-browser-run numbers differ because the isolated
measurement used a single-column fixture on a warm process, while the full
run's fixture has a second (`amount`) column that `_health()` and discovery
also process, and the browser run is a cold process start. Both numbers are
real; neither is cherry-picked. The structural fix (no longer materializing
~99,500 row-detail objects to show 100) is confirmed in both: this was an
O(n) problem that is now O(limit), and the remaining multi-second cost comes
from pre-existing shared Clean code paths (`_health()`'s full quality scan
and `add_revision()`'s fingerprint hashing over the full frame), which the
prior analytical-workspaces release already measured and documented at
similar or worse magnitudes for non-Pattern-Review operations (e.g. that
release's `clean_workspace_open` at 13.6-18.3s, visible again in this run's
`GET /clean/datasets/{id}/state` calls). Fixing those is out of this
feature's scope.

## Full measured timings (after the fix, single browser run)

```json
{
  "rows": 100000,
  "timings_ms": {
    "upload_to_profile_visible_ms": 3569,
    "sample_discovery_visible_ms": 20732,
    "finding_review_render_ms": 71,
    "full_verify_100k_ms": 888,
    "exception_table_render_ms": 5,
    "extraction_preview_ms": 17929,
    "extraction_apply_ms": 28252,
    "cancel_response_ms": 124
  }
}
```

(Raw file: `performance-100k.json`, written by the live test itself.)

- **`sample_discovery_visible_ms` (20.7s) is misleading as a Pattern Review
  number**: the server-side `POST /patterns/discover` call inside this window
  took **278ms** (see the raw server log). The 20.7s is almost entirely the
  pre-existing `GET /clean/datasets/{id}/state` call that the Clean workspace
  already makes before Pattern Review can render anything - the same
  bottleneck the prior release documented. Pattern discovery itself is fast;
  it is gated behind Clean's existing slow initial load.
- **`full_verify_100k_ms` (888ms)** confirms the earlier isolated-detector
  measurement (identifier_structure full-scan: 385ms on a synthetic column) -
  full verification of every one of 100,000 rows is genuinely sub-second.
  This is the evidence the "no background-job cancellation infrastructure"
  design decision was checked against, not assumed.
- **`extraction_preview_ms` / `extraction_apply_ms` (17.9s / 28.3s)**: real,
  multi-second cost remains, now attributable to the shared `_health()` /
  `add_revision()` paths described above, not to anything added by this
  feature's own extraction logic.
- **`cancel_response_ms` (124ms)**: clicking Cancel during a verify call
  removes the Cancel button and returns control well under a second -
  confirms cancellation is responsive even though (per the 888ms full-scan
  number above) there was rarely anything worth cancelling in the first
  place at this scale.

## What this does not claim

No pass/fail latency threshold is declared. 100k rows with a single
extraction operation is a single local measurement, not a service-level
guarantee, and the remaining multi-second cost in `_health()`/`add_revision()`
is real and un-optimized - it is out of this feature's scope, not hidden.
