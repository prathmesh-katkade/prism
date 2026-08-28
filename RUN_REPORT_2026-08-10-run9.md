# Prism Improvement Routine — Run Report, 2026-08-10 (Run 9)

Seventh independent same-day session of the Prism autonomous improvement
routine. Local checkout was stale (behind by 49 commits); fast-forwarded to
`origin/main`'s tip (`77e1d9d`, Run 8) before any work started, then a
docs-only commit logged this run's research and selection (`1c480b8`) —
see `.prism/routine_log.md` for the full history of all eight prior runs.
Per this cycle's "use fewer tokens" directive, this run reused Run 8's
standing research/backlog rather than re-running a full web sweep, and
shipped one feature instead of the two-feature bundles of Runs 5 and 8.

## What shipped

### Agentic Insight Orchestrator

**What it does:** Prism had grown seven independent detector modules —
Auto-Insights (skew/correlation/missingness/outliers/imbalance), Anomaly
Detection (IsolationForest ensemble), Confounder Check (Simpson's
Paradox), the Causal Effect Estimator (ATT + CATE), Drift, and Insight
Verifier — that each ran and rendered standalone, with nothing tying
their outputs together. A user staring at five separate panels had no
signal for which of a dozen findings actually mattered most, and no way
to notice when two detectors were quietly agreeing (higher confidence) or
contradicting each other's assumptions.

`modules/insight_orchestrator.py` is a pure synthesis layer over
already-computed detector output — it never re-runs detection. Given a
dict of `{detector_name: raw_detector_output}`, it:

1. **Normalizes** each detector's own finding shape (auto_insights'
   `{category, severity, column, message}` dicts, confounder_detection's
   nested scan results, causal_inference's ATT/CATE result dicts, a small
   anomaly summary, drift's column reports) into a common `Claim`.
2. **De-duplicates** by grouping claims that share the same subject
   column(s) — two detectors independently flagging the same variable
   pair collapse into one topic instead of two disconnected panel
   entries.
3. **Flags agreement** — a topic with claims from ≥2 distinct detectors
   is badged "✅ Confirmed by N detectors," a real confidence signal a
   flat list of findings can't express.
4. **Flags one specific contradiction pattern** — a causal ATT estimate
   whose outcome variable has an unaddressed confound Confounder Check
   already flagged for that variable, badged "🟠 Check this." This is
   deliberately a flag, not a hard error: the causal estimate may still
   be directionally right, it just deserves a second look.
5. **Severity-ranks** the deduplicated, cross-checked result into a top-5
   "what matters most" list (score = base severity + an agreement bonus
   per extra confirming detector + a contradiction bonus).
6. **Stays silent** — renders nothing — until at least two detectors have
   fired this session, the same "don't manufacture noise" convention as
   every detector it synthesizes.
7. **Optional cached Gemini narration** (`narrate_orchestration`) turns
   the ranked list into one stakeholder paragraph, following the exact
   `call_gemini()` / fingerprint-cached / graceful-fallback convention
   used by `auto_insights.narrate_insights` and `confounder_detection.
   narrate_confounder_finding` — no new LLM-calling pattern introduced.

Wired into `app.py`'s Overview tab as a new "🧠 Agent Summary" panel
placed above the existing Auto-Insights panel, so it reads as the agent's
top-line summary with the individual detector panels available below for
detail.

**Why it was chosen:** this cycle's required agentic-AI-analysis pick,
and a genuine multi-agent pattern (the detectors are independent
executors; this is the critic/synthesizer that cross-checks and ranks
their output) rather than another standalone detector. Directly extends
Prism's own `insight_verifier` precedent — self-verification was already
a proven pattern in this codebase, this generalizes it to cross-detector
synthesis. Addresses a real UX gap none of the 8 prior runs touched.

**Technical-depth argument:** synthesizing findings across statistically
distinct methods — a Pearson-correlation confounder check and a
propensity-score-matched causal estimate — and correctly recognizing when
they *should* be treated as evidence about the same real-world question
(and when a causal estimate's covariate set leaves a known confound on
the table) requires understanding what each method actually claims, not
just concatenating their text output. This is closer to what a senior
analyst does when reconciling five different tools' output before a
stakeholder meeting than to writing another individual detector.

## Bugs caught during build

**1. Contradiction pattern initially unreachable through the live app.**
The first version required a confounder claim's exact (x, y) subject pair
to equal a causal claim's exact (treatment, outcome) pair. This can never
happen in practice: Confounder Check only pairs *numeric* columns, while
the Causal Effect Estimator only accepts a *categorical/boolean*
treatment column — so the two pairs can never be literally identical.
The unit tests (which construct `Claim` fixtures directly) passed fine,
but live verification against `samples/stock_data.csv` showed the badge
never appeared. Generalized the check to look for any confounder claim
whose pair includes the causal claim's *outcome* column, checked against
that claim's actual covariate set — a more realistic reading of "the
causal estimate doesn't account for a confound on the same relationship"
that fires correctly on real data.

**2. Same-script-pass staleness (only visible in the live app, not unit
tests).** Agent Summary renders near the top of the Overview tab, above
the Causal Effect Estimator and Anomaly Detection panels further down.
Streamlit reruns the whole script top-to-bottom on a button click but
doesn't restart execution mid-script — so on the exact rerun where
"Estimate causal effect" or "Find Anomalies" was clicked, Agent Summary
(which executes first) rendered with the *pre-click* session state and
wouldn't reflect the new detector result until some unrelated later
interaction forced a second rerun. This class of bug is invisible to
pure-function unit tests by construction; it was only caught by actually
driving the live app with Playwright, clicking the button, and comparing
the panel's text before and after. Fixed with `st.rerun()` right after
the three affected button handlers write their result to session state —
the same idiom already used throughout `app.py` for cross-panel
reactivity, not a new pattern.

## Screenshots

- `.prism/runs/2026-08-10-run9/01_agent_summary_desktop_dark.png` — Agent
  Summary right after upload: 2 detectors (Auto-Insights + Confounder
  Check, both auto-run on upload), two "Confirmed by 2 detectors" badges
- `.prism/runs/2026-08-10-run9/02_agent_summary_with_contradiction_desktop_dark.png`
  — after running the Causal Effect Estimator with a confounding
  covariate deliberately excluded: 3 detectors, the "🟠 Check this" badge
  now in the top-5 list
- `.prism/runs/2026-08-10-run9/03_agent_summary_no_api_key_fallback_desktop_dark.png`
  — graceful "No Gemini model available for narration." fallback (no
  `GEMINI_API_KEY` in this sandbox, ninth consecutive run)
- `.prism/runs/2026-08-10-run9/04_agent_summary_desktop_light.png` —
  Arctic (Light) theme, readable contrast, badges consistent with dark
- `.prism/runs/2026-08-10-run9/05_agent_summary_mobile_dark.png` — ~390px
  PWA viewport, header wraps cleanly, no horizontal overflow

## Research findings not built (ranked backlog for future runs)

| Feature | Depth | Effort | Notes |
|---|---|---|---|
| PyGWalker-style drag-and-drop chart builder | 2 | L | Competitor-parity with Hex/Deepnote — now the longest-standing unaddressed item across 5+ runs |
| DuckDB/polars path for Auto Cleaner on large samples | 3 | M | Follow-on to Run 8's ingestion fix; still untested against a genuinely huge (500MB+) file |
| Orchestrator coverage of `insight_verifier` | 3 | S–M | Deliberately not wired in this run — its findings live in the Auto Analyst tab, a different render scope from the Overview-tab detectors synthesized here. Worth revisiting once both tabs' findings are addressable at the same point in the render pass |
| Live-Gemini screenshot verification | — | — | Ninth consecutive run with no API key in the sandbox; narration verified via unit tests + the graceful-fallback path |
| Light-theme dataframe/chart repaint-lag | 1 | S | Cosmetic/timing, three prior sessions already invested, not re-attempted |

## Interview notes (STAR-style, verbatim-usable)

> **Agentic Insight Orchestrator:**
> **Situation:** Prism had seven independent analysis modules that each
> detected real issues but rendered as disconnected panels — nothing told
> a user which finding mattered most, or that two different methods had
> independently landed on the same conclusion.
> **Task:** Build a synthesis layer that turns a pile of independent
> findings into a single ranked, cross-checked summary — without
> re-running any of the underlying (sometimes expensive) detection.
> **Action:** Normalized each detector's own output shape into a common
> claim representation, grouped claims by the variable(s) they're about
> to de-duplicate overlapping findings, flagged cases where independent
> detectors agreed (higher confidence) or where a causal estimate's
> covariate set left a confound on the table that another detector had
> already flagged (a "check this," not a hard error), and severity-ranked
> the result into a top-5 list with optional cached LLM narration.
> **Result:** Shipped with 37 passing tests (242/242 full suite) and two
> real bugs caught and fixed via live Playwright verification that the
> unit tests alone couldn't have caught — one where the contradiction
> logic was correct in isolation but unreachable through the live UI's
> actual type constraints, and one where Streamlit's single-pass script
> execution meant the summary panel could render stale state on the exact
> rerun that changed it.

## Recommendation for next run

1. **PyGWalker-style drag-and-drop chart builder** remains the
   longest-standing unaddressed backlog item — a reasonable pick if the
   cycle's theme allows UX-adjacent work, ideally paired with something
   more agentic per this cycle's priority rule.
2. **Extend the orchestrator to Insight Verifier** — once Auto Analyst's
   verified/flagged findings are addressable from the same render scope
   as the Overview-tab detectors, cross-checking "this AI-narrated
   finding was flagged as numerically unverifiable" against the
   deterministic detectors would close the loop on Prism's two
   self-verification patterns.
3. **DuckDB/polars path for Auto Cleaner** on large samples — still
   worth testing against an actually huge (500MB+) file, per Run 8's
   original recommendation, not yet acted on.

---

*Full technical detail is in `.prism/routine_log.md`'s Run 9 entry and
`.prism/research_2026-08-10-run9.md`.*
