# ADR 0013: Operational certification remains a server-owned promotion boundary

## Decision

Operational Certification is an immutable, candidate- and digest-bound server
record. Promotion requires the current frozen suite and hash, the exact live
runtime digest, zero critical failures, and the server-owned minimum pass rate.
The API exposes that threshold and its computed pass result for presentation;
the web client never recreates or weakens the decision.

AtlasBench eligibility, model-authored claims, reference-subject results, and UI
labels cannot substitute for a live candidate certification. Any critical
failure blocks promotion. A failure, timeout, missing record, identity mismatch,
suite drift, or digest drift is a refusal, never an implied pass.

## Consequences

- Promotion and rollback remain durable server mutations with preserved history.
- Clients can explain the recorded gate without owning policy constants.
- Threshold changes require a reviewed backend policy change and fresh evidence.
- Physical certification records remain distinct from Arena and training records.

This ADR narrows and extends ADR 0011; it does not supersede its candidate-trust
requirements.
