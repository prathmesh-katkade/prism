# Pattern Review detector semantics

All four detectors live in `apps/api/src/prism_api/clean_patterns.py`. None
depend on Ollama or any model; `PRISM_AI_PROVIDER` is never consulted here.
Every detector operates on a `pandas.Series` already sliced to either a
bounded sample (`BOUNDED_SAMPLE_ROWS = 2000`) or the full column, and returns
`(families, exception_count, exception_examples, exception_source_rows)`.

## Shared rules (apply to every detector)

- **Minimum evidence**: a signature becomes a reported family only once it
  has matched at least `MIN_FAMILY_SUPPORT = 2` rows. A signature matched by
  exactly one row is never promoted to a spurious one-value "family" - it is
  folded into the exception bucket instead.
- **Ranking and cap**: families are ranked by matching count, descending,
  capped at `MAX_FAMILIES = 6`. A column where (almost) every value is
  distinct therefore produces zero families, not six arbitrary ones.
- **`NO_MATCH_SIGNATURE`**: a reserved sentinel for values the detector's
  grammar cannot describe at all (as opposed to describing but not
  frequently enough). It can never become a family regardless of count, and
  always routes to exceptions - this is what keeps a value like `"invalid"`
  in a numeric column visible as an exception instead of silently vanishing
  between detection and reporting (a real bug found and fixed during this
  release - see `clean_patterns.py`'s `_collect_examples`).
- **Examples and source rows**: up to 5 example values per family, up to
  `MAX_EXCEPTION_EXAMPLES = 10` exception examples and matching source rows.
  Source rows are the pandas index value as a string - the same convention
  `_row_inspection` already uses elsewhere in Clean, so they are stable
  across a preview/apply cycle as long as the operation doesn't reset the
  index (none in this codebase do).
- **Count denominator**: `rows_examined` is the explicit denominator for a
  sampled or verified finding. `missing_count`, `exception_count`, and
  `nonmatching_count` are disjoint from reported family matches and reconcile
  to that denominator. Delimiter values without the winning separator and
  unambiguous dates are nonmatching; they are not called malformed.
- **Exception identity and paging**: example values and source-row IDs are
  captured as pairs in source order. A separate explicit exception-page
  request returns at most 100 pairs, checks the reviewed revision and
  fingerprint, and rejects stale requests with 409. Paging recomputes the
  selected detector on request; opening or rendering the UI does not repeat
  a full verification scan.

## `identifier_structure` (version 1)

Canonicalizes a value into a letter/digit-run signature: each maximal run of
`[A-Za-z]` becomes `L<n>`, each maximal run of `[0-9]` becomes `N<n>`, any
other character is kept literally. `"INV-000123"` → `"L3-N6"`. Two values
with different run lengths are different families by design - `"L3-N6"` and
`"L3-N5"` never merge, since the task is "does this convention hold", not
"is this roughly identifier-shaped."

- **Supported**: prefixes, separators, and lengths in any mix of
  letters/digits/punctuation.
- **Unsupported**: the signature says nothing about which specific letters
  or digits appear - `"ABC-123"` and `"XYZ-456"` share a signature
  (`"L3-N3"`) by design, since the convention being described is structural,
  not content-specific. Case is not folded or normalized (`"inv-123"` has a
  different literal content than `"INV-123"` but the same `L3-N3` structure
  - mixed case within one otherwise-consistent family will still match the
  same signature; case is never used to *reject* a match).

## `numeric_unit` (version 1)

Regex: `^\s*(?P<cmp><=|>=|<|>)?\s*(?P<sign>[+-])?(?P<num>\d+(?:\.\d+)?)\s*(?P<unit>[A-Za-z%°/]+)?\s*$`.
Signature is `"{prefix}unit:{unit or 'none'}"` where `prefix` is `"limit:"`
when a comparator (`<`, `>`, `<=`, `>=`) is present.

- **Supported**: a plain or decimal number, an optional leading sign, an
  optional trailing unit token (letters, `%`, `°`, `/`), and an optional
  leading comparator for detection-limit notation (`"<0.05 kg"`).
- A detection-limit value is a *different family* from the same unit without
  the comparator (`"<0.05 kg"` is `limit:unit:kg`, never merged with plain
  `unit:kg`) - the qualifier is semantically load-bearing, not noise.
- **No unit conversion, ever**: the unit token found is reported verbatim.
  `kg` and `lb` are always distinct families; nothing in this detector or
  the paired `extract_numeric_unit` operation converts between them.
- **Unsupported**: scientific notation (`1.5e10`), fractions, and compound
  units (`"kg/m^2"` matches the unit group as the single token `kg/m` at
  best - not validated, not a target for this release). Thousands separators
  (`"1,250"`) do not match `\d+(?:\.\d+)?` and fall through to `NO_MATCH`.

## `delimited_compound` (version 1)

Tries each of `_DELIMITER_CANDIDATES = [",", ";", "|", "/", ":", "-", "_"]`
against the column's non-null values, computing the distribution of
split-part-counts for each. Keeps only the single delimiter with the
highest-coverage dominant part-count (requires that coverage to be at least
`max(MIN_FAMILY_SUPPORT, 50% of non-null rows)`); reports no finding at all
if no delimiter clears that bar. Signature:
`"delim:{delimiter}:parts:{part_count}"`.

- **Supported**: exactly one delimiter character per column - a column that
  uses two unrelated delimiters interchangeably as the *actual* convention
  is not modeled.
- **Unsupported**: multi-character delimiters, delimiters that are
  themselves regex metacharacters used literally (handled safely since
  matching uses plain substring containment, never regex, but still single-
  character only), and "soft" delimiters like variable whitespace runs.
- Values not containing the winning delimiter at all are excluded from this
  finding's counts entirely (not reported as this detector's exceptions) -
  they are simply a different shape with respect to this delimiter, and may
  still surface as `identifier_structure` exceptions on the same column if
  relevant.

## `date_ambiguity` (version 1)

Thin wrapper around the existing `clean.py::_detect_ambiguous_dates`,
unchanged. Regex: `^\s*(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}\s*$`; a value is
ambiguous when *both* captured components are `<= 12`.

- **Supported**: exactly the day/month-order ambiguity the existing function
  already checked (reused, not reimplemented) - e.g. `"05/12/2026"` is
  ambiguous because `12 <= 12`, not just because the first component is
  small. See `fixtures/README.md` for a concrete case this catches that a
  naive "check only the first component" implementation would miss.
- **Explicitly not supported**: calendar validity. `"31/02/2026"` (day 31 in
  February) is not flagged, because `31 > 12` already rules out the
  ambiguous-order reading and the detector was never scoped to check whether
  the resulting date actually exists on a calendar - that was ADR 0025's
  stated boundary (reuse the existing check unchanged), confirmed and
  documented as a real, current limitation in `fixtures/README.md`, not
  discovered as a surprise afterward.
- There is exactly one family (`"ambiguous_day_month"`) when any ambiguous
  values exist; this detector never reports exceptions (a value is either
  ambiguous or it isn't - there is no third "malformed" bucket here, unlike
  the other three detectors).

## Which detectors run on a column (`_applicable_detectors`)

A cheap, bounded heuristic over the column's sample decides which detectors
are worth running at all, so (for example) a purely numeric column doesn't
waste a scan slot on `identifier_structure`:

- `identifier_structure`: > 30% of sampled values contain both a letter and
  a digit.
- `numeric_unit`: > 30% of sampled values match the numeric/unit regex.
- `delimited_compound`: any of the first 50 sampled values contain any
  candidate delimiter character.
- `date_ambiguity`: `_detect_ambiguous_dates` finds at least one ambiguous
  value in the sample.

More than one detector can and does fire on the same column when the data
genuinely supports it (e.g. a `"99 lb"`-style column matches both
`identifier_structure`'s letter/digit heuristic and `numeric_unit`'s regex -
both findings are reported; detectors are not tuned to suppress a true
secondary signal to keep a demo tidy).

## Resource limits

- Bounded discovery: `BOUNDED_SAMPLE_ROWS = 2000` rows per column per
  detector, regardless of total dataset size.
- Full verification: the entire column, computed synchronously - see
  `performance-100k.md` for why this is safe at 100k rows (every detector's
  full-scan cost is sub-second) without background-job infrastructure.
- Example/exception lists are capped (5 / 10) independent of how large the
  underlying dataset is - no endpoint response scales with total row count
  beyond the `rows_examined`/`total_rows` counters themselves.
