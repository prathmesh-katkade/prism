# Current migration phase

**Phase:** 6.5 complete (native stack integrated + staging-configured); Phase 7 unlocked but
**not yet started** — only `PHASE7_BRIEF.md` (planning) exists on `phase-7-advanced-analytics`.

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
its active dataset on tab switch). Live staging deployment itself is
`BLOCKED_EXTERNAL_DEPLOYMENT_ACCESS` (no hosting credentials in-session) — see
`PHASE6_5_RELEASE_REPORT.md`. Release tag `prism-native-v0.6` exists locally at `349943f` (tag-ref
push to origin is blocked by this session's credential scope; branch pushes work).

**Phase 7** (`phase-7-advanced-analytics` branch): unlocked per the Phase 6.5 release gate, but
**no Phase 7 code has been written yet**. `PHASE7_BRIEF.md` on that branch lays out the migration
plan for the three remaining legacy modules in priority order — **7A Stats Lab** (highest
priority, smallest, deterministic — start here), **7B Forecasting**, **7C ML Lab** — plus how the
existing `packages/analytical-schemas` / `packages/atlas-interfaces` scaffolding fits in. See
`CLAUDE_SESSION_HANDOFF.md` for the exact next implementation task.

**Still forbidden until implemented and gated:** Stats, Forecasting, ML, full autonomous Atlas
orchestration, governance, desktop, and publication work. Streamlit Clean/Visualize
(`modules/cleaning.py`, `modules/visualization.py`, `modules/autocleaner.py`) remain the
parity/rollback reference. Streamlit AI Analyst, SQL Lab, Stats Lab (`modules/stats_lab.py`),
Forecasting (`modules/forecasting.py`), and ML Lab (`modules/mllab.py`) remain available as
parity/rollback references.
