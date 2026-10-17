# Clean + Atlas presentation — Phase 3 status

Continues from `phase-2-presentation-status.md`. Source touched this phase:
`apps/web/src/components/atlas-dock-panel.tsx` (full rewrite),
`apps/web/src/components/clean-workspace.tsx` (keep both inspector tabs
mounted so switching never discards the dock's state),
`apps/web/src/components/clean-workspace.test.tsx` (3 new tests),
`apps/web/app/prism.css`. No `apps/api` source changed - see "Investigated,
not built" below for why, and what the investigation actually found.

## The minimum complete workflow, checked against what's real today

> Select data → ask Atlas → inspect supporting records → review a proposed
> change → approve through Clean → inspect the resulting revision.

This was **already substantially real** before this phase, via the
pre-existing `POST /api/v1/workspace-proposals` endpoint
(`apps/api/src/prism_api/workspace_proposals.py`) and the Phase 2 dock: ask
→ a real synchronous call to a local Ollama model if one is configured and
running (`PRISM_AI_PROVIDER=ollama`), otherwise an honest "unavailable"
response, never a fake fallback → `onReview` routes the proposed operation
through the exact same `previewOperation`/apply path manual Clean steps use
→ approval and the resulting revision are the real, unchanged Clean flow.
This phase's job was closing the specific gaps between that and the
brief's ten required-functionality points.

## Required functionality - before this phase vs. now

| # | Requirement | Before | Now |
|---|---|---|---|
| 1 | Bind conversations/tasks to the dataset revision and selected context | No conversation existed; each ask was a one-shot, stateless call | Each turn records the `revision` it was asked against. If the dataset's current revision has since moved past it (an apply happened), that turn renders with an explicit "asked about revision N; now at revision M - no longer current" note, and its "Review in Step settings" action is withheld. The conversation itself resets when a *different* dataset loads. |
| 2 | Explain why this particular change is proposed, with examples | Already real (`explanation` + `evidence` strings from the real dataset profile) | Unchanged - still real, not touched. |
| 3 | Link messages to actual source records and computed results | `clean_preview` (the real, deterministically computed preview - same engine manual operations use) was already returned by the backend but silently discarded by the Phase 2 dock | Now rendered: a distinct "PRISM computed this deterministically" block showing the real affected-row count and real exception count for that specific proposal, before the user ever leaves the dock. |
| 4 | Distinguish deterministic suggestions from model-generated proposals | Implicit only (`provider: "ollama"` vs `"unavailable"`) | Explicit: the model's own text is labelled "Atlas proposed (local model)"; the computed numbers sit in a visually separate block labelled "PRISM computed this deterministically" - never presented as if the model computed them. |
| 5 | Ask targeted questions when meaning is ambiguous | Nothing - a flat explanation with no distinction between "clean" and "needs a decision" | A real, bounded proxy: when the proposal's own computed preview has unresolved exception rows, the dock states exactly how many and asks the person to review or leave them unchanged - using real numbers already computed, not a fabricated question. **Not built**: a true interactive multi-turn clarification round-trip (the backend already has a generic `AtlasClarification` primitive for the separate Atlas *investigation* system - see "Investigated, not built"). |
| 6 | Persist conversation, decisions and resumable waiting state | Nothing persisted past a page reload | Persists for the life of the mounted component (survives switching Atlas ↔ Step settings, since both tabs now stay mounted and are only hidden, not unmounted) via `hidden` instead of conditional rendering. **Does not** survive a page reload/app restart - see "Investigated, not built". |
| 7 | Show actual task progress and cancellation | No cancel; a single boolean "busy" flag | A real `AbortController` is wired to the fetch call. Clicking Cancel while a turn is pending aborts the in-flight request (proven in a test by asserting the request's own `AbortSignal.aborted` became true, not just that a spinner disappeared) and the turn is marked "Cancelled." True multi-step progress reporting wasn't added - the request is a single bounded HTTP call (≤30s timeout), not a multi-step job, so step-by-step progress would have nothing real to report. |
| 8 | Route proposals into existing Clean/SQL/Visualize workflows, not a second execution system | Already real for Clean (`onReview` → `previewOperation`) | Unchanged - still the same real path. SQL/Visualize docked Atlas panels were not built this phase; the brief's "minimum complete workflow" names only the Clean path explicitly. |
| 9 | Preserve mutation approval and stale-revision rejection | Already real (Clean's own apply-gate and revision checks, untouched) | Unchanged, and now reinforced at the conversation level too (point 1 above) - a stale turn can't be reviewed into Step settings at all. |
| 10 | Show unavailable capabilities honestly | Already real (`"Local model proposals are unavailable; use the manual workspace controls."`, no fake fallback) | Unchanged - still real, still the only message shown when no local model is configured. |

## Investigated, not built - with the actual finding, not an assumption

The brief asks to persist conversation/decision/waiting state "using
existing infrastructure where suitable." Before writing any backend code,
I read `apps/api/src/prism_api/durable_registry.py`,
`apps/api/src/prism_api/analytical_objects.py`, and the shared
`AnalyticalObject`/`ObjectKind` schema
(`packages/analytical-schemas/python/prism_analytical_schemas/models.py`).

**Finding**: `ObjectKind.CLEANING_PLAN` already exists and is durable
(`DurableAnalyticalObjectRegistry.list_for_dataset(dataset_id, revision,
kind)` can retrieve it) - but it is already used, today, exclusively for
*applied* Clean transformations (`register_clean_transformation`, called
only after a transformation actually lands a new revision). Writing
Atlas's *unapplied* proposals into that same bucket would mix "this
happened" records with "this was suggested" records under one kind,
corrupting what every existing lineage/evidence consumer of
`CLEANING_PLAN` already assumes it means. Adding a *new* `ObjectKind`
value is a shared-schema change: it ripples through the generated
TypeScript contract (`packages/api-contracts/typescript/src/generated.ts`)
and every consumer of that enum, in both the Python and TypeScript
packages - a real, separate piece of schema work, not a same-pass
addition alongside everything else in this phase.

Separately, the full Atlas *investigation* system
(`apps/api/src/prism_api/atlas_runtime.py`, 2,134 lines) already has a much
richer, purpose-built model for exactly this - `AtlasRunResponse` with
persisted `AtlasClarification` (open/answered questions),
`AtlasSpecialistMessage` with an explicit `origin:
"deterministic_service" | "model" | "human"` field (precisely requirement
#4, already solved there), and `AtlasRunEvent` (precisely requirement #7's
progress/cancellation, already solved there) - built for the SQL/Stats/ML
investigation workspace's multi-specialist plan-and-council workflow, not
for a lightweight docked single-operation proposal. Wiring the *docked*
Clean assistant onto that full system would be the "right" long-term
answer the brief is gesturing at, but is a substantially larger integration
(a new `AtlasStepKind` for Clean operations, a new `AtlasRunRequest`
analysis variant alongside the existing `sql_analysis`/`stat_analysis`
slots, and reconciling two different "propose a change" code paths into
one) than this phase's remaining time supports doing honestly.

**Decision**: ship the smaller, real, in-session improvements above now;
name the larger persistence integration as the next real step rather than
fake it with a shim. No code was written that pretends this persists past
a reload.

## Bounded desktop extension (detachable Atlas, screen viewing)

**Not attempted this phase**, consistent with the brief's own framing
("after that workflow passes" and "only if a suitable vision path is
available and verified"). No screen-capture, second-native-window, or
vision-model integration exists anywhere in this codebase to verify or
build on - reference #4's detached-assistant concept remains a documented,
deferred direction (see Phase 1's capability table), not a partially-built
feature.

## The owner's revision on desktop automation - respected, not just noted

The brief explicitly recommends against Atlas having general
click-and-type control this release ("Explain and Guide are sufficient").
Nothing built in any phase gives Atlas, the character, or the dock panel
any ability to click, type, or otherwise act outside of the two sanctioned
paths: (a) the existing `onReview` handoff, which only ever populates the
*existing* Step-settings form for the person to review and explicitly
apply themselves, and (b) the person's own direct interaction with PRISM's
controls. There is no code path anywhere that lets a proposal apply
itself.

## Evidence

`docs/clean-atlas-v1/evidence/phase3/01-first-turn.png` and
`02-two-turns-full-page.png` - **captured against a mocked
`/api/v1/workspace-proposals` route** (Playwright `page.route`), not a live
Ollama response. This is a UI/behaviour verification screenshot - it proves
the dock renders a real `clean_preview` payload correctly, distinguishes
model text from computed numbers correctly, and threads multiple turns
correctly. It is **not** evidence of what a real local model would say for
this dataset, and is not presented as such. Real end-to-end verification
against an actual running Ollama instance was not performed this phase
(this environment has no Ollama installation to verify against) - named as
a gap, not silently assumed to work.

## Gates

lint, typecheck, `test:web` (**125 passed**, 18 files, 0 failed - 3 new
tests in `clean-workspace.test.tsx`: multi-turn persistence across tab
switches + stale-revision marking + the deterministic-vs-model distinction
in the same test; genuine request cancellation, verified via the request's
own `AbortSignal`, in a second), `build:web`, `a11y:baseline`: all clean. A
direct axe-core scan of the two-turn conversation state found and fixed one
new contrast violation (the "Review in Step settings" button had no
explicit colour, inheriting a low-contrast default) before this checkpoint
- re-scanned clean. Backend gates not rerun this phase since no `apps/api`
source changed.
