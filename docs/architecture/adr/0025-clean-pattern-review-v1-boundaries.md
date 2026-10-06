# ADR 0025: Clean Pattern Review v1 — scope and architectural boundaries

Date: 2026-10-07

Status: accepted

## Context

Clean currently detects five issue kinds (`CleanIssueKind`: missing values,
duplicate rows, all-null columns, type mismatches, outlier burden) and applies
ten operation kinds (`CleanOperation`) through a revision/fingerprint-bound,
one-use preview/apply flow (`DurableCleanReviewStore.issue`/`consume`).
Validation is a separate, already-durable concept: `ValidationRuleKind`
(uniqueness, nonnegative, date_order) backed by `DurableValidationRuleStore`,
checked read-only against a dataset's current revision via
`run_validation_rule`, never mutating data.

Pattern Review adds a new kind of finding — format-family and compound-value
structure within a single column — that is neither an "issue" (which implies
something is wrong) nor a transformation (which implies a decision has been
made). This ADR fixes the boundary between discovery, review, extraction, and
reusable validation before any detector is tuned against the acceptance
fixtures, per the explicit ground rule that detector tuning must follow
boundary-setting, not precede it.

## Decision

### Product principle (binding on every detector and every UI string)

A frequent format is a possible convention, not proof of correctness. A rare
format is not automatically an error. A semantic suggestion is not a
confirmed type. Similar strings do not prove two records represent the same
entity. No detector or UI copy in this release may assert correctness,
confirmed identity, or confirmed type from frequency or similarity alone —
only "N of M examined rows matched family X."

### Reuse, not a parallel system

- **Source identity**: reuse `_fingerprint()` and `StoredDataset.dataset.revision`
  from `clean.py` exactly as issues and validation rules do. A pattern finding,
  a pattern scan, and a saved pattern-validation rule are all bound to
  `(dataset_id, revision, source_fingerprint)` the same way.
- **Preview/apply**: extraction and standardisation are new `CleanOperation`
  members (not a new mutation pathway), going through the existing
  `preview_transformation` → `DurableCleanReviewStore.issue` →
  `apply_transformation` → `DurableCleanReviewStore.consume` → `_commit_operation`
  chain. The server-side stale-preview rejection Pattern Review needs is this
  existing mechanism, not a new one.
- **Saved validation**: an accepted pattern family becomes a new
  `ValidationRuleKind` member (e.g. `pattern_family`), stored in the existing
  `DurableValidationRuleStore` after a schema migration that adds a nullable
  `parameters_json` column (idempotent nullable-add, following the pattern
  established in ADR 0024 — no literal non-portable default), not a new store.
  `run_validation_rule`'s dispatch (`_run_rule`) gains a new branch; the
  existing "never mutates, reports violations against current revision" shape
  is unchanged.
- **Recipes**: extraction operations are addable to a recipe draft like any
  other `CleanOperation`; no changes to `DurableRecipeStore` or recipe
  publication are needed.

### New durable concepts (genuinely new, not reuse)

- **Pattern findings and scans** are new state: a column can have a bounded
  *sample* discovery result and, separately, a *complete* verified scan
  result, each bound to `(dataset_id, revision, fingerprint, detector_id,
  detector_version, parameters)`. This is new because nothing existing models
  "provisional vs. verified" or "cancellable background work." New table(s)
  in the existing history database (same `history_database_url()`, same
  SQLAlchemy Core + idempotent-migration pattern as every other durable store
  in this app).
- **Review decisions** (accept family / ignore this revision / suppress rule)
  are new durable rows, timestamped and source-bound, distinct from a
  validation rule: accepting a family is a decision about *this revision*
  unless explicitly promoted to a saved rule. A revision-scoped "ignore" must
  not silently carry into a new upload — it is keyed by fingerprint, not just
  dataset_id.

### Detectors: deterministic only

No model dependency in this release. `PRISM_AI_PROVIDER=ollama` is not
consulted by pattern detection. Deterministic suggestions are never labelled
"AI" anywhere in the UI, matching the existing rule for Visualize/Clean
suggestions.

Each detector has an explicit `detector_id` and integer `version`. A
detector's output is a ranked list of findings; each finding states its
minimum-evidence threshold and how examples were selected. Avoid one family
per distinct value (a detector that partitions N rows into N "families"
explains nothing) and avoid patterns so generic they match everything (e.g. a
bare `.+` family). Exact ranking/grouping thresholds are tuned against the
Phase 4 fixtures, not invented here, but the *rule* — bounded family count,
minimum support, no singleton families — is fixed now.

In scope for v1: identifier structures (letter/digit runs, separators,
prefixes, lengths), multiple legitimate format families per column, embedded
numeric value + unit extraction, explicit single-delimiter compound-field
splitting, candidate semantic type suggestions where evidence supports one,
and date/number ambiguity reusing the existing ambiguous-date detection in
`clean.py` (`_detect_ambiguous_dates`) rather than a second implementation.

### Sampling and verification

Discovery runs against a deterministic bounded sample. "Verify all rows" is a
separate, cancellable, progress-reporting action that produces a *complete*
scan result. A sample-derived finding is never presented with the same visual
weight as a complete-scan finding, and a "verified across all N rows" claim
requires a completed (not cancelled, not superseded) full scan matching the
dataset's current revision and fingerprint. A source change invalidates
outstanding scans for that dataset; the cache key is the full
`(revision, fingerprint, detector_id, detector_version, parameters)` tuple, so
a component re-render cannot trigger a redundant full scan — only a genuine
change to one of those fields can.

### Extraction

New `CleanOperation` members for: identifier-component extraction, numeric
value + unit extraction, and explicit-delimiter compound splitting. Source
columns are preserved by default (new columns, not in-place replacement).
Output-column-name collisions are a 422, not a silent overwrite. No `eval`,
no arbitrary Python, no unbounded user-supplied regex — every extraction is a
named operation with typed, server-validated parameters, consistent with
every other `CleanOperation`. No unit conversion or locale guessing: unit
extraction records the unit token found, it does not convert it.

### Context-dependent patterns

The user explicitly picks a grouping column (e.g. country, source system);
the server never searches combinations of columns on its own. Small groups
get an explicit "insufficient evidence" state rather than a forced verdict.
An accepted contextual rule retains its grouping condition as part of the
saved rule's parameters.

### Explicitly deferred (documented, not built)

Fuzzy duplicate merging / entity resolution, automatic cross-column
relationship discovery, statistical/distribution anomaly discovery, automatic
recurring-export drift comparison, and model-written explanations are out of
scope for this release and must be named as future work in the delivered
docs, not silently absent. Existing explicit relationship validations
(`ValidationRuleKind.DATE_ORDER` and similar) remain accessible unchanged.

### Interface

Patterns is a new panel beside Issues and Recipe inside Clean, using the
existing PRISM design system and the established dense three-pane workspace
composition (`three-pane` / `clean-issues` / `clean-inspector` CSS already in
`prism.css`) — no new sidebar, no decorative graph, no generic feature-card
grid. Light/dark and ~400px width are required, matching every other
workspace in this app.

## Consequences

- Pattern Review cannot ship before the `parameters_json` migration on
  `prism_clean_validation_rules` and the new pattern-findings table(s) exist
  and pass the same MySQL-compatibility discipline as ADR 0024 (no literal
  non-portable defaults, idempotent re-runnable migrations).
- Because extraction reuses `CleanOperation`/preview/apply, Pattern Review
  gets revision-bound staleness rejection, recipe composability, and
  provenance history for free — but any extraction operation added here must
  respect `_apply_operation`'s existing contract (pure function over a frame,
  returns `(frame, affected_rows, affected_columns, warnings,
  unresolved_values)`).
- Because saved pattern rules extend `ValidationRuleKind` rather than
  creating a parallel "rule" concept, cross-dataset reuse (Phase 3's
  "reusable validation") is schema-compatibility checking plus a new
  `_run_rule` branch, not a new subsystem.
- The full MySQL-backed live browser suite must be re-run for this feature,
  not just targeted specs — the prior release's three-push CI history (ADR
  0024 and the two follow-up timeout fixes) is the concrete evidence for why
  targeted-only verification is insufficient here.

Atlas bindings, promotion policy, and production data are unaffected; this
ADR touches only Clean's durable stores, contracts, and UI.
