# ADR 0019: Deep planning as an optional asynchronous refinement

Status: Accepted, 2026-09-25

## Context

The first deep-model load on the 8 GB host took 23.15 seconds. This is a
separate measurement from the warm planner p95 gate, but it makes an inline
deep request visibly slow. Round 5 did not qualify a deep model, so the deep
production pointer remains empty.

## Decision

Atlas creates and executes the fast plan first. For objectives selected by
the fixed high-stakes rule, a bound deep production pointer may queue one
background refinement. The refinement is a *proposal*, never a replacement
for an executing or completed plan. It is stored with the source run ID,
dataset revision and fingerprint, deep candidate, model tag and digest,
proposal status, and validated steps. The queue is bounded to one active and
one waiting job; capacity exhaustion is visible. An interrupted queued or
running job becomes failed on restart rather than silently appearing ready.

The user must explicitly accept a ready refinement. Acceptance rechecks the
dataset identity and guardrail, then creates a new child run from the stored,
validated proposal. The original run and its evidence stay intact. Repeated
acceptance returns the same child run. A missing deep pointer, runtime binding,
or valid model proposal fails closed and never calls the model named only in
an environment variable.

## Consequences

Fast planning no longer waits for a deep model load for the initiating run.
The deep call still uses the same GPU and may delay other fast requests while
it runs. No latency guarantee for concurrent fast requests follows from this
design; that requires measurement with an eligible deep model. Today deep is
unavailable because no candidate has cleared all promotion gates.
