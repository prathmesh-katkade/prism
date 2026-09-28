# Local SQL checkpoint, 2026-09-28

Status: first implementation checkpoint complete; first release remains open.

## Executed workflow

The real uvicorn launch on a disposable backup copy accepted a three-row CSV,
created Atlas run `atlas_43873983d90e4c39927bc37ba4245afd`, executed a
typed sum by region through SQL Lab, and recovered the same Atlas run and
dataset revision after process restart. The recorded SQL result was east 7 and
west 15; those totals were independently calculated from the fixture rows
`west: 10,5` and `east: 7`. The Atlas journal contains the exact SQL,
parameters, SQL run ID, result fingerprint, revision, source fingerprint,
execution state, bounded rows, and policy version. The supplied backup SHA-256
remained unchanged. See `verification/disposable-startup-result.json` and both
raw `startup-*.log` files.

An isolated live Playwright run passed the GUI path: select the SQL evidence,
inspect its recorded query, open it as a draft in SQL Lab with the registered
local source, and return to the same investigation tab. The first attempt
found that returning to Atlas lost the run ID; the shell now keeps it. The
subsequent run passed 1/1. See `verification/live-sql-playwright.txt`, the two
PNG screenshots, and `atlas-sql-workflow.webm`.

## Boundary

The initial SQL surface supports count, sum, average, minimum, and maximum,
with an optional group and equality filter. The user selects columns from
the server-reported schema. Values are bound; identifiers are checked and
quoted. The model cannot nominate this executable tool. DuckDB runs in memory
with external access disabled, a 256 MB memory limit, and two threads. Query
runtime is 10 seconds, Atlas polling is bounded to 12 seconds, and no more
than 100 rows are recorded. Invalid columns or nonnumeric measures fail
closed. Profile-only and per-tool policy gates are checked before dispatch;
active SQL is asked to cancel if the policy changes during execution.

This checkpoint does not implement a general SQL join planner or statistical
execution. It does not establish causal conclusions. SQL Lab's generic read
service and its existing certification policies were not expanded. Hosted
deployment remains blocked by PRISM's existing identity boundary.

## Gates

The isolated Python suite passed **603, skipped 7**. The web unit suite passed
**84/84**. Ruff, mypy (89 source files), web lint, typecheck, build, boundary
check, secret check, and generated contract check passed. The first Python
suite used the worktree's preexisting default store and had 5 failures; a
fresh isolated store resolved three state/performance failures and two
expectations were updated to assert the new six-role roster and that the
model cannot propose executable SQL. The first two full web runs exposed
asynchronous test timing in unrelated screens; the assertions now await the
actual state without changing their expected values, and the final full run
passed. Raw failed and passing outputs are retained in `verification/`.

The production-history source was inspected only via `sqlite3` read-only URI.
Its pointer was not changed. The disposable copy alone was migrated and
launched. Real MySQL, warm p95, statistical clarification, and final
accessibility acceptance remain to be proven.
