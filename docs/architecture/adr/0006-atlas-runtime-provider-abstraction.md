# ADR 0006: Atlas runtime and provider abstraction

## Decision

Atlas uses a provider-neutral adapter behind a typed capability interface.
Providers may propose structured planning metadata but cannot call PRISM tools,
access raw data, or alter deterministic results. The deterministic provider is
always available; Ollama is an optional local capability and falls back safely.

## Consequences

The product can support several local/cloud providers later without coupling
tool execution to any vendor. A cloud provider requires an explicit raw-data
policy and remains opt-in.
