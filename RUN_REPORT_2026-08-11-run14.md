# Prism Improvement Routine — Run 14 Report (2026-08-11)

## 0. Process note (same contradiction every run since Run 9 has flagged)

This run's trigger again asked for the full 8-phase routine to repeat "until
the session is 100% used" while also directing "use less tokens" / "don't use
credits" — mutually exclusive instructions (every extra loop iteration costs
both). Consistent with Runs 9–13 and the session's own git instructions
(which take precedence over the scheduling prompt's phrasing), this run
executed **one complete, safely verified cycle** — audit reuse, 2 features,
tests, live verification, merge, push, report — and stopped rather than
looping indefinitely against an already-thin backlog.

## 1. Phase 0–1: audit reuse

Read `.prism/routine_log.md` in full (all 13 prior entries) plus Run 12 and
Run 13's `RUN_REPORT_*.md` files. Confirmed the shipped module list against
`modules/` (43 files) and `tests/` (17 files pre-run) — nothing in this run
duplicates prior work.

**Verified the standing "DuckDB/polars-backed Auto Cleaner path for large
datasets" backlog item is already closed**, per this run's explicit
instruction to check before building against it. Read `modules/data_engine.py`
in full: `_should_attempt_duckdb()`/`_duckdb_sample_csv()` (shipped Run 8)
already reservoir-samples any CSV ≥15MB down to `MAX_ROWS` (50,000 rows, or up
to `HARD_ROW_CEILING`=500,000 if the user explicitly opts into "read the whole
file") *before* the resulting DataFrame ever reaches `autocleaner.scan()` /
`build_plan()`. Read `modules/autocleaner.py` (474 lines) and
`modules/hellmode.py` (867 lines) in full to check whether Auto Cleaner itself
does something that chokes even on that capped sample — the one genuinely
quadratic operation in the module, `hellmode.suggest_fuzzy_groups()`'s
rapidfuzz clustering, is bounded by the same row cap and only runs on
categorical columns (which are themselves cardinality-gated by column-type
detection). **Conclusion: the item as originally framed is closed.** The one
real remaining gap is narrower and different — `_should_attempt_duckdb()`
explicitly excludes `.xlsx`/`.xls` (no out-of-core reader wired for openpyxl),
so a very large Excel upload still loads fully into memory before `MAX_ROWS`
truncation applies. Logged as a new, more precisely scoped backlog candidate
instead of re-building something already shipped (see §5).

No fresh full-app Playwright audit was run — Run 11 covered that two runs ago
and nothing since then would invalidate it (same reasoning Runs 12–13 used).

## 2. Phase 2–3: feature selection

**Feature 1 (mandatory agentic-AI-analysis theme): fact-check badges for
"Generate Key Insights."** Read `modules/insight_verifier.py`,
`modules/insight_orchestrator.py`, `modules/auto_insights.py`, and
`app.py`'s AI Analyst / Auto Analyst tab code to map what already has
verification coverage. Found that Run 10 wired `insight_verifier` into Auto
Analyst's "Run Full Analysis" findings (`auto_analyst.synthesize_findings`),
but the AI Analyst tab's separate "Generate Key Insights" button — a second,
independent Gemini call (`ai_analyst.generate_key_insights`, also reused by
Story Mode's narration and the Report Writer's PDF/HTML export) — renders the
exact same `insight-card` HTML pattern and quotes numbers straight from the
data, with **zero** fact-checking of its own. This is precisely the "extend
the badge pattern to a detector family that doesn't have it yet" direction
this run's prompt named as the strongest candidate, and it closes a real,
evidenced coverage gap rather than adding new UI surface.

**Feature 2 (backlog): Facet (small-multiples) encoding for the Manual Chart
Builder.** Run 13's own report explicitly recommended this as the next
encoding channel after Color + Aggregation, continuing progress on the
longest-standing backlog item (PyGWalker-style chart builder, 8+ runs
unaddressed before Run 13's first slice) without taking on the
architecturally-risky drag-and-drop rebuild explicitly ruled out of scope.
Uses Plotly Express's native `facet_col`/`facet_col_wrap` — no custom JS
component.

Both selections and the DuckDB audit finding were logged to
`.prism/routine_log.md` under "## Run 14 — 2026-08-11" **before** any code was
written, per the routine's own ground rules.

## 3. Phase 4: build

Two feature branches off `claude/adoring-meitner-xwqeom`, tests written first
in both cases:

- `feature/key-insights-verification-badges` — added
  `modules/ui.build_insight_cards_html()` and
  `modules/ui.build_verification_caption()` (pure, side-effect-free HTML/text
  builders, factored out of the badge logic that previously lived inline in
  `app.py`'s Auto Analyst panel). Wired `insight_verifier.verify_findings()`
  into the "Generate Key Insights" button handler and added
  `key_insights_verification` to session state (reset on new dataset load,
  same as `key_insights`/`key_insights_error`). The "🎬 Story Mode" button,
  which hands Auto Analyst's findings to `key_insights` for narration, now
  carries `auto_analyst_verification` along too so the two session-state
  slots stay in sync. 11 new tests in `tests/test_ui.py` (new file).
- `feature/chart-builder-facet-encoding` — added
  `MANUAL_CHART_TYPES_SUPPORTING_FACET`, `MAX_FACET_CATEGORIES` (6),
  `FACET_COL_WRAP` (3) constants and a `facet` parameter to
  `build_manual_chart()`, validated the same way `color` already is (unknown
  column raises `ValueError`; self-encoding — facet duplicating x/y/color —
  is silently dropped). A new `_cap_facet_categories()` helper filters to the
  facet column's N most frequent values before charting, since an uncapped
  high-cardinality facet would render an unreadable, slow subplot grid.
  `plot_scatter()` gained the same optional `facet` passthrough. Bar's
  existing groupby-then-plot path now includes facet in its group columns so
  per-facet aggregates are correct, not just visually split. Wired a "Facet by
  (optional)" selectbox into `app.py`'s Manual Chart Builder UI, alongside a
  refactor of the encoding-channel row to build its `st.columns()` dynamically
  (avoids a visibly empty middle column for chart types that support Color +
  Facet but not Aggregation — everything except Bar). 14 new tests in
  `tests/test_visualization.py`.

Neither feature makes any additional Gemini call, touches secrets, or changes
architecture.

## 4. Phase 5: verification

**Environment:** hit the same `_cffi_backend` sandbox gap Runs 12–13 first
diagnosed (breaks pytest collection for anything importing the Gemini client
chain via `cryptography`). Same documented fix applied:
`pip install --force-reinstall --no-cache-dir cffi`.

**Tests — full suite, both before and after each merge:**

| Stage | Result |
|---|---|
| Baseline (`main`, pre-run) | 285/285 |
| `feature/key-insights-verification-badges` (standalone) | 296/296 (+11) |
| `feature/chart-builder-facet-encoding` (standalone) | 299/299 (+14) |
| `main` after merging both | **310/310** |

**Live verification** (Playwright, headless Chromium, `streamlit run app.py
--server.headless true --server.port 8501`, `samples/sales_data.csv`):

| Viewport | Theme | Coverage |
|---|---|---|
| Desktop 1440px | Dark | AI Analyst tab (Gemini-key warning renders correctly — see below), Visualize tab, Manual Chart Builder with all 3 encoding controls visible, Facet dropdown populated and selectable, built chart (Bar, region × mean quantity, faceted by product) rendering a correct 2×3 subplot grid |
| Desktop 1440px | Light (Arctic) | Same facet chart + AI Analyst tab — contrast and glass panels consistent, no regressions |
| Mobile 390px | Dark | AI Analyst tab, Visualize tab, Manual Chart Builder (single-column stacked controls, no clipping), built facet chart (readable but visually dense with 6 subplots — see note below). Confirmed **zero horizontal overflow** via `document.documentElement.scrollWidth === window.innerWidth === 390` |
| Mobile 390px | Light | **Not captured** — same class of automation gap Runs 10 and 13 logged: the theme selector lives inside a sidebar `st.expander` that Playwright couldn't reliably reach after the mobile viewport's sidebar auto-collapses. Mobile and Light were each independently verified above, just not simultaneously. |

No `pageerror` or console errors were observed in any of the four completed
passes. Screenshots saved to `.prism/runs/2026-08-11-run14/` (18 files):
`desktop_dark_*` (7 steps of the build-a-facet-chart flow),
`desktop_facet_chart_full.png`, `desktop_light_landing.png`,
`desktop_light_ai_analyst.png`, `desktop_light_facet_chart.png`,
`mobile_dark_*` (7 steps), `mobile_facet_chart_full.png`.

**Design review:** faceted subplots use the app's existing cyan-accent Plotly
theme in dark mode and a legible teal-on-white in Arctic light mode; subplot
titles (`product=Desk Chair`, etc.) render via Plotly's own facet annotation
mechanism, consistent with Plotly's native styling elsewhere in the app. One
honest gap: **6 facet subplots at 390px width is visually dense** (subplot
titles sit close together) — this is an inherent small-multiples/narrow-
viewport tradeoff, not a bug introduced by this feature (no clipping, no
overflow, all labels legible on inspection), and matches the same
Streamlit-cannot-know-client-viewport-width constraint every other
container-width chart in the app already has. Noted here rather than silently
accepted.

**Gemini-dependent path (Feature 1's badge rendering):** this sandbox has no
live `GEMINI_API_KEY` configured — confirmed directly this run (14th
consecutive run to hit this constraint): the AI Analyst tab correctly shows
its "Add your free Gemini API key to unlock AI features" warning instead of
the "Generate Key Insights" button, meaning `ai_analyst.get_model()` does
correctly gate this call path on key presence (unlike the Atlas HUD badge,
which shows "ONLINE" without validating connectivity — a distinction Run 13
also noted). The badge-rendering logic itself (confirmed/flagged/unverifiable
→ correct HTML, caption wording, order preservation, graceful degradation
when verification is shorter than findings) is covered by all 11 new unit
tests instead — same fallback verification strategy every prior run since
Run 9 has used for this constraint.

**Fresh-checkout / boot smoke test:** `python -c "import ast; ast.parse(open('app.py').read())"`
passed; `streamlit run app.py --server.headless true` on the merged `main`
returned HTTP 200 with no traceback in the server log; full suite re-run on
`main` post-merge: 310/310 green.

**Secrets hygiene:** `.gitignore` still covers `.env` (line 2); no `.env` file
present in the sandbox; `git status` clean before and after all commits.

## 5. Updated backlog (ranked)

1. **PyGWalker-style chart builder — remaining scope.** Encoding channels now
   cover X/Y/Color/Aggregation/Facet (Run 13 + this run). What's left:
   faceting by a *second* dimension (row vs. column split, not just one
   axis), and a genuine "explore mode" that auto-suggests encodings from
   column types. Still recommend staying selectbox-based — no
   drag-and-drop/custom-component risk.
2. **Large Excel ingestion** (new, narrower successor to the now-closed
   DuckDB/Auto-Cleaner item) — `_should_attempt_duckdb()` explicitly excludes
   `.xlsx`/`.xls`; a very large Excel upload still loads fully into memory via
   openpyxl before `MAX_ROWS` truncation applies. No off-the-shelf
   out-of-core Excel reader is as mature as DuckDB's CSV path, so this needs
   its own design pass (e.g. `openpyxl`'s read-only/streaming mode with
   manual reservoir sampling) rather than a quick patch.
3. **Live-Gemini verification** — 14th consecutive run with no real API key
   in this sandbox; not actionable from inside a run, carried forward as
   informational only.
4. **Light-theme dataframe/chart repaint-lag** (cosmetic, first logged
   several runs ago, not re-attempted).
5. **Mobile+light simultaneous screenshot coverage** — the sidebar-expander-
   on-mobile Playwright automation gap has now recurred across three runs
   (10, 13, 14). If a future run touches theming/mobile nav directly, worth
   fixing the automation (e.g. explicitly expanding the sidebar via its
   toggle button before the theme selectbox) rather than re-logging the same
   gap a fourth time.

## 6. STAR-style interview bullets

**Fact-check badges for Generate Key Insights:**
> "I found that our AI Analyst tab had two separate Gemini call sites
> producing the same kind of numeric, data-quoting findings — one had a
> fact-checking safety net from an earlier project phase, the other didn't.
> Rather than bolt on a second, slightly-different verification path, I
> factored the shared card-rendering and badge logic into two pure,
> independently-testable functions and wired the existing verifier into the
> gap — closing a real 'plausible but wrong number' risk with zero additional
> API cost, and adding 11 tests to a UI module that previously had none."

**Facet encoding for the Manual Chart Builder:**
> "Our manual chart builder could split data by color but not into
> small-multiples, which is table-stakes in tools like Tableau. I added a
> Facet channel using Plotly's native faceting rather than reaching for a
> custom drag-and-drop component — avoiding architectural risk in a
> Streamlit app — and specifically capped it to the most frequent categories
> after realizing an uncapped high-cardinality column would silently render
> an unreadable subplot grid. Wrote 14 tests including one that explicitly
> verifies the capping logic keeps the *most frequent* categories, not an
> arbitrary subset."

## 7. Recommendation for Run 15

Two roughly-equal options depending on available budget:
- **Small/continuation:** row/column dual-axis faceting for the Manual Chart
  Builder — the next natural slice of item #1 above, same low-risk
  selectbox pattern this run and Run 13 both used.
- **Medium/new:** scope out the large-Excel-ingestion gap (item #2) properly
  — evaluate openpyxl's read-only streaming mode against a reservoir-sampling
  strategy before committing to an approach, since (unlike CSV/DuckDB) there
  isn't an obvious drop-in library for this.

Either is safer and better-evidenced than re-attempting the full drag-and-drop
PyGWalker rebuild, which remains out of scope per the no-architecture-rewrite
guardrail.
