# ADR 0009: Atlas memory and RAG contract

## Decision

Memory is typed, provenance-bearing, and scoped to session, project, workspace,
or global. Data evidence, project knowledge, user memory, model knowledge, and
web research remain separate classes. Users must eventually inspect, edit, and
delete memory; retrieval never upgrades unverified text to analytical evidence.

## Consequences

The first wave defines contracts only. No opaque vector store or automatic
long-term memory mutation is introduced before user-facing controls exist.
