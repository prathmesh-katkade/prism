# Phase 10 Architecture — Atlas Local Intelligence Foundry

## Status

Phase 10 is in progress. This document defines its contracts; it does not certify
the phase or authorize Phase 11 work.

## Superseding physical-evolution and retrieval status (2026-09-10)

The first complete trusted physical Evolution loop has now run on the PRISM
Windows host. It produced a real QLoRA adapter from the immutable combined SFT
corpus, verified the adapter artifact, exported/deployed a candidate to Ollama,
bound the daemon's canonical `:latest` name and exact digest, and ran the frozen
AtlasBench corpus through the server-owned evaluator. The candidate was
**REJECTED**, not promoted: 12/90 versus a fresh production 72/90, with critical
regressions. The production pointer and resolved model remain
`qwen3:4b-q4_K_M` at digest
`2bfd38a7daaf4b1037efe517ccb73d1a3bbd4822cf89f1a82be1569050a114e0`.

Memory/RAG V2 now adds a separate durable hybrid-retrieval store. It retains
project/source/version/locator/content-hash provenance, strict knowledge
classes, injection-as-data metadata, tombstones/supersession, content-hash
no-ops, deterministic score breakdowns, lexical fallback, test-only
deterministic embeddings, and an opt-in local Ollama embedding boundary. It
does not globally index raw dataset rows and it refuses client-forged
`DATA_EVIDENCE` records.

## Legitimate candidate search and Model Arena (2026-09-10)

Model selection now begins with an immutable, non-mutating Arena evaluation,
not training. `POST /api/v1/atlas/arena/runs` takes only a locally installed
Ollama model name; the server probes and records its exact daemon digest, then
passes only frozen-benchmark prompts and choices to that model. It cannot
create a Foundry candidate, a verification record, a promotion decision, or a
production-pointer mutation. `GET /api/v1/atlas/arena` derives score deltas,
category deltas, critical-regression flags, and elapsed time from immutable
same-corpus runs only; generic/reference runs and digest-less runs are excluded.

The actual host is a GTX 1650 Max-Q (4 GiB), i5-9300H, and 16 GiB RAM, with
Soup 0.74.0 / Torch 2.14.0+cu126. Granite 3.3 2B is the conservative QLoRA
control. SmolLM3 3B requires a model-specific Soup profile and dry-run; 4B
training is evaluation-first and must retain at least 0.5 GiB VRAM reserve.
No benchmark material is used as training data.

## Candidate Search / Model Arena continuation (2026-09-10, cloud session)

A follow-on session ran with no access to the physical Windows/GTX 1650
machine, no local Ollama daemon, and no Soup/GPU runtime — recorded so a
future reader does not assume a benchmark or training step ran that did not.
It contributed real desk research and one new server-owned subsystem instead:

- **Model Scout shortlist** (cited research, not a run): zero-shot-first
  Arena candidates — Qwen3-4B-Instruct-2507, Phi-4-mini-instruct (MIT,
  function-calling), Granite 3.3 8B (inference-only here), Ministral-3-8B
  (license/build maturity unverified); QLoRA-worth-attempting — Granite 3.3
  2B (confirms SAFE), SmolLM3 3B (BORDERLINE; blocked on
  `huggingface/transformers#41129`, a tokenizer BOS/PAD/EOS mismatch),
  Qwen2.5-1.5B-Instruct (same family as the proven 0.5B pipeline). Excluded:
  Qwen2.5-3B-Instruct (non-commercial "qwen-research" license), Gemma 3 4B
  (multimodal + embedding overhead, plus an active Transformers v5.1.0
  4-bit-quant-ignored regression for its architecture), StableLM 2
  (non-commercial license).
- **Trust/Red Team audit**: reviewed the Arena, promotion, and live-bench
  modules; no forged claims found. Clarified that the identical
  category-coverage/task-totals guard lives in the `/promotion-decisions`
  route handler, not inside `decide_promotion()` itself — both layers are
  real and tested.
- **Feedback Foundation** (new): `atlas_feedback.py` — append-only
  `AtlasFeedbackEvent`s typed by `AtlasFeedbackKind`
  (`helpful`/`not_helpful`/`accepted`/`rejected`/`corrected`), bound to
  `run_id`/`project_id`/`evidence`/server `created_at`. `corrected` requires
  a non-empty `correction` and is the future DPO substrate; the four binary
  kinds are the future KTO substrate. No DPO/KTO training starts here — only
  durable, queryable signal capture. Full quality gates pass.

Corpus V2 curation, any actual Arena run, and any new training experiment
remain not started. **AtlasBench V2 wave 1 is started**: `atlas_bench_corpus_v2.py`
is a genuinely separate 30-task holdout (never imported by dataset-building
code) covering confounding, reverse causation, selection bias, every leakage
type, imbalance, hallucinated schema, evidence freshness/provenance, prompt
injection/tool hijack, Python pitfalls, uncertainty/refusal, and business
reasoning — a real first increment toward 150+, not the finished suite, and
not yet wired into promotion/Arena. A standing leakage-guard test checks
every V2 prompt against v1 by token overlap and already caught one
accidental near-duplicate before it landed.

## Product boundary

Atlas is PRISM's persistent, local-first analytical orchestrator. It plans and
interprets; declared PRISM tools compute. Every conclusion must carry the real
dataset, tool, and/or research evidence that supports it. Atlas never exposes
private reasoning traces, fabricates a graph node, or substitutes generated text
for a deterministic calculation.

## First runtime slice

The initial vertical slice accepts an uploaded CSV already held by Overview,
creates a structured plan, profiles it through the existing Overview service,
collects independent Scout, Stat, and Auditor conclusions, and streams real run
state as SSE. It deliberately does not execute arbitrary Python, SQL, shell, or
network operations. SQL remains inspectable and executable only through SQL Lab.

## Runtime layers

1. **API contracts** define plans, steps, specialists, events, evidence, memory,
   Cortex graph, model trust, benchmarks, and resource priority.
2. **Provider adapters** report capability and may assist planning using compact
   metadata only. A provider cannot invoke tools directly.
3. **Atlas orchestrator** validates the plan against its declared tool registry,
   executes only typed tool handlers, records retries/cancellation, and emits
   append-only execution events.
4. **Specialists and Council** provide visible evidence-backed conclusions.
   Atlas remains the sole speaking voice; specialist private reasoning is never
   stored or surfaced.
5. **PRISM deterministic tools** remain authoritative for profile, SQL,
   statistics, forecasting, and ML outputs.
6. **Memory and knowledge** are separate SQL-backed operational records. Memory
   scopes are user-reviewable and auditable; project text retrieval retains
   source/version/location and must be isolated by project. Retrieval labels
   data evidence, project knowledge, user memory, model knowledge, and web
   research distinctly.
7. **Researcher and resource governance** are explicit server-side boundaries.
   Researcher accepts only allowlisted HTTPS sources and returns bounded,
   untrusted, cited content. The governor admits typed workloads by priority;
   unavailable GPU telemetry and unenforceable quotas are reported honestly.

## Evidence and provenance

Atlas records exact evidence references (dataset revision, Overview profile,
analytical object, or approved research record). The Cortex projection derives
nodes and edges solely from those records plus actual run/step/event state.
It never invents an internal-thought node.

## Security and privacy

Raw datasets remain server-held. Provider calls receive compact schema/quality
metadata only unless a later, explicit policy grants more. The first slice has
no generic command endpoint, no shell surface, and no network tool. The sandbox
uses a separate native worker process with a cleared user environment and
process-tree termination, while Windows CPU/memory quotas are not claimed until
a container-worker adapter is configured. Cancellation and retry are typed per
run; recoverable step retries cap at three attempts.

## Evolution path

Sandbox, memory/RAG, web research, model registry, Foundry, AtlasBench, voice,
Cortex rendering, and desktop packaging are separate incremental additions on
these contracts. Their implementation must not weaken Phase 8/9 immutability,
DatasetStore authority, freshness-at-read, or append-only history invariants.

## Combined SFT and benchmark subject binding (2026-09-08)

The physical SFT path is an immutable source-neutral corpus. Reviewed seeds
retain `system_seed`; genuine Atlas history retains run/dataset lineage.
Deterministic grouped splits plus AtlasBench and cross-split leakage guards fail
closed. Soup receives only TRAIN Alpaca JSONL with a separate provenance
sidecar. Candidate benchmarks are server-owned and bind candidate, verification,
runtime model and digest; promotion rejects substituted runs.
