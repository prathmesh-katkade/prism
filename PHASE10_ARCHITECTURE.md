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
