# Phase 8 Implementation Ledger

## 8A — Unified Provenance Foundation (CI CERTIFIED — PENDING MERGE)

**Base:** `phase-6.5-integration-staging` at
`2741c2ef3c242d3edff7a46beda2acd437da25ac`.

**Objective:** Establish the canonical, framework-free representation of an
analytical object and its reproducible provenance without replacing
`DatasetStore` or widening existing Phase 3–7 HTTP responses.

**Delivered foundation:**

- `packages/analytical-schemas` now defines analytical object identity, kind,
  lifecycle, immutable dataset reference (id/revision/fingerprint), parent and
  evidence references, warnings, producer/service version, creation time, and
  typed cleaning/statistical/generic reproducibility specifications.
- Provenance parameter sanitization recursively redacts credential-like keys
  and common inline bearer/basic credentials or database connection strings.
- `AnalyticalObjectRegistry` is deliberately process-local and append-only.
  It supports `register`, `get`, `list_for_dataset`, and `exists`; rejects
  duplicate ids and self-parenting; and snapshots every record so callers
  cannot mutate historical registry state.
- `DatasetStore` remains the sole owner of dataset revision creation, lookup,
  history, and undo. The registry records a revision after a workflow has used
  that authoritative store; it never creates or rewrites a dataset revision.
- Stats registers each successfully completed deterministic test as an
  `analysis` object. Clean registers each successfully applied transformation
  as a `cleaning_plan` object bound to the new DatasetStore revision.

**Compatibility:** Existing `OverviewProvenance`, Stats, and Clean response
contracts are unchanged. The new registry is an internal foundation rather
than an incomplete public graph API.

**Not implemented (explicit 8A boundary):** dependency graph traversal,
staleness propagation, lineage UI, rerun engine, Atlas lineage awareness,
persistence/database, and Phase 9 work.

**Tests added:**

- `tests/contracts/test_analytical_objects.py` — secret redaction, duplicate
  and self-parent protection, dataset filtering, and immutable snapshots.
- `tests/api/test_analytical_object_integration.py` — Stats and Clean records
  against their active DatasetStore revisions.

**Quality-gate status:** CI run #98 is green for `ff8a6338814f67e4add58730b112464defe66787`:
phase-1-python, phase-1-web, legacy-regression, secret-scan, and phase-4-live-e2e
all passed. The first live-E2E attempt exposed a missing API runtime dependency
for `prism_analytical_schemas`; `apps/api/requirements.txt` now installs the
package. A subsequent SQL Lab browser assertion flaked after the API completed
its request; the failed job was rerun and passed. Local full-suite execution
remains unavailable under this checkout's Python 3.9 runtime because three
pre-existing Forecasting tests require Python 3.10+ `zip(..., strict=True)`;
the required Python 3.11 CI gate is certified.

**8B starting point:** expose read-only registry lineage queries only after a
separate scope decision; do not build a dependency graph, staleness engine, or
UI from this in-process foundation without that decision.
