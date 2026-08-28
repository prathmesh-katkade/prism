# PRISM Migration Lineage Recovery Report

Date: 2026-08-28

## Repository root
`/home/user/prism`

## Remote
`origin` → `https://github.com/prathmesh-katkade/prism`

## Investigation

`main` and the pre-existing `claude/prism-phase-5-6-95ai73` branch both pointed at
commit `6327029` ("Let SQL Lab save named database connections, including the
password") — a Streamlit-only commit. That tree contains **no** `package.json`,
`apps/`, or `next.config.*` anywhere. This matches the prior Codex report that the
checkout had no Next.js frontend, and confirms `main` is **not** the migration
branch — it is the Streamlit legacy line, still receiving parity fixes.

A scan of all 55 remote branches for `package.json` occurrences found exactly one
branch with the migrated architecture: **`origin/phase-5-ai-analyst`**. It contains:

- `apps/web/` — Next.js 15 + React + TypeScript frontend (App Router, `next.config.ts`,
  Vitest, Playwright e2e/visual suites, `prism-shell.tsx`, `overview-workspace.tsx`,
  `query-studio.tsx`, `ai-analyst.tsx`, `command-palette.tsx`)
- `apps/api/` — FastAPI backend (`prism_api/main.py`, `overview.py`, `sql_lab.py`,
  `sql_jobs.py`, `ai_analyst.py`, `migration.py`, `transport.py`)
- `apps/desktop-shell/`, `apps/legacy-streamlit/` — coexistence shells
- `packages/api-contracts/typescript/`, `packages/design-system/typescript/` — shared
  typed contracts/design tokens generated from the Python side
- `.prism/checkpoints/phase-{1,2,3,4,5}.md` and `.prism/implementation-ledger/` — an
  explicit phase-by-phase ledger with PASS/status notes
- `docs/architecture/adr/0001-0004` — ADRs for the contract-first foundation,
  transport/state boundaries, Overview, and SQL Lab
- `docs/migration/CURRENT_PHASE.md` — machine-readable phase state
- `tests/migration/`, `tests/api/`, `tests/overview/`, `tests/sql_lab/` — parity and
  contract test suites

No branch descends from `phase-5-ai-analyst` (it is a tip with no children), so it is
the newest coherent point in the migration lineage, not merely the newest commit
timestamp among unrelated branches.

The designated working branch `claude/prism-phase-5-6-95ai73` has been reset
(`git checkout -B`) to track `origin/phase-5-ai-analyst` at `614a3dc`. This is a
local branch-pointer move only — no commits were rewritten, no other branch was
force-pushed or deleted, and no uncommitted work existed on the prior pointer
(working tree was clean, 0 untracked/modified files before the reset).

## Findings

```
Repository root:      /home/user/prism
Remote:                origin -> prathmesh-katkade/prism
Correct worktree:      /home/user/prism (single worktree, no others exist)
Correct branch:        phase-5-ai-analyst (now checked out as claude/prism-phase-5-6-95ai73)
Correct commit:        614a3dc "fix: support passwordless MySQL parity"

Next.js frontend:      FOUND
Path:                  apps/web (Next.js app router, TypeScript, Vitest, Playwright)
FastAPI backend:       FOUND — apps/api/src/prism_api

Phase 1 (Foundation):              PASS  — .prism/checkpoints/phase-1.md: "Complete, pending architecture review"
Phase 2 (Native Workspace Shell):  PASS  — .prism/checkpoints/phase-2.md: "Complete, awaiting explicit review"
Phase 3 (Overview Migration):      PASS  — .prism/checkpoints/phase-3.md: "Complete, awaiting explicit review"
Phase 4 (SQL Lab Migration):       PASS  — .prism/checkpoints/phase-4.md: "PASS — READY FOR PHASE 5 locally"
Phase 5 (AI Analyst + Atlas):      PARTIAL — .prism/checkpoints/phase-5.md self-reports
                                     "PASS — code complete locally; external delivery
                                     and release gates remain unverified." Ambient
                                     Atlas-as-operating-layer product model (contextual
                                     actions, command palette integration, state grammar)
                                     is not yet distinctly implemented — "Atlas" today
                                     appears only as contextual SQL/action affordances
                                     inside AI Analyst/SQL Lab/Overview components, not
                                     as its own ambient surface. This still needs
                                     independent verification per Part B–N of the task
                                     before being trusted.
```

## Evidence

- `git ls-tree -r --name-only origin/phase-5-ai-analyst | grep package.json` → 6 hits
  (root, apps/web, apps/desktop-shell, packages/api-contracts/typescript,
  packages/design-system/typescript, and one more workspace package).
- `git diff --stat origin/main...origin/phase-5-ai-analyst` → 172 files changed,
  +13,736/−170, mostly additive (new `apps/`, `packages/`, `tests/api`,
  `tests/overview`, `tests/sql_lab`, `tests/migration`, `tools/` scripts). **Correction**
  (flagged by review, verified): this is *not* entirely additive — 19 pre-existing
  Streamlit/legacy files were also modified (`app.py`, `api/main.py`, 15 files under
  `modules/`, 3 under `eval/`), typically 1–20 line diffs. Inspecting each: the large
  majority are non-behavioral (ruff-driven formatting, lambda→`def`, exception
  chaining via `raise ... from error`, import reordering, an unnecessary f-string
  prefix removed) — `modules/ai_analyst.py`, `modules/sql_lab.py`,
  `modules/cleaning.py`, and `modules/autocleaner.py` (the Phase 5/6 parity
  references) all fall in this category, confirmed functionally identical by
  reading each diff. `modules/visualization.py` has zero diff — genuinely
  untouched. The one *substantive* change is `modules/ui.py` (+`modules/theme.py`,
  64 new lines of CSS): a real landing-hero visual redesign, unrelated to any
  Phase 5/6 parity workflow. No file was deleted (`git diff --diff-filter=D`
  is empty). "Streamlit remains the parity reference" holds for every workflow
  this migration branch's Phase 5/6 checkpoints depend on, but the earlier
  "entirely additive" / "no legacy files were deleted or modified" phrasing
  in this report and in `PHASE5_FINAL_REPORT.md` was inaccurate and has been
  corrected.
- `docs/migration/CURRENT_PHASE.md` on this branch: "Phase 5.1 — AI Analyst
  stabilization complete locally... Still forbidden: Clean, Visualize, Stats,
  Forecasting, ML, full autonomous Atlas behavior, governance, desktop, and
  publication work."

## Risks

- Phase 5's own checkpoint already flags external gates (push/PR, staging deploy,
  staging smoke test) as unverified — expected, must be re-confirmed rather than
  assumed.
- The task's Atlas product model (ambient operating layer, explicit state grammar,
  sequential orchestration) is broader than what the current Phase 5 ledger claims;
  needs direct code verification, not just trusting the checkpoint doc.
- 51 other `claude/adoring-meitner-*` / `claude/charming-bohr-*` branches exist off
  the Streamlit `main` line (feature work on the legacy app) — irrelevant to this
  migration and left untouched.
- No branches or worktrees were reset, deleted, or force-pushed. `phase-5-ai-analyst`
  on `origin` is untouched by this recovery; only the local/designated branch pointer
  moved.

## Continuation recommendation

Continue Phase 5 verification and completion directly on `phase-5-ai-analyst`
lineage (now `claude/prism-phase-5-6-95ai73`). Do not rebuild Phases 1–4. Verify
each Phase 5 status line in the task's "PHASE 5 KNOWN HISTORICAL STATUS" table
against actual code/tests before trusting it, with particular scrutiny on the Atlas
ambient product model, live SSE behavior, and local/free provider fallback.
