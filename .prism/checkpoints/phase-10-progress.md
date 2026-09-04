# Phase 10 Progress Checkpoint

Date: 2026-09-05

`PHASE_10_COMPLETE = NO`
`PHASE_10_IN_PROGRESS = YES`
`PHASE_11_UNLOCKED = NO`
`CONTINUATION_SAFE = YES`

## Canonical status

Phase 10 has advanced through the Atlas runtime, agents/specialists, secure
Python worker foundation, memory/RAG foundation, Researcher, Resource Governor,
Foundry/Soup abstraction, verified training-data generation, AtlasBench,
Shadow/promotion policy, Evolution UI, and the software activation path for the
first real self-improvement experiment.

PR #15 remains open against `phase-6.5-integration-staging`; do not merge it yet.

CI #171's single Foundry route failure was corrected without weakening the
TRAIN-only boundary. The route fixture now creates a real completed run whose
existing deterministic split is TRAIN; the route continues to return 409 for
validation/test-only manifests. The same change fixed immutable corpus
reindexing so an example may be retained in more than one immutable dataset
version. PR CI #172 (`33907188462`) is green at `ee0fb53`.

Activation code head before documentation-only commits:
`5ee368e8df911c65c1121be346b0f8c9ccef504f`.

PR #15 CI run #166 (`33904258400`) is fully green at that code head:

- `phase-1-python`: PASS
- `phase-1-web`: PASS
- `phase-4-live-e2e`: PASS (real MySQL 8.0 + browser-to-API)
- `legacy-regression`: PASS
- `secret-scan`: PASS

The earlier lifecycle head also passed all five jobs on run #163; the History
live-E2E root fix independently passed all five on run #152.

## Evolution activation delivered

- History live-E2E now binds to its own uploaded dataset and synchronizes on
  real API state; no timeout inflation workaround.
- Duplicate AI Analyst evidence React keys fixed.
- Live Ollama AtlasBench subject uses production provider/model configuration,
  receives benchmark prompt/choices only, and probes `/api/tags` before any
  baseline can exist.
- Configured-but-unprobed Ollama cannot create a production pointer.
- Verified model digest bootstraps the pre-Foundry production rollback anchor
  once; restart rehydrates an existing pointer.
- Candidate→Ollama runtime bindings are durable/append-only and model names are
  validated.
- Foundry API and experiment runner train on TRAIN split only; zero-TRAIN
  versions fail closed.
- Promotion requires a durable evaluator-owned `PROMOTE_ELIGIBLE` decision, a
  real candidate artifact, and a verified runtime binding; it changes Atlas's
  active Ollama model.
- Rollback verifies the target binding before pointer mutation and restores the
  previous model as a new append-only event.
- Soup activation contract currently pinned to `soup-cli==0.74.0`, Python
  3.10–3.12, with `Qwen/Qwen2.5-0.5B-Instruct` as the first trust-locked smoke
  base model.
- `tools/run_atlas_evolution_experiment.py` now performs the real production
  baseline → verified TRAIN corpus → Soup LoRA/QLoRA → candidate deploy →
  candidate AtlasBench → locked verdict → eligible-only promotion → mandatory
  rollback drill sequence and writes an inspectable JSON report.

## Physical Evolution status

The actual host was rechecked on 2026-09-05: Ollama 0.33.3 is reachable, both
Qwen3 4B local models are installed, and the NVIDIA GTX 1650 Max-Q reports
3,733 MiB free of 4,096 MiB. `soup` is not installed. The physical experiment
is therefore `BLOCKED_EXTERNAL_PHYSICAL_RUNTIME` at the Soup dependency gate;
no training, candidate, verdict, or rollback value has been fabricated.

The only accepted evidence for the first real experiment is the report produced
on the actual PRISM host by:

```text
python tools/run_atlas_evolution_experiment.py
```

Expected report location:
`.prism/runtime/evolution-experiments/experiment-*.json`.

That report must supply the real hardware snapshot, Ollama/model identity,
production baseline, training dataset counts/hash, Soup job metrics, candidate,
candidate benchmark, Shadow comparison/verdict, and promotion/rollback result.
HOLD or REJECT is valid; do not force promotion.

## Trusted Evolution wave (2026-09-05)

Real CI failures were found and root-caused, not papered over -- each is a
genuine, previously-undiscovered bug in already-implemented Phase 10 code:

- `execute()` (Atlas run execution, background thread) wrote terminal
  plan state before appending the matching terminal event, so a concurrent
  poller could observe COMPLETED/FAILED/CANCELLED before the event existed.
  Fixed by reordering all three terminal paths (event first, then state).
- `DurableAtlasRunStore.append_event()`'s optimistic-concurrency retry loop
  allowed only 3 attempts, provably too few under the real concurrent load
  its own regression test exercises. Raised to 20 with jittered backoff.
- `register_ai_evidence()` set every `EvidenceRef.evidence_id` to the
  shared `provenance_ref` instead of a per-item id, producing real
  duplicate React keys in the History workspace's Evidence Inspector. Fixed
  to `{provenance_ref}:{kind}:{index}`, unique per item.
- A separate session added `atlas_event_stream.py`, a defense-in-depth SSE
  transport guard that never closes a terminal stream until the matching
  durable event is actually observed, and wired it into the `/events` route.

**Candidate Artifact Trust Registry** (10M-3 hardening, `atlas_candidate_trust.py`):
real inspection of a candidate's adapter workspace -- recipe/base-model/
dataset cross-checks, SHA-256 per file, an allowlist of real adapter file
types, path-traversal/symlink-escape and executable-file rejection, at
least one real weight file required. Append-only verification history.
`POST /promotion/decisions` and `POST /promotion/promote` now both refuse
(409) a candidate whose latest verification is not VERIFIED, enforced
server-side. 11 regression tests, including a genuinely unverified
candidate refused at both routes and a genuinely verified one passing.

**Atlas System Seed Corpus V1** (`atlas_system_seed.py` +
`atlas_system_seed_content.py`): 125 hand-authored, reviewed SFT examples
across the seven weak areas the first real AtlasBench baseline (71/90)
showed room to improve -- causal safety (20), evidence (20), SQL (20),
statistics (22), forecasting (17), senior-DS behavior (12),
security/agentic (14). `source_kind` is always the literal `"system_seed"`,
structurally distinct from real Atlas-run history and real user
corrections -- never blended into one pool. `check_atlasbench_leakage()` is
a real 8-word-shingle overlap check against AtlasBench's actual
prompts/choices/rationale; it genuinely caught 2 accidental phrase-level
overlaps during authoring (both reworded until it reports zero findings).
`GET /training-datasets:combined-summary` reports
`system_seed_examples` / `verified_history_examples` /
`user_correction_examples` / `total_eligible` as separate counts.

Still open, not attempted: merging system-seed examples with real history
into one physical Soup-consumable TRAIN export -- `export_jsonl()`'s
current per-`AtlasTrainingExample` shape is `source_run_id`-anchored, which
seed examples don't have by construction; that merge is a design decision
for a future session, not solved here.

Full backend suite: 333 passed, 4 skipped, 0 failed (was 312 at the start of
this wave). ruff/mypy/boundaries/secret-scan/TS-contracts/frontend
typecheck+lint all clean throughout.

## Next task

On the actual PRISM host (Windows, GPU, Ollama reachable): install Soup,
re-run `python tools/run_atlas_evolution_experiment.py` using the now-larger
combined training source (once the physical merge above is resolved), and
capture real physical evidence. Only after that evidence exists: continue
local-embedding hybrid RAG V2, durable feedback signals, AtlasBench V2/Model
Arena, durable hypothesis and experiment records, and Cortex V2's truthful
data projection.

Do not start multimodal, voice, Desktop packaging, Cortex V2, Phase 10 final
certification, merge PR #15, or Phase 11 before that evidence exists.
