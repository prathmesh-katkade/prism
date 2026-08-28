# Prism Autonomous Improvement Routine — Run 18 Report
**Date:** 2026-08-11

## Orientation

Read `.prism/routine_log.md` (Runs 1-17) and the tail of `CHANGELOG.md`.
Local `main` matched `origin/main` at `7dbc850` (Run 17's tip) — no
fast-forward needed this run. Confirmed via `git merge-base` after the
merge below that the resulting history is a clean fast-forward-able
descendant of `origin/main`, not a stale-branch merge (a real trap Run 15
hit and logged).

Reused the standing backlog rather than a fresh four-source-class web
research sweep — 10th consecutive run doing so, same token-efficiency
reasoning every run since Run 9 has logged, and this run's trigger
explicitly emphasized using fewer tokens. Run 17 left an exact, well-scoped
candidate in the backlog: four `narrate_*` call sites still had no
fact-check safety net. That is this run's one shipped feature.

## What shipped

### Narration fact-check completion (mandatory agentic-AI-analysis theme)

**What it does:** Runs 10/14/15/16/17 progressively extended
`insight_verifier`'s "recompute the real numbers, cross-check the LLM's
prose against them" pattern to five of the app's narration surfaces
(Auto Analyst, AI Analyst, Report Writer, Story Mode, Demo Mode, and
Hypothesis Sweep). Four `narrate_*` helpers remained uncovered:
`anomaly.narrate_anomalies()`, `anomaly.narrate_ensemble_disagreement()`,
`auto_insights.narrate_insights()`, and
`insight_orchestrator.narrate_orchestration()`. This run closes all four
in one pass:

- `modules/anomaly.py`: `anomaly_reference_numbers(flagged)` and
  `ensemble_reference_numbers(consensus, methods_summary)` pull ground
  truth straight from the DataFrame/dict each narration prompt was built
  from (flagged row count, per-reason counts, per-method flagged
  counts/percentages, full-agreement count) — no DataFrame recomputation
  needed, exact numbers.
- `modules/auto_insights.py`: `insights_reference_numbers(insights)` pulls
  every number already present in the source insight `message` strings
  (themselves deterministic, non-LLM text built by the detectors) via
  `insight_verifier.extract_numbers()`.
- `modules/insight_orchestrator.py`: `orchestration_reference_numbers(result)`
  does the same over the ranked top-list's `headline` strings.
- Each module also gets a `verify_narration()` wrapper reusing
  `insight_verifier.verify_finding()` — same `{"status": "confirmed" |
  "flagged" | "unverifiable", ...}` contract as every other verified
  surface.
- Wired into `app.py`'s three UI call sites (Anomaly Detection panel,
  Auto-Insights panel, Agent Summary panel) with the identical
  cached-verification + `ui.build_verification_caption()` pattern Runs
  15-17 established, including resetting the cached verification
  wherever the narration cache itself is reset (new upload, new
  detection run).

**Why this feature:** it's the strongest remaining candidate for this
cycle's mandatory agentic-AI-analysis theme — closing the exact gap Run
17 logged, with no new UI surface to design and a proven, low-risk
pattern to extend. Every `narrate_*` helper in the app now has a
fact-check safety net; there is no remaining uncovered narration call
site as of this run.

**Technical-depth argument:** this is the self-verifying-agent pattern a
hiring panel would specifically probe for in an "agentic EDA" candidate —
an LLM-written summary is never trusted at face value; every number it
cites is cross-checked against a real, independently computed reference
set before being shown to the user, and the check itself costs zero extra
LLM calls (deterministic, runs in milliseconds). Doing this consistently
across *every* narration surface in the app, not just the flagship one,
is the difference between a demo trick and a genuine safety net.

**Tests:** 22 new tests across `tests/test_anomaly.py`,
`tests/test_auto_insights.py`, `tests/test_insight_orchestrator.py` —
reference-number extraction (including empty/malformed-input safety),
confirmed/flagged/unverifiable status for each of the four narration
paths. Full suite: 360 → **382/382 green**.

## Verification

- **Sandbox setup:** hit and fixed the known `_cffi_backend` gap
  (`pip install --force-reinstall --no-cache-dir cffi`); installed
  `playwright==1.56.0` fresh to match the pre-installed `/opt/pw-browsers`
  chromium revision 1194 (per the note Run 15 logged; not persisted
  between sandbox instances).
- **Full suite:** 382/382 green, both before and after the merge to
  `main`.
- **Live Playwright pass:** desktop (1440px) and mobile (390px)
  viewports, `samples/indian_startup_funding_messy.csv` uploaded — **zero
  console/page errors** across all four combos. Screenshots saved to
  `.prism/runs/2026-08-11-run18/`.
- **Could not visually exercise the new badges live** (18th consecutive
  run with no `GEMINI_API_KEY` in this sandbox — confirmed again this run:
  Atlas's own HUD reports "I can't reach Gemini right now — no API key is
  configured" the moment any Gemini-backed action is attempted). Relied on
  the 22 new unit tests as the actual verification of the badge/caption
  logic, same fallback every constrained run since Run 9 has used.
- **Secrets hygiene:** `.env` confirmed present only locally and covered
  by `.gitignore`; nothing secret touched or logged this run.

## Shipped to `main`

Merged `feature/narration-fact-check-completion` into `main` with
`--no-ff`, re-ran the full suite post-merge (green), updated
`CHANGELOG.md`, pushed `main`. Verified `main`'s tip is a clean
fast-forward-able descendant of `origin/main` before pushing (see
Orientation).

## Not built (backlog, unchanged)

- **PyGWalker-style "explore mode"** (auto-suggested chart encodings) —
  now 5 runs open, still the oldest standing item.
- **Large Excel ingestion** (no out-of-core reader) — unaddressed since
  Run 14 scoped it out of the original DuckDB item.
- **Light-theme dataframe/chart repaint-lag** (cosmetic) — unaddressed.
- **Live-Gemini verification** — structural sandbox constraint, 18th
  consecutive run.
- **Mobile + light theme simultaneous screenshot coverage** (automation
  gap logged since Run 10) — not re-attempted this run (this run's changes
  are non-visual — caption text only, gated behind a live Gemini call the
  sandbox can't make — so a dedicated dark/light toggle pass wasn't the
  highest-value use of this run's Phase 5 budget; the existing app-loads
  screenshot pass at both themes/viewports found nothing broken).
- **Atlas voice/HUD JARVIS-copilot slices beyond the keyword fast path**
  (Run 17) — not attempted this run; this cycle's Atlas-track budget went
  unused since the mandatory agentic-theme feature fully absorbed this
  run's scope (single-feature cycle, per this run's explicit token-
  efficiency emphasis).

## Interview notes (STAR, verbatim-usable)

> "I noticed our AI-generated data insights had no way to catch a subtly
> wrong number — the classic 'plausible but wrong' failure mode for LLM
> summaries. I'd already built a deterministic fact-checker for one
> narration surface; this time I audited every remaining `narrate_*` call
> site in the app, found four still uncovered, and extended the same
> safety net to all of them — each pulling its own ground-truth numbers
> from data the app had already computed, so the check adds zero extra
> API calls. I wrote 22 tests covering the confirmed/flagged/unverifiable
> paths before wiring it into the UI, and the full 382-test suite stayed
> green through the merge."

## Recommendation for next run

The narration fact-check backlog is now fully closed — every angle of
"is Prism's narration pattern applied everywhere" is exhausted. Two clear
next directions: (1) the oldest standing item, PyGWalker's "explore mode"
(auto-suggested chart encodings) — a genuinely new agentic-EDA capability
rather than extending an existing pattern, good for keeping the codebase's
technical-depth story varied rather than repeating one motif; or (2) a
fresh Atlas JARVIS-copilot slice (voice input via Web Speech API is still
wholly unbuilt) — this run's Atlas-track budget went unused, so it's fair
game next run without violating the "at most one Atlas slice per run"
guardrail retroactively. Recommend PyGWalker explore mode as the primary
pick (novel technical depth > incremental extension), with an Atlas voice
slice as the secondary pick if the primary proves too large for one cycle.
