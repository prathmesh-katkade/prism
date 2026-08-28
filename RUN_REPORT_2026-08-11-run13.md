# Prism Autonomous Improvement Routine — Run 13 Report

**Date:** 2026-08-11
**Mode:** Full-auto (research → build → verify → merge → push, no approval gate)

---

## 1. What shipped

### 1.1 Tier-2 proactive Atlas alert for lone confounder paradoxes
*Agentic-AI-analysis theme · JARVIS copilot track*

**What it does:** Atlas's side panel already speaks up unprompted when two or
more of Prism's independent detectors agree (or disagree) on a finding — that
was Run 11's work. This run adds a second, narrower trigger: a lone
*confounder paradox* (a Simpson's-paradox-style sign reversal once you
control for a third variable). Confounder detection runs automatically on
every dataset upload, silently, exactly like Auto-Insights — but unlike
Auto-Insights, nothing ever proactively announced its findings; they sat in a
collapsed panel on the Overview tab until a user happened to scroll to them.
Now, the moment a lone high-severity confounder finding is the top-ranked
result, Atlas says so — even at the plain two-detector baseline (tier 1
needs a third detector to fire first; tier 2 doesn't, because nothing else
is covering this gap).

**Why chosen:** Run 11's log explicitly flagged this as a deferred candidate
("a possible second, still-selective tier for lone high-severity ...
findings — deliberately not built this run to keep the proactive-alert
surface narrow"). It closes a real, previously-identified gap rather than
inventing new scope, extends genuine existing agentic infrastructure
(`insight_orchestrator`), and satisfies this cycle's mandatory agentic-theme
requirement without duplicating any of the 8 detector-synthesis features
shipped in Runs 9–12.

**Technical-depth argument:** This isn't a new detector — it's a policy
decision layered on an existing statistical synthesis pipeline: *which*
already-computed finding is worth interrupting the user for, and why. The
exclusion set (`_TIER2_ALREADY_SURFACED_DETECTORS`) encodes a real design
argument about avoiding redundant interruption — the kind of judgment a
data platform engineer has to make explicit and testable, not hand-wave.
Zero extra Gemini calls; fully deterministic; 7 new unit tests cover the
baseline-fires case, the tier-1-takes-priority case, the already-surfaced
exclusion, severity gating, and fingerprint-based no-refire behavior.

### 1.2 Manual Chart Builder: Color + Aggregation encoding
*Ecosystem/competitor-parity theme*

**What it does:** The existing "pick X, Y, and chart type" Manual Chart
Builder in the Visualize tab gains two new encoding channels: an optional
**Color** column (splits/groups marks — e.g. a scatter plot colored by
category, each color getting its own OLS trendline) for Histogram, Box, Bar,
Scatter, and Line charts; and, for Bar charts specifically, a choice of
**Aggregation** function (mean, sum, median, min, max) instead of always
averaging. Both controls only appear for chart types that actually support
them.

**Why chosen:** "PyGWalker-style drag-and-drop chart builder" has been the
single longest-standing item on the research backlog — flagged as the
recommended next-run focus in Runs 10, 11, and 12 (8+ runs unaddressed
going into this one). A full drag-and-drop rebuild is an L-effort item that
would mean embedding a custom JS component in Streamlit — real architectural
risk, explicitly out of scope under this routine's no-architecture-rewrites
guardrail. Per the Phase 6 failure protocol ("shrink the feature to a
smaller working slice and ship that"), this run ships the actual analytical
capability — multi-dimensional encoding, the "grammar of graphics" core
PyGWalker/Tableau are built on — as ordinary Streamlit selectboxes instead.

**Technical-depth argument:** Grammar-of-graphics encoding (mapping data
dimensions to visual channels — position, color, aggregation — independently
of chart type) is the conceptual model behind ggplot2, Vega-Lite, and
Tableau, and is exactly the kind of "I understand how visualization
composition works, not just how to call `plot()`" signal a technical
interviewer would probe for. 19 new tests (this module — `visualization.py`
— had zero dedicated test coverage before this run, despite being one of
the oldest modules in the app).

---

## 2. Verification

**Tests:** Full suite green both before merge (on the feature branch) and
after merge (on `main`, fresh checkout): **285/285 passing** (259 baseline +
26 new — 7 for the tier-2 alert, 19 for chart encoding).

**Screenshots** (Playwright, `samples/sales_data.csv`, live app):

| Viewport | Theme | Result |
|---|---|---|
| Desktop 1440px | Dark | ✅ Encoded Bar chart (region × quantity, colored by product, summed) renders correctly, Color/Aggregation row visible, no clipping |
| Desktop 1440px | Light | ✅ Same chart, Arctic (Light) theme — contrast and glass panels consistent |
| Mobile 390px (PWA width) | Dark | ✅ Single-column responsive layout, chart legend readable, no horizontal overflow |
| Mobile 390px | Light | ⚠️ Not captured — the in-app theme selector lives inside a sidebar expander that Playwright couldn't reliably scroll into view on the 390px viewport after a dataset-upload rerun. This is a testing-tool limitation, not a UI defect: the mobile layout and the light theme were each independently verified above, just not in the same screenshot. Same class of gap Run 10 logged for its own light-theme pass. |

Screenshots saved to `.prism/runs/2026-08-11-run13/`.

The tier-2 alert has no UI surface of its own beyond the existing Atlas side
panel (same convention as Runs 10 and 12's non-UI detector wiring), so it
wasn't included in the screenshot matrix — verified instead via its 7 unit
tests plus a live no-traceback smoke check loading the Overview tab with the
new wiring active. This sandbox still has no real `GEMINI_API_KEY`
configured (13th consecutive run to hit this), but the tier-2 alert makes
zero Gemini calls, so that constraint doesn't limit verification here.

**Environment note:** Hit the same `_cffi_backend` import gap Run 12 first
diagnosed (breaks `pytest` collection for every test that imports the
Gemini client chain via `cryptography`). Same fix applied:
`pip install --force-reinstall --no-cache-dir cffi`. Now logged in
`CHANGELOG.md` as well as here so it's recognized immediately as an
environment quirk, not a regression, on the next fresh sandbox.

**Fresh-checkout sanity check:** After merging to `main`, re-ran the full
suite from the merged state (not just the feature branch) — 285/285 green.

---

## 3. Research backlog (not built this run)

Reused the standing four-source-class research from Runs 9–12 (no fresh web
sweep this cycle — see the token-efficiency process note below). Carried
forward, updated:

| Item | Status |
|---|---|
| PyGWalker-style chart builder — remaining scope (draggable pills, faceting/small-multiples, auto-suggested encodings) | **Partially addressed this run** (encoding-channel gap closed); interaction-model gap still open |
| DuckDB/polars-backed Auto Cleaner path for large datasets | Unaddressed since first logged |
| Light-theme dataframe/chart repaint-lag | Cosmetic, not re-attempted |
| Live-Gemini verification | 13th consecutive run with no real API key in this sandbox — not actionable from inside a run |

---

## 4. Interview notes (STAR-style, verbatim-usable)

**Tier-2 confounder alert:**
> "I noticed our automated confounding-detection pipeline ran silently on
> every dataset upload but never proactively surfaced its findings, unlike
> our other high-severity alerting — so a genuine Simpson's-paradox-style
> reversal could go unnoticed. I added a second, narrowly-scoped proactive
> alert tier that fires specifically for that gap, with an explicit
> exclusion list to prevent it from duplicating alerts other detectors
> already produce, and covered the decision logic with unit tests for every
> branch — baseline-fires, tier-1-takes-priority, and the exclusion set
> itself."

**Chart builder encoding:**
> "Our manual chart builder only exposed X/Y/chart-type, which is one
> generation behind the grammar-of-graphics model tools like Vega-Lite and
> Tableau use. Rather than take on the risk of embedding a custom drag-and-
> drop JS component in a Streamlit app, I shipped the actual analytical
> capability — color/grouping encoding and configurable aggregation — using
> the framework's native widgets, and wrote the first dedicated test suite
> for a module that had shipped for months with zero coverage."

---

## 5. Recommendation for next run

Continue the PyGWalker-style builder's remaining scope: a faceting/small-
multiples control (row/column split, not just color) would be the next
natural encoding channel to add with the same selectbox-based approach used
here, still without taking on custom-component risk. Separately, the
DuckDB/polars-backed Auto Cleaner path remains the longest-unaddressed item
outside the visualization track and would be a reasonable target if a future
run has budget for an M/L-effort backend item instead.

---

## Process note

This run's trigger again asked for the full 8-phase loop to repeat "until
the session is 100% used" while also directing "use less tokens" / "don't
use credits" — the same contradiction Runs 10 and 12 flagged (every
additional loop iteration costs both). Consistent with those runs and with
the hard guardrails (conservative where damage is possible; no busywork for
its own sake), this run executed one complete, safely verified cycle and
stopped rather than looping against an already-thin backlog.
