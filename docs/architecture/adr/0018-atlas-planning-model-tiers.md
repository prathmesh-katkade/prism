# ADR 0018: Independent fast and deep planning pointers

Status: Accepted, 2026-09-25

## Context

A single Atlas production pointer couples ordinary planning latency to the
model chosen for rare, consequential objectives. Round 5 measured the current
fast model at 1.66 seconds warm p95 and Ministral 3 8B at 9.87 seconds warm
p95. These are different operating points on the same 8 GB device.

## Decision

Atlas has `fast` and `deep` production-pointer histories. Existing events are
`fast`; the migration only adds a column with that default and never rewrites
an event. Each tier's current pointer, prior candidate, and rollback target
are read from that tier alone. Existing callers default to `fast`. A deep
pointer must pass the same AtlasBench, trust, operational-certification, GPU,
valid-JSON, and acceptance gates as fast. Its warm planner p95 ceiling is
15 seconds rather than fast's 12 seconds because deep runs only for explicit
high-stakes routes. No other gate changes.
The promotion API checks these performance measurements against a versioned
arena report matching the exact AtlasBench run ID, runtime tag, and verified
runtime digest. Missing or incomplete evidence blocks promotion. The
Operational Certification prerequisite remains separate and unchanged.

The router uses fixed objective and dataset-health predicates, not a model
decision. An ambiguous objective uses fast. If a deep pointer or verified
runtime binding is unavailable, the request uses fast and records that
fallback in `PLAN_CREATED`; an environment variable alone cannot activate an
unpromoted model. The deterministic planner remains the last fallback.

Only one Ollama model is expected to fit at a time on the 8 GB device. Tier
switches may therefore pay a cold model-load cost, which must be measured and
reported separately from warm planner p95 before calling this practical.

## Consequences

Fast production remains independently stable while deep candidates are
evaluated. An ineligible deep candidate cannot gain a pointer by routing or
by setting `PRISM_ATLAS_DEEP_OLLAMA_MODEL`. Deep stays unavailable until a
server-owned eligible decision and all promotion prerequisites exist.
