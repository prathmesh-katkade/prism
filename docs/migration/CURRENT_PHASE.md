# Current migration phase

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

**Not done here** (needs the physical machine): registering/verifying Qwen3-4B-Instruct-2507 as a real `VERIFIED_BASE_MODEL` candidate against the live daemon, a fresh trusted candidate AtlasBench run through the new path, the Operational Certification Suite (mission WAVE G — not started), and any promotion/rollback drill. See [the runbook this session added](PHASE10_VERIFIED_BASE_MODEL_RUNBOOK_20260910.md) for the exact commands. No candidate was registered, verified, benchmarked, or promoted from this session; production is unchanged; PR #15 remains open and unmerged.

**PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.**

## Superseding physical takeover evidence — 2026-09-10

Qwen3-4B-Instruct-2507 (`qwen3:4b-instruct-2507-q4_K_M`) scored **90/90 twice** on frozen V1, **29/30** on the separate V2 holdout, and **12/12** independent adversarial spot checks. Matched production: **74/90 V1, 19/30 V2**. Phi-4-mini: 23/90; Granite 2B: 10/90 (2 invalid). Production digest/pointer are unchanged; the historical trained 12/90 REJECT is preserved.

A previous default-context attempt exhausted RAM. The opt-in `PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096` was applied uniformly for the new tournament; prompts, scoring, 64-token answer budget, and 20-second timeout were unchanged. Winner artifacts match the official registry hashes. Soup profile/data dry-runs completed, but 4B training is borderline and no Candidate V2 training or promotion occurred. The existing trust gate requires a verified Foundry adapter; Arena alone cannot admit the off-the-shelf model.

Canonical Wave 1 corpus was physically released: 176 records (133 TRAIN / 22 validation / 21 test). No Wave 2 examples were generated from holdout material. Local validation: 392 passed / 5 skipped; ruff, mypy, boundaries, secret scan, and generated contracts passed.

**PHYSICAL_ZERO_SHOT_ARENA_COMPLETE = YES** (selected tournament). **PHASE_10_COMPLETE = NO; PHASE_11_UNLOCKED = NO; CONTINUATION_SAFE = YES.** PR #15 must remain unmerged.

See the [complete physical takeover report](PHASE10_PHYSICAL_ARENA_20260910.md) for exact digests, run IDs, category matrices, resource observations, remaining gate, and source verification. Earlier setup-blocked paragraphs below are historical.


**Phase:** 10 — IN PROGRESS (Atlas Local Intelligence Foundry)

## Superseding 2026-09-10 status

The first actual local physical Evolution experiment is complete with a valid
negative result: verified QLoRA candidate training, artifact trust, GGUF/Ollama
deployment, digest binding, and identical-corpus AtlasBench all ran. The fresh
production score was 72/90; candidate score was 12/90, so the server-owned
verdict is `REJECT` and production remains unchanged. This closes the physical
host-access blocker but does **not** complete Phase 10 or unlock Phase 11.

Memory/RAG V2 core now supplies local-first hybrid retrieval with strict
knowledge classes, durable chunk provenance, lexical fallback, optional local
embeddings, project isolation, retrieval-injection metadata, deterministic
ranking diagnostics, and reindex/supersession/tombstone lifecycle. Durable
feedback, AtlasBench V2, Model Arena, and an eligible candidate experiment are
still Phase 10 gates.

Candidate search has now activated a digest-bound, server-owned Model Arena
for non-mutating off-the-shelf evaluations. It is not a promotion surface;
generic/reference or identity-incomplete evidence is excluded, and promotion
comparisons fail closed on incomplete category coverage. The 4 GiB host admits
Granite 3.3 2B as a conservative training control, keeps SmolLM3 3B conditional
on real preflight, and treats 4B bases as evaluation-first. No new candidate
score is claimed before an immutable run exists.

**Phase 10 integration branch:** `phase-10-atlas-local-intelligence`, based on
`phase-6.5-integration-staging` at `ab75b5a08f03a553fe4d6229c100d0be4c1dc158`.

Phase 10 now has the contract-first Atlas runtime, durable run/event state,
dynamic declared-tool planning, specialist/Council visibility, constrained
Python execution, local memory/RAG foundations, allowlisted Researcher,
Resource Governor, Atlas operations UI, and truthful Cortex V1 built in the
earlier waves.

The Foundry/Evolution stack (10M–10R) is also implemented end-to-end at the
software boundary. It includes versioned verified SFT data, real-correction DPO
pairs, a typed Soup backend, Resource-Governor-admitted training jobs, durable
candidate artifacts, the frozen ten-category AtlasBench corpus, live Ollama
AtlasBench subjects, Shadow Brain comparison, server-owned promotion decisions,
append-only promotion/rollback history, and the native Evolution workspace.
KTO remains deliberately absent because PRISM still has no genuine binary
accept/reject signal to train from.

The activation hardening completed on 2026-09-04 adds the pieces required for a
real first evolution experiment rather than a simulated one:

- the recurring History live-E2E race was fixed by binding SQL Lab to the exact
  dataset created by the test and synchronizing on durable API state; the real
  MySQL/browser CI flow is green;
- the duplicate AI Analyst evidence React key was removed;
- live AtlasBench refuses to persist a baseline unless the configured Ollama
  daemon is reachable and the requested model is present in `/api/tags`;
- the pre-Foundry production rollback anchor is created only after that live
  probe yields a model digest — configuration alone cannot manufacture a
  production pointer;
- candidate-to-Ollama runtime bindings are durable and append-only;
- Foundry exports TRAIN split only and refuses validation/test-only datasets;
- promotion requires both a durable evaluator-owned `PROMOTE_ELIGIBLE`
  decision and a verified candidate runtime binding, then changes the model
  Atlas resolves at runtime;
- rollback verifies the target runtime binding before changing the pointer and
  restores the previous bound model as a new append-only event;
- `tools/run_atlas_evolution_experiment.py` is the one-command physical
  activation path. It pins the first smoke experiment to Soup 0.74.0 and
  `Qwen/Qwen2.5-0.5B-Instruct`, records a real production AtlasBench baseline,
  builds TRAIN-only verified data, performs Soup LoRA/QLoRA training through
  the existing Foundry backend, exports/deploys the candidate to Ollama,
  benchmarks the identical frozen corpus, computes the locked verdict, and —
  only if eligible — performs a real production switch followed by a mandatory
  rollback drill ending on the exact model that started the experiment.

No real GPU/Soup experiment result is claimed by this document yet. The current
GitHub/CI environment cannot execute the user's local Ollama daemon or GPU, so
loss, VRAM/RAM peak, candidate score, Shadow result, promotion verdict, and the
rollback drill remain evidence that must come from the generated local
experiment report. A HOLD or REJECT first candidate is a valid successful test
of the evaluator; PRISM must not force promotion.

Phase 10 is therefore **software-ready for the first physical Evolution
experiment, but not Phase-10-complete**. Multimodal, voice, desktop packaging,
Cortex V2/dense 3D, flagship workflow certification, and Phase 11 remain locked
behind that evidence and the remaining Phase 10 gates.

One real local Ollama baseline was separately observed on 2026-09-04: Qwen3 4B
Q4_K_M scored 71/90 on `atlasbench-v1` in 235.6 seconds. It is only a production
baseline, not an Evolution experiment: verified SFT/DPO data was empty, Soup was
not installed, and no candidate, promotion, or rollback result exists.

The Trusted Evolution wave (2026-09-05) added two mandatory pieces of that
scope at the software boundary: a Candidate Artifact Trust Registry (real
per-file SHA-256/type/path verification, enforced server-side before
promotion evaluation or promotion) and a System Seed Corpus V1 (125 reviewed
SFT examples targeting the first AtlasBench baseline's weak categories,
verified against a real programmatic leakage guard so nothing overlaps
AtlasBench itself). Both are structurally kept as distinct source/trust
classes from real Atlas-run history -- never blended into one indistinguishable
pool. Full detail: `.prism/checkpoints/phase-10-progress.md`.

See `PHASE10_ARCHITECTURE.md`, `PHASE10_IMPLEMENTATION_LEDGER.md`,
`.prism/checkpoints/phase-10-progress.md`, and
`.prism/checkpoints/phase-10-evolution-activation.md`.

```
PHASE_9_COMPLETE = YES
PHASE_10_UNLOCKED = YES
PHASE_10_IN_PROGRESS = YES
PHASE_10_COMPLETE = NO
PHASE_11_UNLOCKED = NO
```

**Phase:** 9 — COMPLETE (durable analytical history and productization,
**PHASE_10_UNLOCKED**)

**Canonical base for the next phase:** `phase-6.5-integration-staging` at
`2013f41faa8a515b039b6a37a493abc2c05c7b23` (PR #14 — Phase 9 merge).

Phase 9 made Phase 8's analytical history durable (SQLAlchemy-backed registry
and DatasetStore, proven to survive a restart), wired the Evidence Inspector
through every native workflow, added a native History workspace, expanded
safe reproduction where an async-safe design exists, and added a lightweight
append-only audit trail — without changing any Phase 8 contract. Full detail:
`PHASE9_FINAL_REPORT.md`. Deployment verification remains
`BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` (no Render credentials in this
environment, and this session's egress policy also rejects `*.onrender.com`).
Next phase: `PHASE10_HANDOFF.md` (unscoped pointer only).

## Phase 8 — COMPLETE (all sub-phases 8A–8H merged)

Canonical base at the time: `phase-6.5-integration-staging` at
`4b291898d38e4397a335aef761ab13b3be197d68` (PR #13 — Phase 8D–8H merge).

Phases 1–7 remain complete. Overview, SQL Lab, AI Analyst, Clean, Visualize,
Stats, Forecasting, and ML Lab stay native and enabled; their Streamlit
implementations remain the parity/rollback references.

## Phase 8A–8H — COMPLETE, all merged

- 8A: [PR #10](https://github.com/prathmesh-katkade/prism/pull/10) at `4912610be584e2b3e9902500bd6585aeebb8a506`.
- 8B: [PR #11](https://github.com/prathmesh-katkade/prism/pull/11) at `670d670ee0cdaaff7a6a62f1281d2df8b6802cf8`.
- 8C: [PR #12](https://github.com/prathmesh-katkade/prism/pull/12) at `79b059f40a85a3ce5dc71500ca23286178ce5948`.
- 8D–8H: [PR #13](https://github.com/prathmesh-katkade/prism/pull/13) at `4b291898d38e4397a335aef761ab13b3be197d68`.

Gate records: `.prism/checkpoints/phase-8a.md` through `phase-8-final.md`.
Full report: `PHASE8_FINAL_REPORT.md`.

## Phase 8D–8H scope

- **8D — Versioning + Staleness Propagation.** Contextual freshness
  (`current`/`stale`/`superseded`/`unknown`/`invalid`), computed live
  against `DatasetStore`'s active identity — `AnalyticalObject` stays fully
  immutable. `GET /objects/{id}/freshness`, `GET /datasets/{id}/freshness`.
- **8E — Evidence + Lineage Inspector UI.** A dedicated `EvidenceInspector`
  React component, integrated additively into the existing shell/Inspector
  architecture, wired through Stats Lab.
- **8F — Reproducibility + Safe Rerun.** `POST /objects/{id}/rerun`
  (`same_revision`/`current_revision`) — never overwrites, always creates a
  new object. Supported: analysis/forecast/ml_model/visualization;
  deliberately unsupported kinds each carry a documented reason.
- **8G — Atlas Lineage Awareness.** Six deterministic Atlas actions
  (`explain_provenance`/`explain_staleness`/`explain_lineage`/
  `compare_versions`/`recommend_reruns`/`explain_evidence`), grounded
  entirely in recorded data — Atlas here is a rule-based explainer, not an
  LLM call, exactly like every other native workspace's existing Atlas
  actions.
- **8H — Hardening + release gate.** End-to-end integration audit (5 real
  HTTP flows), self-code-review, full regression, full repo-standard gate
  suite, `PHASE8_FINAL_REPORT.md`, this checkpoint.

No new graph engine, no dependency-graph redesign, no database/persistence
layer, no governance, no Phase 9 work. Full detail:
`PHASE8_IMPLEMENTATION_LEDGER.md` (8D–8H sections), gate records
`.prism/checkpoints/phase-8d.md` through `phase-8-final.md`.

A post-push automated review found three real gaps in 8D–8H's own new code
(a React state-reset bug and a race-guard gap in the Evidence Inspector,
and a missing `dataset_id` comparison in Atlas's `compare_versions`) — all
fixed and regression-tested in PR #13's final head before merge.

```
PHASE_8A_COMPLETE = YES   PHASE_8E_COMPLETE = YES
PHASE_8B_COMPLETE = YES   PHASE_8F_COMPLETE = YES
PHASE_8C_COMPLETE = YES   PHASE_8G_COMPLETE = YES
PHASE_8D_COMPLETE = YES   PHASE_8H_COMPLETE = YES

PHASE_8_COMPLETE = YES
PHASE_9_UNLOCKED = YES
```

## Still forbidden until a fresh scope decision

- database or persistence layer
- automatic staleness mutation or invalidation propagation
- automatic rerun without an explicit user action
- Atlas inventing a dependency, version, or stale reason (structurally
  prevented, not just policy — see `atlas_lineage.py`)
- governance / access control
- Phase 9 work

See `PHASE9_HANDOFF.md` for candidate Phase 9 directions (unscoped).

## Phase 10 superseding status (2026-09-08)

Combined SFT training and trust-bound candidate AtlasBench provenance are
implemented, but the actual Soup/GPU experiment remains unevidenced.
`PHASE_10_COMPLETE = NO`; `PHASE_11_UNLOCKED = NO`; `CONTINUATION_SAFE = YES`.

## Phase 10 cloud-session continuation (2026-09-10)

The physical Soup/GPU experiment referenced above has since run on the real
Windows host (see `PHASE10_IMPLEMENTATION_LEDGER.md`: 72/90 production,
12/90 rejected candidate). A later continuation session had no access to
that physical machine, no local Ollama, and no Soup/GPU runtime, and
contributed only what does not require it: a cited Model Scout shortlist for
the next training/evaluation candidates, a Trust/Red Team audit of the
Arena/promotion/live-bench trust boundary (no forged claims found), and a
new append-only Feedback Foundation (`atlas_feedback.py`) recording
helpful/not_helpful/accepted/rejected/corrected signal bound to
run_id/project_id/evidence — the future KTO/DPO substrate, not training
itself. It also started **AtlasBench V2**: `atlas_bench_corpus_v2.py` is a
genuinely separate 30-task holdout (confounding, reverse causation,
selection bias, every leakage type, imbalance, hallucinated schema, evidence
freshness/provenance, prompt injection, Python pitfalls, uncertainty/
refusal, business reasoning) with a standing leakage-guard test against v1
that already caught one accidental near-duplicate before it landed — a real
first increment toward the mission's 150+-task target, not the finished
suite, and not yet wired into promotion/Arena. It also started **Corpus
V2's synthetic-teacher source**: `atlas_corpus_v2_synthetic.py` adds 45
examples across 9 skill areas (SQL, statistics, causal reasoning, ML,
forecasting, evidence, agentic safety, Python, senior-DS communication),
generated only from skill specifications and never from AtlasBench, gated
by five checks (V1/V2 leakage, intra-corpus duplicates, license allowlist,
secret scan) before joining the real combined-SFT pipeline as a distinct,
separately-counted source class — a real first increment toward the
500-1,500-example target, not the finished corpus. Any actual Arena run and
any new training experiment remain not started -- both need physical
hardware.
`PHASE_10_COMPLETE = NO`; `PHASE_11_UNLOCKED = NO`; `CONTINUATION_SAFE = YES`.
