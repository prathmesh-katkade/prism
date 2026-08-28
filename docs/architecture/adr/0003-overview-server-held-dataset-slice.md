# ADR 0003: Overview keeps datasets server-held during Phase 3

## Status

Accepted for Phase 3.

## Context

The first native analytical vertical slice needs a real upload → profile → inspect flow without
moving complete datasets into browser state or prematurely building the eventual project store.

## Decision

FastAPI owns a process-local Overview dataset store. The web app uploads a file directly to the
API and receives a dataset reference, a typed profile, and paginated row previews only. Every
profile response includes source fingerprint, dataset revision, computation parameters, service
version, and timestamp. The deterministic profiler is framework-free and does not import legacy
or UI code.

Atlas Overview actions are deterministic, profile-grounded responses. They expose evidence and
uncertainty but do not execute autonomous analysis.

## Consequences

- Large data is not parsed or held by the browser.
- Phase 3 has no durable datasets, multi-user sharing, or restart recovery; a restart requires a
  re-upload.
- A future project/session store can replace the in-memory store behind the same dataset reference
  and response contracts.
- Streamlit remains the parity reference until a later release decision removes it explicitly.
