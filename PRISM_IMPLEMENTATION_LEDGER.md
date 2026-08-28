# PRISM implementation ledger

Running record of meaningful units of work across the migration. Newest first.
Phase-specific detail lives in `.prism/implementation-ledger/` and
`.prism/checkpoints/`; this file tracks cross-phase engineering decisions and
verification units that don't belong to a single phase checkpoint.

---

## Unit: Phase 5 lineage recovery + verification

**Objective:** Recover the true migration branch (previous environments had lost
track of it — `main` and the previously-designated branch pointed at the
Streamlit-only line with no Next.js/FastAPI code), then verify every Phase 5
status claim against real code and test runs rather than trusting prior reports.

**Files changed:**
- `RECOVERY_REPORT.md` (new) — lineage recovery evidence.
- `PHASE5_FINAL_REPORT.md` (new) — gate-by-gate verified Phase 5 status.
- `PRISM_IMPLEMENTATION_LEDGER.md` (new, this file).
- Branch pointer `claude/prism-phase-5-6-95ai73` reset from `main`'s tip
  (Streamlit-only) to `origin/phase-5-ai-analyst`'s tip (the real migration
  lineage). No source files were modified.

**Contracts changed:** none.

**Tests:** Ran the full existing suite rather than adding new tests (verification
unit, not a feature unit): 637 Python tests passed (pytest), ruff clean, mypy
clean (CI-matching invocation), boundary/secret scans clean, npm lint/typecheck/
a11y-baseline/vitest/build all clean, Playwright axe-core scan clean (0
violations). See `PHASE5_FINAL_REPORT.md` for the full breakdown including what
was `BLOCKED_EXTERNAL` (live MySQL e2e — no container runtime in this sandbox;
Ollama live check — this sandbox's loopback is not the user's machine; Monaco CDN
— sandbox network policy; staging deploy — no existing infra for the migrated
stack, not created unilaterally).

**Parity:** No Streamlit files touched; parity reference untouched.

**Performance:** N/A (verification unit).

**Security:** Re-ran `tools/check_secrets.py` and `tools/check_boundaries.py`;
both clean. No new attack surface introduced.

**Architecture decision:** Treat `origin/phase-5-ai-analyst` as the source of
truth for the migration going forward, not `main`. `main` continues to receive
Streamlit-only parity fixes from unrelated agents and should not be assumed to
carry migration work again in future sessions — always verify with
`git ls-tree -r --name-only <branch> | grep package.json` before trusting a
branch name or timestamp.

**Risk:** Branch pointer for `claude/prism-phase-5-6-95ai73` was force-pushed
with `--force-with-lease`. Justified only because the prior remote tip was
bit-identical to `main` (zero unique unmerged commits) — documented in
`RECOVERY_REPORT.md`. Do not repeat a force-push on this branch once it carries
unique commits without the same zero-unique-history justification.

**Technical debt surfaced (not fixed in this unit):**
- Atlas is currently the AI Analyst's execution identity (SSE `atlas.*` events,
  contextual actions) rather than the distinct ambient operating-layer surface
  the target product model describes. Forward-looking contracts already exist
  (`packages/atlas-interfaces/python`) but aren't wired into `apps/api` yet.
- SQL Lab's Monaco editor has no offline/local-asset fallback (CDN-only loader);
  filed as a follow-up task (`task_2fd6fb0f`) rather than patched blind here.
- No Linux Playwright visual-regression baselines are committed (only `win32`).

**Rollback:** Revert the branch pointer to its prior tip (`main`'s commit
`6327029`) if this recovery is judged incorrect — safe, since no source changed.

**Remaining gates:** See `PHASE5_FINAL_REPORT.md` — `CODE_COMPLETE = YES`,
`STAGING_READY = NO`, `RELEASE_READY = NO`.
