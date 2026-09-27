# ADR 0020: Atlas investigation and collaboration project recorded facts

Status: Accepted, 2026-09-27

## Context

The existing Atlas screen takes over PRISM's navigation and inspector. The run
contract persists a plan snapshot, step states and attempts, step evidence,
council conclusions, and a strictly ordered event journal. It does not persist
a general specialist conversation, reply targets, query text for Atlas SQL
steps, or historical snapshots at each event. A council objection is a review
of a claim; a blocked step is an execution refusal. Neither proves the other.

## Decision

Atlas is a tab within the existing PRISM shell. The shell's inspector receives
the selected Atlas record. The investigation presents plan steps in declared
order, with recorded output or refusal in the same position. Collaboration
shows only participating roles and their actual steps. Its exchange shows
recorded council conclusions and objections with explicit source labels and
event ordering; it does not synthesize specialist messages or replies from
step titles. Human interventions require a durable record with target and
authorship before they appear in that exchange.

An answer without an explicit supporting relationship says "Supporting evidence
not linked." A missing query cannot offer "Open exact query". Event stepping
shows journal entries, not reconstructed prior state. The labelled sample is
isolated from production run and promotion stores.

Use shared typed design tokens and CSS properties with native sans and mono
stacks. State colors indicate execution or issue state; roles remain neutral.
No ambient activity animation is allowed. The current user's compact sans,
neutral shell, and event-only motion direction supersedes the older PDF's
expressive hover and editorial type preferences (R3 Q5-Q7 and R3 Q3).

## Data contract audit

| UI feature | Stored source | Status |
| --- | --- | --- |
| Plan sequence, role, method, dependencies | `AtlasRunResponse.plan.steps` | Existing |
| Step state, attempts, refusal explanation | Step snapshot and `step_started` / `step_completed` events | Existing; refusal class is only known where recorded |
| Specialist conclusions and objections | `AtlasRunResponse.council`; `council_conclusion` event | Existing, but no message or reply identity |
| Evidence and step production link | Step evidence; Cortex `produced` edges | Existing |
| Claim-to-evidence support | No claim-level support edge | Unsupported; show missing link |
| Waiting reason | Dependencies and step state; no explicit waiting notification | Dependency only when recorded, otherwise unknown |
| Human targeted intervention | Existing feedback binds answer, not arbitrary target | Requires additive record and API |
| Exact Atlas SQL query and source reference | Atlas step tool name and args, without guaranteed query text | Unsupported unless explicitly persisted |
| Recorded replay | Ordered run event journal | Event log only; historical state reconstruction unsupported |
| Actual concurrency | Event start/completion intervals | May be shown only when intervals establish overlap |

## Consequences

Execution completion remains distinct from evidentiary resolution. Existing
runs continue to render with absent relationships left absent. The sample is
labelled in every view and cannot be mistaken for model or tool execution.
