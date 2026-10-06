# Clean Pattern Review v1 — acceptance matrix

Baseline snapshot: 2026-10-07, branch `prism/clean-pattern-review-v1`, branched
from verified `origin/main` at `bc72625` (tag `prism-native-v1.0`, CI success
confirmed via `gh run list` immediately before branching — not assumed).

| Area | Status | Evidence |
|---|---|---|
| Baseline gates | Passed | Fresh checkout, dependencies installed per `.github/workflows/ci.yml`'s own commands. Python: **1,312 passed, 7 skipped, 43 warnings in 176.15s**. Web: **106 passed across 16 files**. lint, typecheck, build, a11y, Ruff, mypy, boundaries, secrets, generated-contract check: all passed. No MySQL source configured for this baseline run (4 of the 7 skips). |
| ADR 0025 | Written | `docs/architecture/adr/0025-clean-pattern-review-v1-boundaries.md`, defines reuse of source identity/preview-apply/validation-rule infrastructure, new durable concepts (pattern findings/scans, review decisions), detector/sampling/extraction/context rules, and explicit deferrals, before any detector code exists. |
| Detectors | Implemented, backend only | `clean_patterns.py`: identifier-structure (letter/digit-run signatures, e.g. `L3-N6`), numeric+unit (unit never converted, detection-limit `<`/`>` notation captured separately), delimited-compound (best-fit delimiter + part count), date-ambiguity (reuses existing `_detect_ambiguous_dates`). Minimum-support-2 and a reserved `NO_MATCH` bucket keep singleton/no-match values out of "families" and visible as exceptions instead. 17 new backend tests, all passing. |
| Interface (Patterns panel) | Not started | — |
| Evidence/sampling | Implemented, backend only | Bounded sample (2000 rows) for discovery, explicit full-scan `verify` endpoint (`verified=True` only when `rows_examined == total_rows`). No background-job infrastructure yet - full scan is a synchronous vectorized/row-wise computation; see Phase 4 for whether 100k-row timing justifies revisiting this. |
| Review decisions (accept/ignore/suppress) | Implemented, backend only | `DurablePatternReviewStore`: append-only, timestamped, bound to `(dataset_id, column, source_revision, source_fingerprint)`. Verified a decision never mutates the dataset revision. |
| Extraction/standardisation | Implemented, backend only | Three new `CleanOperation` members going through the existing preview/apply/review-token flow unchanged: `extract_identifier_components` (signature-driven, rejects unrecognized signatures, preserves leading zeros - verified), `extract_numeric_unit` (value/unit/comparator columns, no unit conversion - verified), `split_delimited` (explicit delimiter, handles short rows without crashing - verified). Output-column collisions are a 422, verified. |
| Context-dependent patterns | Implemented, backend only | `group_by_column`/`group_value` on scan/verify; verified scoping actually changes family counts (3 US rows vs all 5) and that omitting `group_value` with `group_by_column` set 422s. |
| Reusable validation (pattern rule kind) | Implemented, backend only | `ValidationRuleKind.PATTERN_FAMILY` extends the existing `DurableValidationRuleStore` via an idempotent nullable-column migration. Verified: schema-compatibility 422 on an incompatible dataset, correct violations on a compatible one, `missing_value_policy` allow/reject both verified, survives a fresh store instance (restart proof). |
| Fixtures (business/scientific) | Not started | Phase 4. |
| 100k performance | Not started | Phase 4. |
| Visual/regression evidence | Not started | Phase 5 - no frontend yet. |
| Final gates (incl. full MySQL-backed live suite) | Partial | Fresh full pytest: 1329 passed (1312 baseline + 17 new), 7 skipped. ruff, mypy, boundaries, secrets, generated-contract check, web lint/typecheck: all clean. Full MySQL-backed live browser suite not yet run - no frontend to drive yet. |
| Landing | Not started | No release claim. |

This file is updated as work proceeds; it is not a snapshot of a finished
feature.
