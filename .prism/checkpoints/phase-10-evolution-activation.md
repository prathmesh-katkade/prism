# Phase 10 — Evolution Activation checkpoint

Date: 2026-09-04

`PHASE_10_COMPLETE = NO`
`PHASE_11_UNLOCKED = NO`

This checkpoint records the first operational activation increment built on top
of the completed 10M–10R Foundry wave. It must not be read as evidence that a
real Soup training job or model promotion has occurred.

## Implemented in this activation increment

- Live AtlasBench subject boundary (`atlas_bench_live.py`) for the real optional
  Ollama Atlas provider.
  - The subject receives only benchmark prompt + choices.
  - It never receives `correct_choice`, rationale, scoring thresholds,
    promotion policy, or another subject's result.
  - The deterministic Atlas provider deliberately refuses a general MCQ score
    because it does not expose a general inference capability; PRISM will not
    fabricate a baseline for it.
  - Configuring Ollama is not enough: the subject probes `/api/tags` and
    requires the configured model to be present before a suite can start. A
    dead daemon/missing model yields an unavailable result and no persisted
    fake 0/90 benchmark.
- Server-owned live benchmark action:
  `POST /api/v1/atlas/bench/runs?provider=ollama`.
  AtlasBench corpus, answer key, scorer, and persistence remain server-owned.
- Evolution UI now exposes `Run live AtlasBench` and renders the returned
  durable score/subject identity. Provider-unavailable errors stay explicit.
- Durable immutable promotion-decision store
  (`atlas_promotion_decisions.py`). Recomputing a comparison creates a new
  decision; prior evaluator output is never mutated.
- Server-owned promotion decision action:
  `POST /api/v1/atlas/promotion/decisions` accepts only candidate/run
  identities, loads the two immutable AtlasBench runs, requires the identical
  corpus version/hash, executes the locked `decide_promotion()` policy with no
  client-controlled regression tolerance, and durably records the result.
- Safe promote action:
  `POST /api/v1/atlas/promotion/promote` accepts a durable `decision_id` and
  reason only. The referenced candidate must exist, and
  `DurableAtlasPromotionStore.promote()` independently refuses any decision
  whose verdict is not `PROMOTE_ELIGIBLE`.
- Focused tests cover deterministic-provider refusal, server-owned live-suite
  scoring/persistence, answer-key non-exposure, immutable decision persistence,
  unknown-candidate rejection, promotion requiring a stored decision, and a
  configured-but-unreachable Ollama provider refusing to create a baseline.

## Commits in this increment

- `5705ca9` — `feat: activate AtlasBench against live Atlas provider`
- `267fb3b` — `feat: wire live AtlasBench provider route`
- `ce4dee9` — `test: cover live AtlasBench provider activation`
- `abfe860` — `feat: add live AtlasBench control to Evolution`
- `b72376e` — `test: cover Evolution live AtlasBench action`
- `659c767` — `feat: persist Atlas promotion decisions`
- `f3a85d8` — `feat: add server-owned Atlas promotion decisions`
- `1efd1fa` — `test: cover durable Atlas promotion decisions`
- `f7add33` — `fix: refuse fake AtlasBench scores when Ollama is unavailable`
- `1cffd7c` — `test: reject unreachable Ollama benchmark baselines`

## Still not operationally proven

The following require a real execution environment and are NOT claimed done:

1. A genuine production AtlasBench baseline against a reachable local Ollama
   model.
2. Installing/activating Soup in a real training environment.
3. A real `soup train` smoke run.
4. A real adapter/candidate artifact produced by that job.
5. Candidate inference through a supported provider/runtime.
6. A real production-vs-candidate Shadow Brain comparison.
7. A real promotion verdict derived from those live runs.
8. A real promotion (only if eligible) and rollback drill.

Those cannot be manufactured from test/reference subjects. A rejected first
candidate is a successful validation outcome; promoting an unworthy candidate
would be a failure.

## Exact next task

After CI for this checkpoint is green, run the new live AtlasBench action in an
environment with the user's actual Ollama runtime/model to establish a real
baseline. Then install/pin a verified Soup revision in a controlled local
training environment, build/inspect a real 10N dataset version, perform a tiny
LoRA/QLoRA smoke training job, register its adapter as a candidate, and wire the
candidate into an inference-capable benchmark subject. Only then run Shadow
Brain and `decide_promotion()`.

Do not start Phase 11.
