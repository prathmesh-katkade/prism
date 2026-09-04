# Phase 10 Architecture — Atlas Local Intelligence Foundry

## Status

Phase 10 is in progress. This document defines its contracts; it does not certify
the phase or authorize Phase 11 work.

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

## Evidence and provenance

Atlas records exact evidence references (dataset revision, Overview profile,
analytical object, or approved research record). The Cortex projection derives
nodes and edges solely from those records plus actual run/step/event state.
It never invents an internal-thought node.

## Security and privacy

Raw datasets remain server-held. Provider calls receive compact schema/quality
metadata only unless a later, explicit policy grants more. The first slice has
no generic command endpoint, no shell surface, and no network tool. Cancellation
and retry are typed per run; recoverable step retries cap at three attempts.

## Evolution path

Sandbox, memory/RAG, web research, model registry, Foundry, AtlasBench, voice,
Cortex rendering, and desktop packaging are separate incremental additions on
these contracts. Their implementation must not weaken Phase 8/9 immutability,
DatasetStore authority, freshness-at-read, or append-only history invariants.
