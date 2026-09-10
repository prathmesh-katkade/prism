# Phase 10 Implementation Ledger — Atlas Local Intelligence Foundry

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


## Phase status

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`

## Superseding 2026-09-10 — cloud-session continuation, Feedback Foundation

This continuation ran in a cloud sandbox with **no access to the physical
Windows/GTX 1650 machine, no local Ollama daemon, and no Soup/GPU runtime**.
Recorded explicitly so a future session does not assume otherwise: nothing
below claims a training run, a zero-shot benchmark, or a hardware profile
that did not actually execute.

Recovery confirmed a clean tree at `ec80a7b` (Model Arena) with PR #15 green
(`mergeable_state: clean`, all 5 checks passing) and no lost local work.

**Model Scout (candidate search input).** Real, cited research (not a
benchmark run) shortlisted bases against this exact hardware:
- Zero-shot Arena candidates first (no training risk): Qwen3-4B-Instruct-2507
  (current production family, Apache 2.0), Phi-4-mini-instruct (MIT, supports
  function calling), Granite 3.3 8B (Apache 2.0, inference-only on 4 GiB
  VRAM), Ministral-3-8B-Instruct-2512 (promising; license and Ollama-build
  maturity unverified — confirm before use).
- QLoRA training candidates: Granite 3.3 2B (Apache 2.0, ~1.3 GiB 4-bit
  weights, confirms the existing SAFE flag), SmolLM3 3B (still BORDERLINE;
  root cause now identified — a tokenizer BOS/PAD/EOS mismatch tracked
  upstream at `huggingface/transformers#41129` must be worked around before a
  dry run), Qwen2.5-1.5B-Instruct (Apache 2.0, same tokenizer/family as the
  already-proven 0.5B pipeline, lowest integration risk of the three).
- Excluded: Qwen2.5-3B-Instruct (ships under the non-commercial "qwen-research"
  license, not Apache 2.0 — fails the license constraint as a shipped base),
  Gemma 3 4B (confirms the existing flag: multimodal + oversized embedding
  table, and an active Transformers v5.1.0 regression silently ignores 4-bit
  quantization for `Gemma3ForConditionalGeneration`), StableLM 2 (non-commercial
  license).

**Trust/Red Team audit.** Reviewed `atlas_model_arena.py`, `atlas_promotion.py`,
`atlas_bench_live.py`, and the `/promotion-decisions` route handler in
`atlas_foundry_routes.py`. No forged claims or safety gaps found. One thing
clarified for future auditors: the "identical category coverage and task
totals" guard this ledger already claims lives in the promotion-decision
*route handler* (it compares `production_categories`/`candidate_categories`
dicts and `total_tasks` before calling `decide_promotion`), not inside
`decide_promotion()` itself — both the route guard and the arena's
same-corpus-hash query are real and tested, just at different layers.

**Feedback Foundation (new, implemented and tested).** `atlas_feedback.py`
adds server-owned, append-only feedback: `AtlasFeedbackKind`
(`helpful`/`not_helpful`/`accepted`/`rejected`/`corrected`), bound to
`run_id`, optional `project_id`, `answer`, `evidence` (typed
`AtlasEvidenceReference` list), and a server-set `created_at`. A `corrected`
event requires a non-empty `correction`; every other kind rejects one
(enforced by a `model_validator`, not just a route check). Credential/secret
redaction reuses the existing Atlas safety boundary
(`durable_atlas_store.redact_atlas_payload`). `corrected` events are the
future DPO substrate (`answer` as rejected, `correction` as preferred); the
four binary kinds are the future KTO substrate — `DurableAtlasFeedbackStore`
makes both queryable by kind, but no DPO/KTO training starts here. 7 new
tests (round-trip, append-only, correction validation both directions,
secret rejection, per-project listing). Full quality gates pass from a clean
checkout: `ruff`/`mypy`/dependency-boundaries/secret-scan/OpenAPI-TS-freshness
clean, and `pytest tests/api tests/contracts tests/migration tests/overview
tests/sql_lab` — 364 passed, 4 skipped (expected MySQL-live skips).

**Explicitly not done this session** (recorded so nothing is implied
complete): Corpus V2 curation or any synthetic-teacher data generation, any
actual zero-shot Ollama Model Arena run against a shortlisted model, and any
new QLoRA training experiment. Category-level gap analysis against the real
71/90 → 72/90 / 12/90 runs was not possible from this session — those runs'
per-category breakdowns exist only in the local SQLite history on the
physical machine, which is correctly not part of this repository. What *was*
inspected directly and is a reproducible fact, not a run result: the frozen
`atlasbench-v1` corpus itself is 90 tasks — SQL,
statistics, machine_learning, agentic, general at 10 each; forecasting,
causal_safety, evidence, python_sandbox, personality at 8 each.

## Training Corpus V2, synthetic-teacher wave 1 (2026-09-10, cloud-session continuation)

Same hardware boundary as every other entry in this section: no physical
GPU/Ollama access this session, so nothing here is a training run or a
benchmark result -- this is corpus-construction infrastructure and content.

`atlas_corpus_v2_synthetic.py` + `atlas_corpus_v2_synthetic_content.py` add a
new, clearly-labelled `synthetic_teacher` SFT source class, fully wired into
the canonical `build_combined_sft_dataset` route alongside `system_seed` and
`atlas_run` (never a parallel pipeline). Every example is generated directly
against an `AtlasSyntheticTeacherSkillArea` specification (SQL, statistics,
causal reasoning, machine learning, forecasting, evidence, agentic safety,
Python, senior-DS communication) -- never against an AtlasBench question,
choice, or rationale, which is structurally impossible here since skill area
plus topic is the only generation input. Real provenance is recorded per
example: teacher model/revision, generation-policy version, license,
validation status (`executed` for SQL genuinely run against SQLite,
`calculated` for statistics independently recomputed, `reviewed` for
conceptual content), and a note describing exactly how it was checked.

**Wave 1 is 45 examples, 5 per skill area** -- a real first increment
toward the mission's 500-1,500-example target, not the finished corpus.
Five quality gates run before release and fail closed: AtlasBench V1
leakage (word-shingle overlap, the same technique `atlas_system_seed.py`
already uses), AtlasBench V2 leakage (same technique against the holdout),
intra-corpus near-duplicate detection, license-allowlist validation, and a
secret/credential scan reusing the existing Atlas redaction boundary. These
guards are not decorative: building this wave caught and forced fixes to
two real issues before anything landed --

- a `class-imbalance` example's rationale phrased itself almost identically
  to this session's own AtlasBench V2 `v2_ml_003` task (an 8-word shingle
  match), reworded to remove the overlap while keeping the lesson intact;
- the durable store's `get_manifest` raised `OperationalError: no such
  column` against an already-existing local database, because two new
  manifest fields (`license_validation_passed`, `secret_scan_passed`) were
  added to the Pydantic contract without the matching `ALTER TABLE`
  backfill `atlas_bench_store.py` already established for exactly this
  situation -- fixed by adding that migration.

`AtlasCombinedSftDatasetVersion` and `AtlasCombinedTrainingSourceSummary`
now report `synthetic_teacher_count`/`synthetic_teacher_examples` as a
distinct, separately-counted source class, never blended into system-seed
or history counts. New routes: `POST/GET /synthetic-teacher`,
`GET /synthetic-teacher/{version}/preview`. 14 new tests (unit-level guard
tests plus one real HTTP round trip through the actual route wiring, not
just the library functions). Full quality gates green from a clean
checkout: `ruff`, `mypy`, dependency boundaries, secret scan, OpenAPI/TS
freshness, and the full backend suite -- 388 passed, 4 skipped.

Real user corrections (the Feedback Foundation's `corrected` events) are
not yet part of this corpus: the durable feedback store is genuinely empty
in this environment (no real user has used the product yet), so that
source class is correctly absent rather than fabricated. Hand-authored
human examples and properly licensed public examples are also not yet
added -- everything in this wave is honestly labelled `synthetic_teacher`
(LLM-generated), not `system_seed` (human-authored) or a licensed-public
source, because that is what it actually is.

## AtlasBench V2 holdout, wave 1 (2026-09-10, cloud-session continuation)

`atlas_bench_corpus_v2.py` adds a genuinely separate holdout corpus (never
imported by any dataset-building code path) covering exactly the trap
categories the mission named: causal confounding (a fresh case-mix hospital
example, not v1's ice-cream/drowning one — the first draft accidentally
reused that exact example and a new leakage-guard test caught it before
merge), reverse causation, survivorship/selection bias, target/feature/
temporal leakage, class-imbalance metric selection, hallucinated-schema
handling, evidence freshness/provenance/conflict, prompt injection/tool
hijack, Python correctness pitfalls (mutable defaults, silent exception
swallowing, SQL injection), uncertainty/refusal, and business-reasoning
traps (seasonality, vanity metrics, statistical-vs-practical significance).

This is **Wave 1: 30 hand-authored tasks** (machine_learning: 4; sql,
statistics, forecasting, causal_safety, agentic, evidence, python_sandbox,
general: 3 each; personality: 2) — a real starting increment toward the
mission's 150+-task target, not the finished V2 suite, and it is not yet
wired into the promotion/Arena runtime. A new automated leakage guard
(`test_v2_holdout_is_not_a_near_duplicate_of_v1`) checks every V2 prompt's
normalized token overlap against every v1 prompt and fails the build above a
0.6 Jaccard threshold — this is a standing regression test, not a one-time
manual check, and it already caught and forced a fix to one duplicate before
this landed. Self-consistency is verified the same way v1 is: a perfect
reference subject scores 30/30, a worst-case subject scores 0/30, and an
always-pick-first-choice baseline is provably not perfect. 9 new tests, full
quality gates green (`ruff`, `mypy`, boundaries, secrets, TS freshness,
373 passed / 4 skipped across the full backend suite).

## Superseding 2026-09-10 physical evidence and Memory/RAG V2

The canonical runner completed on the actual Windows host. Soup 0.74.0 used
QLoRA over `Qwen/Qwen2.5-0.5B-Instruct`; job
`foundryjob_b077ca27d02446679e3c2e3a4b93db59` completed 23 steps with recorded
loss 3.490427 -> 3.304634. The 131-record corpus had 125 system-seed and six
eligible history records (99/16/16 TRAIN/validation/test), aggregate hash
`25e5f88d447b3dce18543070731deb62c931146c51e1311ac41f5dbe17d43b9b`, TRAIN
SHA-256 `4976c11c5f97bf4f655a6a93501096b1ea6042defec5e60fcd88264d6eacaa1e`,
and provenance SHA-256
`a0f119c486dbaf4b3c5f9f9a6ccea31d195d705a278ac616d6ec406199f84d31`.

Verified candidate `candidate_foundryjob_b077ca27d02446679e3c2e3a4b93db59`
(fingerprint `84f64a8f1ce1b21e93520441db5e2903c5760bce0145faf8c66d4b579f357cd6`)
was bound to `atlas-candidate-92c971286e836cc2:latest`, digest
`91bd27c7fac143fbfcd62aeff930a0c969757c3a77da4b4e3138278ed823c7ba`.
Its trusted AtlasBench run was 12/90 against fresh production 72/90 on the
identical `atlasbench-v1` corpus/hash; server-owned decision
`promodecision_a75ea63e04bb448382c433c7b676b616` is `REJECT`. Production was
therefore not switched and rollback was not applicable. This is a valid
scientific outcome, not a Phase 10 completion.

10E is now **ADVANCED** with durable Memory/RAG V2 hybrid retrieval: local-only
embedding capability abstraction, lexical fallback, typed classes, safe source
allowlist, project isolation, provenance/injection safety, deterministic hybrid
ranking, no-op/reindex/supersession/tombstone lifecycle, and retrieval inspector
APIs. Feedback, AtlasBench V2, Model Arena, and a real candidate that passes the
locked gate remain future Phase 10 work.

## Legitimate candidate search / Model Arena activation (2026-09-10)

Model Arena is now **ADVANCED**: off-the-shelf local Ollama models can be
evaluated through an immutable, digest-bound, server-owned AtlasBench path
without becoming Foundry candidates or changing production. The arena summary
compares only identical corpus version/hash evidence, reports category and
overall deltas plus locked critical-regression flags, and excludes generic or
identity-incomplete runs. Promotion comparison additionally rejects any run
pair with missing/mismatched category coverage or task totals before policy
calculation.

Research/profiling admission: Granite 3.3 2B is SAFE for a conservative
4-bit QLoRA control; SmolLM3 3B is BORDERLINE pending a real Soup profile and
dry-run; Qwen3 4B/Phi-4-mini are zero-shot evaluation candidates first; Gemma
3 4B is not a default training choice on this host. A trained V2 corpus,
feedback events, AtlasBench V2, and a candidate meeting the locked policy are
still pending. No score is claimed until the new server-owned run completes.

## Superseding 2026-09-08 status

Combined SFT dataset/export and trust-bound candidate benchmark provenance are
implemented. Physical Soup/GPU/Ollama experiment evidence remains pending; no
training result or promotion is claimed.

Canonical starting point: `phase-6.5-integration-staging` at `ab75b5a`.
Phase 9 remains complete; its externally blocked Render certification is not an
engineering blocker for this phase.

## First real Evolution execution (2026-09-04)

The first server-owned, real local Ollama AtlasBench baseline completed on the
user machine. Qwen3 4B Q4_K_M (`qwen3:4b-q4_K_M`, digest
`2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`) scored
**71/90** in **235.6 seconds** on frozen `atlasbench-v1`
(`f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`), durable
run `benchrun_e22b23a14daa4590bc917922113f6547`. This baseline was run through
the server-owned subject boundary; answer keys, rationales, and policy stayed
server-only. The local machine is Windows 11 / i5-9300H / 16 GiB RAM / GTX
1650 Max-Q 4 GiB VRAM / 190.23 GiB free disk.

The first truthful dataset build contains zero eligible SFT examples and zero
DPO pairs because the isolated runtime has no completed evidence-backed Atlas
runs or real correction pairs. AtlasBench is not training data. Training,
candidate registration, and promotion therefore remain blocked until a
clearly-labelled verified corpus (or restricted smoke-only seed corpus),
candidate-artifact trust verification, and a real adapter inference path are
implemented.

## CI recovery increment (2026-09-04, before the Foundry wave)

A prior session's Foundry work was interrupted mid-wave with PR #15's CI red.
Recovery check found no interrupted local work anywhere (fresh clone, empty
`git status`/`diff`/`stash`, no Foundry-named branch or commit repo-wide) — the
pushed HEAD (`351f299`) was the honest last state. Fixed, tested, and pushed
(`9134f99`, `eb3a12b`, `65faec8`):

- Windows-only mypy symbols (`subprocess.CREATE_NEW_PROCESS_GROUP`,
  `ctypes.windll`) isolated behind a new `atlas_platform` module so Linux CI
  type-checks; Windows behavior unchanged, POSIX now gets real memory
  telemetry instead of always `None`.
- `CREATE INDEX IF NOT EXISTS` (invalid on MySQL 8.0) replaced with an
  Inspector-checked, restart-safe, MySQL/SQLite-portable `_ensure_index()`.
- A third, previously CI-unreached failure: `-> None` DELETE routes made
  FastAPI infer a truthy `NoneType` response_model, tripping its 204 assert
  at import time and breaking every test/tooling import of `prism_api.main`.
  Fixed with explicit `response_model=None`; stale generated TS contract
  regenerated.

- A fourth failure, found only once the live-MySQL job got this far:
  `prism_atlas_knowledge_chunks.source_ref` was indexed at its full
  `String(2000)` length, exceeding MySQL InnoDB's 3072-byte max index key
  under utf8mb4 (error 1071) — failing at `DurableAtlasMemoryStore`
  construction, i.e. `prism_api.main` import time. Fixed (`27923a4`) with a
  short `source_ref_hash` lookup column; `source_ref` keeps its full value
  and exact-equality semantics for callers. The MySQL-safe index helper was
  extracted into a shared `atlas_schema_utils` module used by both durable
  stores.

Local evidence: `ruff`/`mypy` clean (exact CI invocation), `pytest tests/api
tests/contracts tests/migration tests/overview tests/sql_lab` → 246 passed, 4
skipped, boundaries/secrets/contract-freshness all pass.

**CI on PR #15 is confirmed green at `27923a4`**: `phase-1-python`,
`phase-1-web`, `phase-4-live-e2e` (the real MySQL 8.0 job), `legacy-regression`,
and `secret-scan` all passed; `mergeable_state: clean`. The live-MySQL fixes
could not be reproduced locally in this sandbox (no Docker daemon, no
installable `mysql-server`), so this CI run is the authoritative
confirmation. **The Foundry wave (10M–10R) begins now.**

## First implementation wave

| Internal gate | Status | Evidence |
| --- | --- | --- |
| 10A Runtime/provider abstraction | ADVANCED | Deterministic fallback is always available. Ollama may now propose JSON plans from capped compact metadata only; schema/tool validation rejects invalid output and records provider/model/prompt-schema provenance. It cannot execute tools or receive raw rows. |
| 10B Orchestrator/planning | ADVANCED | SQLAlchemy-backed runs/event journal, deterministic event sequence, idempotency key, durable cancellation intent/replay, dynamic typed planner, declared-tool validation, and safe insufficient-context blocking. |
| 10C Specialist team/Council | ADVANCED | Visible Atlas/Scout/Curator/Stat/Auditor identities; Curator now performs actual quality review. Query/Forge/Oracle/Lens are typed plan identities only when the required native request context exists; none is faked as an executor. |
| 10D Secure Python sandbox | PARTIAL | Native-worker process boundary now has an empty user environment, new process group/tree termination, deny-by-default network/import/filesystem policy, bounded output, artifacts, health/capability reporting, and honest Windows quota status. Hard CPU/memory enforcement requires a configured container worker and remains unclaimed. |
| 10E Memory/RAG | PARTIAL | SQL-backed scoped memory CRUD/reinforcement/supersession/audit plus project-isolated lexical knowledge indexing, source version/reindex/delete, provenance and prompt-injection flags. Local embedding adapter and analytical-history ingestion remain next increments. |
| 10F Researcher | PARTIAL | Explicit server-side allowlisted-HTTPS Researcher has typed results/citations, offline/blocked behavior, bounded untrusted content, and injection flags. It is not unrestricted search or a sandbox capability. |
| 10G Cortex graph data model | ADVANCED | Cortex projects durable run, dataset, plan, specialist, declared tool, and evidence IDs only. |
| 10H Cortex visual system | PARTIAL | Native SVG Cortex V1 provides organic curved paths, state styling, Focus Lens, zoom controls, and reduced-motion mode over only real graph records. Dense/3D visualization remains out of scope. |
| 10I Observable execution UI | ADVANCED | Native Atlas operations desk renders objective, state, live SSE-updated plan, specialist activity, Council/evidence, cancellation, errors, grounded answer, and Cortex V1. |
| 10L Resource Governor | PARTIAL | Typed priority leases, cancellation-aware preemption, concurrency admission, CPU/RAM/storage snapshot, optional GPU telemetry, truthful no-GPU reporting, **and now real Foundry-training integration** (`atlas_foundry_orchestration.start_training_job`/`reconcile_foundry_jobs`): every training job is admitted at `FOUNDRY_TRAINING` priority, and a preempting interactive lease hard-cancels the running job (an honest "yield," not a claimed graceful pause). |
| 10M Atlas Foundry | ADVANCED | `FoundryBackend` (ABC) / `MockFoundryBackend` / `SoupFoundryBackend` (real, tested against the actual `soup` CLI inspected from its upstream repo — v0.73.3's `soup.yaml` schema, `soup profile --json`, checkpoint conventions). Recipes reach Soup only via a validated `AtlasTrainingRecipe` rendered to YAML, never a string-built command. `soup` is absent in every environment this project runs in so far; every backend method degrades to an honest "unavailable" result rather than a crash or a pretend success. Resource-Governor-admitted job lifecycle (queue/start/poll/cancel) plus a durable, MySQL-safe job/recipe store. |
| Candidate Registry | ADVANCED | `DurableAtlasCandidateRegistry`: a completed job with real adapter output on disk registers exactly one `AtlasCandidateArtifact`, idempotently. Deliberately just the durable fact of what was produced — no promotion-status lifecycle (DISCOVERED/PROMOTED/...) is invented here; that is 10Q's concern once AtlasBench exists to gate it. |
| 10N Verified training-data generator | ADVANCED | `AtlasTrainingDatasetBuilder`: eligible-only (completed, evidence-backed, answered, ≥1 completed tool step), redacted a second time at the export boundary, deterministic ~80/10/10 split keyed on `dataset_id` so near-duplicates never straddle splits, content-hash dedup, deterministic JSONL export, idempotent durable versioned storage with preview/exclusion inspection. No hidden chain-of-thought: reuses Atlas's own typed, already-user-visible plan/council structures. |
| 10O SFT/DPO/KTO | PARTIAL | SFT is 10N. DPO (`AtlasPreferenceDatasetBuilder`) sources real chosen/rejected pairs from Atlas memory's existing `supersede()` correction workflow — never a manufactured negative example; a dangling successor or no-op correction is excluded, not faked. **KTO is deliberately not implemented**: no genuine binary accept/reject feedback signal exists anywhere in the product yet, and inventing one would violate the same rule that makes the DPO source trustworthy. PPO/GRPO remain explicitly out of scope. |
| 10P AtlasBench | ADVANCED (initial corpus) | 90 hand-authored, correctness-checked tasks across all ten required categories (SQL/statistics/ML/forecasting/causal-safety/agentic/evidence/Python-sandbox/personality/general) — an initial wave chosen for correctness over volume, not yet the "thousands of tasks" scale the architecture supports. Frozen, version-controlled answer key with no runtime write path (a candidate cannot see or influence its own judge); deterministic `run_suite()` scoring against a pluggable `AtlasBenchSubject`; append-only durable run history (a rerun is a new `run_id`, never an edit). |
| 10Q Shadow Brain / Promotion / Rollback | ADVANCED | `shadow_compare()` runs production and candidate through the identical AtlasBench corpus — non-mutation is structural (a subject only ever receives a prompt + choices, returns an index). `decide_promotion()` enforces the locked policy: IMPROVE TARGET CAPABILITY + NO UNACCEPTABLE CRITICAL REGRESSION, against `CRITICAL_CATEGORIES` (SQL/statistics/ML/causal-safety/agentic/evidence/Python-sandbox) — a candidate cannot win on aggregate score while regressing any one critical category. `DurableAtlasPromotionStore` is an append-only production-pointer event log: `promote()` is atomic and refuses any non-`PROMOTE_ELIGIBLE` decision at the storage boundary itself; `rollback()` restores the previous production candidate as a new explicit event, never an in-place undo — the full history IS the rollback list, and no row is ever overwritten. |
| Adapter Foundation | ADVANCED (honest stub) | Typed logical adapter identities (`atlas-core/sql/statistics/ml/forecast/research`) with a capability report that is truthfully all-`False` right now: no runtime wired into this project can load, unload, or hot-swap a LoRA adapter at inference time, and reporting otherwise would be exactly the fabricated-capability failure this module exists to prevent. Falls back to core Atlas by construction. |
| 10R Atlas Evolution UI | ADVANCED (real data, no live promotable candidate yet) | Native `EvolutionWorkspace` tab wired into the shell, reading Foundry capability, AtlasBench corpus summary, current/history promotion pointers, candidates, training/preference dataset versions, training jobs, and adapter capabilities from the routes below. Every panel renders a specific, honest empty state (no candidate trained, no promotion made, no job queued) rather than a placeholder — there is nothing to fake because no candidate has ever actually been trained or promoted in this environment. The only mutating action on the promotion panel is rollback (operator-supplied reason, never a client-supplied verdict); dataset builders and job reconciliation call the same read/write boundary the REST layer enforces. |
| 10J–10K, 10S–10T | NOT STARTED | Multimodal, voice, and desktop-packaging-adjacent gates remain future internal gates untouched by this wave. |
| 10U–10W | NOT STARTED | Flagship workflow and final certification remain out of scope for this wave. |

## Invariants preserved

- Existing AI Analyst remains compatible and retains its compact, server-only
  context plus SQL Lab-only execution path.
- Atlas invokes only declared deterministic tools. Python is a separately typed,
  constrained project sandbox; it has no generic shell, network, package-install,
  model-download, or inferred-code path. SQL remains SQL Lab-only.
- DatasetStore remains the revision/content authority. Atlas evidence references
  its active identity and never changes it.
- No historical analytical object, lineage edge, audit event, or freshness value
  is mutated by this wave.
- Cortex derives from stored runtime records; it does not expose fabricated
  thoughts or a chain of thought.

## First demonstrator

`unknown CSV → Overview profile → Scout conclusion → Stat methodology review →
Auditor evidence review → Atlas grounded answer`, with events available through
`GET /api/v1/atlas/runs/{run_id}/events` and the real-state graph through
`GET /api/v1/atlas/runs/{run_id}/cortex`.

## Verification to date

- `pytest tests/api/test_atlas_runtime.py tests/api/test_atlas_durable_runtime.py tests/api/test_atlas_sandbox.py tests/api/test_atlas_memory_resources_research.py -q` → **16 passed** (one non-failing FastAPI deprecation warning).
- `npm run typecheck`, `npm run lint`, and `npm run test:web` → **passed** (35 frontend tests).
- `python tools/check_boundaries.py`, `python tools/check_secrets.py`, and TypeScript contract freshness → **passed**.
- `npm run build:web` is **BLOCKED_LOCAL_WORKTREE**: Next/Turbopack rejects this worktree's `node_modules` symlink because it points outside the worktree root. This is not a source compilation/type failure; supported CI must build from a normal checkout.
- `pytest tests/api/test_atlas_runtime.py tests/api/test_ai_analyst.py tests/api/test_contracts.py -q` → **19 passed**.
- Broader API/contract/parity run reached **42 passed** before the known local
  Python 3.9 incompatibility in pre-existing Forecasting tests
  (`zip(..., strict=True)`, a Python 3.10+ API). This is not an Atlas failure;
  authoritative full certification requires the project CI's supported Python
  3.11 environment.
- `ruff check` over the new runtime, public contracts, and tests → **passed**.
- targeted `mypy` over the new runtime and contracts → **passed**.
- TypeScript public contract regenerated and freshness check passed.
- Full repository, browser, sandbox-isolation, memory, model-trust, AtlasBench,
  and accessibility gates are intentionally not yet certification evidence.

## Foundry wave (2026-09-04, 10M–10Q)

Built only after PR #15's foundation CI was confirmed green at `27923a4`, in
this order, one commit per coherent unit:

| Commit | Unit | Module(s) |
| --- | --- | --- |
| `b0926ca` | 10N | `atlas_foundry_dataset.py` |
| `4c6e8e4` | 10O | `atlas_foundry_preference.py` |
| `856fb30` | 10M-1/2/3 + Candidate Registry | `atlas_foundry_backend.py`, `atlas_foundry_orchestration.py`, `atlas_platform.py` additions |
| `1af8562` | 10P | `atlas_bench_corpus.py`, `atlas_bench_runner.py`, `atlas_bench_store.py` |
| `063de4d` | 10Q + Adapter Foundation | `atlas_promotion.py`, `atlas_adapter_foundation.py` |

Every commit above: `ruff`/`mypy` clean (exact CI invocation), full
`pytest tests/api tests/contracts tests/migration tests/overview
tests/sql_lab` suite green before pushing (288 passed / 4 skipped at
`063de4d`), boundaries/secrets/contract-freshness all pass. CI on PR #15
confirmed green through `1af8562`; `063de4d`'s run was in flight at last
check (see `.prism/checkpoints/phase-10-progress.md` for the live status).
`phase-4-live-e2e` intermittently fails on two different frontend Playwright
specs unrelated to any file this wave touched — a pre-existing,
Phase-9-documented CI-runner-timing flake (see the standing-down comment on
PR #15); not this wave's regression.

Deliberately not fabricated in this wave:
- **KTO** (10O): no genuine binary accept/reject feedback signal exists in
  the product.
- **Adapter hot-swap**: no runtime here can load/unload/hot-swap a LoRA
  adapter; `AtlasAdapterCapability` reports that honestly.
- **Real Soup training**: `soup` is not installed anywhere this project has
  run; `SoupFoundryBackend` is real, tested code, but has never actually
  launched a training subprocess outside its own "absent" path. The recipe
  → YAML rendering, capability probing, and process lifecycle logic are
  fully tested; the live end-to-end training path is not, and should not be
  claimed as verified until it has actually run against a real `soup`
  install.
- **A wired AtlasBench subject**: the corpus/runner/store are real and
  tested against reference subjects (Perfect/Worst/FirstChoice) that prove
  the harness itself is correct. No subject wrapping a live Atlas provider
  (deterministic or Ollama) exists yet — that is the natural next increment,
  not assumed done here.
- **REST endpoints / UI**: nothing in `atlas_foundry_dataset.py`,
  `atlas_foundry_preference.py`, `atlas_foundry_backend.py`,
  `atlas_foundry_orchestration.py`, `atlas_bench_*.py`, or `atlas_promotion.py`
  is wired to `apps/api/src/prism_api/atlas.py` (the FastAPI router) yet.
  Everything above is backend modules, durable stores, and tests only.

## REST wiring + 10R (2026-09-04, same session, continued autonomously)

| Commit | Unit | Module(s) |
| --- | --- | --- |
| `61124f5` | REST wiring for 10M–10Q | `atlas_foundry_routes.py` (new), `main.py` router registration, `generated.ts` regenerated |
| `779222b` | 10R Atlas Evolution UI | `evolution-workspace.tsx` (new), `evolution-workspace.test.tsx` (new), `prism-shell.tsx`, `shell-model.ts`, `prism.css` |

`atlas_foundry_routes.py` exposes `/api/v1/atlas/foundry`, `/api/v1/atlas/bench`,
`/api/v1/atlas/promotion`, and `/api/v1/atlas/adapters`, deliberately narrower
than the backend surface it wraps on two security-relevant boundaries: no
route ever returns an `AtlasBenchTask`'s `correct_choice`/`rationale` (only
the safe `AtlasBenchCorpusSummary` — counts, no answer key — is public), and
there is no "promote" endpoint — only read-only current-production/history
and the no-client-input `rollback` action, because a promotion decision must
come from a real server-side `decide_promotion()` call over a real suite run,
never a client-supplied `AtlasPromotionDecision`. 9 new integration tests
verify both boundaries plus the training/preference dataset build-list-preview
round trip, job start/cancel/reconcile, and clean 404s. 10R's
`EvolutionWorkspace` consumes exactly this surface; see the 10R row above for
what it renders and why every empty state is honest rather than a fabricated
"current model."

Both commits: `npm run typecheck`/`lint`/`test:web` pass (38/38 across 11
suites at `779222b`); `61124f5`'s backend changes also passed the full
`ruff`/`mypy`/pytest (297 passed)/boundaries/secrets/contract-freshness
pass locally before pushing. `phase-4-live-e2e` failed a third time at
`61124f5` (CI run #131) on the same pre-existing `history-live.spec.ts`
timing flake already documented in the standing-down PR comment (see
`b0926ca`/`4c6e8e4`'s occurrences above) — same assertion
(`'3 returned / 3 total rows'`), still nowhere near this wave's diff.
`779222b`'s CI run (#132) is the natural re-run this situation calls for;
see `.prism/checkpoints/phase-10-progress.md` for its outcome.

Deliberately not done in this increment:
- No live `AtlasBenchSubject` wraps a real Atlas provider yet, so there is
  no "run the benchmark suite" REST action — only read-only run history for
  whatever a caller runs out-of-band.
- No candidate has ever actually been promoted in any environment this
  project has run in, so the Evolution UI's production/candidate/history
  panels are exercised by tests against real (empty or seeded-in-test) durable
  state, not against a real end-to-end promotion that has actually happened.
- `soup` remains absent from every environment this project runs in; starting
  a real Foundry job through the UI will queue or fail honestly, exactly as
  the backend already did before this wiring.

## Exact next task

The build order specified for this session (10N, 10O, 10M, Candidate
Registry, 10P, 10Q, Promotion/Rollback, Adapter Foundation, 10R) is now
complete. Remaining natural next increments, none started here: wire a first
real `AtlasBenchSubject` around the existing deterministic Atlas provider so
`shadow_compare`/`decide_promotion` can run against a live subject instead of
only the reference (Perfect/Worst/FirstChoice) subjects; expose a "run the
benchmark suite" REST action once that subject exists; and exercise an actual
end-to-end `soup train` run against a real Soup install to move
`SoupFoundryBackend` from "real and tested" to "verified end-to-end."
`PHASE_10_COMPLETE` remains `NO`. Do not start Phase 11.

## Evolution activation hardening — canonical current state (2026-09-04)

This section supersedes earlier statements above that describe live AtlasBench,
Foundry REST wiring, History live-E2E, or promotion as not yet operational at
the software boundary. Those entries are retained as historical implementation
records.

### Gate status after activation

| Gate | Current state |
| --- | --- |
| 10M Atlas Foundry | **ADVANCED / PHYSICAL RUN PENDING.** Current upstream contract was re-verified and the first experiment is pinned to `soup-cli==0.74.0`; the normal API and local runner use the same typed `SoupFoundryBackend`. |
| 10N training data | **ADVANCED.** Normal Foundry and experiment activation export `TRAIN` only; validation/test-only versions fail closed. Hidden CoT, secrets, and raw private rows remain excluded. |
| 10P AtlasBench | **ADVANCED / LIVE OLLAMA SUBJECT IMPLEMENTED.** A real Ollama subject probes `/api/tags`, uses the production model/provider configuration, receives prompt+choices only, and persists no fake baseline when the runtime/model is unavailable. |
| 10Q Shadow/Promotion/Rollback | **ADVANCED / RUNTIME-EFFECTIVE.** Candidate→Ollama bindings are durable. A verified model digest is required before the first production rollback anchor may be created. Promotion requires an evaluator-owned eligible decision plus a real runtime binding, changes Atlas's active model, and rollback verifies/binds the previous runtime before changing the pointer. |
| 10R Evolution UI | **ADVANCED.** It reads durable production/candidate/benchmark/training/history state. Synthetic demo data is not introduced. |

### CI and browser recovery

The recurring History live-E2E failure was fixed at the actual synchronization
boundary: the test now binds SQL Lab to the exact dataset it created and waits
on real API state instead of depending on cross-test connection ordering or
arbitrary timeout growth. The duplicate AI Analyst evidence React key was also
removed.

Activation code head `5ee368e8df911c65c1121be346b0f8c9ccef504f`
is certified by PR #15 CI run **#166** (`33904258400`):

- `phase-1-python` PASS
- `phase-1-web` PASS
- `phase-4-live-e2e` PASS, including real MySQL 8.0/browser-to-API flow
- `legacy-regression` PASS
- `secret-scan` PASS

The earlier lifecycle head was independently all-green on run #163, and the
History root fix was independently all-green on run #152.

### One-command real evolution experiment

`tools/run_atlas_evolution_experiment.py` is now the canonical first physical
activation path. It:

1. restores any already-durable production runtime pointer;
2. benchmarks the actual reachable Ollama production model;
3. creates the first rollback anchor only from that successful model probe and
   digest;
4. builds/persists verified training data and exports TRAIN only;
5. installs/uses isolated pinned Soup 0.74.0 when required;
6. runs a Resource-Governor-admitted SFT LoRA/QLoRA smoke job using the first
   trust-locked base model `Qwen/Qwen2.5-0.5B-Instruct`;
7. requires actual adapter output before registering a candidate;
8. exports/deploys the candidate to Ollama and verifies it appears in
   `/api/tags`;
9. persists the candidate runtime binding;
10. runs candidate AtlasBench on the identical frozen corpus version/hash;
11. computes and persists the locked server-side verdict;
12. for `PROMOTE_ELIGIBLE` only, performs a real runtime promotion, verifies
    Atlas resolves to the candidate, then performs the mandatory rollback drill
    and verifies the exact pre-experiment production model is restored;
13. leaves production untouched for HOLD/REJECT;
14. writes the complete local evidence report beneath
    `.prism/runtime/evolution-experiments/`.

### Remaining non-fabricated boundary

The GitHub/CI environment does not have access to the user's local Ollama daemon
or physical NVIDIA GPU. Therefore no baseline score, training loss, VRAM/RAM
peak, local candidate artifact, candidate AtlasBench score, Shadow result, or
promotion verdict is claimed here. Those values must come from the real local
experiment report.

### Exact next task — supersedes the older next-task section above

On the actual PRISM host, from repository root, run:

```text
python tools/run_atlas_evolution_experiment.py
```

Inspect `.prism/runtime/evolution-experiments/experiment-*.json`. If the report
is blocked/failed, fix the concrete local issue and rerun; do not skip or
manufacture a gate. If it completes, record its real baseline, training,
candidate, Shadow, verdict, and rollback evidence here before continuing to
multimodal, voice, Desktop packaging, Cortex V2, flagship certification, or
Phase 11.

`PHASE_10_COMPLETE = NO`
`PHASE_11_UNLOCKED = NO`
