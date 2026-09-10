# Runbook: certify Qwen3-4B-Instruct-2507 as a VERIFIED_BASE_MODEL candidate

This is an execution runbook for the physical Windows/GTX 1650 machine, not a
report of anything already done. Nothing in this file has been run by any
cloud session -- there is no GPU, no Ollama daemon, and no Soup runtime
reachable from the cloud sandbox that authored `atlas_base_model_trust.py`,
`atlas_bench_policy.py`, and the source-neutral promotion path. Every command
below is real and calls real, tested server code; none of it is simulated.

Run these from the repository root, on the branch that already contains this
work (`phase-10-atlas-local-intelligence`), with the API server running
(`PRISM_AI_PROVIDER=ollama`) and Ollama reachable at
`PRISM_OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`).

## 0. Confirm the branch and starting state

```powershell
git fetch origin phase-10-atlas-local-intelligence
git log --oneline -3 origin/phase-10-atlas-local-intelligence
# should show this session's commit(s) adding atlas_base_model_trust.py
```

## 1. Confirm the live Ollama identity has not drifted

```powershell
ollama list
# confirm qwen3:4b-instruct-2507-q4_K_M is still present with digest
# 0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0
# (per docs/migration/PHASE10_PHYSICAL_ARENA_20260910.md). If the digest has
# changed, use the NEW live digest below instead of the historical one --
# never the other way around.
```

## 2. Register the declared identity (no verification yet)

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/atlas/base-model-candidates `
  -H "Content-Type: application/json" `
  -d '{
    "upstream_model_id": "Qwen/Qwen3-4B-Instruct-2507",
    "upstream_revision": "cdbee75f17c01a7cc42f958dc650907174af0554",
    "license": "Apache-2.0",
    "official_source": "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
    "runtime_model": "qwen3:4b-instruct-2507-q4_K_M",
    "declared_runtime_digest": "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0",
    "quantization": "Q4_K_M",
    "parameter_count": 4022468096
  }'
```

Record the returned `candidate_id` (deterministic, `basemodel_...`); it will
be identical on a re-run of this exact command.

## 3. Verify against the live daemon (server-owned, fail-closed)

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/atlas/base-model-candidates/<candidate_id>/verify
```

Expect `verification_state: "verified"`. If it instead returns `rejected`,
the `verification_failure_reason` names exactly what failed (model not
found, digest mismatch, manifest fetch failure, license, or source
mismatch) -- read it and fix the declared identity or the daemon state,
never the verification code, to make it pass.

## 4. Bind the verified candidate to its Ollama runtime

This uses the existing `atlas_candidate_runtime` binding store, which is
already source-neutral (keyed by the plain `candidate_id` string). If no
route already exists for this in your checked-out revision, bind it directly:

```python
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore

DurableAtlasCandidateRuntimeStore().bind_ollama(
    "<candidate_id>",
    "qwen3:4b-instruct-2507-q4_K_M",
    runtime_model_digest="0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0",
)
```

## 5. Run a fresh trusted candidate AtlasBench pass (V1, then V2 holdout)

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/bench/candidates/<candidate_id>/runs?corpus=atlasbench-v1"
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/bench/candidates/<candidate_id>/runs?corpus=atlasbench-v2-holdout"
```

`corpus` is a bounded, server-owned selector added after this runbook was
first written -- omitting it defaults to V1 (unchanged prior behavior).
Each is a *new* promotion-eligible run through the candidate path -- not a
relabeling of the existing Arena evidence. Set
`PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096` in the server's environment
first so this run's `evaluation_policy_id` matches the production run's.
The V2 holdout is now 80 tasks (waves 1-3) -- inside the deadline-sprint
80-100 task target for a serious independent holdout; the original ~150+
stretch goal is deferred as a future-wave improvement, not a blocker.

## 6. Run a fresh production AtlasBench pass under the same policy and corpus

If production has not already been benchmarked under the pinned-context
policy (check `GET /api/v1/atlas/bench/runs/{production_subject_id}` for a
run with a non-null `evaluation_policy_id`), run one for each corpus you
intend to compare against:

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/bench/runs?provider=ollama&corpus=atlasbench-v1"
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/bench/runs?provider=ollama&corpus=atlasbench-v2-holdout"
```

## 7. Compute the promotion decision

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/decisions?candidate_id=<candidate_id>&production_run_id=<production_run_id>&candidate_run_id=<candidate_run_id>"
```

This will fail closed with a clear 409 if the corpus, category coverage, or
evaluation-policy identity do not match exactly between the two runs -- that
is the new gate working as designed, not a bug to route around.

## 8. Run the Operational Certification Suite (reference subjects only)

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/operational-cert/reference-runs?kind=perfect"
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/operational-cert/reference-runs?kind=unsafe"
```

This exists to prove the harness's own scoring logic is correct (mirroring
`PerfectReferenceSubject`/`WorstReferenceSubject` for AtlasBench) -- it does
**not** run the actual candidate. There is no live-provider Operational
Certification subject yet; wiring one that drives real SQL/Python/RAG tool
execution against Qwen 2507 is separate, substantial future work (it needs
the physical tool-orchestration stack: `ai_analyst.py`, `atlas_research.py`,
`sql_lab.py`). Until that exists, the suite (23 scenarios as of this update)
is real and tested but not part of any promotion decision for this candidate.

## 9. Only if verdict is `promote_eligible`: the full promote / rollback / final-promote drill

Record the exact current production identity first (do not trust the
historical digest below without re-reading it live):

```powershell
curl http://127.0.0.1:8000/api/v1/atlas/promotion/current
ollama list  # cross-check the live digest for qwen3:4b-q4_K_M matches
```

Then, in order, never skipping a step:

```powershell
# 1. Promote
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/promote?decision_id=<decision_id>&reason=<reason>"
curl http://127.0.0.1:8000/api/v1/atlas/promotion/current   # verify pointer now names the Qwen candidate_id
ollama list                                                  # verify the live digest matches the candidate's

# 2. Smoke-test the new production model directly (a real generate call)
curl -X POST http://127.0.0.1:11434/api/generate -d '{"model": "qwen3:4b-instruct-2507-q4_K_M", "prompt": "2+2=", "stream": false}'

# 3. Mandatory rollback -- prove the rollback path actually works before trusting this promotion
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/rollback?reason=<reason>"
curl http://127.0.0.1:8000/api/v1/atlas/promotion/current   # verify pointer is back to the prior candidate_id
ollama list                                                  # verify the live digest is back to the historical one

# 4. Final promotion -- only after the rollback above is verified exact
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/promote?decision_id=<decision_id>&reason=<final promotion after verified rollback drill>"
curl http://127.0.0.1:8000/api/v1/atlas/promotion/current   # verify final production identity
```

Never delete the old production model (`qwen3:4b-q4_K_M`) -- keep it
available as the rollback target. Do not skip step 3: proving the rollback
path actually restores the exact prior digest is the whole point of doing
this on a real daemon rather than trusting the code by inspection alone.

## What this runbook does not cover

- The Operational Certification Suite has a real, tested harness (23
  scenarios, within the deadline-sprint 20-25 target) as of this update, but
  no live-provider subject -- see step 8. Running it against the actual
  candidate is still future work, not something this runbook can complete.
- AtlasBench V2 is now selectable through the same candidate/production
  routes (step 5/6) and has grown to 80 tasks (waves 1-3) -- within the
  deadline-sprint 80-100 task target for a serious independent holdout. It
  has still never been run against any live model. The original ~150+
  stretch goal remains a future-wave improvement, not a blocker.
- Fine-tuning Qwen3-4B-Instruct-2507 remains explicitly out of scope unless
  a genuine capability gap is found later; nothing here trains anything.
- **ATLAS First Light GUI work has not started.** Per the mission's own
  sequencing, GUI work begins only once Qwen is safely in production --
  i.e. after this entire runbook (steps 1-9) has actually been run and the
  final promotion verified. Do not start GUI work before that.
