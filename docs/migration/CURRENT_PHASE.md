# Current migration phase

**Phase:** 6.5 complete; **Phase 7 (Stats Lab, Forecasting, ML Lab) is COMPLETE — all three
slices ENABLED**, merged into `phase-6.5-integration-staging` (PR #7, merge commit `d39b8ea`),
with a release-hardening pass on top (PR #8, merge commit `371572d` — see
`PHASE7_STAGING_RELEASE_REPORT.md`) that fixed a P0 Contextual Inspector text-clipping bug, a
P1 three-pane responsive-breakpoint collapse, a P1 nav accessible-name gap, the known
`.data-table-wrap` keyboard-focusability debt in Overview/Clean/Stats, and an ML Lab
target/feature-selection bug found by an automated review after PR #7 merged. Every navigation
workflow in the shell opens a native surface. **`371572d` is the current tip of the native
migration lineage and the exact commit a live redeploy should use** — it has not yet been
redeployed to `prism-native-api-staging`/`prism-native-web-staging` (no Render deployment access
existed in the session that did this hardening pass; see `PHASE7_STAGING_RELEASE_REPORT.md`'s
gate flags, `NATIVE_V07_DEPLOYED=NO`). Phase 8 is not started and out of scope for this session;
see `PHASE8_HANDOFF.md`.

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

**Phase 7** (`phase-7-advanced-analytics` branch, head `ec2a22a`): **7A Stats Lab, 7B
Forecasting, and 7C ML Lab are all COMPLETE and `ENABLED`** — native APIs
(`apps/api/src/prism_api/stats.py`, `forecasting.py`, `mllab.py`), native workspaces
(`apps/web/src/components/stats-workspace.tsx`, `forecasting-workspace.tsx`,
`mllab-workspace.tsx`), full parity/accessibility/performance/Atlas gates passed for all three
(`.prism/checkpoints/phase-7a.md`, `phase-7b.md`, `phase-7c.md`, `PHASE7_IMPLEMENTATION_LEDGER.md`).
See `PHASE7_FINAL_REPORT.md` for the full cross-slice summary and gate flags,
`PHASE7_STAGING_RELEASE_REPORT.md` for the staging-verification/hardening pass that followed,
and `PHASE8_HANDOFF.md` for minimal next-phase context (Phase 8 itself is not started).

**Still forbidden:** full autonomous Atlas orchestration, governance, desktop, and publication
work (none of these were in Phase 7's scope). Streamlit Clean/Visualize (`modules/cleaning.py`,
`modules/visualization.py`, `modules/autocleaner.py`) remain the parity/rollback reference.
Streamlit AI Analyst, SQL Lab, Stats Lab, Forecasting, and ML Lab (`modules/mllab.py`) remain
available as parity/rollback references.
