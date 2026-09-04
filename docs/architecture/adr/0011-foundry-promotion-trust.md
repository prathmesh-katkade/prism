# ADR 0011: Foundry and model-promotion trust model

## Decision

Soup/Foundry is training infrastructure, not Atlas runtime. Candidate artifacts
need verified origin, licence, manifest, compatibility, safe format preference,
local benchmark evidence, AtlasBench verdict, shadow evaluation, and a rollback
path before promotion. A candidate never silently replaces production Atlas.

## Consequences

The current wave defines model and benchmark contracts only; it does not download
or train a model.

## Update (2026-09-04, Foundry wave 10M–10Q)

This decision is now implemented, not just contracted for:

- **Foundry backend** (`atlas_foundry_backend.py`): a typed `FoundryBackend`
  abstraction with `MockFoundryBackend` and a real `SoupFoundryBackend`
  (inspected against the actual upstream Soup CLI, not assumed). Recipes
  reach Soup only through a validated `AtlasTrainingRecipe` rendered to
  YAML via a fixed, constant argv shape — never a string built from user or
  model text. `soup` has not been installed in any environment this project
  has run in; every backend method degrades to an honest "unavailable"
  result rather than a crash or a pretended success.
- **Resource-governed job lifecycle** (`atlas_foundry_orchestration.py`):
  every training job is admitted through `AtlasResourceGovernor` at
  `FOUNDRY_TRAINING` priority before the backend is touched at all; a
  preempting interactive lease hard-cancels the job. No backend implements
  graceful pause/resume, and `AtlasFoundryCapability.can_pause` is
  explicitly always `False` rather than claiming otherwise.
- **Candidate Registry**: a completed job with real adapter output on disk
  durably registers exactly one `AtlasCandidateArtifact` — the fact of what
  was produced, not a promotion-status lifecycle (that remains 10Q's job).
- **AtlasBench** (`atlas_bench_corpus.py`/`_runner.py`/`_store.py`): a
  90-task frozen, version-controlled corpus with no runtime write path (a
  candidate cannot see or influence its own judge), scored deterministically
  via a pluggable subject protocol, with durable append-only run history.
- **Shadow Brain + promotion** (`atlas_promotion.py`): `shadow_compare()`
  runs production and candidate through the identical corpus with
  structurally-enforced non-mutation; `decide_promotion()` implements
  IMPROVE TARGET CAPABILITY + NO UNACCEPTABLE CRITICAL REGRESSION against a
  fixed critical-category set; `DurableAtlasPromotionStore.promote()` is
  atomic and refuses any non-`PROMOTE_ELIGIBLE` decision at the storage
  boundary itself, and `rollback()` is a new explicit event, never an
  in-place undo -- the append-only history IS the rollback list.

Still not implemented, and not claimed as implemented: KTO (no genuine
feedback signal exists to source it from), a live-wired AtlasBench subject
(the harness is proven against reference subjects only), an actual
end-to-end Soup training run, any REST/UI surface for any of the above, and
any candidate that has actually been promoted to production (there is no
real "current production Atlas" pointer yet — nothing has been promoted).
