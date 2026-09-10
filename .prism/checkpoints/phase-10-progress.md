# Phase 10 Progress Checkpoint

## Superseding: live Operational Certification path + promotion gate — 2026-09-10 (cloud continuation, fourth pass)

Fourth cloud-safe pass, resuming right after a **real physical certification pass** landed on this branch (commit `5cdb8dd`, from the physical GTX-1650 machine, not this cloud session): Qwen3-4B-Instruct-2507 was genuinely registered (`basemodel_585b7e79e9f195024a57dc9a`), verified against the live Ollama daemon, and durably bound; fresh V1 (`90/90` vs. production `74/90`) and V2 holdout (`78/80` vs. production `58/80`) candidate benchmarks both computed `promote_eligible`. That session correctly stopped short of promoting: no live Operational Certification subject existed yet, so the operational-safety prerequisite could not be met, and it said so plainly rather than promoting anyway. PHYSICAL_ACCESS re-confirmed NO for this cloud session (no `nvidia-smi`, no `ollama` binary, `127.0.0.1:11434` connection refused, this is a generic Linux VM, not `C:\Users\prath\prism-phase10`).

This pass builds exactly that missing piece — the one named blocker, nothing more, nothing repeated:

- `atlas_operational_live.py` (new): `AtlasProviderOperationalSubject` drives a real local model over Ollama through all 23 frozen scenarios. It fails closed to an honest empty (never fabricated-pass) response on any model/parse failure, and — critically — the harness itself, not the model's self-report, owns the two objectively-checkable results (dataset profiling stats, the sandbox median): if the model calls the tool, the harness recomputes the real answer over the fixed fixture and overwrites whatever the model claimed; if it never calls the tool, any such claimed value is stripped before scoring, preserving the existing `FABRICATED_TOOL_COMPLETION` judge exactly as it works for the deterministic reference subjects. Every other scenario is scored on the same observable tool-call/disclosure evidence the frozen judges already inspect — no suite/judge code was touched.
- `POST /api/v1/atlas/operational-cert/candidates/{candidate_id}/runs` (new route in `atlas_operational_cert.py`): requires a VERIFIED, runtime-bound candidate whose live Ollama digest matches its durable binding right now (fails closed with a 409 otherwise), then runs and durably persists a real `subject_kind: "candidate"` run.
- `operational_certification_failure_reason` (new, `atlas_operational_cert.py`): the actual server-owned promotion prerequisite — requires the candidate's latest operational run to be a fresh candidate run (exact candidate_id/runtime-digest/suite-version/suite-hash match), `critical_failure_count == 0`, and pass rate ≥ `OPERATIONAL_CERT_MIN_PASS_RATE` (90%, documented in code). `atlas_foundry_routes.promote_candidate` now calls this and refuses (409) without it — for every candidate, Qwen included, with no bypass.
- Tests: `tests/api/test_atlas_operational_live.py` (10 tests: fail-closed on unreachable/malformed model responses, harness-owned real execution for the two checkable scenarios, disallowed-tool/disclosure filtering, a full 23-scenario pass through the live wiring with a scripted well-behaved model) and `tests/api/test_atlas_operational_promotion_gate.py` (6 tests: promote refused with no op-cert run, promote refused on a critical failure, promote succeeds once a fresh clean run is on record, the live route's verification/binding/digest-drift/success paths).
- `docs/migration/PHASE10_VERIFIED_BASE_MODEL_RUNBOOK_20260910.md` updated with a dated superseding note plus a replacement step 8.5 covering the new route and gate; steps 0-7's already-done work is marked reuse-only, never to be repeated absent real digest drift.

**Still not done here** (needs the physical machine): actually running the new live route against the real Qwen candidate, reading its real result, and — only if it passes cleanly — the promote → smoke → mandatory-rollback → verify-exact-restoration → final-promote drill (runbook step 9). No candidate was promoted; production is unchanged (`qwen3:4b-q4_K_M`, pointer `promo_19bfa15e3fee4cd295bdb1519650f4b9`); PR #15 remains open and unmerged; no second PR was created.

Full gate green this pass: ruff, mypy (strict, `apps/api/src packages`), dependency boundaries, secret scan, contracts freshness (no contract changes this pass), and the full pytest suite (457 passed, 5 skipped, up from 441 -- the 16 new tests are exactly the live-subject and promotion-gate suites above).

**PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.**

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


Date: 2026-09-05

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`

## Superseding 2026-09-10 cloud-session continuation

Ran with no access to the physical Windows/GTX 1650 machine, no local Ollama,
no Soup/GPU runtime — recorded explicitly so this is never mistaken for a
benchmark or training result. Recovered a clean tree at `ec80a7b`, PR #15
green throughout. Contributed: a cited Model Scout shortlist (zero-shot-first:
Qwen3-4B-Instruct-2507, Phi-4-mini-instruct, Granite 3.3 8B, Ministral-3-8B;
QLoRA candidates: Granite 3.3 2B, SmolLM3 3B [blocked on upstream
`transformers#41129`], Qwen2.5-1.5B-Instruct; excluded: Qwen2.5-3B-Instruct
[non-commercial license], Gemma 3 4B, StableLM 2); a Trust/Red Team audit of
the Arena/promotion/live-bench modules (no forged claims found); and a new
**Feedback Foundation** (`atlas_feedback.py`) — append-only
helpful/not_helpful/accepted/rejected/corrected events bound to
run_id/project_id/evidence, `corrected` carrying the future DPO correction,
7 new tests, full quality gates green. Any Arena run and any new training
experiment remain not started -- both need physical hardware. **AtlasBench
V2 wave 1 started**: `atlas_bench_corpus_v2.py`, 30 hand-authored holdout
tasks (confounding, reverse causation, selection bias, every leakage type,
imbalance, hallucinated schema, evidence freshness/provenance, prompt
injection, Python pitfalls, uncertainty/refusal, business reasoning), a
standing leakage-guard test against v1 (already caught one near-duplicate
before it landed), 9 new tests, quality gates green — a real first
increment toward 150+, not the finished suite. **Corpus V2 wave 1 started**:
`atlas_corpus_v2_synthetic.py`, 45 `synthetic_teacher` examples across all 9
skill areas, wired into the real combined-SFT route as a distinct source
class, five quality gates (V1/V2 leakage, intra-corpus duplicates, license
allowlist, secret scan) that caught and forced fixes to two real bugs
before landing, 14 new tests, quality gates green — a real first increment
toward the 500-1,500 target, not the finished corpus.
`CONTINUATION_SAFE = YES`

## Superseding 2026-09-08 status

The source-run-only Soup blocker is closed in software. The combined corpus has
deterministic TRAIN-only Alpaca export and separate provenance; candidate
benchmarks require VERIFIED trust and matching runtime digest. Physical evidence
is still required before Phase 10 completion.
`CONTINUATION_SAFE = YES`

## Superseding 2026-09-10 continuation state

Physical Evolution is no longer blocked: the canonical local runner completed
the full trusted sequence through candidate benchmark and server-owned verdict.
Fresh production (`qwen3:4b-q4_K_M`, exact digest retained) scored 72/90;
verified QLoRA candidate `candidate_foundryjob_b077ca27d02446679e3c2e3a4b93db59`
scored 12/90 on the same `atlasbench-v1` corpus hash and was `REJECT` due to
critical regressions. No promotion occurred; production remains restored by
non-mutation. The local report is retained only under `.prism/runtime/` and is
not a Git artifact.

Memory/RAG V2 core is implemented and tested alongside the existing memory API:
durable provenance-rich chunks, strict knowledge classes, local-only embedding
abstraction, lexical fallback, optional Ollama backend, hybrid score inspector,
project isolation, injection metadata, supersession/tombstones, and content-hash
no-op behavior. It does not authorize Phase 11.

## Candidate Search / Model Arena continuation (2026-09-10)

The next experiment is governed by an immutable Model Arena, not subjective
model selection: local models are evaluated with a server-probed Ollama digest
and frozen corpus without becoming candidates or mutating production. Arena
views exclude generic/reference and identity-incomplete runs, calculate
score/category deltas and critical regressions server-side, and promotion now
fails closed on incomplete category coverage. The admission order is Granite
3.3 2B control, conditional SmolLM3 3B, then only justified 4B experiments
after profile/dry-run. AtlasBench remains isolated from all data.

## Canonical status

Phase 10 has advanced through the Atlas runtime, agents/specialists, secure
Python worker foundation, memory/RAG foundation, Researcher, Resource Governor,
Foundry/Soup abstraction, verified training-data generation, AtlasBench,
Shadow/promotion policy, Evolution UI, and the software activation path for the
first real self-improvement experiment.

PR #15 remains open against `phase-6.5-integration-staging`; do not merge it yet.

CI #171's single Foundry route failure was corrected without weakening the
TRAIN-only boundary. The route fixture now creates a real completed run whose
existing deterministic split is TRAIN; the route continues to return 409 for
validation/test-only manifests. The same change fixed immutable corpus
reindexing so an example may be retained in more than one immutable dataset
version. PR CI #172 (`33907188462`) is green at `ee0fb53`.

Activation code head before documentation-only commits:
`5ee368e8df911c65c1121be346b0f8c9ccef504f`.

PR #15 CI run #166 (`33904258400`) is fully green at that code head:

- `phase-1-python`: PASS
- `phase-1-web`: PASS
- `phase-4-live-e2e`: PASS (real MySQL 8.0 + browser-to-API)
- `legacy-regression`: PASS
- `secret-scan`: PASS

The earlier lifecycle head also passed all five jobs on run #163; the History
live-E2E root fix independently passed all five on run #152.

## Evolution activation delivered

- History live-E2E now binds to its own uploaded dataset and synchronizes on
  real API state; no timeout inflation workaround.
- Duplicate AI Analyst evidence React keys fixed.
- Live Ollama AtlasBench subject uses production provider/model configuration,
  receives benchmark prompt/choices only, and probes `/api/tags` before any
  baseline can exist.
- Configured-but-unprobed Ollama cannot create a production pointer.
- Verified model digest bootstraps the pre-Foundry production rollback anchor
  once; restart rehydrates an existing pointer.
- Candidate→Ollama runtime bindings are durable/append-only and model names are
  validated.
- Foundry API and experiment runner train on TRAIN split only; zero-TRAIN
  versions fail closed.
- Promotion requires a durable evaluator-owned `PROMOTE_ELIGIBLE` decision, a
  real candidate artifact, and a verified runtime binding; it changes Atlas's
  active Ollama model.
- Rollback verifies the target binding before pointer mutation and restores the
  previous model as a new append-only event.
- Soup activation contract currently pinned to `soup-cli==0.74.0`, Python
  3.10–3.12, with `Qwen/Qwen2.5-0.5B-Instruct` as the first trust-locked smoke
  base model.
- `tools/run_atlas_evolution_experiment.py` now performs the real production
  baseline → verified TRAIN corpus → Soup LoRA/QLoRA → candidate deploy →
  candidate AtlasBench → locked verdict → eligible-only promotion → mandatory
  rollback drill sequence and writes an inspectable JSON report.

## Physical Evolution status

The actual host was rechecked on 2026-09-05: Ollama 0.33.3 is reachable, both
Qwen3 4B local models are installed, and the NVIDIA GTX 1650 Max-Q reports
3,733 MiB free of 4,096 MiB. `soup` is not installed. The physical experiment
is therefore `BLOCKED_EXTERNAL_PHYSICAL_RUNTIME` at the Soup dependency gate;
no training, candidate, verdict, or rollback value has been fabricated.

The only accepted evidence for the first real experiment is the report produced
on the actual PRISM host by:

```text
python tools/run_atlas_evolution_experiment.py
```

Expected report location:
`.prism/runtime/evolution-experiments/experiment-*.json`.

That report must supply the real hardware snapshot, Ollama/model identity,
production baseline, training dataset counts/hash, Soup job metrics, candidate,
candidate benchmark, Shadow comparison/verdict, and promotion/rollback result.
HOLD or REJECT is valid; do not force promotion.

## Trusted Evolution wave (2026-09-05)

Real CI failures were found and root-caused, not papered over -- each is a
genuine, previously-undiscovered bug in already-implemented Phase 10 code:

- `execute()` (Atlas run execution, background thread) wrote terminal
  plan state before appending the matching terminal event, so a concurrent
  poller could observe COMPLETED/FAILED/CANCELLED before the event existed.
  Fixed by reordering all three terminal paths (event first, then state).
- `DurableAtlasRunStore.append_event()`'s optimistic-concurrency retry loop
  allowed only 3 attempts, provably too few under the real concurrent load
  its own regression test exercises. Raised to 20 with jittered backoff.
- `register_ai_evidence()` set every `EvidenceRef.evidence_id` to the
  shared `provenance_ref` instead of a per-item id, producing real
  duplicate React keys in the History workspace's Evidence Inspector. Fixed
  to `{provenance_ref}:{kind}:{index}`, unique per item.
- A separate session added `atlas_event_stream.py`, a defense-in-depth SSE
  transport guard that never closes a terminal stream until the matching
  durable event is actually observed, and wired it into the `/events` route.

**Candidate Artifact Trust Registry** (10M-3 hardening, `atlas_candidate_trust.py`):
real inspection of a candidate's adapter workspace -- recipe/base-model/
dataset cross-checks, SHA-256 per file, an allowlist of real adapter file
types, path-traversal/symlink-escape and executable-file rejection, at
least one real weight file required. Append-only verification history.
`POST /promotion/decisions` and `POST /promotion/promote` now both refuse
(409) a candidate whose latest verification is not VERIFIED, enforced
server-side. 11 regression tests, including a genuinely unverified
candidate refused at both routes and a genuinely verified one passing.

**Atlas System Seed Corpus V1** (`atlas_system_seed.py` +
`atlas_system_seed_content.py`): 125 hand-authored, reviewed SFT examples
across the seven weak areas the first real AtlasBench baseline (71/90)
showed room to improve -- causal safety (20), evidence (20), SQL (20),
statistics (22), forecasting (17), senior-DS behavior (12),
security/agentic (14). `source_kind` is always the literal `"system_seed"`,
structurally distinct from real Atlas-run history and real user
corrections -- never blended into one pool. `check_atlasbench_leakage()` is
a real 8-word-shingle overlap check against AtlasBench's actual
prompts/choices/rationale; it genuinely caught 2 accidental phrase-level
overlaps during authoring (both reworded until it reports zero findings).
`GET /training-datasets:combined-summary` reports
`system_seed_examples` / `verified_history_examples` /
`user_correction_examples` / `total_eligible` as separate counts.

Still open, not attempted: merging system-seed examples with real history
into one physical Soup-consumable TRAIN export -- `export_jsonl()`'s
current per-`AtlasTrainingExample` shape is `source_run_id`-anchored, which
seed examples don't have by construction; that merge is a design decision
for a future session, not solved here.

Full backend suite: 333 passed, 4 skipped, 0 failed (was 312 at the start of
this wave). ruff/mypy/boundaries/secret-scan/TS-contracts/frontend
typecheck+lint all clean throughout.

## Next task

On the actual PRISM host (Windows, GPU, Ollama reachable): install Soup,
re-run `python tools/run_atlas_evolution_experiment.py` using the now-larger
combined training source (once the physical merge above is resolved), and
capture real physical evidence. Only after that evidence exists: continue
local-embedding hybrid RAG V2, durable feedback signals, AtlasBench V2/Model
Arena, durable hypothesis and experiment records, and Cortex V2's truthful
data projection.

Do not start multimodal, voice, Desktop packaging, Cortex V2, Phase 10 final
certification, merge PR #15, or Phase 11 before that evidence exists.

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
