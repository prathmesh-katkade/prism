# Pattern Review acceptance fixtures

Synthetic, non-sensitive, deterministic. Every fact below was checked against
a real run of `POST /patterns/discover` (or `/scan`, `/verify` as noted)
against the exact CSV in this directory - not hand-derived and left
unverified. Row numbers are 0-indexed source rows, matching what
`exception_source_rows` actually returns.

## `business-invoices.csv` (9 rows, 5 columns)

| Requirement | Verified fact |
|---|---|
| Two legitimate invoice-ID formats | `invoice_id` identifier_structure: family `L3-N6` (3 letters, dash, 6 digits) count **5** - `INV-000123, INV-000456, INV-007007, INV-000321, INV-000999`; family `L2-N4-N3` count **2** - `RE-2024-001, RE-2024-002`. Both meet the minimum-support-2 threshold and are reported as families, not merged. |
| Malformed minority value | `AB12` (row 6) matches neither family (count 1) and is correctly bucketed as the sole exception, not a spurious third family. |
| Leading-zero identifiers | `INV-000123` etc. - confirmed the `000123` component survives `extract_identifier_components` unchanged (string, not coerced to int 123) - see `tests/api/test_clean_patterns.py::test_extract_identifier_components_preserves_leading_zeros...`. |
| Missing cells | `invoice_id` missing_count = **1** (row 5, Gamma LLC); `order_date` missing_count = **1** (row 4, Gamma LLC). Counted separately from exceptions, not conflated. |
| Ambiguous currency/date strings | `order_date` date_ambiguity: family `ambiguous_day_month` count **4** - `01/01/2026, 01/02/2026, 02/02/2026, 05/12/2026` (all have both components ≤12, so day/month order cannot be inferred - note `05/12/2026` is ambiguous too since 12≤12, which a naive "month>12 only" check would miss). Currency amounts (`$1,250.00`, `€750,00`, `€1.200,50`, `£99.99`) use genuinely different thousands/decimal conventions; no v1 detector attempts to parse or compare currency amounts across locales - this is deliberately out of scope (see "No guessed unit conversion or locale," ADR 0025), not silently mishandled. |
| Group-specific formats | Scoping `invoice_id` discovery to `country=DE` (`POST /patterns/columns/invoice_id/scan` with `group_by_column=country, group_value=DE`) surfaces only the `L2-N4-N3` family at count 2, scoped to exactly the 2 DE rows - confirmed by `tests/api/test_clean_patterns.py::test_group_by_column_scopes_discovery_and_requires_group_value`. |
| Similar supplier names, different entities | `supplier_name` (`Acme Corp`, `Acme Corp Ltd`, `Acme Corporation`, `Beta Industries`, `Gamma LLC`) produces **zero** pattern findings - no v1 detector attempts fuzzy matching or entity resolution; similar names are never silently treated as the same supplier. Confirmed by a live scan returning `[]`. |

Secondary, true findings not explicitly requested but worth noting: `delimited_compound` also fires on `order_date` (splits on `/` into 3 parts, 8 of 9 rows) and on `invoice_id` (splits on `-`), since both are genuinely present - detectors are not tuned to suppress a true secondary signal just to keep the demo tidy.

## `scientific-measurements.csv` (8 rows, 3 columns)

| Requirement | Verified fact |
|---|---|
| Numeric values with units | `measurement` numeric_unit: family `unit:kg` count **4** - `10.5 kg, 20 kg, 15.2 kg, 18.0 kg`. |
| Mixed units remain distinct | `99 lb` and `2.1 mg` are never folded into the `kg` family - each is a singleton, correctly reported as an exception rather than invented into its own spurious one-value family. No unit conversion is attempted anywhere. |
| Detection-limit notation (`<0.05`) | `<0.05 kg` is excluded from the `unit:kg` family specifically because of the `<` prefix (its internal signature is `limit:unit:kg`, distinct from plain `unit:kg`) - confirmed it is *not* silently treated as the plain value `0.05 kg`. |
| Invalid numeric text | `invalid` matches no numeric shape at all and is reported as an exception (not silently dropped) - confirmed via the reserved `NO_MATCH` sentinel reaching the finding's `exception_examples`, not vanishing between detection and reporting. |
| Ambiguous dates | `observed_at` date_ambiguity: family `ambiguous_day_month` count **1** - `03/04/2026`. |
| Impossible dates | **Known, documented boundary**: `31/02/2026` (day 31 in February, which does not exist) is *not* flagged by date_ambiguity - the detector only checks whether both components could plausibly be a month (≤12), not whether the resulting date is calendar-valid. `31>12` rules out the ambiguous-order reading entirely, so the detector reports nothing for this value. Calendar-validity checking was never in ADR 0025's scope (it reuses `clean.py`'s existing day/month-order ambiguity check unchanged) and is not implemented in this release. |
| Legitimate rare formats | `S-001`..`S-008` all share one `identifier_structure` family (`L1-N3`, count 8) - a *consistent* rare-looking format across every row is correctly reported as the single real convention, not flagged as suspicious merely for being short. |

Exact exception source rows for `measurement` numeric_unit: `['2', '3', '4', '7']` =
`<0.05 kg` (S-003), `99 lb` (S-004), `invalid` (S-005), `2.1 mg` (S-008) - each
resolves to its real source row, confirmed against the live API response.
