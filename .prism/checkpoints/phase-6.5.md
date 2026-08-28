# Phase 6.5 Checkpoint — Native Stack Integration, Staging, and Release Gate

- Branch: `phase-6.5-integration-staging`
- Head commit: `349943ff681869b05778060c754192eb928f755a`
- Tag: `prism-native-v0.6`
- Date: 2026-08-28

## Gate summary (PASS/FAIL)

| Gate | Status | Notes |
|---|---|---|
| Phase 5 code complete | PASS | Verified in prior session gate-by-gate; merged via PR #6. |
| Phase 6 code complete | PASS | Clean + Visualize vertical slices merged via PR #6. |
| PR #6 merged into `phase-5-ai-analyst` | PASS | Merge commit `a203eea`, CI was green pre-merge. |
| Native web production build | PASS | `npm run build:web` succeeds, no errors. |
| Native API startup (no optional providers) | PASS | Starts cleanly with `PRISM_AI_PROVIDER=deterministic`; never blocks/crashes without Ollama. |
| Native web staging deployment (live) | BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS | No Render/hosting credentials or deployment MCP tool available in this session. Configuration (`render.yaml`) is complete and additive. |
| Native API staging deployment (live) | BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS | Same as above. |
| End-to-end staging smoke test (live-hosted) | BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS | Substituted with local integrated smoke test against real `uvicorn` + real `next dev` (`apps/web/e2e-live/`), all flows A–H exercised and passing. |
| Accessibility (workspace tablist) | PASS | 0 axe-core violations with 2+ tabs open; proper `tablist`/`tab`/`tabpanel`, `aria-selected`, `aria-controls`, roving-tabindex keyboard nav (arrows/Home/End), Delete/Backspace to close. |
| Monaco offline asset path | PASS | Bundled `monaco-editor` npm package via `loader.config({ monaco })`; verified interactive with all non-localhost network blocked at the Playwright network layer. |
| CI (GitHub Actions) | PASS | Green prior to and through PR #6 merge; local full quality gate re-run green after Phase 6.5 changes (one pre-existing sandbox-only DuckDB-extension-download test failure, documented, not a real regression — see MySQL parity note below). |
| Rollback documented | PASS | See `docs/ROLLBACK.md`. |
| No paid infrastructure | PASS | `render.yaml` additions use `plan: free` only; no managed database added. |
| Legacy Streamlit service unaffected | PASS | `render.yaml`'s `prism` service definition untouched; `py_compile` + eval suite + live boot verified independently in this session. |
| Ollama reachability | BLOCKED_EXTERNAL_LOCALHOST_ISOLATION | This sandboxed environment cannot reach the user's Windows-hosted local Ollama. Deterministic fallback verified working; UI communicates unavailability; no request hangs; no public Ollama endpoint was created. |

## Full quality gate (re-run on this head)

**Python**
- `pytest tests/ apps/api -q` → 659 passed, 1 failed (`test_mysql_results_schema_nulls_order_plan_and_legacy_parity`; sandbox-only DuckDB extension-download block, not reproducible in real CI which has network access — see MySQL parity fix already merged in PR #6).
- `ruff check apps/api/src packages tools tests` → clean.
- `mypy --follow-imports=skip --allow-subclassing-any --allow-untyped-decorators --no-warn-return-any apps/api/src packages` → clean (25 source files).
- `python tools/check_boundaries.py` → passed.
- `python tools/check_secrets.py` → passed.
- `python tools/generate_typescript_contracts.py --check` → fresh, no drift.

**Frontend**
- `npm run lint` → clean.
- `npm run typecheck` → clean.
- `npm run test:web` → 4 files, 11 tests passed (includes the new Overview tab-switch persistence regression test).
- `npm run a11y:baseline` → passed.
- `npm run build:web` → Next.js production build succeeds.
- Playwright (mocked, `playwright.config.ts`) → 9/9 passed, incl. new ARIA-tablist and Monaco-offline tests.
- Playwright (live, `playwright.live.config.ts`, real `uvicorn` + real `next dev`) → 5/5 passed, incl. new Clean/Visualize round-trip integration tests.

## Real integration bug found and fixed during Phase 6.5

Overview lost its loaded dataset every time the user switched away and back to
the Overview tab (it re-rendered the "load a dataset" prompt instead of the
already-active dataset). This was only discoverable via real, non-mocked
end-to-end testing across tab switches — exactly the class of defect Phase 6.5
was scoped to find. Fixed in `overview-workspace.tsx` by restoring the active
dataset from shell state on mount/tab-switch instead of relying on local
upload-only state. Regression test added in `prism-shell.test.tsx`.

## Deployment status

Deployment configuration for the native staging services
(`prism-native-api-staging`, `prism-native-web-staging`) is complete in
`render.yaml`, additive to the existing `prism` Streamlit service. Actual
live deployment could not be performed in this session: no Render API
token, Render MCP tool, or other hosting credential is available. This is
classified `BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS`, not an implementation
defect — see `PHASE6_5_RELEASE_REPORT.md` for full detail and the explicit
Phase 7 gate reasoning.

## Rollback

See `docs/ROLLBACK.md`.
