# Prism Autonomous Improvement Routine — Run 16 (2026-08-11)

## Scope note

This run's trigger asked for the routine to loop "until the session is 100%
used" while also saying "use less tokens" — the same contradiction every run
since Run 9 has logged. Following that established precedent (and the hard
guardrail against runaway, unverified changes): ran **one** complete,
fully-verified cycle and stopped, scoped to a **single** feature rather than
two, given this run's extra emphasis on token efficiency.

## What shipped

### Fact-check badges for Story Mode and Demo Mode

**What it does.** `ai_analyst.generate_key_insights()` is Prism's core
"quote 3–5 numbers straight from the data" Gemini call, reused across five
places in the app. Runs 10, 14, and 15 progressively wired
`modules.insight_verifier` — a static, zero-extra-Gemini-call pass that
recomputes every number Gemini claims and tags each finding
confirmed/unconfirmed — into three of those five call sites (Auto Analyst,
the AI Analyst tab, and the Report Writer's HTML/PDF export). This run
closed the other two: **Story Mode** (Atlas's voice-narrated slide deck)
and **Demo Mode** (the scripted hands-free walkthrough). Both now run the
same verification pass and show the same `✓ verified` / `⚠ unconfirmed`
badge every other insight list in the app already has. Demo Mode's summary
card list was also switched from its own hand-duplicated HTML onto
`modules.ui`'s shared `build_insight_cards_html()` builder — one less place
in the codebase re-implementing the same markup.

**Why chosen.** This cycle's mandatory theme is agentic AI analysis. A grep
across every `generate_key_insights()` call site showed exactly two of five
still had zero fact-checking — the same "plausible-but-wrong-number" risk
the prior three runs closed elsewhere, now closed everywhere that function
is used. This is the smallest, most precisely-scoped candidate available:
additive, no new UI surface, no architecture change, reuses code already
proven correct by 3 prior runs' worth of tests.

**Technical-depth argument (interview-relevant).** This is a self-checking
agentic pipeline, not a single LLM call taken on faith: every generative
claim the model makes about the data is independently re-derived from the
DataFrame and cross-checked before it reaches the user, in every surface
that claim can appear — a chat panel, a voice-narrated slide, a scripted
demo, and a downloadable PDF a user might hand to someone else. That's the
"trust but verify" pattern real production LLM systems need, applied
consistently across an entire codebase rather than bolted onto one screen.

## Verification

- **Tests:** 336 → 341/341 green, full suite, post-merge on `main`.
  5 new tests in `tests/test_story_mode.py` (previously zero coverage for
  this module) cover the shared `_generate_and_verify_insights()` helper
  directly — a wrong-number case (asserts a mix of `confirmed`/`flagged`
  statuses), an empty-findings case, `_ensure_insights()`'s populate path,
  its no-API-key path, and its skip-regeneration-when-already-cached path
  (asserting zero wasted Gemini calls).
- **Live app / screenshots:** Playwright, desktop (1440px) and mobile
  (390px), dark theme, `samples/indian_startup_funding_messy.csv`. App
  loads clean, zero console/page errors, Auto-Insights panel and the Atlas
  HUD render correctly. Screenshots in `.prism/runs/2026-08-11-run16/`.
- **Known sandbox limitation — could not screenshot the badges themselves.**
  This sandbox has no live `GEMINI_API_KEY` (16th consecutive run). Worse
  than the usual "the AI Analyst button shows a setup warning" gap: trying
  to trigger Demo Mode via Atlas's command bar showed that Atlas's
  command-routing itself needs a live Gemini call just to parse free-text
  input — it fails with a graceful "I can't reach Gemini right now" message
  before `story_mode.py` is ever reached. Confirmed that failure is
  graceful (no traceback) and relied on the unit tests as the real
  verification of the badge logic, matching the fallback strategy every
  Gemini-gated feature in this routine has used since Run 9.

## Research findings not built (standing backlog)

| Candidate | Why not this run |
|---|---|
| PyGWalker-style chart builder "explore mode" (auto-suggested encodings) | Larger, open-ended UI scope; deferred every run since first logged |
| Large Excel ingestion (no out-of-core reader) | No streaming reader available without a new dependency; higher risk than this cycle's scope |
| Light-theme dataframe/chart repaint-lag | Cosmetic, low priority vs. depth-signaling work |
| Live-Gemini end-to-end verification | Sandbox constraint, not actionable from inside a run |
| Mobile + light theme simultaneous screenshots | Automation gap (sidebar expander), logged Runs 10/13 |
| **New:** Atlas command-bar keyword fast path before the Gemini NLU call | Discovered this run; touches core command dispatch rather than being additive — candidate for a dedicated future cycle |

## Interview notes (STAR, verbatim-usable)

> "I noticed our AI-generated insights were shown to users with no way to
> tell a real number from a hallucinated one, across five different places
> in the app — a chat panel, a narrated slide deck, a scripted demo, and an
> exported PDF report. I built a lightweight verification layer that
> recomputes every numeric claim directly from the source data and tags
> each finding as confirmed or unconfirmed, with zero extra API calls, and
> rolled it out consistently across every surface that displays generative
> output — closing the last two gaps this run after three earlier passes
> covered the rest. It's backed by unit tests that assert on a deliberately
> wrong number actually getting flagged, not just the happy path."

## Recommendation for next run

The Atlas command-bar keyword-fast-path gap found this run is a strong
candidate: it would both reduce Gemini quota usage for common commands
(cuts one full API round-trip per literal command like "clean the nulls")
and — as a side effect — finally make Demo/Story Mode screenshot-testable
in this sandbox, closing a verification gap that's blocked live UI proof of
five insight-related features across the last several runs. Second choice:
resume the PyGWalker-style builder's "explore mode" (auto-suggested
encodings), the oldest open item on the backlog.
