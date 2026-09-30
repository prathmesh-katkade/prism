# Statistical method coverage and warm workflow timing

Status: locally verified on 2026-09-30. The first release remains open.

## Method fixtures

The Atlas adapter now reports analyzed and excluded row counts for all four supported Stats Lab procedures. Pearson uses the paired `n`; t-test and ANOVA use their recorded group counts; chi-square uses the complete paired rows because its Stats Lab result has no `n` or group map. A new focused test independently determines the statistics for three additional fixtures:

| Method | Declared design and fixture | Expected statistic | Rows |
| --- | --- | ---: | ---: |
| Welch t-test | Two groups `A=[1,2]`, `B=[3,4]`, with one missing value | `-sqrt(8)` | 4 analyzed, 1 excluded |
| One-way ANOVA | Four values each in `A=[1,2,1,2]`, `B=[3,4,3,4]`, `C=[5,6,5,6]`; between MS=16, within MS=1/3 | F=48 | 12 analyzed, 0 excluded |
| Chi-square | 2x2 diagonal table with 20 in each occupied cell; Yates correction gives `4×9.5²/10` | 36.1 | 40 analyzed, 0 excluded |

The first test run exposed the chi-square row-count defect, and its raw output is retained in `verification/stat-methods-initial.txt`. The ANOVA fixture was enlarged to meet the existing categorical type detector's sample threshold; the intermediate diagnostic output is in `verification/stat-methods-debug.txt`. The corrected focused suite passed **10/10** (`verification/stat-methods-final.txt`). The separate Pearson fixture with five pairs `(1,2)` through `(5,10)` remains r=1 with five analyzed rows and zero exclusions.

## Warm end-to-end measurement

`tools/benchmark_atlas_warm_workflows.py` launched real uvicorn with an explicit URL to a temporary copy of the local backup. It uploaded the frozen three-row SQL and five-row Pearson fixtures. After one SQL and one statistical warmup run, it measured ten sequential runs of each, including HTTP admission, planning, queueing, computation, review, durable evidence and terminal polling. Each run asserted the independently calculated result. It excluded API cold start and both warmup runs; no human clarification time occurred. The nearest-rank p95 of the **20** measured runs was **2,584.48 ms**, p50 **509.49 ms**, maximum **4,038.92 ms**, below the proposed 60-second target. SQL runs ranged from 133.39 to 509.49 ms; statistical runs from 2,276.49 to 4,038.92 ms. Per-run planning, queue, tool and review timings, plus run and execution references, are in `verification/warm-workflow-result.json`; raw server and console output are alongside it.

The measurement used the deterministic provider and sequential requests. It is evidence for this declared small-dataset fixture set, not for model-backed review, overlapping users, hosted databases or arbitrary datasets. The backup SHA-256 stayed `03bbc35cb97e84abc1a92d54a9f5fbeb3592d5b208c6d0c01d397afdffcc6afc`, and the copied promotion pointer response was unchanged. The original production database and pointer were not used or changed. Model concurrency 1 versus 2 has not yet been measured, so parallel model review remains disabled.

After the row-count correction, the isolated full Python gate passed **614, skipped 7** (`verification/stat-python.txt`). Ruff, mypy (91 files including the benchmark driver), boundaries, secrets and generated-contract checks passed (`verification/stat-*.txt`). The web code and contracts did not change in this checkpoint; the preceding checkpoint's web unit, lint, typecheck, build and 15-case live browser gates still apply to those files.
