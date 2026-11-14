# SQL Lab + Visualize finish — discrepancy table and fixes (2026-11-14)

## Continuation — 2026-11-14 (round 2)

Picked up from the checkpoint below (`cef4ef6`) per explicit owner instruction
to continue without restarting, inspect the `Cargo.toml` change before acting
on it, re-request the two previously-denied approvals narrowly, check an
identity-conflation edge case in the missing-dimension fix, and do an actual
geometry/density comparison against the references rather than a source-code
inventory.

**`Cargo.toml`**: inspected byte-for-byte against `HEAD` (`git show
HEAD:...Cargo.toml` diffed with CRLF stripped from both sides) — content is
**identical**; the working-tree diff is a pure CRLF line-ending artifact the
build tooling wrote to disk, not a real change. Left alone; nothing to commit.

**The two approval blockers**: re-identified the port-8000 occupant first
(`Get-CimInstance Win32_Process -Filter "ProcessId=16988"` — same PID, same
executable path, same 06:21:47 creation time as before, ~9.5h uptime, so it is
confirmed the *same* process, not a reused PID) and re-verified the Clean+Atlas
landing state was unchanged (`origin/main` still `c9472ca`, merge-base still
exact). Both actions were then re-requested narrowly through the same
mechanism, each naming the prior denial:
- **Terminating PID 16988**: denied again, identically, with the same binding
  instruction not to pursue the outcome through any other mechanism. This
  confirms the restriction sits below the conversational layer — explicit
  owner instruction in chat does not clear it; only the owner's own Bash
  permission settings (named in the denial itself) or the owner acting
  directly can. **Native desktop live proof remains blocked for this reason
  alone** — not a defect in this round's build.
- **Fast-forwarding `main` to `a2a75f9`**: this one **succeeded**. `git merge
  --ff-only origin/prism/clean-pattern-review-v1 && git push origin main` from
  the clean `prism-track-a-main` worktree went through without denial.
  **`main` is now landed at `a2a75f9` (`c9472ca..a2a75f9 main -> main`,
  confirmed on the remote via a fresh `git fetch`).** CI on that exact SHA
  (run `43584531056`) finished **all 5 jobs green**
  (secret-scan/phase-4-live-e2e/legacy-regression/phase-1-python/phase-1-web)
  — verified via `gh run view --json status,conclusion`, not inferred from an
  earlier run. **Phase 1 is complete.**

**Identity-conflation edge case** (a dataset with both a real null `region`
and a literal `"(missing region)"` category): confirmed this was a real gap —
the placeholder label could collide with real data, merging two different row
sets under one display string and making drilldown ambiguous. Fixed narrowly:
`_missing_dimension_label` now checks the actual column for a collision and
appends a numeric disambiguator (`"(missing region) [2]"`) only when one
exists, so the two stay distinct in aggregation and in drilldown (drilldown
re-derives the same disambiguated text from the same filtered frame, so it
never needs a new identity field on the wire). The same fix extends to
small-multiples facets, which previously dropped rows with no facet value
from every panel with no disclosure at all. Four new tests cover this exactly
(`test_a_real_category_literally_named_like_the_placeholder_...`,
`..._drilldown_on_the_real_colliding_category_...`,
`..._drilldown_on_the_disambiguated_placeholder_...`,
`..._small_multiples_give_rows_with_no_facet_value_their_own_panel`).

**A second, unrelated real bug found while live-testing the join-evidence
panel**: `sql_lab_join_diagnostics.py` reported every join as `"inner"`
regardless of its actual kind, because sqlglot splits a join's type across
two attributes (`side` for LEFT/RIGHT/FULL, `kind` for INNER/OUTER/CROSS) and
the code only read `kind` — which is empty for a plain `LEFT JOIN`, falling
through to the `"inner"` default. This wasn't just a labeling slip: it made
the panel's own "unmatched rows retained by INNER JOIN" message
self-contradictory, since an inner join is exactly what does *not* retain
unmatched rows. Fixed by preferring `side` over `kind` over the `"inner"`
default. Regression test
`test_detect_equi_joins_reports_the_real_join_kind_not_a_blanket_inner_default`
covers all seven join-keyword variants sqlglot can produce.

**Geometry/density comparison, done properly this time** (re-reading both
references at full size, not from memory of "the control exists"): see §6
below for the per-element table. Two real presentation gaps were found and
fixed in this round (join-evidence readability, chart leading-bar color) on
top of the two correctness bugs above; one gap (the shared
`--good`/`--danger` tokens being a softer variant of the palette's
Success/Error hexes) is named and deliberately left alone, same reasoning as
before — it is a global, cross-workspace token change outside this round's
two-screen scope, not a SQL Lab/Visualize-specific fix.

**Local-only false failure, not a regression**: a full-suite re-run hit
`tests/api/test_phase8c_lineage_traversal.py::test_ancestors_never_cross_into_a_different_fingerprint_sharing_the_same_revision_number`
failing with `Analytical object 'fp_child' is already registered.` Root
cause: that test (and the module it exercises) uses the durable registry's
*default* on-disk path (`.prism/runtime/analytical-history.sqlite`) whenever
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` is unset, and this worktree had
accumulated state in that file across many local pytest invocations run today
without ever clearing it between runs. Deleting that local, gitignored,
disposable file and re-running gave a clean pass. **This is a local
environment-reuse artifact of running the same checkout repeatedly, not a
code regression** — CI's ephemeral filesystem starts fresh every run and
would never accumulate this state. Confirmed by running the single test
alone (clean), the full suite with the stale file present (fails,
reproducibly), and the full suite again right after deleting it (clean):
**831 passed, 3 skipped**, final.

Evidence for this round: `evidence-20261114/sql-lab-join-evidence-synthesis.jpg`,
`evidence-20261114/visualize-leading-bar-highlight.jpg` (both captured live
against the same disposable MySQL fixture as round 1, after restarting the
dev API with every fix in this round applied).

---

Branch: `prism/sql-visualize-finish-v1`, based on `prism/clean-pattern-review-v1` @
`a2a75f9` (now the actual `main` tip, landed in this round — see
`docs/clean-atlas-v1/landing-20261114.md` for the full Phase 1 record).

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

## 5. Native desktop verification — rebuilt successfully; live functional proof blocked

The sidecar was rebuilt from this branch (`apps/api/build_sidecar.py`, PyInstaller
`--onefile`, 212 MB, `x86_64-pc-windows-msvc`) and the Tauri desktop app was rebuilt
from source against it (`npx tauri build`; the Rust compile and both bundles — MSI
and NSIS — completed successfully; a later, unrelated updater-signing step then
failed for lack of a `TAURI_SIGNING_PRIVATE_KEY`, which does not affect
`target/release/app.exe` itself). This confirms both fixes compile and package
cleanly into the real desktop binary.

Launching that rebuilt `app.exe` to prove the fixes live in the native app is
**blocked by a specific, already-encountered external constraint**: the desktop
sidecar always binds `127.0.0.1:8000` (`sidecar.rs`'s `SIDECAR_ADDR` constant; no
port override exists), and that port is already held by a `prism-api.exe` left
running from earlier in this same long session (PID 16988) — a known, documented
class of issue in this codebase's own `sidecar.rs` (PyInstaller's onefile
bootloader can be reaped on Windows while its real child process, which is what's
actually listening, survives as an orphan; see the long comment above `pub fn
kill()` there). Freeing that port means terminating that specific process, which
the harness's own safety classifier explicitly denied earlier this session with a
binding instruction not to pursue the same outcome through any other mechanism or
later turn — so launching the rebuilt app now would silently talk to that stale,
pre-fix sidecar (serving its own unrelated leftover dataset) instead of proving
anything about this round's changes, and was not a safe substitute for a real test.
Confirmed and then cleaned up (stopped the newly-launched `app.exe`/sidecar pair
this attempt spawned, since they weren't exercising the fix).

**This is the specific external blocker Phase 3 ends on.** Everything else in this
document stands as real, live-verified evidence of both fixes — the pytest suites
(including a live-MySQL test actually executed, not skipped), `mypy`/`ruff`, and
the full end-to-end browser-dev-server run against the real disposable MySQL
fixture (§2–§3's screenshots) — none of that depends on the native desktop binary.
To complete native verification, the owner can restart the machine (clearing the
orphaned process) or explicitly authorize terminating PID 16988, then re-run
`target/release/app.exe` from this worktree with the three env vars in
`.prism/viz-finish-20261114/launch-native.ps1` set.

## 6. Geometry/density comparison (round 2) — per-element, not "control exists"

Done by re-reading both reference PNGs at full resolution and comparing
against live screenshots of the same disposable fixture at a matching window
size, element by element:

| Element | Reference | Current (round 1 end) | Verdict |
|---|---|---|---|
| SQL Lab data-source list | Cards with per-source Revision + row count | Plain `<select>`, label+dialect only, no revision/row count | Real gap, **not fixed**: a MySQL/external connector has no PRISM revision concept at all (only a promoted local CSV dataset does), so the reference's exact framing doesn't transfer 1:1 to the scenario this round's fixture uses. Naming it rather than fabricating a revision number for a live external table. |
| SQL Lab toolbar buttons | Explicit icons (▶ play, 💾 save) | Text-only buttons | Named, not fixed — icon-only polish, lowest-value item found, deferred rather than touched under time pressure for a cosmetic-only change. |
| **Join evidence panel** | Human-readable synthesis (relationship type, unique-keys, matched/unmatched with ✓/⚠, amber callout) *above* any raw numbers | Raw per-side cardinality only (rows/distinct/duplicate/null) with no synthesis | **Fixed this round**, see §7. |
| Join evidence handoffs placement | Dedicated "Result handoffs" section in the right rail | Inline in the grid's own toolbar row | Named, not fixed — a defensible alternate placement (handoffs next to the data they act on), not a functional gap; moving it is a larger layout change than this round's fix budget covers. |
| Visualize Fields panel | One flat field list, type-glyph coded (Ab/#/123/📅) | Split into DIMENSION/MEASURE group headers, plain bullet dot | Named, not fixed — a different, defensible grouping paradigm (maps directly to what you're about to pick for the active mark) rather than a regression; retrofitting the reference's exact glyph system is a broader Fields-panel redesign outside this round's two fixes. |
| Visualize chart canvas | Bordered/panelled card around the chart | Marks float on the bare canvas background, no panel border | Named, not fixed — real, visible, but purely cosmetic framing; deferred alongside the toolbar-icon item above. |
| **Chart bar coloring** | Leading category highlighted gold/brass, others a distinct blue | Every bar the same brass color (the `is-leading` CSS hook existed for horizontal_bar only and was a no-op duplicate of the default fill; vertical bar had no hook at all) | **Fixed this round**, see §7. |
| Filter-chip rendering | Not independently verified | Not independently verified | No active filter was applied in either round's capture; this specific visual (pill shape, fill, border) was not compared and is not claimed as matching or non-matching. |
| Palette tokens (Canvas/Panel/Raised/Brass/Selected-row) | Exact hexes | `prism.css` already defines the exact matching hex for all five | Match (unchanged from round 1's finding). |

## 7. Round 2 fixes: join-evidence synthesis and value-based chart highlighting

**Join evidence** (`query-studio.tsx`'s `JoinDiagnosticsPanel`): added a
synthesized summary derived entirely from the existing real `JoinDiagnostic`
fields — relationship type (`sideIsUnique` on each side → one-to-one /
one-to-many / many-to-one / many-to-many), the matched side's own key
uniqueness, a matched-count (`left.total_rows - unmatched_left_rows`, a real
derived number, not a new field), status dots (green/amber), and an amber
callout naming the actual join kind when any rows are unmatched. The raw
per-side cardinality detail is kept, not removed — it now sits behind a "Key
cardinality detail" disclosure instead of being the first and only thing
shown, matching the reference's "synthesis first, detail available" ordering.
Discovering this surfaced the join-kind bug in §"Continuation" above (the
callout would have read "retained by INNER JOIN" for an actual LEFT JOIN,
which is self-contradictory) — fixed alongside it.

**Chart leading-bar highlight** (`visualize-workspace.tsx`'s `ChartCanvas` +
`prism.css`): the highlight is now keyed on the data point's actual value
(`point.value === Math.max(...data.map(d => d.value))`) rather than array
index, so it stays correct under every `sort_by` option, not just the default
value-descending one. Extended from horizontal_bar-only (where it existed but
did nothing, per the table above) to the vertical bar mark too, explicitly
excluded from histogram bins (a distribution has no single "leading" bin to
single out). Reuses the existing `--blue` token (already used elsewhere for
Clean's "reviewed" status chips) for the non-leading bars rather than
inventing a new color, per instruction not to retint shared tokens casually
and not to add a color without a reason tied to an existing, approved one.

Both verified live end-to-end against the same disposable fixture: Join
evidence now reads "left join / Many to one / Unique / 250 / 10" with the
correct amber callout; the revenue-by-region chart now shows Bengaluru (the
largest) in brass against the other three regions in blue. Screenshots:
`evidence-20261114/sql-lab-join-evidence-synthesis.jpg`,
`evidence-20261114/visualize-leading-bar-highlight.jpg`.

Tests: `query-studio.test.tsx` gained
`"synthesizes a human-readable relationship type and matched count..."` and
`"omits the unmatched-rows callout entirely when a join's keys fully match"`
(11 tests total, was 9); `visualize-workspace.test.tsx` gained
`"highlights only the largest-value bar's own group, by value rather than
array position, on both bar orientations"` and `"gives a histogram bin no
leading-bar highlight..."` (15 tests total, was 13).

## 8. What was not touched

No change to Atlas orchestration, model bindings, promotion policy, cleaning
semantics, or report correctness, in either round. No fabricated data,
disabled-looking fake controls, or invented statistics — every number in
every screenshot in this document came from a real query against the
disposable fixture. No new dependency, framework, or abstraction was
introduced. Round 1's two fixes were backend-only (`visualize.py`,
`sql_lab_join_diagnostics.py`); round 2 added two narrow frontend
presentation fixes (`query-studio.tsx`, `visualize-workspace.tsx`,
`prism.css`) directly demonstrated by the reference comparison in §6, plus
one more backend correctness fix (join-kind detection) found while verifying
the first frontend fix live — none of the four are a new architecture or a
global retint of shared tokens.
