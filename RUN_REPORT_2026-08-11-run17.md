# Prism Autonomous Improvement Routine — Run 17 (2026-08-11)

## Process notes

Same standing contradiction every run since Run 9 has logged: this run's
trigger asks to "loop until the session is 100% used" while also saying
"use less tokens" / "don't use credits." Per the hard guardrails
(conservative, no wasted spend, never leave main broken) I ran **one
complete, safely verified cycle** and stopped — consistent with every prior
run's resolution of the same conflict.

Reused Run 11's full-app audit and the standing research backlog rather
than re-running a fresh Playwright audit or four-source-class web sweep
(9th consecutive run doing so — no new UI has shipped since Run 11 that
would invalidate that audit, and the backlog items logged by Runs 14-16
were still open and current).

Orientation: local `main` was 1 commit behind `origin/main` (Run 16's tip)
— fast-forwarded before starting. Full suite green at start: 341/341
(after the standard sandbox fix, see below).

## What shipped

### 1. Hypothesis Sweep narration fact-check (mandatory agentic-AI theme)

**What it does:** Stats Lab's Hypothesis Sweep automatically runs every
statistically viable pairwise test across a dataset with Benjamini-Hochberg
FDR correction, then offers a Gemini narration of the significant findings.
That narration cites real numbers (p-values, effect sizes, significant-pair
counts) but — unlike the five `generate_key_insights()` call sites Runs
9/10/14/15/16 already verified — had zero fact-checking of its own. Added
`sweep_reference_numbers()` (reads the sweep's own already-computed
statistics as ground truth — no DataFrame recomputation needed, since
`sweep_hypotheses()` already produced every number the narration could cite)
and `verify_narration()` (reuses `insight_verifier.verify_finding()` for
the actual matching logic). The narration panel now shows the same
confirmed/unconfirmed fact-check caption every other verified insight
surface in the app already has.

**Why chosen:** this cycle's mandatory theme is agentic AI analysis
(auto-EDA, insight generation, hypothesis suggestion, anomaly narration).
Hypothesis Sweep *is* the automated hypothesis-suggestion feature — grepping
every Gemini narration call site (`narrate_sweep`, `narrate_anomalies`,
`narrate_ensemble_disagreement`, `narrate_insights`, `narrate_orchestration`)
found none of them fact-checked, a real coverage gap in the exact "extend
the badge pattern" direction five prior runs already established as the
strongest, lowest-risk agentic-theme move. Picked `narrate_sweep` specifically
because its ground-truth numbers are already fully structured and exact in
the result dict (no recomputation risk), making it the cleanest of the five
to close correctly in one cycle.

**Technical-depth argument for interview purposes:** this is a two-layer
statistical-rigor story. Layer one (already shipped, unmodified this run):
automatically generating and Benjamini-Hochberg-correcting *every* viable
pairwise hypothesis test in a dataset is the difference between "ran a
t-test" and understanding *why* naive multi-testing p-hacks itself. Layer
two (this run): even a statistically sound pipeline's plain-English summary
is only as trustworthy as its LLM narrator, so closing the loop with a
recompute-and-check verification step is the same self-verifying-agent
principle used throughout the app — extended here to a family of Gemini
call sites (prose narration over structured stats) distinct from the
"findings list" shape the badge pattern was originally built for.

**Tests:** 9 new unit tests (`tests/test_hypothesis_sweep.py`) — reference-set
construction from real sweep output, confirmed/flagged/unverifiable status
on real vs. fabricated numbers, and non-raising behavior on malformed input.

### 2. Atlas keyword fast path (Atlas copilot track, incremental slice)

**What it does:** `classify_intent_fast()` matches a small, deliberately
conservative set of always-unambiguous commands — navigate to a named tab,
start demo/story mode, next/previous (slide stepping), cancel — without a
Gemini API round-trip. Wired ahead of `classify_intent()` in
`handle_utterance()`; anything not an exact match (including the router's
own documented ambiguity between "confirm" and "execute_plan" for words
like "go"/"do it"/"start") falls through unchanged to the full Gemini
classifier.

**Why chosen:** Run 16's routine log flagged this exact gap after hitting it
live — Atlas's command bar requires a live Gemini call to route *any*
utterance, even an exact literal phrase like "start demo mode," which is
both a latency/quota cost on every command and the reason Demo/Story Mode
couldn't be screenshot-tested in three consecutive sandbox runs. This is a
genuinely incremental JARVIS-copilot slice (per the run instructions' "at
most one Atlas feature per run, built as a slice, not the whole vision") —
it doesn't touch voice, HUD styling, or proactive insights, just the
routing layer's Gemini-dependency for the cases where a full LLM
classification is provably unnecessary.

**Risk discipline:** cross-checked every fast-matched action string against
`app.py`'s `COMMAND_REGISTRY` and `atlas.py`'s own `register_command()`
calls to confirm each one dispatches to the same handler the Gemini path
would have reached (`navigate`, `demo_mode`, `start_story_mode`, `next`,
`previous`, `cancel`). Deliberately excluded "confirm"/"yes"/"go"/"do it"
from the fast path — the router's own system prompt documents these as
context-dependent between "confirm" (approving a pending destructive
cleaning action) and "execute_plan" (approving a proposed analysis), so
guessing here risked misrouting a destructive-action confirmation. That
ambiguity is exactly why a full Gemini call still handles them.

**Tests:** 19 new unit tests (`tests/test_atlas.py`) — every fast-matched
phrase, case/punctuation insensitivity, unknown-tab fallthrough, and
explicit assertions that the excluded ambiguous words return `None`
(forcing the Gemini path).

## Verification

- Full suite: 341 → **360/360 green** after both merges (no regressions).
  Hit and fixed the known `_cffi_backend` sandbox gap
  (`pip install --force-reinstall --no-cache-dir cffi`) — same documented
  fix every run since Run 12 has needed. Installed `playwright==1.56.0`
  fresh to match the pre-installed `/opt/pw-browsers` chromium revision
  1194, per Run 15's note.
- Live-launched the app and captured Playwright screenshots at desktop
  1440px and mobile 390px, dark and light: **zero console/page errors**
  across all four captures. Screenshots saved to
  `.prism/runs/2026-08-11-run17/`.
- **Could not visually exercise either new UI surface live**, same
  17th-consecutive-run sandbox constraint (no `GEMINI_API_KEY`): the
  Hypothesis Sweep verification caption only renders after a real Gemini
  narration call, and the Atlas fast path's dispatch targets (demo mode,
  story mode) themselves render UI that isn't reachable without loading a
  dataset and navigating past the landing page in this headless run. Relied
  on the 28 new unit tests (9 + 19) as the actual correctness verification,
  same fallback strategy every constrained run since Run 9 has used.
- Both feature branches (`feature/sweep-narration-verification`,
  `feature/atlas-keyword-fast-path`) built with tests first, merged to
  `main` with `--no-ff`, zero conflicts. `.env`/secrets hygiene re-checked
  (clean; `.gitignore` covers `.env`, no real `.env` file present in the
  tree). Pushed `main` to `origin`.

## Research findings not built (backlog, carried forward)

- **PyGWalker-style chart builder "explore mode"** (auto-suggested
  encodings) — unaddressed, Runs 13-16 built the manual grammar-of-graphics
  channels (Color, Aggregation, Facet row/col) this would sit on top of.
- **Large Excel ingestion** — no out-of-core reader for `.xlsx`/`.xls`
  (Run 14 scoped this out of the original DuckDB item as a distinct, narrower
  gap; still open).
- **Light-theme dataframe/chart repaint-lag** — cosmetic, low priority.
- **Live-Gemini verification of any narrated/badge feature** — structural
  sandbox constraint, 17th consecutive run affected.
- **Mobile + light theme simultaneous screenshot coverage** — a Streamlit
  sidebar-expander automation gap in headless Playwright, logged by Runs
  10/13/14, not re-attempted this run (didn't touch theming/mobile-nav
  code).
- **Remaining narration call sites without fact-checking**: `narrate_
  anomalies`, `narrate_ensemble_disagreement` (`modules/anomaly.py`),
  `narrate_insights` (`modules/auto_insights.py`), `narrate_orchestration`
  (`modules/insight_orchestrator.py`) — this run closed `narrate_sweep`
  specifically because its reference numbers are exact and pre-structured;
  the other four are the same class of gap and a reasonable next-run
  candidate, each needing its own reference-number extractor tailored to
  what it narrates (anomaly reason counts, correlation/outlier percentages,
  cross-detector claim severities respectively).

## Interview notes (STAR-style, verbatim-usable)

**Hypothesis Sweep narration fact-check:**
*"I noticed our automated hypothesis-testing pipeline's plain-English
summary — generated by an LLM — had no safeguard against the LLM misstating
a p-value or effect size it had just been given, even though the underlying
statistics were already exact. I built a lightweight verifier that extracts
every number from the generated text and checks it against the pipeline's
own computed results, badging each explanation as fact-checked or flagged
for review, closing a real 'plausible but wrong' risk without adding any
extra API calls."*

**Atlas keyword fast path:**
*"Our voice/chat copilot required a full LLM API round-trip to route even
an exact, unambiguous command like 'next slide' — costing both latency and
API quota on every single interaction. I added a keyword fast path that
short-circuits the LLM call for a carefully scoped set of context-free
commands, while explicitly keeping anything genuinely ambiguous (like a
bare 'go' that could mean two different things depending on conversation
state) routed through the full classifier — a concrete example of knowing
when a cheap heuristic is safe to substitute for a model call and when it
isn't."*

## Recommendation for next run

Continue closing the narration-verification family (`narrate_anomalies`,
`narrate_ensemble_disagreement`, `narrate_insights`, `narrate_orchestration`)
— same well-evidenced, low-risk pattern this run used for `narrate_sweep`,
each needing a purpose-built reference-number extractor. Separately, the
PyGWalker-style chart-builder "explore mode" is now the oldest unaddressed
backlog item (4 runs) and would be a good visualization-side pick to pair
with the next narration-verification slice.
