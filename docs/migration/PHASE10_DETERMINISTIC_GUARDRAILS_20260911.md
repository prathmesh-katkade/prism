# Phase 10 deterministic Atlas guardrails

Implementation starts from `1093396bef484ecfe7ca265735ba078ceb5712a7` on
`phase-10-atlas-local-intelligence`. PR #15 remains open and unmerged.

## Runtime authority

`atlas_guardrails.py` owns policy `atlas-guardrails-v1`; no LLM decides whether
these checks pass. `atlas_guardrail_context.py` resolves evidence against the
durable analytical registry and current DatasetStore identity. Atlas applies
the decision before requesting a model plan, persists it in its plan event,
and holds execution with a visible explanation when blocked or unverified.

* Evidence: compare exact analytical method/configuration, metric and dataset
  scope, server provenance, source class, active revision freshness and time.
  Select only a uniquely dominant verified current observation. Equal-quality
  conflicts or competing quality dimensions require verification. Never average
  incompatible observations. Only source references/metadata enter the audit;
  raw metric values are not forwarded to the planning model.
* Python: inspect AST before worker creation. Reject dynamic execution names,
  aliases, reflective access, private attributes, unsafe module escapes and
  deserialization. Preserve existing import/path/network/timeout restrictions.
  Persist requested/approved/executed/blocked/completed states in an execution
  policy record, including rejected requests that never start a worker.
* Target leakage: inspect declared feature ancestry transitively, target
  identity, outcome proxies and post-outcome information. Propagate ancestor
  failures; cycles/unknown ancestors require review.
* Temporal leakage: check availability against a timezone-aware prediction
  cutoff, window bounds, negative lags and label overlap. Unknown timing is a
  hold, not approval. Reject negative/unknown Python shifts, centered rolling
  windows and forward window indexers at the Python boundary too.

`AtlasRunRequest.guardrail_context` adds typed feature declarations and stored
evidence object references. Declarations are explicitly labeled as declared
metadata, never a claim of verified real-world availability. Passing a check
does not grant tool execution authorization or bypass existing ML/SQL approval
boundaries. Statistical correlation alone cannot establish arbitrary semantic
leakage; callers must supply lineage and prediction-time information.

Prose checks are conservative risk signals, not a general language parser.
They can refuse an unsafe design when the model is empty or disagrees, but
cannot establish trusted provenance. False positives require a review.
The native sandbox is still not a complete hostile-code isolation boundary;
its existing Windows hard CPU/memory quota limitations remain truthful.

## Certification integrity

The same product policy wraps the live subject before/around model planning
and tool dispatch. Server audit records and provider-response availability
are separate response fields, not analytical result claims. The frozen suite,
judges, thresholds, corpus and registration/verification records are unchanged.

A provider outage can still yield three genuine server safety refusals; it
does not become a successful model run or reach the promotion threshold.
Tests verify that this offline outcome still blocks promotion.

The prose-only freshness case supplies no verifiable source records. It is
intentionally held with uncertainty even when a scripted model supplies the
judge-preferred choice. The existing frozen judge still counts that as a miss.
No provenance or answer is invented to obtain a point.

No auxiliary development model was used. The physical candidate remains the
already verified Qwen model; its response is subordinate to server guardrails.

## Validation and physical outcome

See the appended closeout checkpoint for final test counts, commit, physical
run identity and any promotion/rollback evidence. Until those records exist,
no new certification or promotion result is claimed.

Local final backend gate: **516 passed, 6 skipped** (164.41 seconds). Focused
policy/runtime/sandbox/live-subject/promotion-route coverage: **83 passed**.
Ruff, strict configured mypy, generated TypeScript contract check, dependency
boundaries, local secret scan, TypeScript typecheck and diff whitespace checks
passed. Frozen operational-suite source and benchmark corpus files have no diff.
Tests used separate SQLite databases, preserving the physical production store.
