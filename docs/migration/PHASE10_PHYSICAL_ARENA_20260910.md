# PRISM PHASE 10 — TAKEOVER REPORT

Date: 2026-09-10. This supersedes earlier local-setup and physical-Arena status notes; historical evidence is preserved.

**Result: Qwen3-4B-Instruct-2507 reached 90/90 twice on frozen AtlasBench V1, 29/30 on V2 holdout wave 1, and 12/12 independent adversarial spot checks. Production is unchanged.**

## Repository and audit

- Repository: `C:\Users\prath\prism-phase10`; branch `phase-10-atlas-local-intelligence`.
- Starting HEAD: `43d4b8a46cdb0d267b84a2ed8ea8e91d68c7465c`; clean and 0 ahead / 0 behind origin after fetch.
- Existing PR #15 was open, mergeable, unmerged, 89 commits; base `phase-6.5-integration-staging`. Starting CI #196 succeeded on that exact SHA.
- Preserved `stash@{0}` (pre-handoff evolution documentation), ignored environments/runtime artifacts, dirty unrelated `C:\Users\prath\prism`, and the detached verification worktree. No clone, reset, clean, force push, new PR, merge, or Phase 11 work.
- Found an interrupted prior local task with an active official Qwen download; preserved it until successful completion. Recovered historical Granite 2B and alternate Qwen Arena records absent from the handoff. Artifact history proves actions, but cannot reliably attribute every action to Luna versus Claude.
- Claude Code `2.1.267` works from the repository through `C:\Users\prath\.local\bin\claude.exe`; `claude auth status` reports logged out. No positive teleport evidence was found in reviewed repository artifacts. Claude login/teleport was unnecessary for this execution.
- Ollama `0.33.3`, loopback `127.0.0.1:11434`, isolated Soup `0.74.0`, Torch `2.14.0+cu126`, CUDA available, GTX 1650 Max-Q with 4096 MiB VRAM. About 158 GiB disk remained after downloads. No installers or driver changes were needed.

## Runtime repair and measurement policy

The earlier attempted baseline used a 40,960-token default context, allocated 9.35 GB, and reached 95% system RAM. Its report remains `aborted_resource_pressure` with no suite score.

Added the opt-in server environment setting `PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS`. The tournament consistently used `4096`, including production. Existing defaults remain unchanged when unset; invalid non-positive/non-integer values fail before evaluation. The same canonical Arena handler and trusted `run_suite` evaluated the models. V2 and adversarial runs use that same runner and durable store with distinct corpus identities.

All new runs used temperature 0, 64 output tokens, JSON format, and the existing 20-second task timeout. No timeout increase, prompt/scoring/answer-key edit, model-specific answer correction, or training occurred. Warm-up used an empty prompt. Every recorded task prompt was at most 262 tokens, below the 4096-token context. Models were evaluated sequentially and unloaded afterward. Sidecars record policy, token/resource observations, run IDs, and before/after identities. Historical default-context results are retained separately; the generic Arena view also retains those older runs, so use the policy-matched table below for comparisons.

## Physical results

| Model / evaluation | Score | Invalid | Suite seconds | Peak sampled GPU MiB |
|---|---:|---:|---:|---:|
| `qwen3:4b-q4_K_M / atlasbench-v1` | 74/90 | 0 | 164.171 | 2874 |
| `qwen3:4b-instruct-2507-q4_K_M / atlasbench-v1` | 90/90 | 0 | 136.072 | 2820 |
| `qwen3:4b-instruct-2507-q4_K_M / atlasbench-v1` | 90/90 | 0 | 139.659 | 2858 |
| `qwen3:4b-instruct-2507-q4_K_M / atlasbench-v2-holdout-wave1` | 29/30 | 0 | 49.529 | 2739 |
| `qwen3:4b-instruct-2507-q4_K_M / takeover-adversarial-20260910-v1` | 12/12 | 0 | 18.11 | 2715 |
| `qwen3:4b-q4_K_M / atlasbench-v2-holdout-wave1` | 19/30 | 0 | 58.424 | 2754 |
| `phi4-mini:3.8b-q4_K_M / atlasbench-v1` | 23/90 | 0 | 131.063 | 2767 |
| `granite3.3:2b / atlasbench-v1` | 10/90 | 2 | 89.957 | 2357 |

GPU figures are whole-device sampled usage, not isolated tensor allocations. System RAM stayed at or below 66% for these completed runs. All identity and production-pointer comparisons passed. No HTTP timeout/error was recorded in the sidecar task telemetry.

Granite’s two invalid responses are genuine failures under the unchanged harness. Separate non-benchmark index-format probes: Phi answered all 4 simple position-permuted arithmetic cases correctly; Granite answered 0/4, with two invalid responses. This qualifies interpretation of Granite’s score; no official result was rescored.

Granite 3.3 8B and Ministral were researched against current official model/build pages but not downloaded or scored. After two V1 ceiling results from the 4B model, priority shifted to holdout, artifact verification, and feasibility. No claim is made about those untested models; this completes the selected physical tournament, not an exhaustive search of all open-weight models.

## V1 category gap matrix

| Category | Production | Qwen 2507 | Phi mini | Granite 2B | Best | Remaining gap | Critical |
|---|---:|---:|---:|---:|---:|---:|---|
| agentic | 9/10 | 10/10 | 4/10 | 1/10 | 10/10 | 0 | yes |
| causal_safety | 5/8 | 8/8 | 2/8 | 1/8 | 8/8 | 0 | yes |
| evidence | 6/8 | 8/8 | 1/8 | 0/8 | 8/8 | 0 | yes |
| forecasting | 7/8 | 8/8 | 1/8 | 0/8 | 8/8 | 0 | no |
| general | 10/10 | 10/10 | 1/10 | 2/10 | 10/10 | 0 | no |
| machine_learning | 9/10 | 10/10 | 2/10 | 1/10 | 10/10 | 0 | yes |
| personality | 7/8 | 8/8 | 1/8 | 1/8 | 8/8 | 0 | no |
| python_sandbox | 7/8 | 8/8 | 1/8 | 2/8 | 8/8 | 0 | yes |
| sql | 7/10 | 10/10 | 4/10 | 0/10 | 10/10 | 0 | yes |
| statistics | 7/10 | 10/10 | 6/10 | 2/10 | 10/10 | 0 | yes |

Qwen 2507 has no critical regression against the matched production run. Phi and Granite regress in all seven critical categories.

## V2 holdout comparison

| Category | Production | Qwen 2507 | Remaining Qwen gap |
|---|---:|---:|---:|
| agentic | 3/3 | 3/3 | 0 |
| causal_safety | 2/3 | 3/3 | 0 |
| evidence | 2/3 | 3/3 | 0 |
| forecasting | 2/3 | 3/3 | 0 |
| general | 3/3 | 3/3 | 0 |
| machine_learning | 3/4 | 4/4 | 0 |
| personality | 1/2 | 2/2 | 0 |
| python_sandbox | 2/3 | 3/3 | 0 |
| sql | 0/3 | 2/3 | 1 |
| statistics | 1/3 | 3/3 | 0 |

V2 remains a 30-task holdout, not a broad certification suite. Its single SQL miss is retained; no answer, rationale, or paraphrase was used for training. The 12 evaluation-only adversarial cases were authored and hashed before model responses; they cover untrusted instructions, fabricated evidence, sandbox boundaries, point-in-time validity, and statistical/causal errors. These multiple-choice checks do not certify real tool execution.

## Exact identities and immutable run references

- `qwen3:4b-q4_K_M`: `2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`.
- `qwen3:4b-instruct-2507-q4_K_M`: `0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0`.
- `phi4-mini:3.8b-q4_K_M`: `78fad5d182a7c33065e153a5f8ba210754207ba9d91973f57dffa7f487363753`.
- `granite3.3:2b`: `07bd1f170855240f9e162bf54ea494a8bc1c73d8cbd1365d7fccbeb7d2504947`.

V1 corpus SHA-256: `f0af1e39a778755a925f70570c19a4e5754e2dcccbb57d44e8673627a7f4f10f`.
V2 corpus SHA-256: `d66c182f02dc14e7269e10ac036f34ead3b458dc30133cb98e1e85987309ca2a`.

- `benchrun_b2aad4c6c5e541d7946d8004cbd481de` — qwen3:4b-q4_K_M, 74/90, `20260910T002210Z-qwen3_4b-q4_K_M.json`.
- `benchrun_dad8f847e7144659930b1b19bed4d7e0` — qwen3:4b-instruct-2507-q4_K_M, 90/90, `20260910T002518Z-qwen3_4b-instruct-2507-q4_K_M.json`.
- `benchrun_5510398bc6794eb694bc80611c50e797` — qwen3:4b-instruct-2507-q4_K_M, 90/90, `20260910T002809Z-qwen3_4b-instruct-2507-q4_K_M.json`.
- `benchrun_decc8d1ccb4243feb376dcbfabda6f5f` — qwen3:4b-instruct-2507-q4_K_M, 29/30, `20260910T003148Z-qwen3_4b-instruct-2507-q4_K_M-v2-holdout.json`.
- `benchrun_58060203fe30487c8327ae860efc26ee` — qwen3:4b-instruct-2507-q4_K_M, 12/12, `20260910T003258Z-qwen3_4b-instruct-2507-q4_K_M-adversarial.json`.
- `benchrun_c5bb1fd7ebc74201ae32f31de6849632` — qwen3:4b-q4_K_M, 19/30, `20260910T003347Z-qwen3_4b-q4_K_M-v2-holdout.json`.
- `benchrun_4f69526959e94cc28e82fe9950894225` — phi4-mini:3.8b-q4_K_M, 23/90, `20260910T003611Z-phi4-mini_3.8b-q4_K_M.json`.
- `benchrun_74170173832143888a8c7955f5e3e0c0` — granite3.3:2b, 10/90, `20260910T003900Z-granite3.3_2b.json`.

The winning manifest was independently hashed and matched both the installed Ollama digest and the live `registry.ollama.ai` manifest. Every referenced blob (model, template, license, parameters, config) passed its SHA-256 and byte-size check. The model blob is `sha256:85e4a5b7b8ef0e48af0e8658f5aaab9c2324c76c1641493f4d1e25fce54b18b9`.

Source/licensing verification: [Qwen official card](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507) (Apache-2.0), [exact Qwen Ollama build](https://ollama.com/library/qwen3:4b-instruct-2507-q4_K_M), [Microsoft Phi card](https://huggingface.co/microsoft/Phi-4-mini-instruct) (MIT), [exact Phi build](https://ollama.com/library/phi4-mini:3.8b-q4_K_M), [IBM Granite card](https://huggingface.co/ibm-granite/granite-3.3-8b-instruct) (Apache-2.0), [Granite builds](https://ollama.com/library/granite3.3/tags), [Mistral official card](https://huggingface.co/mistralai/Ministral-3-3B-Instruct-2512) (Apache-2.0), [Ministral builds](https://ollama.com/library/ministral-3/tags).

## Corpus and training feasibility

- No Corpus V2 Wave 2 expansion and no Candidate V2 training were performed. The zero-shot model already reached the V1 ceiling; generating hundreds of examples from a single holdout miss would not be a sound next experiment.
- Canonical combined-SFT release: `combinedsft_133ada54d71e15f6b0a76d38`; 125 System Seed + 6 eligible history + 45 synthetic teacher = 176 records. Splits: 133 TRAIN / 22 validation / 21 test. This physically activates existing Wave 1 data, not new authored corpus content.
- Aggregate hash: `133ada54d71e15f6b0a76d384aee632d3f57741ffea8806d70b87bd4a41eb64e`.
- TRAIN export SHA-256: `629b4958f12aff74c1da72f9141a91b0bc0f21404ee594a2c7fc8c393f081370`; provenance SHA-256: `9ca9a47e49ddf245264c2b60af778d048941bfa52b03b70df0ab37682af4a6d3`.
- Canonical Foundry recipe rendering and real Soup `profile --json` / `train --dry-run` both completed for Qwen3-4B-Instruct-2507 and Qwen2.5-1.5B-Instruct. Only TRAIN records were exported; Soup internally split those into 119 training and 14 validation samples for the dry run.
- **Qwen3 4B: BORDERLINE.** Raw Soup output incorrectly assumed 7B and estimated 5.58 GB. Source inspection found the missing 4B name marker. Using the official 4,022,468,096 parameter count with the same advisory estimator gives 3.97 GB, or 3.64 GB with gradient checkpointing. Architecture remains estimated; neither number proves a real forward/backward pass. The pinned Soup installation was not modified.
- **Qwen2.5 1.5B: SAFE by profile/data validation only**, estimated 2.50 GB. Actual training and export compatibility remain unproven in this takeover.
- Observed Qwen 2507 source revision: `cdbee75f17c01a7cc42f958dc650907174af0554`; Qwen2.5 1.5B revision: `989aa7980e4cf806f80c7fef2b1adb7bc71aa306`. These are source metadata observations, not claims that those full checkpoints were downloaded or trained.

## Preserved historical experiment

The completed canonical experiment remains `experiment-20260909T190538Z.json`: Qwen2.5-0.5B-Instruct QLoRA, 131 raw records / 99 TRAIN, 23 steps, loss 3.490427 to 3.304634. Candidate `candidate_foundryjob_b077ca27d02446679e3c2e3a4b93db59`, fingerprint `84f64a8f1ce1b21e93520441db5e2903c5760bce0145faf8c66d4b579f357cd6`, runtime `atlas-candidate-92c971286e836cc2:latest`, digest `91bd27c7fac143fbfcd62aeff930a0c969757c3a77da4b4e3138278ed823c7ba`: 12/90 versus production 72/90, server verdict REJECT. No promotion occurred.

Earlier immutable Arena evidence is also preserved: Granite 2B 12/90 with 5 invalid (`benchrun_681550a43cad40e39a6bca4777a4bc56`); alternate `qwen3:4b` digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7` scored 0/90 with 90 invalid (`benchrun_c7d253a61a274f2794660e1e527acf56`). The latter is invalid-response evidence, not a clean knowledge comparison.

## Remaining gate and next action

**Best zero-shot challenger identified and confirmed; production has not been switched.** Existing promotion requires a verified Foundry adapter candidate and durable candidate binding. The official off-the-shelf GGUF has neither a Foundry job nor an adapter artifact; Arena scores cannot confer that trust. No fake job, adapter, candidate ID, verdict, or promotion was created. The first-experiment CLI also remains trust-locked to the historical 0.5B smoke base.

The next highest-value work is a reviewed admission design for official off-the-shelf artifacts within the existing server-owned trust/promotion system, plus a larger independent SQL development evaluation before deciding whether any fine-tuning is justified. Do not silently broaden that trust gate or turn holdout failures into training data. Physical 4B training remains borderline pending an admitted, pinned model-load/backward-pass check. Claude authentication is optional and is not the blocker.

## Validation and final repository state

- Supported local suite: **392 passed, 5 skipped** in 123.63 seconds, using an isolated history database. Four MySQL parity cases were unconfigured; one POSIX executable-permission case is skipped on Windows.
- Ruff, mypy (70 source files), dependency boundaries, local secret scan, and OpenAPI/TypeScript freshness all passed. Five context-policy cases were added; the focused activation suite passed 10 tests.
- No frontend behavior changed. The existing PR CI runs frontend/build and real MySQL/browser coverage; exact post-push CI and final SHA are recorded in the delivered takeover report.
- Initial CI: [#196](https://github.com/prathmesh-katkade/prism/actions/runs/34414579565), green at starting HEAD. Historical 388/4 results remain historical; current Windows result is the 392/5 result above.

## Evidence location and flags

Local detailed evidence: `C:\Users\prath\prism-phase10\.prism\runtime\arena-tournament-20260910`. Reports, downloads, artifact checks, training profiles, code hashes, and evaluation-only adversarial cases remain outside Git. `completed-run-index.json` is the compact numeric index. Reproduce the policy through the canonical Arena handler with `PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096`; do not compare an unlabelled default-context run as if it used the same policy.

```text
PHYSICAL_ZERO_SHOT_ARENA_COMPLETE = YES
PHASE_10_COMPLETE = NO
PHASE_11_UNLOCKED = NO
CONTINUATION_SAFE = YES
```
