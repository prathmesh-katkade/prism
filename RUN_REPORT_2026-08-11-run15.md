# Prism Improvement Routine — Run 15 Report (2026-08-11)

## 0. Process note (same contradiction every run since Run 9 has flagged)

This run's trigger again asked for the full 8-phase routine to repeat "until
the session is 100% used" while also directing "use less tokens" / "don't use
credits" — mutually exclusive instructions. Consistent with Runs 9–14 and the
session's own git instructions (which take precedence over the scheduling
prompt's phrasing), this run executed **one complete, safely verified
cycle** — orientation, a modest research check, 2 features, tests, live
verification, merge, push, report — and stopped.

## 1. Orientation

Read `.prism/routine_log.md` in full (all 14 prior entries), `CHANGELOG.md`,
and Run 14's report. Discovered local `main` was **76 commits stale**
(last synced around Run 7) — fast-forwarded to `origin/main`'s real tip
(`6d273ea`, Run 14) via `git merge --ff-only` before touching anything, per
Run 8's documented precedent for exactly this situation. No work was lost;
feature branches were built fresh off the correct tip.

**Research pass (per this run's instruction to check, not skip, after 6
consecutive reuse runs):** a modest WebSearch-scale check of agentic-EDA/
auto-insight tooling, Hex/Deepnote/Julius AI/ChatGPT-ADA feature moves, and
DuckDB/polars adoption trends turned up nothing that would change this run's
selection — no new competitor feature category emerged that isn't already
either shipped (auto-insights, confounder detection, causal inference,
hypothesis sweep, ensemble anomaly consensus, chart-builder encoding
channels) or already on the standing backlog (PyGWalker drag-and-drop,
large-Excel ingestion). Fell back to the standing backlog, same as every run
since Run 9 — logged explicitly here rather than skipped silently, per this
run's instructions.

**Verification-badge coverage audit** (explicitly requested this run): read
`modules/insight_verifier.py`, `modules/ai_analyst.py`, `modules/
story_mode.py`, and `modules/report_writer.py` end to end. Found that
`ai_analyst.generate_key_insights()` has **three** independent call sites
sharing the same "quote a number straight from the data" findings shape:

| Call site | Verified since |
|---|---|
| Auto Analyst "Run Full Analysis" | Run 10 |
| AI Analyst tab "Generate Key Insights" | Run 14 |
| **`report_writer.build_report_content()`** (exported PDF/HTML) | **never** |

The third — Report Writer's exported HTML/PDF — was the only one still
unverified, and the only one whose output leaves the app as a downloadable
artifact a user might hand to someone else, making it the most consequential
gap of the three rather than a marginal one. `story_mode.py`'s Demo Mode also
renders its own duplicate insight-card HTML with no badges, but its output
never leaves the live session (no export), so it was lower priority and not
picked this run.

## 2. Feature selection

1. **Mandatory agentic-AI-analysis theme:** Report Writer fact-check badges
   (closes the gap found above).
2. **Backlog continuation:** Facet Row — the second facet dimension for the
   Manual Chart Builder, closing exactly what Run 14's own report
   recommended next ("row/column dual-axis faceting... same low-risk
   selectbox pattern"). No Atlas/JARVIS-track feature was picked this run
   (optional, not mandatory, per the routine's guardrails) — both selections
   fit the run's effort budget better as agentic-theme + backlog-burn-down.

Both logged to `.prism/routine_log.md` before any code was written.

## 3. Build (TDD: tests first, per this run's instructions)

**`feature/report-writer-verification-badges`** — `modules/report_writer.py`:
- `build_report_content()` now calls `insight_verifier.verify_findings()`
  over the generated findings and attaches the result as
  `findings_verification` (returns `None`, not `[]`, when there's nothing to
  verify — findings empty or `insight_verifier` itself errors — so callers
  can distinguish "verification ran and found nothing to badge" from
  "verification never ran").
- `generate_html_report()`: new `_findings_html()`/`_verification_caption()`
  helpers badge each finding `VERIFIED`/`UNCONFIRMED` via new
  `.badge`/`.badge-ok`/`.badge-warn` CSS (self-contained — the exported HTML
  has no Streamlit theme CSS loaded, unlike the in-app `modules/ui.py`
  equivalent Run 14 built), plus a one-line fact-check caption under "Key
  Findings".
- `generate_pdf_report()`: new `_build_findings_pdf_lines()` tags each
  finding with a plain-ASCII `[VERIFIED]` / `[UNCONFIRMED - verify before
  citing]` suffix — fpdf2's core Helvetica font can't render the checkmark
  glyphs the HTML badges use (`_sanitize_for_pdf` is latin-1-only), so this
  is a deliberately different but equivalent representation, not a
  downgrade of the same one.
- Both renderers degrade gracefully (no badges, no crash) when
  `findings_verification` is absent from an older/partial `report_content`
  dict — a badge is a nice-to-have annotation, never a precondition.

12 new tests in `tests/test_report_writer.py` (new file — this module had
zero tests before this run), including a synthetic fixture with one
genuinely-correct number and one fabricated one, asserting the split lands
as confirmed/flagged, plus PDF-bytes validity and HTML-badge-string checks.

**`feature/chart-builder-facet-row`** — `modules/visualization.py` +
`app.py`:
- `build_manual_chart()` and `plot_scatter()` gain an optional `facet_row`
  parameter using Plotly Express's native `facet_row`, validated the same
  way `facet` already is (unknown column → `ValueError`; self-encoding
  against x/y/color/**and now facet itself** → silently dropped).
- New `MAX_FACET_ROW_CATEGORIES = 4` (tighter than the column facet's 6,
  since the two dimensions multiply — up to 6×4=24 subplots in the worst
  case is already a lot for one chart). `_cap_facet_categories()` was
  generalized to accept a `max_categories` parameter and is now called
  independently for each dimension, so one dimension's cap doesn't starve
  the other's own frequency ranking.
- Bar's groupby-then-plot path and Line's dropna/sort subset now include
  `facet_row` in their group/subset columns so per-cell aggregates and
  filtering are correct, not just visually split.
- `app.py`: new "Facet rows by (optional)" selectbox in the Manual Chart
  Builder's dynamic encoding-channel row, alongside the existing Facet
  columns control — still selectbox-based, no drag-and-drop/custom JS
  component, same no-architecture-rewrite-risk approach Runs 13–14 used.

14 new tests in `tests/test_visualization.py` (33 → 47 standalone),
including a two-dimension frequency-capping test with an independent
fixture column, self-encoding-against-the-other-facet-dimension, and a
backward-compatibility check that omitting `facet_row` renders identically
to before.

Neither feature makes an additional Gemini call, touches secrets, or
changes architecture.

## 4. Verification

**Environment:** hit the known `_cffi_backend` sandbox gap (Runs 12–14) —
same documented fix (`pip install --force-reinstall --no-cache-dir cffi`).
Also hit a **new** environment gap: this sandbox's pre-installed Playwright
browsers at `/opt/pw-browsers` are chromium/chromium-headless-shell
**revision 1194**, but `pip install playwright` pulls the latest package
(1.62.0), which expects a newer revision and fails to launch
(`Executable doesn't exist at .../chromium_headless_shell-1234/...`). Per
this run's instruction to **not** run `playwright install`, resolved by
bisecting pip's version history for the `playwright` package whose bundled
`browsers.json` lists revision 1194 (`playwright==1.56.0`) and installing
that instead — logged in `.prism/routine_log.md` so a future run recognizes
this on sight rather than re-diagnosing it.

**Tests:**

| Stage | Result |
|---|---|
| Baseline (`main`, pre-run, after fast-forward) | 310/310 |
| `feature/report-writer-verification-badges` (standalone) | 322/322 (+12) |
| `feature/chart-builder-facet-row` (standalone) | 324/324 (+14) |
| `main` after merging both | **336/336** |

**Live verification** (Playwright, headless Chromium 1194, `streamlit run
app.py --server.headless true --server.port 8501`,
`samples/indian_startup_funding_messy.csv` — chosen because it has three
genuine categorical columns, `sector`/`funding_round`/`city`, needed to
exercise *both* facet dimensions at once with a real numeric Y-axis,
`founded_year`, unlike the sample datasets' currency-text `salary`/
`revenue`/`funding_amount` columns):

| Viewport | Theme | Coverage |
|---|---|---|
| Desktop 1440px | Dark | Landing, Overview after load, Manual Chart Builder with all 5 encoding controls populated (X=sector, Chart type=Bar, Y=founded_year, Facet columns=funding_round, Facet rows=city), the resulting faceted grid (`funding_round=Angel/Seed/Series.../Bridge` columns × `city=Chennai/Gurugram/...` rows all visible in `fig.layout.annotations`), Auto-Report Writer's graceful no-key state, and a live "Generate Report" click confirming the whole pipeline degrades cleanly (templated executive summary, "Gemini request failed" caption instead of a crash, Download PDF/HTML buttons both render) |
| Desktop 1440px | Light (Arctic) | Same facet-row chart + theme selector — contrast and glass panels consistent, no regressions |
| Mobile 390px | Dark | Landing, Overview, single-column stacked encoding controls (no clipping), built facet-row chart, Auto-Report Writer. Confirmed **zero horizontal overflow** via `document.documentElement.scrollWidth === window.innerWidth === 390` |

No `pageerror` or console errors observed in any pass; server log shows zero
tracebacks across the whole session.

**Gemini-dependent path (badge rendering) — went one step further than the
usual unit-test-only fallback:** this sandbox has no live `GEMINI_API_KEY`
(15th consecutive run) — confirmed live: clicking "Generate Report" calls
`ai_analyst.get_model()`, which (per Run 13's standing finding) returns a
non-`None`-but-unconnected client object rather than gating like the AI
Analyst tab does, so `call_gemini()` catches the resulting `AttributeError`
and the UI shows "Gemini request failed: ..." with a graceful templated
summary — no crash, `findings=[]`, `findings_verification=None`, exactly
matching `test_build_report_content_verification_is_none_when_no_findings`.
Since the actual badge rendering couldn't be triggered through the live UI,
this run additionally **generated a real report file** in-process with a
fake Gemini model returning one correct number, one fabricated number, and
one non-numeric claim — then rendered that actual `.html` file in a browser
and extracted the actual `.pdf` bytes as text:

- HTML: a green `VERIFIED` pill next to the correct finding, a red
  `UNCONFIRMED` pill next to the fabricated one, the third finding unbadged
  — see `.prism/runs/2026-08-11-run15/15_demo_html_report_verification_badges.png`
  and `16_demo_html_report_unconfirmed_badge.png`.
- PDF (extracted via `pypdf`): `"...2016.4, showing a recent cohort skew.
  [VERIFIED]"` and `"...900000 total companies tracked. [UNCONFIRMED -
  verify before citing]"`.

This is stronger evidence than the unit-test-only fallback every run since
Run 9 has used for this constraint — the exact artifact a real user would
download was inspected byte-for-byte, not just the function that builds it.
Demo files kept at `.prism/runs/2026-08-11-run15/demo_report_with_badges.
{html,pdf}`.

**Design review:** faceted-grid subplot titles at 390px are visually dense
with two dimensions active (same honest small-multiples-at-narrow-viewport
tradeoff Run 14 logged for a single facet dimension) — not a bug, no
clipping or overflow, consistent with the app's existing container-width
chart convention. Badge pill colors (`#4ade80` green / `#f87171` red on
translucent fills) meet contrast against the report's dark `#0a0e17`
background.

**Fresh-checkout / boot smoke test:** `python -c "import ast;
ast.parse(open('app.py').read())"` passed; `streamlit run app.py
--server.headless true` on merged `main` returned HTTP 200 with no
traceback; full suite re-run on `main` post-merge: 336/336 green.

**Secrets hygiene:** `.gitignore` still covers `.env` (line 2); no `.env`
file present in the sandbox (only `.env.example`); `git status` clean
before and after all commits.

## 5. Updated backlog (ranked)

1. **PyGWalker-style chart builder — remaining scope.** Encoding channels
   now cover X/Y/Color/Aggregation/Facet columns/Facet rows (Runs 13–15).
   What's left is a genuine "explore mode" that auto-suggests encodings from
   column types — the dual-axis faceting slice this run closed was the last
   concrete encoding-channel item on the list.
2. **Large Excel ingestion** — `_should_attempt_duckdb()` still excludes
   `.xlsx`/`.xls`; unaddressed since Run 14 first scoped it narrowly. No
   off-the-shelf out-of-core Excel reader is as mature as DuckDB's CSV path.
3. **Live-Gemini verification** — 15th consecutive run with no real API key
   in this sandbox; not actionable from inside a run.
4. **Light-theme dataframe/chart repaint-lag** (cosmetic, not re-attempted).
5. **Mobile+light simultaneous screenshot coverage** — the sidebar-expander
   automation gap (Runs 10, 13, 14) wasn't hit this run (this run's theme
   switch used the "App Preferences" expander successfully on desktop; mobile
   + light together still wasn't attempted, so the gap count is unchanged,
   not newly confirmed or newly fixed).
6. **Story Mode's Demo Mode insight cards** — renders its own duplicate
   insight-card HTML (not `modules/ui.build_insight_cards_html()`) with no
   fact-check badges. Found during this run's audit, not picked (its output
   never leaves the live session — no export — making it lower-value than
   Report Writer's exported artifacts). Small, well-scoped candidate for a
   future run: swap Demo Mode's inline HTML for the shared builder.

## 6. STAR-style interview bullets

**Report Writer fact-check badges:**
> "I audited every call site sharing our AI Analyst's 'quote a number from
> the data' findings function and found three, but only two had a
> fact-checking safety net — the third was the one whose output actually
> leaves the app as a downloadable PDF/HTML report a user might hand to a
> stakeholder, which made it the highest-stakes gap, not the smallest. I
> wired the existing deterministic verifier in, then proved it worked by
> generating a real report end-to-end with a fake model returning one
> correct and one fabricated number, and confirmed both the exported HTML's
> colored badge and the PDF's plain-text tag rendered correctly — not just
> that the unit tests passed, but that the actual downloadable artifact was
> right."

**Facet Row (dual-axis small multiples):**
> "Our chart builder could split a chart into a column of subplots but not
> a full grid. I added a second, independent facet dimension using Plotly's
> native `facet_row`, and specifically capped it tighter than the column
> facet — 4 versus 6 — because I realized two uncapped high-cardinality
> facets multiply into a genuinely unreadable subplot count, not just an
> additively larger one. Verified live against a real dataset with three
> categorical columns, confirming the actual row×column grid rendered with
> correct subplot titles for both dimensions simultaneously, not just that
> each dimension worked in isolation."

## 7. Recommendation for Run 16

Two options depending on available budget:
- **Small/continuation:** swap Story Mode's Demo Mode insight-card HTML for
  the shared `modules/ui.build_insight_cards_html()` builder Run 14 created
  — closes the "duplicate markup, no badges" gap found in this run's audit
  (item 6 above). Small, low-risk, no new UI surface.
- **Medium/new:** scope out the large-Excel-ingestion gap (item 2) — the
  next backlog item without an obvious drop-in library, worth a dedicated
  design pass evaluating openpyxl's read-only streaming mode against a
  reservoir-sampling strategy before committing to an approach.

Either is safer and better-evidenced than attempting the PyGWalker
"explore mode" auto-suggestion feature cold — that one would benefit from
its own dedicated design pass (what signal decides "these two columns
should be plotted this way?") rather than a same-cycle build.
