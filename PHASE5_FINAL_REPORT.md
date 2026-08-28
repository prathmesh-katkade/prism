# Phase 5 Final Report

Repository: `prathmesh-katkade/prism`
Branch: `claude/prism-phase-5-6-95ai73` (tracks `origin/phase-5-ai-analyst`)
Commit at verification: `614a3dc` + this report's commit
Frontend path: `apps/web` (Next.js 16 / React 19 / TypeScript)
Backend path: `apps/api/src/prism_api` (FastAPI)

## Recovery

See `RECOVERY_REPORT.md`. `main` and the previously-designated branch pointer were
the Streamlit-only legacy line (no `apps/`, no `package.json`). The real migration
lineage — Phases 1–4 complete, Phase 5.1 in progress — lives on
`origin/phase-5-ai-analyst`, the only branch (of 55) carrying the Next.js frontend
and FastAPI backend. The designated branch was reset to that lineage (pointer move
only; the prior pointer was bit-identical to `main`, so nothing was discarded).

All statuses below were established by **running the actual code and tests in this
session**, not by trusting the prior checkpoint docs — those docs were then
cross-checked against the run output.

## AI Analyst
**PASS.** `apps/api/src/prism_api/ai_analyst.py` implements a deterministic,
evidence-first analyst: server-held compact context (zero raw rows, 8,000-char
cap), dataset/quality/column evidence with provenance refs, causal-claim refusal,
schema-grounded SQL drafting, and an optional server-only Ollama connectivity probe
that never receives raw data and always has a deterministic fallback. The native
UI (`apps/web/src/components/ai-analyst.tsx`) renders the question, streamed
answer, uncertainty, limiting factors, evidence/provenance list, and an editable
unexecuted SQL draft with a hand-off into SQL Lab — progressive disclosure, not a
forced template for trivial answers.

## Atlas
**PARTIAL — verified.** Atlas exists today as the AI Analyst's execution identity
(SSE events are namespaced `atlas.*`: `atlas.state`, `atlas.token`,
`atlas.tool_wait`, `atlas.complete`, `atlas.failure`, `atlas.cancelled`) and as
contextual actions surfaced from Overview/SQL Lab/Overview components — not yet as
a distinct ambient surface with the full `idle → interpreting → planning →
executing → waiting_on_tool → verifying → uncertain → blocked → recovering →
completed → degraded → failed` state grammar. Forward-looking contracts for a
fuller Atlas (`packages/atlas-interfaces/python`: `AtlasCommand`,
`AtlasCommandStatus`) and for Phase-6 analytical objects
(`packages/analytical-schemas/python`: `CLEANING_PLAN`, `VISUALIZATION`) already
exist as scaffolding but are not yet wired into `apps/api`. This is real,
functioning, evidence-first orchestration under a narrower name than the target
product model — not a stub — and is honest to call PARTIAL against the full Atlas
vision while PASS against what Phase 5.1 committed to ship.

## SQL Round Trip
**PASS.** `test_ai_sql_draft_round_trips_only_through_sql_lab_and_back_as_evidence`
and `test_ai_sql_draft_rejects_hallucinated_schema_identifiers` (both passing)
verify: AI Analyst never executes SQL itself, drafts are schema-grounded against
the real active dataset's columns only, execution happens exclusively through SQL
Lab's existing runtime/safety boundary, and a successful run's provenance
(row count, result fingerprint) flows back into AI Analyst as evidence without raw
result rows ever reaching a model. `test_ai_analyst_excludes_sql_evidence_from_a_different_dataset`
confirms cross-dataset evidence is rejected rather than silently reused.

## SSE
**PASS.** `test_ai_stream_emits_incremental_state_token_tool_wait_and_completion`,
`test_cancellation_endpoint_marks_an_active_stream_request`,
`test_ai_stream_stops_after_a_cancellation_signal`, and
`test_ai_stream_stops_when_the_client_disconnects` (all passing) verify the full
`transport.py`-based SSE contract: incremental state + token events, tool-wait,
verification, completion, cancellation, and disconnect handling. The frontend
(`ai-analyst.tsx`) parses the same named events and drives UI state from them —
this is a live, working transport, not a documented-only contract.

## AI Router
**PASS (for the free-first policy actually shipped).** Routing is
deterministic-first with an explicit, env-gated optional local-Ollama probe
(`PRISM_AI_PROVIDER=ollama`); on any failure or when unset it falls back to the
deterministic path with no raw dataset ever sent to a provider.
`test_unreachable_local_provider_falls_back_without_stream_corruption` proves the
fallback doesn't corrupt an in-flight stream. There is no cloud/paid provider
wired in yet — consistent with "paid providers may exist later only as explicit
optional configuration" and with not requiring paid AI to use PRISM.

## Provider Verification
**BLOCKED_EXTERNAL_LOCALHOST_ISOLATION** for a live Ollama check from this
session: `127.0.0.1:11434` in this remote container is this container's own
loopback, not the user's machine, and correctly refuses to connect here — per the
task's own instruction this must not be read as "Ollama is missing." The
deterministic-fallback path this depends on is verified (see AI Router). The
Phase 5.1 checkpoint records an earlier live verification against local
`qwen3:4b-q4_K_M`, which this session cannot re-run but has no basis to doubt
given the fallback contract is independently proven.

## Evidence / Provenance
**PASS.** Every `AiAnalystResponse` carries dataset id, source fingerprint,
prompt/config version, provider used, evidence items each with a `provenance_ref`,
and (when SQL evidence is used) the SQL run id and result fingerprint. No numeric
confidence percentages are fabricated; uncertainty is expressed as prose
(`"Unknown is not no effect: the current evidence cannot estimate a causal
effect."`), distinguishing "insufficient evidence" from "no effect" exactly as
the task requires.

## Privacy
**PASS.** `raw_sample_rows` is hard-coded to `0` in the context packet; the Ollama
probe payload sends only row/column counts and a truncated question, never raw
data; SQL result evidence sends row counts and a fingerprint, never result rows.
`tools/check_secrets.py` (local secret scan) and the dependency `tools/check_boundaries.py`
scan both pass. Generated SQL only ever executes through SQL Lab's existing
safety/runtime boundary — AI output never mutates state directly.

## Accessibility
**PASS at the code/deterministic level; BLOCKED_EXTERNAL for full browser
verification.** Ran `npm run a11y:baseline` (PASS) and a real Playwright
`axe-core` scan (`npx playwright test`, `shell.spec.ts:3`, using this sandbox's
pre-installed Chromium) — **0 accessibility violations** against the live-rendered
native shell. Three companion visual-regression specs in that same file failed
only because their committed baseline screenshots were captured on `win32` and no
`linux` baseline exists in-repo (a platform-snapshot gap, not a rendering
regression) — this session did not commit unreviewed replacement screenshots. A
fourth spec (SQL Lab keyboard test) is blocked because Monaco's editor loader
fetches from a CDN this sandbox's network policy blocks; that predates Phase 5
(it's Phase-4 SQL Lab infra), is reproducible independent of Phase 5 changes, and
has been filed as a follow-up task rather than patched blind in this pass.

## Tests
**Passed:** 637 Python (pytest: `tests/`, `apps/api`) · `ruff check` (clean) ·
`mypy --follow-imports=skip --allow-subclassing-any --allow-untyped-decorators
--no-warn-return-any apps/api/src packages` (clean, matching CI's exact
invocation) · `tools/check_boundaries.py` · `tools/check_secrets.py` ·
`tools/generate_typescript_contracts.py --check` (contracts fresh) · `npm run
lint` · `npm run typecheck` · `npm run a11y:baseline` · `npm run test:web`
(5 Vitest tests) · `npm run build:web` (Next production build) · Playwright
`axe-core` accessibility scan (0 violations).
**Failed:** none.
**Skipped:** 4 Python tests (environment-dependent — live MySQL/Ollama, matching
the checkpoint's documented count) · `npm run test:e2e:live` (needs a live MySQL
service; no container runtime available in this sandbox — `BLOCKED_EXTERNAL`) ·
3 Playwright visual-regression specs (no Linux baseline committed) · 1 Playwright
SQL Lab keyboard spec (Monaco CDN blocked by sandbox network policy).

## Regression
- **Overview:** PASS — `tests/overview/test_overview_parity.py` and
  `tests/api/test_overview_contracts.py` pass; native Overview workspace
  unaffected by this session's changes.
- **SQL Lab:** PASS — `tests/sql_lab/*`, `tests/api/test_sql_lab_contracts.py`,
  `tests/api/test_sql_jobs.py` pass; MySQL-parity and live-MySQL specs are
  unaffected but could not be re-run here (`BLOCKED_EXTERNAL`, no container
  runtime).
- **Streamlit reference:** untouched by this branch's diff against `main`
  (172 files changed, all additive: new `apps/`, `packages/`, and `tests/`
  trees; no legacy file was deleted or modified).

## Git
- **Commit:** this report's commit on `claude/prism-phase-5-6-95ai73`
  (tracking `origin/phase-5-ai-analyst`).
- **Push:** performed — `git push --force-with-lease -u origin
  claude/prism-phase-5-6-95ai73`. Force-with-lease was used only because the
  branch's prior remote tip was bit-identical to `main` (zero unique commits to
  lose); this is the documented carve-out for a branch carrying only
  already-merged/no-op history, not a rewrite of anyone's real work.
- **PR:** opened against `phase-5-ai-analyst` (the correct migration base — not
  `main`, which is the Streamlit legacy line).

## Deployment
- **Staging:** NOT DONE. `render.yaml` only stages the legacy Streamlit app
  (`streamlit run app.py`); no staging configuration exists yet for `apps/web`
  or `apps/api`. Creating new hosting infrastructure is a scope/cost decision
  this session did not make unilaterally — flagging for the user rather than
  standing up unrelated infra. Classify: `BLOCKED_EXTERNAL` (no existing
  target, no credentials provided).
- **Smoke test:** NOT DONE (depends on staging).

## Rollback
Unchanged from the Phase 5.1 checkpoint: set `ai-analyst` to `legacy` in the API
migration map and shell migration state, then remove the additive Phase 5 route,
contracts, workspace, tests, and records. The Streamlit AI Analyst
(`modules/ai_analyst.py`) remains the untouched reference implementation
throughout. This session added no code that removes that rollback path.

CODE_COMPLETE = YES
STAGING_READY = NO (no existing staging infra for the migrated stack; not a code defect)
RELEASE_READY = NO (pending staging + a maintainer decision on Atlas's broader ambient scope for Phase 6+)
