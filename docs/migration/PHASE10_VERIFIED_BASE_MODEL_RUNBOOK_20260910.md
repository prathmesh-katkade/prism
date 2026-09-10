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

## 5. Run a fresh trusted candidate AtlasBench V1 pass

```powershell
curl -X POST http://127.0.0.1:8000/api/v1/atlas/bench/candidates/<candidate_id>/runs
```

This is a *new* promotion-eligible run through the candidate path -- not a
relabeling of the existing Arena evidence. Set
`PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS=4096` in the server's environment
first so this run's `evaluation_policy_id` matches the production run's.

## 6. Run a fresh production AtlasBench V1 pass under the same policy

If production has not already been benchmarked under the pinned-context
policy (check `GET /api/v1/atlas/bench/runs/{production_subject_id}` for a
run with a non-null `evaluation_policy_id`), run one:

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/bench/runs?provider=ollama"
```

## 7. Compute the promotion decision

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/decisions?candidate_id=<candidate_id>&production_run_id=<production_run_id>&candidate_run_id=<candidate_run_id>"
```

This will fail closed with a clear 409 if the corpus, category coverage, or
evaluation-policy identity do not match exactly between the two runs -- that
is the new gate working as designed, not a bug to route around.

## 8. Only if verdict is `promote_eligible`: promote, smoke-test, then decide on rollback

```powershell
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/promote?decision_id=<decision_id>&reason=<reason>"
# verify: GET /api/v1/atlas/promotion/current, and `ollama ps` / a direct
# generate call against the new runtime model
curl -X POST "http://127.0.0.1:8000/api/v1/atlas/promotion/rollback?reason=<reason>"
# verify: GET /api/v1/atlas/promotion/current is back to the prior candidate_id
```

Never skip the rollback drill before a final, intentional promotion --
proving the rollback path actually restores the exact prior digest is the
whole point of doing this on a real daemon rather than trusting the code by
inspection alone.

## What this runbook does not cover

- The Operational Certification Suite (WAVE G of the mission) does not exist
  in this repository yet. Building and running it is separate future work,
  not a step this runbook can skip past.
- AtlasBench V2 wave 2 (in this same commit) has not been run against any
  model yet; step 5 above only covers V1. Run
  `POST /api/v1/atlas/bench/candidates/<candidate_id>/runs` is V1-corpus-only
  today -- extending it to V2 requires wiring the V2 corpus into the same
  candidate route, which has not been done.
- Fine-tuning Qwen3-4B-Instruct-2507 remains explicitly out of scope unless
  a genuine capability gap is found later; nothing here trains anything.
