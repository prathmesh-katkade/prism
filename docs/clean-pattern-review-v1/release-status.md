# Clean Pattern Review v1 — release status

See `acceptance-matrix.md` for the full, item-by-item evidence table;
`detector-semantics.md` for exact detector rules and limits;
`fixtures/README.md` for declared-and-verified fixture facts;
`performance-100k.md` for 100k-row measurements and a real regression found
and fixed; `restart-evidence.md` for the genuine two-process restart proof.

## What shipped

A complete, usable, durable Pattern Review workflow inside Clean:
discover → inspect evidence and exceptions → accept legitimate families
(one or several) → preview extraction/standardisation → explicitly apply →
save a reusable validation rule → reopen after a real process restart →
validate a subsequent, schema-compatible dataset. Ignore and suppress are
genuinely distinct in scope (revision-bound vs. persistent), and revocation
is append-only and inspectable.

## Explicitly deferred (not built, named as follow-up)

Fuzzy duplicate merging/entity resolution, automatic cross-column
relationship discovery, general statistical anomaly detection, automatic
recurring-export drift comparison, model-written explanations. Confirmed
empirically, not just by omission: similar-but-distinct supplier names in
the business fixture produce zero pattern findings, since no detector
attempts entity resolution.

## Known, documented boundaries (not gaps discovered after the fact)

- `date_ambiguity` checks day/month-order plausibility only, not calendar
  validity - `31/02/2026` is not flagged. This was ADR 0025's stated scope
  (reuse the existing check unchanged).
- Extraction preview/apply at 100k rows remains multi-second (not
  sub-second) due to pre-existing shared `_health()`/`add_revision()` cost,
  already measured at similar magnitude for other Clean operations in the
  prior analytical-workspaces release. This feature's own new code (the
  detectors, the extraction logic itself) is fast; a real O(n) regression in
  shared code that this feature's extraction exposed at unusual severity was
  found and fixed (see `performance-100k.md`), but the remaining shared cost
  is out of this feature's scope to optimize further.

## Gate results (final HEAD)

- Full pytest: **1353 passed, 7 skipped**, 0 regressions vs. the 1312
  baseline captured before any Pattern Review code existed.
- Web unit tests: **106 passed / 16 files**, 0 regressions.
- `npm run test:e2e:live` under MySQL (matching CI's `phase-4-live-e2e`
  exactly): run twice. First run had 2 transient failures in pre-existing,
  non-Pattern-Review specs; investigated (isolated re-run passed; full
  re-run passed both) rather than dismissed. Second run: **23 passed, 0
  failed, 4 skipped**.
- `npm run test:e2e:live` under the ordinary SQLite-backed path: **23
  passed, 0 failed, 4 skipped**.
- lint, typecheck, build:web, a11y:baseline, ruff, mypy, boundaries,
  secrets, generated-contract check: all clean.

## Branch and landing

- Feature branch: `prism/clean-pattern-review-v1`, pushed, all checkpoints
  verified before each push.
- Landing to `main`: see the final report for the exact SHA, CI link, and
  tag status at the time this session concluded.

## Production and Atlas state

Unchanged. This feature touches only Clean's durable stores, contracts, and
UI. No Atlas binding, promotion policy, or production database was read,
written, or configured.
