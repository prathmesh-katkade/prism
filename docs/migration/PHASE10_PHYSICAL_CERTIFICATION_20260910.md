# Phase 10 physical certification — 2026-09-10

Qwen passed fresh V1 and frozen V2 comparisons. Production promotion remains blocked by missing live operational certification. No promotion or rollback was attempted.

## Repository and physical access

- Physical checkout: `C:\Users\prath\prism-phase10`.
- Starting local HEAD: `a325b84f6ac473489930a6095f480ae3087f05b9`.
- Clean fast-forward to evaluated API HEAD: `93304868cce631be4fc874280ef4643416ea3997`.
- Branch: `phase-10-atlas-local-intelligence`; existing PR #15 remains open and unmerged.
- Starting CI #202 succeeded on that exact remote HEAD.
- GPU and Ollama access: YES. GTX 1650 / 4 GiB, driver 560.94, Ollama 0.33.3.
- Existing stash and `.prism/runtime` evidence preserved; old model remains installed.

## Verified identity

- Candidate: `basemodel_585b7e79e9f195024a57dc9a` (`VERIFIED_BASE_MODEL`).
- Verification: `basemodelverify_01789045436959639800_309c2afdeb0d4010969d307a25dfb373`; state `verified`.
- Fingerprint: `751a7e3691c77af1c49a5dab83624be35a0f92a02e4c2c24f04aa37b89717796`.
- Runtime: `qwen3:4b-instruct-2507-q4_K_M`.
- Live runtime digest: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- Live manifest digest: `d6f2a22ac09fbcc8960fa1065c07b4cb05bd517b5b00daab60055dd2e5bac9ec`.
- Declared upstream: `Qwen/Qwen3-4B-Instruct-2507`, revision `cdbee75f17c01a7cc42f958dc650907174af0554`.
- Declared license: `Apache-2.0`; canonical source: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507.
- The existing server verifier checked the approved license declaration, canonical source identity, and live Ollama digest/manifest. This is not an independent cryptographic attestation of upstream weight ancestry.
- Durable runtime binding: `runtimebind_01789045454554534000_8c5a131da117428db4940ba3d4b67569`.

## Fresh benchmarks

All four runs were made through existing server-owned production/candidate routes. No Arena runs were reused. Inference policy: Ollama, context 4096, temperature 0, num_predict 64, timeout 20 seconds. Corpus, task count, category coverage and policy IDs match within each comparison.

### atlasbench-v1

- Production: **74/90**, `benchrun_7a0e6ac7c5114702bc12f1d2629fe470`.
- Qwen candidate: **90/90**, `benchrun_f4638ff45ac24edba56411bcbc6feadd`.
- Corpus hash: `f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`.
- Both policy IDs: `75886a208c87534da2f2605d6ac1358d449bbe8d413f86903e8c8736cca02443`.

| Category | Production | Qwen |
|---|---:|---:|
| agentic | 9/10 | 10/10 |
| causal_safety | 5/8 | 8/8 |
| evidence | 6/8 | 8/8 |
| forecasting | 7/8 | 8/8 |
| general | 10/10 | 10/10 |
| machine_learning | 9/10 | 10/10 |
| personality | 7/8 | 8/8 |
| python_sandbox | 7/8 | 8/8 |
| sql | 7/10 | 10/10 |
| statistics | 7/10 | 10/10 |

### atlasbench-v2-holdout-wave3

- Production: **58/80**, `benchrun_5ee370e70b8c486fa9e24ebfee3675c4`.
- Qwen candidate: **78/80**, `benchrun_9ca690c306574e368e04fc761b720e8b`.
- Corpus hash: `e3cd54b5ff58b7170d08672bee1cd7984f5a1c27dfa5eccbd48cbb10118771db`.
- Both policy IDs: `33209015d9217262406ddd228ba9295a5714869479b642e2e0d78c5dcc5aca52`.

| Category | Production | Qwen |
|---|---:|---:|
| agentic | 7/8 | 8/8 |
| causal_safety | 6/8 | 8/8 |
| evidence | 6/8 | 8/8 |
| forecasting | 6/8 | 8/8 |
| general | 6/8 | 7/8 |
| machine_learning | 7/9 | 9/9 |
| personality | 3/7 | 7/7 |
| python_sandbox | 6/8 | 8/8 |
| sql | 5/8 | 7/8 |
| statistics | 6/8 | 8/8 |

## Operational certification and promotion

- Frozen suite: `atlas-operational-cert-wave2`, **23 scenarios**, hash `b5b2646896fc6f6486e82cd537c5e95b8a3e1bcb35964b09958abf674a39be69`.
- Live candidate run: **NOT RUN**. Passed/failed/critical-failure counts are unknown, not zero.
- Live OpenAPI exposes GET candidate runs and POST reference runs only. Reference subjects test judges; they cannot certify Qwen.
- `atlas_runtime.EXECUTABLE_TOOLS` contains profile, quality review, methodology review and evidence audit. SQL/Python/research requests route to review/approval-required states. Wiring a genuine live suite requires the real stack and persisted execution evidence; replacing it with model-declared tool calls would not satisfy certification.

- Existing server V1 decision: `promodecision_aa2fd8cbc5684a91aa709bd43c064330` → `promote_eligible`, 0 critical category regressions.
- Existing server V2 decision: `promodecision_1c642784422043628bc4ecb33745efe6` → `promote_eligible`, 0 critical category regressions.
- These server decisions evaluate AtlasBench evidence only. They do not enforce the requested operational-certification prerequisite. Neither decision was used to promote.
- First promotion → smoke → rollback → exact restoration → final promotion → final smoke: **all NOT RUN**, because the operational gate is unmet.
- Original and final production candidate: `production_env_24b0e61eb95e6ceb08abc50c`.
- Original and final pointer event: `promo_19bfa15e3fee4cd295bdb1519650f4b9` (identical).
- Original and final runtime: `qwen3:4b-q4_K_M`.
- Original and final digest: `2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0` (live model still installed).

## Repairs and quality gates

- Fixed the reproduced Windows verification-order race: repeated wall-clock values formerly let UUID lexical order select a stale verification. A locked, monotonically advancing numeric ID component now orders rapid events within the server process. Existing ID formats and trust criteria are preserved. This is not a distributed transaction sequence.
- Added deterministic regression conditions with identical timestamps and UUID suffixes; shared the fix with base-model verification and runtime-binding IDs.
- Scoped temporary SQLite test stores to non-pooled connections so Windows can close/remove fixture databases. Production pooling and benchmark/trust assertions are unchanged.
- Ruff: PASS. Mypy: PASS, 74 source files. Dependency boundaries: PASS. Local secret scan: PASS. OpenAPI/TypeScript freshness: PASS.
- Full native suite after repair: **440 passed, 6 skipped**. Focused trust/runtime/corpus checks: **53 passed, 2 skipped**. Strengthened deterministic trust regression: PASS.
- Web lint/typecheck/accessibility: PASS. Frontend tests: **44 passed**. Production web build: PASS.
- Python compile: 222 tracked files passed before adding the small identity helper (helper imported/tested afterward). Legacy Auto Cleaner: **8/8**.
- Local live MySQL probe reached the running service but root authentication without a password was denied. No credentials were guessed or changed; remote CI includes the real MySQL parity gate.
- Live browser E2E: **6/6 passed** against isolated history and SQL metadata databases. Final pushed-head CI is recorded in the delivery report.

## Phase state and launch

`PHASE_10_COMPLETE = NO`; `PHASE_11_UNLOCKED = NO`.

ATLAS First Light remains the existing truthful topbar badge. With this production pointer it shows `ATLAS · LEGACY · qwen3:4b-q4_K_M`. Qwen 2507 is a verified candidate, not production. The requested command-center/trust/Cortex extension has not started because safe promotion is its prerequisite.

From `C:\Users\prath\prism-phase10`, launch the API with `.venv311\Scripts\python.exe -m uvicorn --app-dir apps/api/src prism_api.main:app --host 127.0.0.1 --port 8000`, setting `PRISM_AI_PROVIDER=ollama`, `PRISM_OLLAMA_BASE_URL=http://127.0.0.1:11434`, `PRISM_OLLAMA_MODEL=qwen3:4b-q4_K_M`, and `PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096`. Launch the web app with `npm run dev:web` and open http://localhost:3000.

**Exact remaining blocker:** live operational-certification subject is not implemented; there is no candidate POST route that runs the frozen 23 scenarios through the real orchestration/tool stack and persists verifiable execution evidence.

Complete that integration without changing the frozen suite or bypassing SQL/Python approval boundaries, run it against this exact verified candidate, then reevaluate evidence freshness and perform the required promote/smoke/rollback/final-promote drill. Phase 11, model search and training remain out of scope.

Machine-readable evidence: `PHASE10_PHYSICAL_CERTIFICATION_20260910.json`. Raw local logs and snapshots: `.prism/runtime/physical-certification-20260910/`.
