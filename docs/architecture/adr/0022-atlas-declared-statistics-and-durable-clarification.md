# ADR 0022: Declared statistics and durable clarification

Status: Accepted for the local first-release investigation workflow, 2026-09-28.

## Context

The investigation plan could name statistical work without executing it. A statistical method, columns, and study design cannot be inferred safely from a short objective. PRISM already has a tested Stats Lab service for independent t tests, one-way ANOVA, chi-square, and Pearson correlation.

## Decision

Atlas accepts a typed statistical declaration from the local user. It checks the named columns against the active uploaded dataset, checks that the method agrees with Stats Lab's deterministic suggestion, and requires the corresponding design declaration. The server executes only the four supported methods through Stats Lab. The model cannot nominate the executable statistical tool.

When a statistical objective lacks the required declaration, Atlas stores a question and a waiting plan state. Waiting releases its worker slot. A clarification answer is validated against the original dataset revision and claimed once with a state comparison before work is dispatched. Completed profile evidence is reused on resume; a changed revision rejects the answer. On restart, waiting work remains waiting, while uncertain in-flight work follows the existing failed-recovery path.

The Atlas journal records method, columns, design, sample count, exclusions, complete computed result, limitations, source fingerprint, revision, policy, and an evidence ID. Statistical conclusions cite that evidence. Shared model roles do not count as independent confirmation.

## Consequences

The bounded procedure set produces descriptive or inferential results within the declared assumptions. It does not establish causality. Stats Lab's existing implementation and validation remain the calculation authority. A result can be inspected from the investigation UI, and the question can be answered after an API restart. Hosted deployment still requires the identity and authorization boundary described in ADR 0021.
