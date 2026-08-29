# Current migration phase

**Phase:** 6.5 complete, native staging LIVE and verified; Phase 7A (Stats Lab) and Phase 7B
(Forecasting) both COMPLETE and ENABLED. Phase 7C (ML Lab) not yet started.

**Enabled:** native Overview, native SQL Lab, native AI Analyst, native Clean, and native Visualize.
Clean and Visualize both operate on the same server-held `overview.store` dataset that Overview,
SQL Lab, and AI Analyst already share — a Clean transformation is a new dataset revision, visible
immediately to every other native workspace under the same `dataset_id`, with no dataset ever
mutated in place. Clean issue detection reuses Overview's own deterministic quality profile (no
recomputation), offers preview-before-apply for every transformation, and undo as a linear
revision stack. Visualize suggests a chart mark deterministically from column types and intent,
aggregates data server-side (the browser never receives raw rows), and flags trust issues
(category truncation, overplotting) as warnings rather than silently misleading. Both expose
Atlas as contextual, evidence-grounded actions — explain an issue/chart, propose a fix,
identify anomalies — never as autonomous unattended mutation.

**Phase 6.5** (`phase-6.5-integration-staging`, merged history through `ee17be4`) added: workspace
tablist ARIA fix (0 axe violations), Monaco's CDN dependency removed (bundled npm package, works
fully offline), a single typed frontend API-config boundary, a `/api/v1/platform/ready` endpoint
(config-only provider check, never a live probe), structured request logging, additive staging
deployment config (`render.yaml`: `prism-native-api-staging` / `prism-native-web-staging`, free
tier, legacy Streamlit `prism` service untouched), and a real integration bug fix (Overview losing
its active dataset on tab switch). Live staging deployment is now **CONFIRMED LIVE**: a real
authenticated Render session (2026-08-30, run directly by the user) deployed
`prism-native-api-staging` and `prism-native-web-staging` and verified every native workflow in a
real browser against the live URLs — full detail and gate flags
(`NATIVE_STAGING_COMPLETE=YES`) in the "Live staging addendum" section of
`PHASE6_5_RELEASE_REPORT.md` and `.prism/checkpoints/phase-6.5.md`. That evidence, plus a Render
Python-runtime pin (`render.yaml`), has been folded into `phase-6.5-integration-staging` (now at
`aaf5b7f`) and merged into `phase-7-advanced-analytics`. Release tag `prism-native-v0.6` exists
locally at `349943f` (tag-ref push to origin is blocked by this session's credential scope; branch
pushes work).

**Phase 7** (`phase-7-advanced-analytics` branch): **7A Stats Lab and 7B Forecasting are both
COMPLETE and `ENABLED`** — native APIs (`apps/api/src/prism_api/stats.py`,
`apps/api/src/prism_api/forecasting.py`), native workspaces
(`apps/web/src/components/stats-workspace.tsx`, `forecasting-workspace.tsx`), full
parity/accessibility/performance/Atlas gates passed for both
(`.prism/checkpoints/phase-7a.md`, `.prism/checkpoints/phase-7b.md`,
`PHASE7_IMPLEMENTATION_LEDGER.md`). **7C ML Lab** is not started. `PHASE7_BRIEF.md` on this branch
has the full migration plan and sequencing rationale. See `CLAUDE_SESSION_HANDOFF.md` for the
exact next implementation task.

**Still forbidden until implemented and gated:** ML, full autonomous Atlas orchestration,
governance, desktop, and publication work. Streamlit Clean/Visualize (`modules/cleaning.py`,
`modules/visualization.py`, `modules/autocleaner.py`) remain the parity/rollback reference.
Streamlit AI Analyst, SQL Lab, Stats Lab, Forecasting, and ML Lab (`modules/mllab.py`) remain
available as parity/rollback references.
