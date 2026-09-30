# ADR 0023: Contribution provenance and bounded statistical worker

Status: Accepted for the local Atlas investigation runtime, 2026-09-28.

## Context

The existing council array recorded conclusions but did not identify each contribution, its inputs, reply target, model binding, or server order. The UI could display those conclusions as a conversation even though they were deterministic summaries. Stats Lab's synchronous calculation had no deadline or active cancellation boundary.

## Decision

Every new computed contribution has a run-scoped message ID, sequence, role, task, kind, origin, input evidence IDs, optional reply target, optional model binding, and timestamp. The current computed messages are marked `deterministic_service` with no model binding. Objections are separate records. Atlas's final synthesis is a resolution over cited evidence. Historical council records remain available and are labelled as legacy records by the UI. The six defined role identities are Atlas, Scout, Curator, Query, Stat, and Auditor.

Plan steps are dispatched in stable topological order. Cycles, duplicate IDs, and missing dependencies fail validation. A step whose prerequisite was blocked is itself blocked with the dependency named. The execution policy is checked before each dispatch.

Atlas statistical work uses the existing Stats Lab calculation inside a short lived process. Only two validated columns are sent. Input is capped at 10,000 rows and 8 MiB, calculation at 12 seconds. Cancellation or tool disable terminates the worker. After successful calculation, the parent rechecks dataset revision and registers the resulting analytical object. The normal Stats Lab API still computes and registers in its original call path.

## Consequences

Messages have actual computation or review provenance; deterministic role labels are not presented as independent model corroboration. A process crash, timeout, cancellation, or policy change cannot leave a statistical worker running indefinitely. Atlas still needs final acceptance and concurrency measurements before the first release can be called complete.
