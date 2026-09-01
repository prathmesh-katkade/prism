# Phase 10 Handoff

**Phase 9 is complete** (durable analytical history, full Evidence Inspector
coverage, a native History workspace, safe reproduction expansion, a
lightweight append-only audit trail, and operations hardening — all on top
of Phase 8's provenance/lineage/freshness/reproducibility/Atlas foundation,
unchanged). This document points at what comes next; it implements none of
it.

## What Phase 9 leaves in place

- A durable, restart-safe analytical-object registry and dataset store
  (`DurableAnalyticalObjectRegistry`, `DurableDatasetStore`), backed by a
  configured SQL database (managed MySQL in staging, local SQLite
  otherwise), with `DatasetStore` still the sole authority for active
  revision identity and `AnalyticalObject` still fully immutable.
- One shared Evidence Inspector architecture wired through every native
  workflow (SQL Lab, Clean, AI Analyst, Visualize, Forecasting, Stats, ML
  Lab).
- A native, searchable History workspace with live-computed
  current/stale/superseded state and direct Evidence Inspector navigation.
- An append-only creation/rerun audit trail with an explicit `system`
  actor and a read-only `GET /objects/{id}/audit` route.
- Safe, non-destructive rerun for the object kinds Phase 8F already
  covered, plus current-revision Clean reapply.

## Explicitly not built in Phase 9

- **Authenticated actor/session correlation.** PRISM has no identity or
  session boundary anywhere in the product; audit events record `system`
  rather than inventing one. A Phase 10 slice could scope this
  deliberately — as a decision (does PRISM need multi-user identity at
  all, and if so what boundary) before any implementation.
- **Deterministic SQL rerun.** SQL Lab's async submit/poll execution model
  isn't safe to replay without either a synchronous execution path or a
  way to pin execution context; still explicitly unsupported, with the
  reason returned directly in the `/rerun` response.
- **Live deployment verification.** `BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS`
  throughout both Phase 8 and Phase 9 — no session in this environment has
  had Render credentials, and this session additionally found the sandbox's
  egress policy rejects outbound connections to `*.onrender.com` entirely.
  The infrastructure-as-code (`render.yaml`) is ready; the actual deploy and
  the "restart the API and prove history survives" live proof have never
  been performed.
- **RBAC / access control.** Explicitly out of scope for Phase 9 exactly as
  it was for Phase 8; never touched.

## Candidate Phase 10 directions (unscoped — pick one deliberately, do not assume)

1. **Deployment access.** Getting a session actual Render credentials (or
   equivalent) would let a future phase close the one proof every phase
   since 8 has had to report as blocked: a live restart with durable
   history surviving it, in the actual deployed environment.
2. **Identity boundary decision.** Write the ADR this needs before any
   implementation — does PRISM need multi-user identity, sessions, or
   authentication at all, and if so, what's the minimal boundary that lets
   audit events attribute to something more specific than `system`.
3. **Deterministic SQL rerun design.** A dedicated design slice for
   replaying a SQL Lab run safely — likely requires either a synchronous
   execution path for the rerun case specifically, or a way to durably pin
   and revalidate execution context (connector availability, parameters)
   before replay.
4. **Product surface beyond History.** The History workspace is
   deliberately minimal (search, kind filter, current/stale counters).
   Atlas already explains lineage/staleness/reruns (Phase 8G); a Phase 10
   slice could extend Atlas's lineage awareness to reason over durable
   cross-session history specifically, if that's judged worth the added
   complexity over what 8G already does live.

## Explicit non-goals carried forward

Nothing in Phase 10 should retroactively relax any Phase 8 or Phase 9
invariant:
- `AnalyticalObject` stays immutable; no route may mutate a persisted
  snapshot, lineage edge, or audit event.
- `DatasetStore` stays the sole authority for active revision identity and
  content; no future work should let the registry or its durable store
  reinterpret or replace that authority.
- A rerun creates a new object; it never overwrites history.
- Freshness stays computed live at read time; it is never written onto an
  object.
- No generic mutation API — only typed, purpose-built, append-only writes.
