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

## Fixed-harness controls — 2026-09-25

[Four durable control runs](controls-fixed-2026-09-25.md) used shuffled presentation and exact choice strings. Phi scored 90/90 with either envelope; OLMo scored 88/90 nested and 90/90 prose. The earlier opposite-direction prompt effect did not persist. Round 5 uses the nested envelope for continuity with the production request shape.

## Round 5 — 2026-09-25

[Durable Round 5 results](round-5.json) measure the ten installed models in the recorded order, starting with the actual production binding. All ten used the same nested-JSON prompt envelope, `atlasbench-shuffle-v1` choice permutation, exact choice-string enum response, `think: false`, temperature 0, 256 output tokens, 4096 context, and 60-second bench timeout. Their shared evaluation policy ID is `2567d704bfb69b3335a93a47e0b4ecf817522c1fd71c4c8504c27080741dd531`. The corpus remains V1 with hash `f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`. Planner measurements used 40 objectives (the first cold request excluded from 39 warm samples), 1800 output tokens, 4096 context, and a 30-second timeout. The JSON report includes per-category outcomes, each model digest, run ID, raw `ollama ps` output, GPU allocation percentage after bench and planner, each `done_reason` and `eval_count` distribution, and planner samples.

| Model | Correct / wrong / invalid | GPU minimum | Planner p50 / p95 | JSON / acceptance | AtlasBench verdict |
|---|---:|---:|---:|---:|---|
| `qwen3:4b-instruct-2507-q4_K_M` (production) | 90 / 0 / 0 | 100% | 0.75s / 1.66s | 100% / 100% | baseline |
| `qwen2.5:3b` | 88 / 2 / 0 | 100% | 0.65s / 3.08s | 100% / 100% | reject |
| `ministral-3:8b` | 89 / 1 / 0 | 92% | 5.02s / 9.87s | 100% / 100% | reject |
| `ministral-3:3b` | 89 / 1 / 0 | 100% | 0.95s / 1.80s | 100% / 100% | reject |
| `granite4:micro` | 90 / 0 / 0 | 100% | 1.75s / 3.99s | 100% / 100% | hold |
| `granite4:tiny-h` | 89 / 1 / 0 | 100% | 0.95s / 2.42s | 100% / 100% | reject |
| `qwen3:8b` | 90 / 0 / 0 | 100% | 0.98s / 3.10s | 100% / 100% | hold |
| `qwen2.5:7b-instruct` | 90 / 0 / 0 | 100% | 1.13s / 6.45s | 100% / 100% | hold |
| `phi4-mini:latest` | 90 / 0 / 0 | 100% | 0.74s / 2.33s | 100% / 100% | hold |
| `olmo-3:7b-instruct` | 88 / 2 / 0 | 89% | 1.77s / 3.19s | 100% / 100% | reject |

All 900 bench responses ended with `done_reason=stop`, and every response had `eval_count`. GPU ≥85%, warm planner p95 ≤12 seconds, valid JSON ≥95%, and acceptance ≥90% each passed for 10/10 models. No challenger was AtlasBench `PROMOTE_ELIGIBLE`: four held at 90/90 and five had critical-category regressions against the perfect production baseline. Operational Certification was not run and is unknown for all ten. No model was registered or promoted; the production pointer remains on `qwen3:4b-instruct-2507-q4_K_M`.

The predicted broad score fall did **not** occur: every fixed-harness model scored 88–90/90, even though a constant answer scored only 24/90 after shuffling. Phi and OLMo rose sharply from the old harness, so the old claim that their low results showed weak capability was wrong. The concurrent shuffling and string-answer changes do not isolate which change caused the rise. Rounds 1–4 and both earlier prompt-envelope controls are historical and non-comparable with Round 5. The V1 corpus's authored 81/90 index-1 skew remains a known issue; rebalance requires a separate corpus version bump and full new baseline.
