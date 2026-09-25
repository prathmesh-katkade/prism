# Atlas Model Arena rounds

## Round 1 -- 2026-09-24T02:56:06.899618+00:00

- Commit: `d4225b4`
- Hardware: NVIDIA GeForce RTX 5060, 8151 MB VRAM
- Production run for comparison: `benchrun_914cf836996e485b87eb69f69aa1d3e8`

| Tag | License | Outcome | GPU % | Verdict | Pass rate (cand/prod) | Planner p95 | Valid-JSON | Acceptance | Failing gates |
|---|---|---|---|---|---|---|---|---|---|
| ministral-3:8b | Apache-2.0 | evaluated_not_qualified | 92% | promote_eligible | 100.0%/93.3% | 8.06s | 95% | 0% | gpu_100_percent, valid_json_rate_ge_95pct, acceptance_rate_ge_90pct |
| ministral-3:3b | Apache-2.0 | evaluated_not_qualified | 100% | reject | 92.2%/93.3% | 2.55s | 100% | 0% | atlasbench_promote_eligible, acceptance_rate_ge_90pct |
| qwen3:4b-instruct-2507-q4_K_M | Apache-2.0 | evaluated_not_qualified | 100% | promote_eligible | 98.9%/93.3% | 3.56s | 100% | 16% | acceptance_rate_ge_90pct |
| phi4-mini:latest | MIT | evaluated_not_qualified | 100% | reject | 25.6%/93.3% | 4.51s | 100% | 26% | atlasbench_promote_eligible, acceptance_rate_ge_90pct |

## Round 2 -- 2026-09-24T03:46:29.997404+00:00

- Commit: `d4225b4`
- Hardware: NVIDIA GeForce RTX 5060, 8151 MB VRAM
- Production run for comparison: `benchrun_74f6d9fdea52478b918c5be3fdb6dd5b`

| Tag | License | Outcome | GPU % | Verdict | Pass rate (cand/prod) | Planner p95 | Valid-JSON | Acceptance | Failing gates |
|---|---|---|---|---|---|---|---|---|---|
| olmo-3:7b-instruct | Apache-2.0 | evaluated_not_qualified | 89% | reject | 43.3%/93.3% | 11.57s | 100% | 47% | atlasbench_promote_eligible, gpu_100_percent, acceptance_rate_ge_90pct |
| granite4:micro | Apache-2.0 | evaluated_not_qualified | 100% | reject | 87.8%/93.3% | 5.27s | 89% | 16% | atlasbench_promote_eligible, valid_json_rate_ge_95pct, acceptance_rate_ge_90pct |

## Round 3 -- 2026-09-24T04:30:41.448573+00:00

- Commit: `8d0da8c`
- Hardware: NVIDIA GeForce RTX 5060, 8151 MB VRAM
- Production run for comparison: `benchrun_cc784fb15dd54ea8b50558c04b298f94`
- Acceptance gate: max(90%, qwen2.5:3b measured full-40 acceptance 100%) = 100%.

| Tag | License | Outcome | GPU % | Verdict | Pass rate (cand/prod) | Planner p95 (full) | Valid-JSON (full) | Acceptance core/full | Failing gates |
|---|---|---|---|---|---|---|---|---|---|
| ministral-3:8b | Apache-2.0 | evaluated_not_qualified | 92% | promote_eligible | 100.0%/94.4% | 10.26s | 95% | 100%/95% | gpu_100_percent, valid_json_rate_ge_95pct, acceptance_rate_ge_gate |
| qwen3:4b-instruct-2507-q4_K_M | Apache-2.0 | evaluated_not_qualified | 100% | promote_eligible | 98.9%/94.4% | 0.74s | 100% | 26%/21% | acceptance_rate_ge_gate |
| granite4:micro | Apache-2.0 | evaluated_not_qualified | 100% | reject | 87.8%/94.4% | 3.89s | 100% | 100%/100% | atlasbench_promote_eligible |
| ministral-3:3b | Apache-2.0 | evaluated_not_qualified | 100% | reject | 92.2%/94.4% | 1.54s | 100% | 100%/100% | atlasbench_promote_eligible |

## Round 4 -- 2026-09-24T05:16:21.673832+00:00

- Commit: `79e26c1`
- Hardware: NVIDIA GeForce RTX 5060, 8151 MB VRAM
- Production run for comparison: `benchrun_2b6d9e14e9ad411f933d26a8cc76b2e0`
- Acceptance gate: fixed 90% floor (the original product bar), not max(90%, measured baseline). Round 3 measured the baseline at exactly 100% (0/39 rejected), which made the gate a literal perfect score at n=39 -- a 100% point estimate's confidence interval reaches well below 90%, so requiring an exact tie to it fits noise, not a real requirement.

| Tag | License | Outcome | GPU % | Verdict | Pass rate (cand/prod) | Planner p95 (full) | Valid-JSON (full) | Acceptance core/full | Failing gates |
|---|---|---|---|---|---|---|---|---|---|
| ministral-3:8b | Apache-2.0 | evaluated_not_qualified | 92% | promote_eligible | 100.0%/94.4% | 10.90s | 95% | 100%/95% | valid_json_rate_ge_95pct |
| qwen3:4b-instruct-2507-q4_K_M | Apache-2.0 | qualified | 100% | promote_eligible | 98.9%/94.4% | 1.70s | 100% | 100%/100% | - |
| granite4:micro | Apache-2.0 | evaluated_not_qualified | 100% | reject | 87.8%/94.4% | 4.19s | 100% | 100%/100% | atlasbench_promote_eligible |
| ministral-3:3b | Apache-2.0 | evaluated_not_qualified | 100% | reject | 92.2%/94.4% | 1.58s | 100% | 100%/100% | atlasbench_promote_eligible |

## Harness boundary — 2026-09-25

Rounds 1–4 used the former loose JSON output mode and 64-token AtlasBench cap. They are historical results and are not directly comparable with runs using the decoder schema, `think: false`, 256-token cap, and three-way outcome reporting. [Preflight controls](controls-2026-09-25.md) found a large, model-dependent prompt-envelope effect. Round 5 has not been run.

## Choice-order defect — 2026-09-25

The V1 answer key is authored at indices 0/1/2/3 in counts 8/81/1/0. A constant index-1 answer scored 81/90 before shuffling and 24/90 after deterministic shuffling with seed `atlasbench-shuffle-v1`. The fixed harness also requires the exact choice string instead of an index. All earlier arena rounds, including the preflight envelope controls, are non-comparable with this fixed policy. [ADR 0016](../../architecture/adr/0016-atlasbench-choice-order-and-string-answers.md) records the scoring remedy. The corpus itself still needs a future versioned rebalance; its content and hash are unchanged in this pass.
