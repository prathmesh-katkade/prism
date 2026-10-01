# PRISM Atlas first-release acceptance status

Status: **implemented and verified for the bounded local desktop workflow, including bounded specialist
model review; release acceptance remains open pending hosted-deployment verification only.**
Evidence captured 2026-10-01 through 2026-10-02 on `atlas/production-investigation-v1`, HEAD `16356d0`.
`origin/main` is unchanged at `02264f0` throughout this work; no merge, tag, or PR was created.

## Delivered workflow

The implemented path accepts a registered CSV/Excel dataset and objective, creates a validated plan,
profiles the data, runs a server-compiled read-only SQL aggregate or a supported typed statistical
procedure, and presents the result in the existing PRISM investigation view. SQL aggregation supports a
declared two-source inner join with checked keys/cardinality/dtype and reports matched/excluded row
counts. The exact recorded SQL and parameters can be inspected and opened as a SQL Lab draft; edits
remain drafts. Clarification questions persist as waiting runs, survive a store restart, and resume from
completed work after an answer. Cancellation, stale dataset revisions, profile-only mode, per-tool
disable, timeout, and interrupted tasks have explicit handling and tests.

Atlas SQL is generated from typed inputs and server-resolved registered sources; model-authored SQL is
never executed. Identifiers are schema-checked and quoted, values are bound, the SQL service enforces
read-only execution and bounded output/runtime, and external file/network access is disabled at the
engine boundary. Prompt-shaped uploaded values and SQL-shaped uploaded identifiers remain quoted data.
The declared procedures are Welch two-sample t test, one-way ANOVA, chi-square independence, and Pearson
correlation. Causal attribution, ML, forecasting, arbitrary Python, and unrestricted research remain
outside this release and are refused/unavailable.

### Deterministic computation vs. model review (new this phase)

**Deterministic service outputs remain the sole authority for every number, p-value, SQL result row, and
join accounting figure.** Nothing a model says can change `answer`, `uncertainty`, a result row, or an
evidence record. On top of that unchanged deterministic layer, Atlas now optionally adds bounded,
schema-validated model review contributions (`apps/api/src/prism_api/atlas_runtime.py`):

- **Query/Stat** interpret the just-computed deterministic result.
- **Auditor** reviews any model-origin *proposal* claims specifically (not the deterministic record)
  against the same bounded evidence set and may raise objections.
- **Atlas** attempts one additional, best-effort, non-blocking synthesis review after the run is already
  durably completed, so the deterministic answer never waits on it.

Every review call resolves the durably promoted production Ollama binding and live-verifies its exact
digest against the Ollama daemon before it is used; if that binding cannot be verified right now, review
is not attempted at all (fail closed, never a silent fallback to another tag). Each call is schema-
constrained (`REVIEW_RESPONSE_SCHEMA`) to cite only `evidence_ids` from the bounded set it was given; the
caller independently filters out any claim/objection citing an id outside that set before persisting
anything. A timeout, invalid/malformed response, ungrounded response, or unverifiable binding is recorded
as a visible `review_unavailable` message (`origin: "deterministic_service"`) — never fabricated. A
grounded contribution is persisted with `origin: "model"` and an explicit `model_binding` (`tag@digest`).
Review calls are strictly sequential (one in-flight at a time); the existing model-concurrency evidence is
the basis for keeping it that way. No role is required to speak on every run.

## Frozen acceptance matrix

Unchanged from the prior checkpoint: frozen and committed 2026-09-28 in `4300beb`, before any warm
end-to-end measurement existed. Not re-frozen here.

## Acceptance evidence

| Area | Result and retained evidence |
|---|---|
| Full Python suite (`pytest -q`, entire `tests/` tree) | `1231 passed, 7 skipped` (1238 collected); raw: `verification/final-python-full-suite.txt`. +5 over the prior checkpoint for the new specialist-review tests. |
| Specified focused gate subset (`tests/api tests/contracts tests/migration tests/overview tests/sql_lab`) | `621 passed, 7 skipped`; raw: `verification/final-python.txt`. |
| Specialist review unit tests (`tests/api/test_atlas_specialist_review.py`) | 5/5: distinct grounded contributions with a real unsupported-claim challenge, timeout, malformed response, hallucinated-evidence-reference rejection, and an unverifiable production binding all handled correctly — covered inside the full suite above. |
| Web unit | 87 passed across 16 files; raw: `verification/final-webunit.txt`. +1 for the model-origin/`review_unavailable` collaboration-view rendering test. |
| Accessibility baseline (`npm run a11y:baseline`) | Passed — a CI gate not previously run locally in this branch's checkpoints. |
| Frontend gates | `npm run lint`, `npm run typecheck`, `npm run build:web` all passed clean. |
| Python quality gates | Ruff: all checks passed. mypy: no issues in 90 source files (strict). |
| Repository gates | `check_boundaries.py`, `check_secrets.py`, `generate_typescript_contracts.py --check` all passed. |
| Live browser (SQLite history, default gate) | 15 passed, 1 skipped (the new real-model recording spec, which only runs with `PRISM_AI_PROVIDER=ollama`); raw: `verification/final-live.txt`. Overflow regression repeated 20× on both desktop and mobile projects (40/40); raw: `verification/overflow-grid-repeat20.txt`. |
| **Real MySQL integration gate** | **Now run for real**, not blocked. With explicit user approval, installed MySQL Community Server 8.4.9 via winget and ran it as a disposable standalone process (own scratch data directory, not a Windows service) bound to `127.0.0.1:3306`, mirroring `.github/workflows/ci.yml`'s `phase-4-live-e2e` job exactly (`prism_phase4`/`prism_history` databases, same seeded `sales` table). `tests/sql_lab/test_mysql_connector_parity.py` + `test_durable_registry.py` + `test_atlas_promotion.py`: **31/31 passed** against the live MySQL connector and a MySQL-backed durable history store (not SQLite, not mocked); raw: `verification/mysql-parity-gate.txt`. Full live Playwright suite with history backed by that same MySQL instance: **15/15 passed**; raw: `verification/mysql-backed-live-e2e.txt`. No production data was touched. |
| Phase 1: real isolated specialist-review investigation | `tools/verify_atlas_specialist_review.py` — real SQL and Stat investigations through the live-verified production model (`qwen3:4b-instruct-2507-q4_K_M`) against a disposable copy of the preserved backup, restarted once, with every persisted message (deterministic and model-origin alike) confirmed byte-identical before/after restart. Backup hash and promotion pointer unchanged; raw: `verification/specialist-review/specialist-review-result.json`. The real model genuinely challenged the deterministic conclusion's unsupported framing in multiple runs (e.g. "the declared evidence does not contain the actual query text or result data") — not a scripted fixture. |
| Phase 2: production-model warm performance (**supersedes the dev-model number for latency acceptance**) | `tools/benchmark_atlas_production_warm_workflow.py`: resolved and live-verified `qwen3:4b-instruct-2507-q4_K_M` before launch, pinned it for every model call (plan proposal and every review alike — confirmed via `models_used_for_plan_proposal` and `model_bindings_used_for_review`, both single-valued), with specialist review enabled throughout. 20/20 correct warm runs; p50 **11,908.52 ms**; nearest-rank p95 **14,240.97 ms**; max **14,933.41 ms** — well under the 60 s target. Cold start 2,200.54 ms (n=1, separate). 0 `review_unavailable` outcomes across all 20 runs; 59 model-origin messages persisted. GPU peaked 4,672 MiB / 97% utilization (actual `nvidia-smi` telemetry, not inferred). Backup hash and promotion pointer unchanged. Raw: `verification/production-warm/production-warm-workflow-result.json`. |
| Prior dev-model warm measurement (retained, historical, **not superseded**) | `qwen2.5:3b`, no specialist review (predates this phase): p50 762.73–9,276.23 ms across two captures on this shared desktop (GPU/model warm-state variance, documented). Raw: `verification/model-warm/`, `verification/model-warm-rerun/`. Kept as historical evidence per instruction, not representative of current production latency. |
| Model concurrency (historical, unchanged) | 1 worker 37,285.87 ms vs 2 workers 35,646.38 ms wall time; mean per-task latency rises under concurrency; GPU saturates. Parallel dispatch remains disabled — this decision is unchanged and was not re-litigated this phase. Raw: `verification/model-concurrency-result.json`. |
| Real workflow recording | `apps/web/e2e-live/atlas-specialist-review-workflow-live.spec.ts` (skipped unless `PRISM_AI_PROVIDER=ollama`): a genuine real investigation showing (1) the deterministic SQL computation, (2) a real persisted model-origin specialist contribution, (3) evidence inspection, (4) the exact-query SQL Lab handoff. Screenshots `verification/specialist-review-0{1..4}-*.png`, recording `verification/specialist-review-workflow.webm`. This recording used the scratch dev database's unpromoted fallback model (`qwen2.5:3b`; that database has no promotion pointer); the production-pointer-verified `qwen3:4b-instruct-2507-q4_K_M` binding is what Phase 1/2's tools above actually exercise. |
| Local startup and restart | Explicit absolute SQLite history URL + disposable backup copy + (for the two tools above) the live-verified production-model binding + durable investigation records across a real process restart + unchanged copied promotion history — all proven by `tools/verify_atlas_disposable_startup.py` (waiting/resumption specifically) and `tools/verify_atlas_specialist_review.py` (production-model binding specifically) in combination; both launch a genuine second `uvicorn` process, not just store construction. UI/API connection is proven separately by the live Playwright suite (not within the same restart cycle as the API-level proof). |
| CI status | Checked via the GitHub REST API (no `gh`), not the browser: `GET /repos/.../actions/runs?branch=atlas/production-investigation-v1` returns `total_count: 0`. This is not a failure — `.github/workflows/ci.yml` triggers only on `push: branches: [main]` and `pull_request`; this branch has received neither, by instruction. The repo's CI is otherwise active (246 total runs across the repo; most recent `main` run: `failure`, unrelated to this branch). All CI job-equivalent commands were run locally instead, including the MySQL and accessibility-baseline jobs this checkpoint newly covers; see the rows above. |
| Production pointer | Re-confirmed unchanged and untouched this phase: `integrity_check=ok`, fast pointer `basemodel_585b7e79e9f195024a57dc9a`, rollback candidate `production_env_e77dbfc3de7584a8c502a6f8`, 2 promotion events, no deep pointer. The canonical checkout at `C:\Users\Admin\source\repos\prism` was never written to (read-only `git status` only). |

## Artifact reconciliation (this phase)

Running the full live/artifacts suite repeatedly regenerates several pre-existing, intentionally-committed
screenshots/recordings in `docs/atlas/investigation-collaboration/` and
`docs/atlas/production-investigation-v1/verification/atlas-{sql,join,stat}-*`, plus `apps/web/next-env.d.ts`
(an auto-managed Next.js file). These are a known side effect of that test design (it captures current
screenshots as evidence every time it runs), not a defect. Each time this happened, the regenerated bytes
were archived to the session scratchpad first, then the tracked files were restored to their last
intentionally-committed version via path-scoped `git checkout --`, so no incidental re-capture noise was
committed. Nothing was staged with a broad `reset`/`clean`.

## Startup, backup, and rollback boundary

Unchanged from the prior checkpoint. Backup `backups/analytical-history-20260928T065043Z.sqlite`,
SHA-256 `03bbc35cb97e84abc1a92d54a9f5fbeb3592d5b208c6d0c01d397afddfcc6afc`, confirmed unchanged after every
test run this phase, including the production-model benchmark and the real specialist-review investigation.

## Remaining acceptance blockers

- **Hosted deployment, hosted authentication/authorization, and hosted restart behavior remain
  unverified and are explicitly out of scope for this local desktop release.** This is the only
  remaining category of unverified work.
- No GitHub workflow run exists for this branch, by the repository's own CI trigger configuration
  (`push: branches: [main]` + `pull_request`) combined with the instruction not to open a PR — not a
  defect in this work. Local gate-equivalents for every CI job were run and are recorded above.
- The MySQL instance used for the real integration gate is a disposable local test instance (installed
  with explicit approval), not the supported hosted managed database; hosted MySQL/managed-database
  behavior is still unverified, consistent with the hosted-deployment blocker above.

The raw verification output is retained under `verification/`. No GitHub CLI, PR creation, merge, or tag
was used. The feature branch is pushed; create/pull link:
<https://github.com/prathmesh-katkade/prism/pull/new/atlas/production-investigation-v1>.
