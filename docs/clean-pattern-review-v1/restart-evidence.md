# Pattern Review restart evidence

## What this proves and what it doesn't

`test_clean_patterns.py::test_saved_pattern_rule_survives_reopening_the_store`
proves a SQL row round-trips through a fresh `DurableValidationRuleStore`
instance bound to the same database file. It does **not** prove persistence
across a real API process restart - the Python interpreter, and anything it
might have cached in memory, never actually stops.

`apps/web/e2e-live/pattern-review-restart-live.spec.ts` is the genuine proof:
two separate `uvicorn` **operating-system processes**, run from two separate
`npx playwright test` invocations, against the same
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` database file.

## Run log

First invocation (creates the data, then skips itself):

```
[WebServer] INFO:     Started server process [1484]
...
POST /api/v1/overview/datasets 201
POST /api/v1/clean/datasets/{id}/patterns/decisions 201
POST /api/v1/clean/validation-rules 201
PRISM_RESTART_PROOF_IDS {"dataset_id":"ds_a77f9192183b4ed58341aa6aa27987d9",
  "decision_id":"patterndecision_8c309c0552084786986d1b11d6a445fe",
  "rule_id":"rule_fcc0241d079d480bb69eb63ac06a5ff5"}
1 skipped
```

Port 8000 confirmed free between invocations (no server left running, so the
second invocation cannot be reusing the first's process).

Second invocation, `PRISM_PATTERN_RESTART_PROOF=1`, fresh process:

```
[WebServer] INFO:     Started server process [12360]
...
GET /api/v1/overview/datasets 200          <- dataset ds_a77f919... still present
GET /api/v1/clean/validation-rules 200     <- "Restart-proof invoice format" still present
1 passed (10.8s)
```

Process ID 1484 vs. 12360 confirms these were two distinct OS processes, not
the same interpreter reused. The dataset, the pattern decision, and the saved
`pattern_family` validation rule (with its `accepted_family_signatures` and
`missing_value_policy` intact) all survived.

## Reproduce

```
rm -f apps/web/.prism/runtime/analytical-history.sqlite apps/web/.prism/runtime/sql-lab.sqlite
npx playwright test --config apps/web/playwright.live.config.ts pattern-review-restart-live.spec.ts
# wait for it to finish and the server to exit (port 8000 free)
PRISM_PATTERN_RESTART_PROOF=1 npx playwright test --config apps/web/playwright.live.config.ts pattern-review-restart-live.spec.ts
```
