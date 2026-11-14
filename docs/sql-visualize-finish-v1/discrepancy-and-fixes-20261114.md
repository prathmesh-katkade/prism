# SQL Lab + Visualize finish — discrepancy table and fixes (2026-11-14)

Branch: `prism/sql-visualize-finish-v1`, based on `prism/clean-pattern-review-v1` @
`a2a75f9` (content-identical to pending merged `main` — see
`docs/clean-atlas-v1/landing-20261114.md` for the Phase 1 landing blocker).

Per instruction: capture the current populated SQL Lab and Visualize screens against
the approved references first, write the discrepancy table, then implement. This file
is that record. References read in full before any edit:
`docs/clean-pattern-review-v1/references/sql-lab-concept.png`,
`visualize-concept.png`, `palette-a-charcoal-brass.png`.

## 0. Fixture used for this comparison

One disposable fixture, reused for every screenshot and test run in this document:
a local MySQL 8.0.40 instance (`.prism/mysql-disposable-20261114-viz/`, port 3309,
never touched by anything else) seeded with `orders` (260 rows) and `customers`
(6 rows), built to reproduce the reference's exact numbers: Bengaluru 120 orders /
₹240,000, Mumbai 50 / ₹160,000, Pune 80 / ₹100,000, and 10 orders whose
`customer_id` matches no `customers` row (left-join "unmatched"). Verified via
direct SQL before use:

```
region      n    rev
Bengaluru   120  240000.00
Mumbai      50   160000.00
Pune        80   100000.00
NULL        10   20000.00
```

Seed script: `.prism/seed-visualize-fixture-20261114.sql`. The API was run from
source (not the frozen sidecar binary, which hardcodes port 8000) against this
fixture via `PRISM_EXTERNAL_SQL_SOURCES_JSON` / `PRISM_ORDERS_MYSQL_URL`, with its
own isolated `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` (sqlite) — no shared or
production binding touched.

## 1. Current component structure vs. the references

Both `query-studio.tsx` (SQL Lab) and `visualize-workspace.tsx` (Visualize) were
last touched 2026-10-09 and 2026-10-17 respectively, and already implement nearly
every structural element the two reference images call for — read in full before
concluding this (see component source). Comparison:

| Reference element | Current implementation | Verdict |
|---|---|---|
| SQL Lab: Data sources list + Schema navigator + Saved queries (left panel) | Present: source `<select>`, searchable schema tree with type badges, saved-queries list | Match |
| SQL Lab: editor + Run/Save/Format/Plan/Join-checks/Find-CTEs toolbar | Present, including `⌘ ↵` hint and a "safe reads run without a prompt" disclosure | Match |
| SQL Lab: results grid with real row counts, sort, filter, pagination, CSV export | Present (`DataGrid`), including "returned / total rows", truncation disclosure, per-column sort | Match |
| SQL Lab: Join evidence card with real matched/unmatched counts | Present (`JoinDiagnosticsPanel`) — **was broken for any real MySQL connection; fixed, see §2** | Fixed this round |
| SQL Lab: Result → Clean / Visualize / AI-evidence handoffs | Present ("Use in Clean", "Use in Visualize", "Use as AI evidence", "Create dataset") | Match |
| SQL Lab: error/loading/empty states | Present (`loading-state`/`empty-state`/`error-state` sections, per-field validation) | Match |
| Visualize: Fields panel (dimension/measure picker, search, saved views) | Present | Match |
| Visualize: Chart/Data/Small-multiples tabs | Present | Match |
| Visualize: active filter chips + "+ Add filter" | Present | Match |
| Visualize: dominant chart canvas (bar/horizontal_bar/line/scatter/histogram/box) | Present, all six marks implemented as real SVG renderers | Match |
| Visualize: rows with no matched/missing dimension value stay visible with a disclosure, not silently dropped | **Was silently dropped with no warning; fixed, see §3** | Fixed this round |
| Visualize: real contributing-row inspection on mark click, with "Clear selection" | Present (`selectMark` → drilldown table) — **was broken for the missing-value category specifically; fixed as part of §3** | Fixed this round |
| Visualize: Chart settings (mark/category/measure/aggregation/sort/axis-start/currency) | Present | Match |
| Visualize: Reference line + annotation | Present | Match |
| Visualize: Save chart / Open reports handoff | Present | Match |
| Visualize: empty/loading/error states | Present | Match |
| Palette (Canvas/Panel/Raised/Accent/Selected-row) | `prism.css` already defines `--canvas:#141310`, `--surface:#1C1A16`, `--surface-raised:#25221C`, `--accent:#D6AE50`, `--accent-soft:#3B301A` — **exact matches** to the reference's Canvas/Panel/Raised/Brass/Selected-row tokens | Match |
| Palette (Success/Error) | `--good:#94B48A` / `--danger:#D99B9B` vs. the reference's Success `#5A7F4E` / Error `#9C4B4B` — a softer variant of the same two hues | Named gap, not fixed (see §4) |

No missing *capability* was found in either screen once the two bugs below were
fixed — the remaining differences are either already-matching or a single, scoped,
named styling gap (§4), not absent functionality.

## 2. Fix: Join evidence failed outright against any real MySQL connection

**Found by**: running the reference's own join scenario
(`orders LEFT JOIN customers ON o.customer_id = c.customer_id`) against the
disposable MySQL fixture in SQL Lab and opening "Join evidence."

**Symptom** (verbatim, from the live UI before the fix):

> Could not compute key cardinality for orders.customer_id:
> (pymysql.err.ProgrammingError) (1064, 'You have an error in your SQL syntax;
> check the manual that corresponds to your MySQL server version for the right
> syntax to use near \"orders\") AS prism_result LIMIT 1001\' at line 1'...

**Root cause**: `apps/api/src/prism_api/sql_lab_join_diagnostics.py`'s `_quote()`
always wrapped identifiers in double quotes. That is correct ANSI-SQL quoting
(DuckDB, PostgreSQL, SQLite, and SQL Server under its default
`QUOTED_IDENTIFIER ON`), but MySQL's default `sql_mode` does **not** include
`ANSI_QUOTES` — it parses `"orders"` as a string literal, not an identifier, and
the surrounding query fails to parse. Every join-diagnostics query against a real
MySQL connector failed before this fix; it only ever worked against the DuckDB
("local dataset") connector used by the existing test suite, which is why it
shipped unnoticed.

**Fix**: `_quote()` now takes the connection's dialect and uses backtick quoting
(with proper `` ` `` doubling for escaping) for MySQL, double-quote for every
other dialect — unchanged behavior there. Verified live end-to-end against the
disposable fixture after the fix: Join evidence now reports real cardinality
(260 rows, 7 distinct keys, 253 duplicate-key rows, 0 null keys, 10 unmatched) —
screenshot: `evidence-20261114/sql-lab-after-fix-join-evidence.jpg`.

**Tests added**:
- `tests/api/test_sql_lab_join_diagnostics.py`: two new dialect-quoting unit tests
  (no live DB needed — lock the backtick-vs-double-quote behavior directly).
- `tests/sql_lab/test_mysql_connector_parity.py`: a new live-MySQL regression test
  (`test_mysql_connector_join_diagnostics_quote_identifiers_correctly`), run under
  CI's existing `mysql:8.0` service the same way its sibling tests already are.
  **Actually executed** (not just added) against the disposable fixture, seeded
  with CI's exact `sales` table, before being committed — passed.

## 3. Fix: rows with a null dimension were silently dropped from every chart, with no disclosure, and could not be drilled into

**Found by**: promoting the join query's result into Visualize ("Use in
Visualize") and charting revenue by region. The reference's bar chart has four
bars (Bengaluru/Mumbai/Pune/Unmatched, ₹240k/₹160k/₹100k/₹20k) with a warning
banner ("10 orders have no matched region. They remain included."). The current
chart rendered only three bars (₹240k/₹160k/₹100k) — the 10 unmatched orders'
₹20,000 vanished from the chart with no warning, no trace, and no way to
discover why the total didn't add up.

**Root cause**: `apps/api/src/prism_api/visualize.py`'s aggregation used
`frame.groupby(dimension, dropna=True)` (the box-plot path additionally dropped
these rows earlier via `.dropna(subset=[measure, dimension])`) — pandas excludes
any row whose grouping key is null, with no warning. This module's own stated
design principle is "every response carries a trust warning when the aggregation
would mislead" (see its module docstring) — a silent drop is exactly the failure
mode that principle exists to prevent, so this is a correctness bug against the
module's own stated intent, not a missing feature.

**Fix**: the bar/horizontal_bar/line aggregation path and the box-plot path now
group with `dropna=False`, relabel the null-key group as `(missing <dimension>)`
(a generic, honest label — Visualize has no join context to know the null came
from an unmatched join key specifically, so it does not claim that), and add an
explicit warning: `"N row(s) have no value for '<dimension>'; shown as '(missing
<dimension>)' rather than being dropped."` The drilldown endpoint was also fixed:
it resolved a clicked category back to its rows via
`frame[dimension].astype(str) == dimension_value`, which can never match a real
`NaN` row (its string form is `"nan"`, not the placeholder text) — it now checks
for the placeholder explicitly and masks on `.isna()` instead, so "contributing
rows" on the missing-value bar/box now returns the real rows instead of zero.

Verified live end-to-end against the disposable fixture after the fix: the chart
shows all four bars (₹240k/₹160k/₹100k/₹20k) with the warning banner, and
clicking the fourth bar shows its real 10 contributing rows (order_id 251–260,
customer_id 999, region `—`, revenue 2000 each) — screenshot:
`evidence-20261114/visualize-after-fix-missing-region-bar.jpg`.

**Tests added** (`tests/api/test_visualize.py`): a 5-row fixture with two blank
`region` values —
- bar aggregation keeps the missing-dimension row as an explicit category and
  discloses the drop count;
- box plot does the same;
- drilldown on the placeholder resolves to the real null rows;
- a dataset with no nulls gets no placeholder and no spurious warning (confirms
  the fix is additive, not a behavior change for the common case).

All 75 pre-existing Visualize tests plus the 4 new ones pass (32 total in
`test_visualize.py`); all 16 join-diagnostics/MySQL-parity tests pass (including
the live-MySQL one, actually executed against the disposable fixture, not
skipped). Full suite: `821 passed, 8 skipped` across `tests/api`, `tests/sql_lab`,
`tests/test_visualization.py`. `mypy --follow-imports=skip ...` (CI's own
invocation) and `ruff check` are clean on every touched file. Frontend:
`query-studio.test.tsx` (9) and `visualize-workspace.test.tsx` (13) pass
unchanged — this round's fixes are backend-only; no component source was edited.

## 4. Named gap, not fixed (styling, deliberately out of scope this round)

`--good`/`--danger` (used across every workspace, not just SQL Lab/Visualize) are
a softer variant of the reference palette's Success/Error tokens (`#94B48A` vs
`#5A7F4E`, `#D99B9B` vs `#9C4B4B`). Retinting them would be a global, app-wide
color change with a blast radius far beyond SQL Lab + Visualize (every status
dot, chip, and warning border in Clean, Overview, Atlas, etc.), and the brief
explicitly scopes this round to "one bounded visual milestone" for these two
screens — changing a shared design token is a separate, deliberate design
decision for the owner to make, not an implicit side effect of finishing these
two screens. Named here rather than silently left alone or silently changed.

## 5. What was not touched

No change to Atlas orchestration, model bindings, promotion policy, cleaning
semantics, or report correctness. No fabricated data, disabled-looking fake
controls, or invented statistics — every number in every screenshot in this
document came from a real query against the disposable fixture. No new
dependency, framework, or abstraction was introduced; both fixes are narrow,
in-place corrections to existing aggregation/quoting logic already present in
`visualize.py` and `sql_lab_join_diagnostics.py`.
