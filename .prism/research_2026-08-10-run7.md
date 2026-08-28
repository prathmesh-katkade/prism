# Prism Research — 2026-08-10, Run 7

Light targeted pass (sixth/seventh consecutive same-day run — the broad
four-source sweep has been done repeatedly today; this run focused on
validating one specific pick rather than re-surveying the whole landscape).

## Candidate table

| Feature | Evidence | Depth | Effort | Risk | Roadmap theme |
|---|---|---|---|---|---|
| **Causal effect estimation (propensity score matching)** | Standard fixture in applied-DS interview loops and observational-studies coursework (Card/Krueger-style natural experiments, causal inference chapters in *Causal Inference for the Brave and True*, widely cited on Kaggle "causal ML" notebooks); direct follow-on to this codebase's own Confounder/Simpson's-Paradox detector, which diagnoses confounding but stops short of correcting for it | 5 | M | Low (pure sklearn/numpy, deterministic, no new dependency) | Agentic AI analysis (this cycle's required theme) |
| polars/DuckDB large-file path | Hex/Deepnote both default to a columnar/out-of-core engine for large files; Prism's own SQL Lab already proves DuckDB works in this codebase | 4 | L | Medium (architecture-adjacent, touches the core data pipeline) | Ecosystem tech |
| PyGWalker drag-and-drop chart builder | Competitor-parity with Hex/Deepnote's visual query builders | 2 | L | Low | Competitor tools |
| Uplift modeling / heterogeneous treatment effects (CATE) | Natural extension of this run's PSM (ATT is an average; CATE asks "for whom is the effect biggest") — flagged as a *future* extension, not built this run | 5 | L | Medium (needs a second causal ML pass — meta-learners like S/T/X-learner) | Agentic AI analysis |

## Selection

**Causal Effect Estimator (Propensity Score Matching)** — picked over the
architecture-adjacent DuckDB item (still correctly deferred to its own
dedicated session per six consecutive prior runs' agreement) and the
chart-builder (lower technical depth, cosmetic-adjacent). This is the
strongest technical-depth pick available today specifically because it's
diagnostically connected to already-shipped work: Confounder Check
(Run 6) tells the user "this correlation might not be real," and this
feature answers "okay, then what IS the real effect" — the natural
two-step agentic analysis arc a senior analyst would actually walk through,
not a bolt-on. Interview-relevant because propensity score matching (vs.
naive A/B group comparison) is a standard screening question for causal
inference maturity.

## Not pursued (backlog, carried forward)

- polars/DuckDB large-file path (seven consecutive runs now — worth
  scheduling as its own dedicated run rather than deferring an eighth time).
- PyGWalker-style chart builder.
- CATE / uplift modeling (new item, natural next step after this run's ATT
  estimator — "does the effect vary by subgroup" is the next causal-
  inference question after "is there an effect at all").
- Live-Gemini screenshot verification (seventh consecutive run with no API
  key in the sandbox — `narrate_causal_effect()` verified via unit tests +
  the graceful "No Gemini model available" fallback screenshot instead,
  same documented limitation as every prior run).
