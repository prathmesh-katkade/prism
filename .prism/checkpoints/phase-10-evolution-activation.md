# Phase 10 — Evolution Activation checkpoint

## Superseding: deadline-sprint pass — Operational Certification wave 2 (23 scenarios) — 2026-09-10 (cloud continuation, third pass)

Third cloud-safe pass on the same PHYSICAL_ACCESS = NO session (re-confirmed again: no `nvidia-smi`, no `ollama` binary, `127.0.0.1:11434` connection refused). Responding to an explicit deadline-sprint framing: get Phase 10 to the closest legitimate production-ready state, without repeating already-completed work or weakening any gate.

Recovered state first: HEAD was already at `cb6a735` (V2 candidate-path selector, AtlasBench V2 wave 3 at 80 tasks, Operational Certification wave 1 at 15 scenarios) — all of Software Waves A/B and most of C from the prior pass were already done and were **not** rebuilt. The deadline brief's own target reframed the V2 corpus goal from ~150 tasks down to a "80-100 strong tasks minimum" independent holdout; 80 tasks (waves 1-3) already meets that, so no further corpus authoring was done this pass.

The one genuine gap against the deadline brief was the Operational Certification Suite's scenario count (15 built vs. a 20-25 target). Extended `atlas_operational_cert.py` with 8 more scenarios (23 total, `atlas-operational-cert-wave2`): preprocessing-leakage detection, time-series feature leakage, a genuine Python-sandbox analysis task (distinct from the existing unsafe-rejection scenario), evidence-freshness-conflict handling, RAG-specific prompt injection, business recommendation under risk/variance tradeoff, uncertainty communication, and concise senior-DS explanation. Same deterministic, non-self-graded judging discipline as wave 1: structured claims and tool-call evidence checked against ground truth, never "did you do X correctly?" asked of a model. 3 new critical-failure-path tests added (RAG injection obedience, sandbox-result fabrication, evidence-blending-as-fabrication) on top of the existing ones — `PerfectOperationalSubject` passes all 23, `UnsafeOperationalSubject` still trips real critical failures across all 23.

New/modified: `atlas_operational_cert.py`, `AtlasOperationalScenarioId` (8 new enum members), regenerated TypeScript contracts. Full gate green: ruff, mypy (strict, whole tree), dependency boundaries, secret scan, contracts freshness, and the full pytest suite (439 passed, 5 skipped).

The physical runbook (`docs/migration/PHASE10_VERIFIED_BASE_MODEL_RUNBOOK_20260910.md`) was updated to reflect: the 23-scenario suite, the 80-task V2 holdout now framed as meeting (not falling short of) the deadline-sprint target, and an explicit, fully-sequenced promote → smoke → mandatory-rollback → verify-exact-restoration → final-promote drill (steps 1-9) that must run in full on the real machine before Qwen 2507 can honestly be called production.

**Not done here** (needs the physical machine, unchanged from prior passes): registering/verifying Qwen3-4B-Instruct-2507 as a real `VERIFIED_BASE_MODEL` candidate, any fresh trusted candidate V1/V2 run, running the Operational Certification Suite against the real candidate, and the promotion/rollback drill. No candidate was registered, verified, benchmarked, or promoted from this session; production is unchanged; PR #15 remains open and unmerged.

**ATLAS First Light GUI has not started.** Per the mission's own sequencing, GUI work begins only once Qwen is safely in production -- which requires the physical runbook above to actually run to completion. Starting GUI work before that would violate the stated P0-before-P1 priority order, so this pass did not touch the frontend.

**PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.**

## Superseding: V2 candidate-evaluation path, blind V2 wave 3, and Operational Certification wave 1 — 2026-09-10 (cloud continuation, second pass)

Continuing on the same PHYSICAL_ACCESS = NO cloud session (confirmed again this pass: `nvidia-smi`, `ollama`, and `curl 127.0.0.1:11434` all fail here) after the VERIFIED_BASE_MODEL / evaluation-policy landing above. This pass built the three cloud-safe pieces the mission's next stage asked for; it does not touch, re-verify, or re-run anything physical.

**V2 candidate-evaluation support** (mission SOFTWARE WAVE A): both the candidate route (`POST /api/v1/atlas/bench/candidates/{id}/runs`) and the production route (`POST /api/v1/atlas/bench/runs`) now take a bounded, server-owned `corpus` selector (`AtlasBenchCorpusId`: `atlasbench-v1` default / `atlasbench-v2-holdout`) — the client can only name an existing frozen corpus module, never tasks, answers, or scoring. Both converge through the same `_resolve_corpus` helper, so a V2 candidate run and a V2 production run can now actually be compared under `compute_promotion_decision`'s existing corpus/policy gates. Fully backward compatible: omitting `corpus` reproduces the exact prior V1-only behavior.

**AtlasBench V2 wave 3** (mission SOFTWARE WAVE B): 30 more hand-authored holdout tasks (3 per category, 80 total across waves 1-3) from the predeclared taxonomy — grain/fan-out errors, `= NULL` vs `IS NULL`, point-in-time SCD joins, calibration, base-rate fallacy, optional stopping, hyperparameter-tuning leakage, spurious ID features, concept drift, structural breaks, prediction intervals, exogenous-variable leakage, immortal time bias, p-hacking, causal overclaiming, RAG injection, destructive-action confirmation, instruction hierarchy, fabricated citations, broken lineage, evidence misattribution, path traversal, unsafe dynamic dependency installation, insecure deserialization, overclaiming caution, stakeholder-conflict consistency, error acknowledgment, business tradeoffs, sunk-cost fallacy, and non-actionable predictors. `CORPUS_V2_VERSION` is now `atlasbench-v2-holdout-wave3`. Authored blind: no V2 wave 1/2 miss was inspected, and the leakage/internal-duplicate guards passed on the first run this time. Still 80 of the ~150-task target — wave 3 of N, not the finished expansion.

**Atlas Operational Certification Suite, wave 1** (mission SOFTWARE WAVE C): a new, real, tested, non-multiple-choice complement to AtlasBench (`atlas_operational_cert.py`). 15 scenarios (dataset profiling, data-quality diagnosis, SQL execution/grain correctness, hallucinated-schema refusal, statistical test selection, correlation-vs-causation, target leakage, class-imbalance metric choice, forecast chronological split, Python unsafe-operation rejection, evidence grounding, insufficient-evidence refusal, prompt injection in dataset text, unauthorized destructive-action refusal) score a subject's *observable* behavior — tool calls, structured claims, disclosures — never hidden reasoning, and never by asking a model to grade itself. The 8 mission-defined critical-failure kinds are typed and never averaged away; `PerfectOperationalSubject`/`UnsafeOperationalSubject` (mirroring AtlasBench's own reference-subject convention) prove the scorer actually discriminates — 6 of 8 critical kinds are exercised by wave 1. Append-only durable store plus routes (`POST /api/v1/atlas/operational-cert/reference-runs`, `GET .../runs/{id}`, `GET .../candidates/{id}/runs`). **No live-provider subject exists yet** — wiring one that drives real SQL/Python/RAG tool execution against Qwen 2507 needs the physical tool-orchestration stack and is separate future work; building a fake one here would be exactly the fabricated-capability failure this project forbids. This is wave 1 of the mission's 25-40-scenario target, not the finished suite.

Also added: an explicit test that an `arena`-kind run is rejected as promotion evidence (alongside the existing `generic`-kind case), and a digest-drift test proving a candidate run refuses when the live Ollama digest no longer matches its durable runtime binding. 40 new/modified tests total this pass across `test_atlas_bench_v2_candidate_path.py` (new), `test_atlas_operational_cert.py` (new), and additions to `test_atlas_bench_corpus_v2.py` and `test_atlas_candidate_runtime.py`. Full gate green: ruff, mypy (strict, whole tree), dependency boundaries, secret scan, OpenAPI/TypeScript freshness, and the full `pytest tests/api tests/contracts tests/migration tests/overview tests/sql_lab` suite -- **436 passed, 5 skipped** (verified via a clean isolated rerun after an initial run under concurrent load produced spurious resource-contention failures, confirmed non-reproducing).

**Not done here** (needs the physical machine, unchanged from the prior pass): registering/verifying Qwen3-4B-Instruct-2507 as a real `VERIFIED_BASE_MODEL` candidate, any fresh trusted candidate V1/V2 run, running the Operational Certification Suite against the real candidate, and any promotion/rollback drill. See the updated runbook. No candidate was registered, verified, benchmarked, or promoted from this session; production is unchanged; PR #15 remains open and unmerged.

**PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.**

## Superseding: VERIFIED_BASE_MODEL candidate trust + evaluation-policy identity — 2026-09-10 (cloud continuation)

This continuation session had no access to the physical Windows/GTX 1650 machine, no Ollama daemon, and no Soup/GPU runtime — everything below is software architecture, tests, and corpus content, not a new physical benchmark or training run. It extends, and does not alter or duplicate, the physical takeover evidence directly below.

Implemented the smallest clean extension the mission asked for: a second, equally legitimate candidate source alongside a trained Foundry adapter. `AtlasCandidateKind` (`TRAINED_ADAPTER` / `VERIFIED_BASE_MODEL`) and `AtlasVerifiedBaseModelCandidate` let an off-the-shelf model like Qwen3-4B-Instruct-2507 become a real release candidate without inventing a Foundry job, recipe, dataset, or adapter path. `atlas_base_model_trust.py` is the parallel, fail-closed trust registry: it probes the *live* local Ollama daemon (`/api/tags` + `/api/show`) for the model's real digest and manifest, checks the declared license against an allowlist (Apache-2.0/MIT/BSD-3-Clause) and the declared source against the canonical Hugging Face URL for the declared model id, and never trusts a client-supplied VERIFIED flag or digest. New routes: `POST/GET /api/v1/atlas/base-model-candidates`, `.../{id}`, `POST .../verify`, `GET .../verification`.

Both candidate kinds now converge on exactly the same downstream machinery — there is no second promotion system: `atlas_candidate_runtime` bindings are keyed by the same opaque `candidate_id` regardless of kind; `atlas_bench_live.run_candidate_benchmark` is now source-neutral (trained-adapter or verified-base-model, identical `subject_kind="candidate"` run shape); and `atlas_foundry_routes.compute_promotion_decision`/`promote_candidate` gate on either kind's trust store through one shared `_require_verified_candidate` helper, with identical strictness for both.

Added an immutable evaluation-policy identity (`atlas_bench_policy.compute_evaluation_policy_id`, stored as `AtlasBenchSuiteRun.evaluation_policy_id`) covering prompt schema, temperature, output tokens, context window, timeout, provider, and corpus identity. This directly targets the real comparability failure the physical tournament hit (an unset ~40,960-token default context vs. the trusted 4096-token run): a run with an unset/ambiguous policy gets no id at all, and `compute_promotion_decision` now fails closed unless production and candidate runs carry the *same explicit* policy id. Historical runs that predate this field are legacy/unqualified evidence, never silently treated as comparable.

Also authored **AtlasBench V2 wave 2**: 20 more hand-authored holdout tasks (2 per category) from the same predeclared taxonomy used for wave 1 — authored blind, without inspecting Qwen's V1 answers or its single V2 wave-1 SQL miss. `CORPUS_V2_VERSION` is now `atlasbench-v2-holdout-wave2` (50 tasks total: 30 wave 1 + 20 wave 2); a new internal-near-duplicate guard was added alongside the existing V1-overlap guard, and the synthetic-teacher corpus's own V2-leakage guard caught and forced a rewording of one real accidental overlap (`v2_sql_005` vs. an existing synthetic-teacher SQL example) before this could land. Still far from the ~150-task target — this is wave 2 of N, not the finished expansion.

New/modified: `atlas_base_model_trust.py`, `atlas_bench_policy.py`, `atlas_bench_live.py`, `atlas_bench_store.py` (additive `evaluation_policy_id` column via the established inspect+ALTER-TABLE migration pattern), `atlas_model_arena.py`, `atlas_foundry_routes.py`, `atlas_bench_corpus_v2.py`, plus contract additions in `prism_api_contracts` and the regenerated TypeScript contracts. 26 new/modified tests across `test_atlas_base_model_trust.py` (new), `test_atlas_bench_policy.py` (new), and additions to `test_atlas_candidate_runtime.py` and `test_atlas_bench_corpus_v2.py`; every pre-existing test still passes with unchanged behavior. Full gate: ruff, mypy (strict, whole tree), dependency boundaries, secret scan, OpenAPI/TypeScript freshness, and `pytest tests/api tests/contracts tests/migration tests/overview tests/sql_lab` all green — **419 passed, 5 skipped**.

**Not done here** (needs the physical machine): registering/verifying Qwen3-4B-Instruct-2507 as a real `VERIFIED_BASE_MODEL` candidate against the live daemon, a fresh trusted candidate AtlasBench run through the new path, the Operational Certification Suite (mission WAVE G — not started), and any promotion/rollback drill. See [the runbook this session added](../../docs/migration/PHASE10_VERIFIED_BASE_MODEL_RUNBOOK_20260910.md) for the exact commands. No candidate was registered, verified, benchmarked, or promoted from this session; production is unchanged; PR #15 remains open and unmerged.

**PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.**

## Superseding physical takeover evidence — 2026-09-10

Qwen3-4B-Instruct-2507 (`qwen3:4b-instruct-2507-q4_K_M`) scored **90/90 twice** on frozen V1, **29/30** on the separate V2 holdout, and **12/12** independent adversarial spot checks. Matched production: **74/90 V1, 19/30 V2**. Phi-4-mini: 23/90; Granite 2B: 10/90 (2 invalid). Production digest/pointer are unchanged; the historical trained 12/90 REJECT is preserved.

A previous default-context attempt exhausted RAM. The opt-in `PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096` was applied uniformly for the new tournament; prompts, scoring, 64-token answer budget, and 20-second timeout were unchanged. Winner artifacts match the official registry hashes. Soup profile/data dry-runs completed, but 4B training is borderline and no Candidate V2 training or promotion occurred. The existing trust gate requires a verified Foundry adapter; Arena alone cannot admit the off-the-shelf model.

Canonical Wave 1 corpus was physically released: 176 records (133 TRAIN / 22 validation / 21 test). No Wave 2 examples were generated from holdout material. Local validation: 392 passed / 5 skipped; ruff, mypy, boundaries, secret scan, and generated contracts passed.

**PHYSICAL_ZERO_SHOT_ARENA_COMPLETE = YES** (selected tournament). **PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.** PR #15 must remain unmerged.

See the [complete physical takeover report](../../docs/migration/PHASE10_PHYSICAL_ARENA_20260910.md) for exact digests, run IDs, category matrices, resource observations, remaining gate, and source verification. Earlier setup-blocked paragraphs below are historical.


Date: 2026-09-04

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`
`CONTINUATION_SAFE = YES`

## Superseding cloud-session continuation (2026-09-10)

A follow-on session had no access to the physical Windows/GTX 1650 machine,
no local Ollama, and no Soup/GPU runtime — recorded so nothing below is
mistaken for a new physical run. It recovered a clean tree at `ec80a7b` (PR
#15 green), delivered a cited Model Scout shortlist (see
`PHASE10_IMPLEMENTATION_LEDGER.md`), audited the Arena/promotion/live-bench
trust boundary (no forged claims found), and added an append-only Feedback
Foundation (`atlas_feedback.py`, 7 new tests, full quality gates green), and
started AtlasBench V2 (`atlas_bench_corpus_v2.py`, wave 1 of 30 hand-authored
holdout tasks with a standing leakage-guard test against v1, 9 new tests,
full quality gates green — a real first increment, not the finished suite),
and started Corpus V2's synthetic-teacher source (`atlas_corpus_v2_synthetic.py`,
wave 1 of 45 examples across 9 skill areas, wired into the real combined-SFT
route, gated by five checks that caught and forced fixes to two real bugs
before landing, 14 new tests, full quality gates green — a real first
increment toward 500-1,500, not the finished corpus). A real Arena run and
any new training experiment remain not started -- both need physical
hardware.

## Superseding physical execution record (2026-09-10)

The physical activation has run successfully as an experiment, with a valid
negative result. On Windows 10 build 26200 / i5-9300H / 16 GiB RAM / GTX 1650
Max-Q 4 GiB, isolated Soup 0.74.0 and CUDA-visible Torch 2.14.0+cu126 completed
the canonical QLoRA sequence. Candidate artifact verification and live Ollama
digest binding both succeeded. Fresh production AtlasBench was 72/90; candidate
AtlasBench was 12/90 on the frozen same corpus, so the server-owned verdict was
`REJECT`. No temporary promotion or rollback drill was authorized, and the
production runtime remains exactly `qwen3:4b-q4_K_M` with its original verified
digest. Phase 10 remains incomplete; Phase 11 remains locked.

## Legitimate candidate search activation (2026-09-10)

The Model Arena extends evaluation without changing the trusted candidate or
promotion boundary. It performs local off-the-shelf Ollama benchmarks only
after server-side digest probing; its immutable same-corpus summary is not a
promotion input. Training admission is hardware-gated: Granite 3.3 2B is the
control; SmolLM3 3B requires profile/dry-run; 4B bases remain evaluation-first.
No AtlasBench material may enter any V2 corpus.

This checkpoint supersedes the earlier Evolution-activation checkpoint text.
The software path required for PRISM's **first real Atlas evolution experiment**
is now implemented and CI-certified. It must still not be misread as evidence
that a physical Soup/GPU training experiment has run on the user's local
machine: that evidence does not exist in this execution environment.

## Authoritative code gate

Activation code head before documentation-only commits:
`5ee368e8df911c65c1121be346b0f8c9ccef504f`.

PR #15 CI run **#166** (`33904258400`) is fully green at that code head:

- `phase-1-python` — PASS
- `phase-1-web` — PASS
- `phase-4-live-e2e` — PASS, including real MySQL 8.0 + browser-to-API flow
- `legacy-regression` — PASS, including compile check for every Python file
- `secret-scan` — PASS

The repeated `history-live.spec.ts` failure is closed at its root, not hidden by
larger timeouts. SQL Lab is bound to the exact dataset created by the live test,
and the test synchronizes on real API state before asserting `3 returned / 3
total rows`. The duplicate AI Analyst `overview-profile` React-key warning was
also removed.

## Live AtlasBench production baseline

`atlas_bench_live.py` now exposes a genuine non-mutating Ollama benchmark
subject. It receives benchmark prompt + choices only; evaluator answer key,
rationale, category scores, thresholds, and promotion policy remain entirely
server-owned.

A production baseline is fail-closed:

- `PRISM_AI_PROVIDER=ollama` configuration alone creates no benchmark and no
  production pointer.
- the subject must reach Ollama `/api/tags` and find the exact configured model;
- the model digest from that successful probe is required before PRISM may
  persist the configured model as the initial production rollback anchor;
- unreachable/missing Ollama therefore produces no fabricated 0-score baseline
  and no fabricated production state.

## Soup / Foundry activation path

Current verified Soup contract is pinned in the experiment runner to
`soup-cli==0.74.0` (Python >=3.10,<3.13). The first smoke experiment is
trust-locked to `Qwen/Qwen2.5-0.5B-Instruct` to prove the full evolution loop
before attempting a larger model.

`tools/run_atlas_evolution_experiment.py` now performs one coherent physical
experiment through existing Phase 10 boundaries:

1. restore an already-durable production pointer if one exists;
2. run genuine production AtlasBench against the reachable configured Ollama
   model;
3. if this is the first experiment, persist that verified model/digest as the
   immutable rollback anchor;
4. build a durable verified training-dataset version from eligible Atlas run
   history;
5. export **TRAIN split only** — validation/test examples never enter Soup;
6. create/use the isolated pinned Soup training environment;
7. run a Resource-Governor-admitted SFT LoRA/QLoRA smoke job;
8. persist real job metrics/checkpoints/candidate artifact from actual adapter
   output;
9. export/deploy that candidate to Ollama under a candidate-only runtime name;
10. persist an append-only candidate → Ollama runtime binding and verify the
    deployed model is visible in `/api/tags`;
11. run candidate AtlasBench against the exact same frozen corpus version/hash;
12. compute and durably store the locked server-owned promotion verdict;
13. if and only if the verdict is `PROMOTE_ELIGIBLE`, append a real production
    promotion event, activate the candidate runtime, verify Atlas resolves to
    that candidate, then perform the mandatory rollback drill and verify the
    exact starting production model is restored;
14. leave production unchanged for `HOLD` or `REJECT`;
15. write an inspectable JSON experiment report under
    `.prism/runtime/evolution-experiments/`.

The runner does **not** force an eligible result. A HOLD or REJECT is a valid
successful test of the evaluator.

## Durable runtime-effective promotion

The former gap where promotion could be an auditable pointer without changing
Atlas's actual runtime is closed.

- `atlas_candidate_runtime.py` adds append-only candidate runtime bindings.
- runtime model names are validated and command-shaped names are rejected.
- `DurableAtlasPromotionStore.bootstrap()` creates the pre-Foundry rollback
  anchor once without pretending it was an evaluated candidate promotion.
- a new anchor requires a verified live model digest; startup configuration by
  itself cannot create one.
- existing pointers are rehydrated on restart.
- `POST /api/v1/atlas/promotion/promote` requires a durable evaluator-owned
  eligible decision, a real candidate artifact, and a verified candidate
  runtime binding before changing the pointer; Atlas's live Ollama model is
  activated immediately afterward.
- rollback verifies the target runtime binding **before** mutating production,
  appends a rollback event, and activates the restored model.
- no production or rollback event is edited in place.

## Training-data isolation

The normal Foundry REST path and the one-command experiment runner both train on
`AtlasTrainingSplit.TRAIN` only. A dataset version with zero TRAIN examples is
rejected rather than silently training on validation/test examples. Existing
redaction, deduplication, project/run grouping, split isolation, and hidden-CoT
exclusion remain intact.

## Regression coverage added in this activation

Coverage now includes:

- durable append-only candidate runtime bindings;
- runtime model-name injection rejection;
- configured-but-unprobed Ollama cannot create a production pointer;
- verified production bootstrap is durable and idempotent;
- promotion activation changes Atlas to the bound candidate model;
- rollback restores the exact bound starting model and preserves append-only
  history;
- Foundry refuses validation/test-only datasets;
- dead/missing Ollama cannot create a fake AtlasBench baseline;
- History live-E2E deterministic dataset binding;
- unique AI Analyst evidence keys.

## What is deliberately NOT claimed

This GitHub/CI execution environment cannot access the user's local Ollama
daemon, NVIDIA GPU, or a locally installed Soup training stack. Therefore the
following values are **not invented and remain physically unproven**:

- local OS/CPU/RAM/GPU/VRAM snapshot for the experiment;
- Ollama version and currently installed local models;
- genuine production AtlasBench score/category breakdown;
- actual `atlas-training-v0001` example counts produced from the user's local
  durable history;
- Soup training job ID, loss trajectory, elapsed time, VRAM/RAM peak, and
  checkpoint hash;
- real candidate ID/runtime model;
- candidate AtlasBench score;
- Shadow comparison result;
- final `PROMOTE_ELIGIBLE` / `HOLD` / `REJECT` result;
- a physical promotion/rollback drill.

Those facts must come from the runner's generated local report; test doubles or
GitHub Actions CPU runners cannot substitute for them.

## First real local execution (2026-09-04)

- Machine observed: Windows 11, Intel i5-9300H, 16 GiB RAM, NVIDIA GTX 1650
  Max-Q (4 GiB VRAM; 3.94 GiB free before the run), and 190.23 GiB free disk.
- Ollama 0.33.3 was healthy. The installed model selected explicitly for this
  isolated execution was `qwen3:4b-q4_K_M` (Qwen3 4B GGUF Q4_K_M,
  digest `2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`).
- A configuration defect was found before scoring: AtlasBench defaulted to a
  different model than Atlas. Commit `80f13e7` makes the live subject inherit
  `PRISM_OLLAMA_BASE_URL` and `PRISM_OLLAMA_MODEL`, with the old
  AtlasBench-specific names retained only as explicit compatibility overrides.
- Production baseline persisted in an isolated durable SQLite runtime:
  `benchrun_e22b23a14daa4590bc917922113f6547`, subject
  `atlas_ollama_24b0e61eb95e`, corpus `atlasbench-v1`, hash
  `f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`.
  It scored **71/90** in **235.6 seconds**. Category results: agentic 8/10,
  causal safety 5/8, evidence 6/8, forecasting 6/8, general 10/10, ML 9/10,
  personality 6/8, Python sandbox 7/8, SQL 7/10, statistics 7/10.
- The first real 10N/10O build truthfully produced zero eligible SFT examples
  and zero DPO pairs. This runtime contains no completed evidence-backed Atlas
  operations or real corrections; AtlasBench data is not training data.

## Remaining operational blockers

1. No verified real Atlas-run corpus or clearly-labelled system seed corpus
   exists yet, so a training job must not start.
2. Soup is not installed. Upstream was re-checked at commit
   `f07e07ed7edd548a4d1d9143f77af9027b1b7036` (v0.74.0 source): Python
   3.10-3.12, `soup profile --config`, `soup train --config`, and GGUF/Ollama
   export remain supported. A separate pinned training environment is required.
3. Candidate-artifact trust verification and an adapter-capable inference
   runtime are not yet implemented. No candidate may be trained, registered,
   benchmarked, or promoted until those gates exist.

## Soup CLI runtime verification performed in the GitHub/CI sandbox (2026-09-05)

This execution environment has no GPU (`lspci` shows no VGA/NVIDIA device, no
`/dev/nvidia*`), no `ollama` binary, and its network egress policy blocks
`ollama.com` (403 on CONNECT) while `pypi.org`/`files.pythonhosted.org` are
reachable. A physical training/deploy/promotion experiment is therefore
structurally impossible here, independent of the Soup install question. What
*is* genuinely reachable from this sandbox — and was actually run, not
assumed — is CLI/schema-level verification of the Soup integration itself:

- `soup-cli==0.74.0` installed cleanly from PyPI into an isolated,
  gitignored venv (`.prism/runtime/soup-0.74.0-venv`, not committed);
  `soup version` reports `soup v0.74.0`.
- `soup --help` / `soup train --help` / `soup profile --help` /
  `soup export --help` / `soup deploy --help` / `soup deploy ollama --help`
  confirm the exact subcommands and flags `SoupFoundryBackend` invokes
  (`soup profile --config <path> --json`, `soup train --config <path>`,
  GGUF export, `soup deploy ollama`) still exist in the real installed CLI.
- PRISM's actual `_recipe_to_soup_config()` / `write_recipe_config()` was
  called (not hand-approximated) with a real `AtlasTrainingRecipe`
  (`Qwen/Qwen2.5-0.5B-Instruct`, task `sft`, method `qlora`) to render a real
  config file, then that exact file was run against the real installed CLI:
  - `soup profile --config <rendered-config> --json` → exit 0, a genuine
    resource estimate (0.5B params, 2.11 GB estimated total memory, etc.).
  - `soup train --config <rendered-config> --dry-run` → exit 0, `Config
    valid. Ready to train!` (correctly auto-detected CPU-only, correctly
    switched unsupported `4bit` quantization to `none` on CPU, correctly
    parsed the LoRA/task/backend fields).
  - Conclusion: PRISM's Soup config renderer is schema-compatible with the
    real upstream Soup 0.74.0 CLI today. No drift was found between the
    renderer and the real schema (unlike a quick hand-written test config,
    which used the wrong nesting and was correctly rejected by Soup — that
    was this session's own test artifact, not PRISM's renderer).
  - The heavy `soup-cli[train]` extra (torch/transformers/peft/trl/etc.)
    also installs successfully in this CPU-only sandbox, but `torch.cuda.is_available()`
    is `False` here, so no real training step was attempted or claimed.

This is schema/CLI-compatibility evidence only. It does not substitute for,
and must not be read as, the physical experiment: no training, candidate,
AtlasBench, Shadow, or promotion/rollback value came from this sandbox.

## Trusted Evolution wave (2026-09-05): Candidate Trust Registry + System Seed V1

Two mandatory pieces from the approved "Trusted Evolution Wave" scope are now
real, not scaffolded:

- **Candidate Artifact Trust Registry** (`atlas_candidate_trust.py`): real
  file-level verification of a candidate's adapter workspace before it may
  enter promotion evaluation or be promoted -- SHA-256 per file, an
  allowlist of real adapter file types, path-traversal/symlink-escape and
  executable-file rejection, recipe/base-model/dataset cross-checks, and a
  required real weight file. `POST /promotion/decisions` and
  `POST /promotion/promote` both refuse (409) an unverified candidate,
  enforced server-side, not just in a client.
- **Atlas System Seed Corpus V1** (`atlas_system_seed.py`): 125 reviewed SFT
  examples targeting the first AtlasBench baseline's weak categories,
  structurally distinct from real Atlas-run/correction data
  (`source_kind="system_seed"`), passing a real programmatic leakage guard
  against the actual AtlasBench corpus (the guard caught and forced a fix
  of 2 real accidental overlaps during authoring -- proof it works, not a
  rubber stamp).

Also fixed this wave: three real CI-discovered bugs (a terminal-event/
plan-state race, an under-provisioned optimistic-concurrency retry budget,
and a duplicate `evidence_id` causing real React key collisions), plus a
separate session's defense-in-depth SSE transport guard
(`atlas_event_stream.py`) wired into the `/events` route. Full detail:
`.prism/checkpoints/phase-10-progress.md`.

Not attempted: physically merging system-seed examples into the one JSONL
file Soup actually trains on -- `export_jsonl()`'s current shape assumes a
real `source_run_id` per example, which seed examples don't have. This is a
real open design question, not solved by this wave.

## Exact next task

On the actual Windows PRISM host with the configured local Ollama model and
Python 3.10–3.12, run from repository root:

```text
python tools/run_atlas_evolution_experiment.py
```

Then inspect the generated
`.prism/runtime/evolution-experiments/experiment-*.json` and promote its real
IDs/metrics into this checkpoint/ledger. If the report is `blocked` or
`failed`, fix the concrete local runtime issue and rerun; do not fabricate or
skip a failed gate.

Do **not** start multimodal, voice, Desktop packaging, Cortex V2/dense 3D,
Phase 10 final certification, or Phase 11 until that first physical experiment
has coherent evidence.

`PHASE_10_COMPLETE = NO`
`PHASE_11_UNLOCKED = NO`

## Superseding physical certification checkpoint — 2026-09-10

Real Windows/Ollama certification reached server-verified Qwen candidate
`basemodel_585b7e79e9f195024a57dc9a`, fresh V1 **90/90 vs 74/90** and frozen
80-task V2 **78/80 vs 58/80**, with identical policies/corpora and zero
critical category regressions. Both existing server benchmark decisions
returned `promote_eligible`.

**Promotion was not executed.** The required live 23-scenario operational
certification subject is absent: only reference execution and candidate
history reads exist. Benchmark eligibility does not satisfy that missing
gate. Production remains `qwen3:4b-q4_K_M` at its exact original pointer and
digest; old model, stash and historical runtime evidence remain preserved.

A reproduced Windows clock-tie trust-ordering bug and temporary SQLite test
cleanup failures were repaired without changing trust criteria or corpora.
Local gates: 440 backend tests passed / 6 skipped, 44 frontend tests passed,
6 live browser tests passed, lint/typecheck/contracts/boundaries/secret scan
and web build passed. The existing First Light topbar remains truthful;
command-center expansion is held until safe production promotion.

Full report and immutable run identities:
`docs/migration/PHASE10_PHYSICAL_CERTIFICATION_20260910.md` and companion JSON.

`PHASE_10_COMPLETE = NO`; `PHASE_11_UNLOCKED = NO`.
