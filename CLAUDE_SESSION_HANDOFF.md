# PRISM Claude Session Handoff

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

**Not done here** (needs the physical machine): registering/verifying Qwen3-4B-Instruct-2507 as a real `VERIFIED_BASE_MODEL` candidate against the live daemon, a fresh trusted candidate AtlasBench run through the new path, the Operational Certification Suite (mission WAVE G — not started), and any promotion/rollback drill. See [the runbook this session added](docs/migration/PHASE10_VERIFIED_BASE_MODEL_RUNBOOK_20260910.md) for the exact commands. No candidate was registered, verified, benchmarked, or promoted from this session; production is unchanged; PR #15 remains open and unmerged.

**PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.**

## Superseding physical takeover evidence — 2026-09-10

Qwen3-4B-Instruct-2507 (`qwen3:4b-instruct-2507-q4_K_M`) scored **90/90 twice** on frozen V1, **29/30** on the separate V2 holdout, and **12/12** independent adversarial spot checks. Matched production: **74/90 V1, 19/30 V2**. Phi-4-mini: 23/90; Granite 2B: 10/90 (2 invalid). Production digest/pointer are unchanged; the historical trained 12/90 REJECT is preserved.

A previous default-context attempt exhausted RAM. The opt-in `PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096` was applied uniformly for the new tournament; prompts, scoring, 64-token answer budget, and 20-second timeout were unchanged. Winner artifacts match the official registry hashes. Soup profile/data dry-runs completed, but 4B training is borderline and no Candidate V2 training or promotion occurred. The existing trust gate requires a verified Foundry adapter; Arena alone cannot admit the off-the-shelf model.

Canonical Wave 1 corpus was physically released: 176 records (133 TRAIN / 22 validation / 21 test). No Wave 2 examples were generated from holdout material. Local validation: 392 passed / 5 skipped; ruff, mypy, boundaries, secret scan, and generated contracts passed.

**PHYSICAL_ZERO_SHOT_ARENA_COMPLETE = YES** (selected tournament). **PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.** PR #15 must remain unmerged.

See the [complete physical takeover report](docs/migration/PHASE10_PHYSICAL_ARENA_20260910.md) for exact digests, run IDs, category matrices, resource observations, remaining gate, and source verification. Earlier setup-blocked paragraphs below are historical.


## Read this first — Phase 10 Evolution activation (2026-09-04)

This file is intentionally reset to the current continuation state. Historical
Phase 7/8/9/early-Phase-10 detail remains in the phase reports, implementation
ledgers, and `.prism/checkpoints/`; do not use an older handoff paragraph to
infer current capability.

### Repository truth

### Superseding cloud-session continuation (2026-09-10)

This continuation session had **no access to the physical Windows/GTX 1650
machine, no local Ollama daemon, and no Soup/GPU runtime** — record this
explicitly before trusting anything below as a hardware-verified result.
Recovery confirmed a clean tree at `ec80a7b` (Model Arena) with PR #15 green
throughout and no lost local work. This session added:

- A cited Model Scout shortlist (not a benchmark run): zero-shot-Arena-first
  candidates Qwen3-4B-Instruct-2507, Phi-4-mini-instruct (MIT,
  function-calling), Granite 3.3 8B, Ministral-3-8B-Instruct-2512
  (license/build maturity unverified); QLoRA-training candidates Granite 3.3
  2B (confirms SAFE), SmolLM3 3B (BORDERLINE — root cause identified:
  `huggingface/transformers#41129` tokenizer mismatch), Qwen2.5-1.5B-Instruct
  (same family as the proven 0.5B pipeline). Excluded: Qwen2.5-3B-Instruct
  (non-commercial "qwen-research" license), Gemma 3 4B (active Transformers
  v5.1.0 4-bit-quant-ignored regression for its architecture, plus
  multimodal/embedding overhead), StableLM 2 (non-commercial license).
- A Trust/Red Team audit of `atlas_model_arena.py`, `atlas_promotion.py`,
  `atlas_bench_live.py`, and the `/promotion-decisions` route: no forged
  claims found; clarified that the category-coverage/task-totals guard lives
  in the route handler, not `decide_promotion()` itself.
- **Feedback Foundation** (new): `atlas_feedback.py` — append-only
  `AtlasFeedbackEvent`s (`helpful`/`not_helpful`/`accepted`/`rejected`/
  `corrected`), bound to `run_id`/`project_id`/`evidence`/server
  `created_at`; `corrected` requires a non-empty `correction` and is the
  future DPO substrate, the four binary kinds are the future KTO substrate.
  7 new tests; full quality gates (`ruff`, `mypy`, dependency boundaries,
  secret scan, OpenAPI/TS freshness, `pytest tests/api tests/contracts
  tests/migration tests/overview tests/sql_lab` — 364 passed, 4 skipped)
  all pass from a clean checkout.

Any actual zero-shot Arena run and any new training experiment remain not
started -- both need the physical machine this session cannot reach.
**AtlasBench V2 wave 1 is started**: `atlas_bench_corpus_v2.py` adds 30
hand-authored holdout tasks (causal confounding/reverse-causation/
selection-bias, every leakage type, imbalance, hallucinated schema, evidence
freshness/provenance, prompt injection/tool hijack, Python pitfalls,
uncertainty/refusal, business reasoning) — a real first increment toward
150+, not the finished suite, not yet wired into promotion/Arena. A new
leakage-guard test checks V2 against v1 by token overlap and already caught
one accidental near-duplicate before it landed. **Corpus V2 wave 1 is also
started**: `atlas_corpus_v2_synthetic.py` adds 45 `synthetic_teacher`
examples across all 9 skill areas, fully wired into the real combined-SFT
route (not a side pipeline), gated by five checks (V1 leakage, V2 leakage,
intra-corpus duplicates, license allowlist, secret scan) that caught and
forced fixes to two real bugs before landing — see
`PHASE10_IMPLEMENTATION_LEDGER.md` for both. 23 new tests total this
increment, full quality gates green (388 passed, 4 skipped). None of this
required or claimed physical hardware access.

### Superseding continuation state (2026-09-10)

- Physical Evolution report: completed with an honest `REJECT`, not a blocked
  runtime. Fresh production scored 72/90 and verified candidate
  `candidate_foundryjob_b077ca27d02446679e3c2e3a4b93db59` scored 12/90 against
  the same frozen corpus; production was not promoted or changed.
- The real adapter, GGUF, export logs, and report stay under `.prism/runtime/`
  and must never be committed.
- The current working tree includes an uncommitted fix which persists Ollama's
  canonical `:latest` candidate tag (rather than a non-probeable alias), plus
  Memory/RAG V2 core and tests. Preserve and finish this work on PR #15 only.
- Memory/RAG V2 provides durable hybrid retrieval with lexical fallback by
  default, deterministic test embeddings, optional local Ollama embeddings,
  provenance/injection safety, project isolation, and lifecycle APIs. It is not
  a cloud embedding integration and raw private dataset rows remain excluded.
- Model Arena is now a server-owned, digest-bound, non-mutating evaluation
  surface. It is separate from candidate trust and promotion, excludes generic
  or identity-incomplete evidence, and promotion fails closed on incomplete
  category coverage. Start candidate research with Granite 3.3 2B, admit
  SmolLM3 3B only after real Soup profile/dry-run, and treat 4B training as
  evaluation-first on this 4 GiB host.
- Do not create another PR, merge PR #15, or start Phase 11.

- Repository: `prathmesh-katkade/prism`
- Active branch: `phase-10-atlas-local-intelligence`
- PR: #15 → `phase-6.5-integration-staging`
- Canonical Phase 10 base: `ab75b5a08f03a553fe4d6229c100d0be4c1dc158`
- Activation code head certified before documentation-only commits:
  `5ee368e8df911c65c1121be346b0f8c9ccef504f`
- PR #15 CI run #166 (`33904258400`) at that code head: all five jobs PASS,
  including the real MySQL 8.0 + browser-to-API flow.
- Starting head for the candidate-search increment: `26d0c1d`; PR #15 CI #192
  is green. Preserve its historical physical REJECT evidence.
- Do not merge PR #15 yet.

```text
PHASE_9_COMPLETE = YES
PHASE_10_UNLOCKED = YES
PHASE_10_IN_PROGRESS = YES
PHASE_10_COMPLETE = NO
PHASE_11_UNLOCKED = NO
CONTINUATION_SAFE = YES
```

### What is actually implemented now

Phase 10's earlier runtime foundation remains intact: durable Atlas runs/events,
dynamic declared-tool planning, visible specialists/Council, constrained Python
sandbox, memory/RAG foundation, allowlisted Researcher, Resource Governor,
observable Atlas workspace, and truthful Cortex V1.

The Foundry/Evolution software path is now also operational rather than only
scaffolded:

- verified SFT training-data builder and real-correction DPO pairs;
- `SoupFoundryBackend` with Resource-Governor job admission;
- frozen ten-category AtlasBench and durable run history;
- real Ollama AtlasBench subject using the same provider/model configuration as
  production Atlas;
- `/api/tags` reachability/model check before any live baseline can exist;
- no production rollback anchor may be created from configuration alone — a
  verified live model digest is required;
- server-owned durable promotion decisions under the locked
  `PROMOTE_ELIGIBLE` / `HOLD` / `REJECT` policy;
- durable append-only candidate → Ollama runtime bindings;
- promotion requires an eligible evaluator decision + real candidate artifact
  + verified runtime binding and changes Atlas's active model immediately;
- rollback verifies its target runtime before changing the production pointer,
  then restores the previous bound model as a new append-only event;
- Foundry trains on TRAIN split only; validation/test-only datasets fail closed;
- native Evolution UI reads real durable state; no synthetic candidate/promotion
  values are injected;
- recurring History live-E2E dataset-ordering race is fixed and green in the
  real browser/MySQL job;
- duplicate AI Analyst evidence React key warning is fixed.

### Current Soup activation contract

The physical experiment runner pins the first activation to:

- Soup: `soup-cli==0.74.0`
- Python: 3.10–3.12
- first trust-locked smoke base model: `Qwen/Qwen2.5-0.5B-Instruct`
- default method: QLoRA/SFT, deliberately small to prove the complete evolution
  loop before scaling model size.

Canonical runner:

```text
python tools/run_atlas_evolution_experiment.py
```

It performs, in order:

1. rehydrate an existing durable production pointer when present;
2. genuine production Ollama AtlasBench;
3. verified production rollback-anchor bootstrap on the first run;
4. durable verified training-data build and TRAIN-only export;
5. isolated pinned Soup environment setup if needed;
6. Resource-Governor-admitted LoRA/QLoRA smoke training;
7. real adapter/candidate registration;
8. Soup GGUF export + candidate-only Ollama deployment;
9. durable candidate runtime binding and `/api/tags` verification;
10. candidate AtlasBench on the identical frozen corpus version/hash;
11. locked server-side promotion decision;
12. if `PROMOTE_ELIGIBLE` only: real production switch, runtime verification,
    mandatory rollback drill, and exact starting-model restoration;
13. no promotion for HOLD/REJECT;
14. JSON evidence report beneath
    `.prism/runtime/evolution-experiments/experiment-*.json`.

### What is NOT proven yet

The actual Windows host is accessible and was checked on 2026-09-05: Ollama
0.33.3, Qwen3 4B Q4_K_M, and an NVIDIA GTX 1650 Max-Q are available. `soup` is
not installed, so the experiment must stop before training. Therefore do not
claim values for:

- local OS/CPU/RAM/GPU/VRAM at experiment time;
- Ollama version/model inventory;
- real production AtlasBench scores;
- real local training-dataset counts;
- Soup loss/elapsed/VRAM/RAM/checkpoint hash;
- candidate ID/model;
- candidate AtlasBench/Shadow result;
- final promotion verdict;
- physical promotion/rollback drill.

A HOLD or REJECT result is a valid successful experiment outcome. Never force a
promotion to make the demo look successful.

### Exact next task

Continue the approved Memory/RAG V2 through Cortex V2 data-architecture wave.
Treat Soup installation as a separate physical-runtime dependency decision;
without it, the canonical evolution experiment must remain blocked and no
candidate evidence can exist.

If the report is `blocked` or `failed`, diagnose that concrete local runtime
failure and rerun. Do not start another Phase 10 product wave to avoid the
physical gate.

### Stop boundary

Do not begin multimodal, voice, Desktop packaging, Cortex V2/dense 3D, flagship
workflow/final certification, merge PR #15, or Phase 11 until the first physical
Evolution experiment has coherent evidence and the user explicitly advances
scope.

Canonical current records:

- `docs/migration/CURRENT_PHASE.md`
- `PHASE10_IMPLEMENTATION_LEDGER.md`
- `.prism/checkpoints/phase-10-evolution-activation.md`
- `.prism/checkpoints/phase-10-progress.md`
- `PHASE10_ARCHITECTURE.md`
