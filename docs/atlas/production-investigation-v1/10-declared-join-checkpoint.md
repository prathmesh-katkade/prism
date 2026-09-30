# Declared two-source SQL join checkpoint

Status: locally verified on 2026-09-30. The first release remains open.

## Implemented boundary

Atlas can sum, count, average, minimize or maximize active-dataset values against one separately registered uploaded source. The request names both dataset IDs, both join keys and either many-to-one or one-to-one cardinality. The server resolves both active revisions, checks column names against each schema, rejects repeated right-side keys (and repeated left-side keys for one-to-one), quotes identifiers and compiles a fixed inner-join aggregate. Equality-filter values remain bound. The existing SQL Lab engine registers only `data` and `joined` in an in-memory DuckDB connection with external access disabled, 256 MiB memory and two threads. Atlas uses its existing ten-second SQL timeout, 12-second polling bound and 100-row result cap. There is no model-authored executable SQL or mutation path in this adapter.

The composite SQL Lab source fingerprint binds both dataset IDs, revisions and source fingerprints. The recorded Atlas output includes both revisions, cardinality, exact SQL, parameters, SQL run ID, policy version, state, result fingerprint and bounded rows. The SQL result analytical object has both dataset revisions as parents. A change to either active revision during execution makes the result stale. The SQL Lab handoff resolves the composite source, opens the exact recorded query as a draft, and permits returning to the same investigation.

## Independently checked workflow

The fixture uploaded `sales.csv` with `A,10`, `A,5`, `B,7` and `segments.csv` with `A,west`, `B,east`. The many-to-one join must yield east 7 and west 15; the repeated `A` on the left must not multiply revenue. The focused test asserts those rows, the exact join condition, the right-source revision evidence and a rejection when the right key repeats. The live browser test selects the join fields, sees the recorded totals, inspects the immutable query, opens and reruns it in SQL Lab, sees west 15 in its result grid, and returns to Atlas. See `verification/atlas-join-evidence.png`, `verification/atlas-join-workflow.webm`, and `verification/join-video-live.txt`. These runs used isolated temporary SQLite stores. No production database was used for tests.

## Gates and failed attempts retained

The isolated Python gate passed **611, skipped 7** (`verification/join-pytest-isolated.txt`). The initial run against the checkout's preexisting default store had **609 passed, 7 skipped, 2 failed** because durable test IDs and training records from earlier runs were present; its raw trace is `verification/join-pytest.txt`. The first join live test found an assertion that expected compact JSON although the correct result was rendered with spaces; the raw failure is `verification/join-live-initial.txt`. The corrected full live run passed **15/15** across desktop and mobile (`verification/join-full-live.txt`), and the final two-case SQL workflow run passed **2/2** with a saved recording. Focused SQL tests passed **22, skipped 4**. Web unit passed **86/86**. Lint, typecheck, build, Ruff, mypy (90 files), boundaries, secrets and generated-contract checks passed; raw output is in the `verification/join-*.txt` files.

## Remaining boundary

The join is an explicit two-source inner join. Unmatched left rows are excluded by SQL semantics; this checkpoint does not report their count or support a user-reviewed exclusion decision. It does not support general join graphs or many-to-many aggregation. The frozen acceptance case is satisfied for the declared many-to-one fixture, not for arbitrary joins. Warm 20-run p95, model concurrency comparison, and isolated MySQL integration remain unverified. The designated production model pointers were not changed by this work; this checkpoint did not reread them.
