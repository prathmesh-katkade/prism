# ADR 0011: Foundry and model-promotion trust model

## Decision

Soup/Foundry is training infrastructure, not Atlas runtime. Candidate artifacts
need verified origin, licence, manifest, compatibility, safe format preference,
local benchmark evidence, AtlasBench verdict, shadow evaluation, and a rollback
path before promotion. A candidate never silently replaces production Atlas.

## Consequences

The current wave defines model and benchmark contracts only; it does not download
or train a model.
