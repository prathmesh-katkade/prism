# Specialist provenance, scheduler and bounded statistics checkpoint

Status: locally verified on 2026-09-30. The first release remains open.

## Implemented

New investigations persist ordered specialist messages with message ID, role, task, type, origin, input evidence IDs, reply target and model binding. Scout, Curator, Query, Stat and Auditor records are grounded in their actual deterministic computation or review; Atlas stores the final evidence-linked resolution. No shared-model conclusion is called independent corroboration. The collaboration view displays these records and labels older council-only records as legacy.

The planner validates unique step IDs and acyclic dependencies. Dispatch uses stable dependency order. A blocked prerequisite blocks its dependent with the missing input recorded. The existing profile-only and per-tool policy controls still gate each dispatch. A focused test proves a disabled statistical tool prevents the dependent audit and retains the completed profile.

Atlas statistics now run a validated two-column input through Stats Lab's tested calculation in a disposable worker. The adapter caps input at 10,000 rows and 8 MiB, enforces a 12 second deadline, and terminates on cancellation or active tool disable. The parent rechecks the dataset revision and registers the resulting analytical object before citing it. The normal Stats Lab endpoint retains its original compute-and-register behavior. Focused tests exercise timeout and active cancellation without evidence registration.

A descriptive request to compare groups and test causal attribution no longer enters statistical clarification solely because it says “compare.” It completes with the SQL refusal and an explicit statement that causal attribution was not performed without assignment provenance and a causal design. Requests for correlation, significance, a named method or group means still request statistical inputs when missing.

## Verification

The final isolated Python suite passed **610, skipped 7** after the causal-routing correction; raw output is in `verification/specialist-python-final.txt`. Web unit passed **86/86**. Lint, typecheck, production build, Ruff, mypy (90 source files), boundary, secrets, and generated-contract checks passed; raw outputs are in `verification/specialist-*.txt`.

The first full live desktop run found the causal-routing defect (10 passed, 2 failed); the two affected flows passed after the fix. Another full run exposed a two-pixel transient desktop overflow (11 passed, 1 failed); an isolated three-run diagnostic passed, and the following full run passed **12/12**. Both raw failures and reruns are retained. The mobile live project passed **2/2** at 390px. The real API restart on a disposable backup copy passed after the final citation correction: SQL Atlas run `atlas_fce4eb862f3b41948b3f17e5ce390802`, resumed statistical run `atlas_7bd7347efffb4ac697f2bb748e51eaa9`, Pearson r=1 over five rows, 1,094 ms calculation, registered object `stats_e73257711e4e4919ae7bed66bc535321`. Auditor's message cites the statistical evidence. The source backup SHA-256 and copied promotion pointer stayed unchanged.

## Remaining acceptance boundaries

The current Atlas SQL adapter executes a single uploaded source and cannot yet prove join grain across two sources. Parallel role-specific model calls and concurrency 1 versus 2 measurements are not implemented. Warm end-to-end p95 has not been measured against the frozen 20-run fixture set. No isolated MySQL instance or configured integration URL is available in this environment; port 3306 was closed on 2026-09-30. The current local workflow is verified, but hosted authorization and the final release remain blocked.
