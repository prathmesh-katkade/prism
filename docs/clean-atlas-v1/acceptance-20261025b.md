# Clean + Atlas visual-acceptance pass — 2026-10-25 (round 2: completion)

Continues `acceptance-20261025.md` (round 1) directly - that round fixed three button
treatments but left the dev server down, with no after-screenshot and the step-marker
composition gap undone. This round had a live server throughout and finished that work,
then audited the rest of the Clean + Atlas composition against `references/01`, `05`,
`06`, `03` and shipped one more real, evidence-backed gap it found along the way. Not a
redesign round - every change here is CSS/markup reuse of existing tokens and components,
or a direct port of an already-proven pattern.

Starting point this round: `5573abf` (branch `prism/clean-pattern-review-v1`), working
tree already carrying round 1's uncommitted `clean-workspace.tsx`/`prism.css` changes.
No concurrent agent activity found (clean `git status` apart from those two files and
long-standing untracked `.prism/` scratch output from earlier rounds). Round 1's ~60%
fidelity estimate was explicitly flagged in the brief as subjective, not a verified
metric, and is not repeated here as a number.

## What this round verified and finished (carried over from round 1, now actually looked at)

**Recipe panel heading hierarchy** (`clean-workspace.tsx` ~L950, `prism.css`
`.clean-recipe-subtitle`): "Transformation recipe" now renders as the large heading,
with the step count as a small subtitle below it - matching reference 05's hierarchy.
Verified rendering correctly via screenshot, not just source reading (round 1 could not
do this; the dev server was down).

**Connected circular step markers** (`prism.css` `.clean-recipe-unified li > i` and
`::before`/`::after`): replaced the flat 4px colour bar with a vertical connecting line
and a 12px circle per step - green filled with a ✓ for Applied, amber filled for the
selected/Review step, hollow faint-bordered for Draft. Verified rendering correctly in
both dark and light theme at the reference's own 1586×992 dimensions and at 400×844 -
see `evidence/milestone-20261025/clean-populated-after-dark-1586x992.png` against
`references/05-clean-workspace-substantial-panels.png`.

## Found and fixed this round

**NEXT WORKSPACE handoff rows were bare arrow-prefixed links, not the icon+title+
supporting-text+chevron row the brief names explicitly** ("Handoff actions need
icon+title+supporting text+chevron, not bare links"). Before: `<span aria-hidden>→</span>
Use this revision in SQL Lab`, with the blocked-reason as a separate `<small>` only shown
when disabled - no icon, no supporting copy when enabled, arrow on the wrong side.
Confirmed via screenshot (`.prism/verify-20261025b/inspector-handoff-check2.png`), not
assumed from source.

Fixed by reusing the app's own existing `Icon` component (`apps/web/src/components/
icons.tsx`) - already built, previously unused in this file, not a new icon system -
plus a new `.clean-handoff-row`/`.clean-handoff-copy`/`.clean-handoff-chevron` CSS block
that lays out icon (left) / title+supporting-text (stacked, middle) / chevron (right).
Applied to all three handoff rows: "Use this revision in SQL Lab" (database icon),
"Visualize this revision" (layers icon), "Open Reports" (panel icon) - each now always
shows a real supporting line (either a short description, or the live blocked-reason
when a preview is pending), not just on the disabled path.
Verified rendering correctly: `.prism/verify-20261025b/handoff-rows-after-1586x992.png`.

Files: `apps/web/src/components/clean-workspace.tsx` (added `Icon` import, restructured
the three handoff buttons), `apps/web/app/prism.css` (`.clean-handoff-row` reworked,
`.clean-handoff-icon`/`.clean-handoff-copy`/`.clean-handoff-chevron` added,
`.clean-handoff-reason` removed as no longer needed - its job is now the `<small>`
inside `.clean-handoff-copy`).

## Checked and found already correct (not touched)

- **Compact switches** (`.clean-switch-row input[type="checkbox"]`, 34×19px pill
  toggles): already matches the brief's "replace oversized circular toggles" ask - this
  was evidently done in an earlier round. Confirmed via CSS read and screenshot; no
  oversized circular toggle exists in the current build.
- **Current vs. suggested mapping distinction**: `clean-workspace.tsx` shows "Suggested
  mapping"/"Rule-based" pre-application and "Current mapping" post-application (after
  "Apply suggested grouping"). Directly satisfies the brief's "distinguish current
  mappings from suggested mappings" - reconfirmed this round by rebuilding the exact
  state transition live.
- **Central review surface** (Before/Changes/After segmented control, impact metrics,
  table headers/row rhythm, exception banner with inspection action, Affected
  rows/Exceptions/Validation tabs, persistent Apply/Discard bar): already present and
  matches reference 05's composition closely on direct screenshot comparison. No gap
  found worth a change.
- **Atlas dock structure** (character/identity/context header, context chips, real
  per-dataset conversation, computed preview-checks card gated on an actual model turn
  with "Measured checks, not model confidence" labelling, evidence disclosure, handoff
  to Step settings): already implements the 7-part composition the brief asks for,
  confirmed by triggering a real turn against the local Ollama model (`qwen2.5:3b`) and
  reading the rendered response - see `.prism/verify-20261025b/atlas-dock-turn-
  1586x992.png`. The brief's "Preview checks already exist - do not duplicate them" is
  accurate; no new preview-checks UI was added.

## Investigated: the "Scanning for quality issues" loading path

Measured directly rather than inferred. `build_overview()` (`packages/overview-analytics/
python/prism_overview_analytics/service.py`) takes **~1.5s on a synthetic 99,000-row,
4-column dataset** and **~4.2s on a 99,000-row, 12-column dataset with PII-shaped columns
(email/phone)** - bounded and proportional to rows × columns, not an infinite hang.

Root cause of the apparent stall: it is computed **twice, redundantly, on every Clean
page load**. `clean-workspace.tsx`'s `refresh()` fires `GET /clean/datasets/{id}/state`
and `GET /overview/datasets/{id}/profile` in parallel (`Promise.all`); the first calls
`detect_issues()` → `build_overview(frame)` (`apps/api/src/prism_api/clean.py` `_state`),
and the second calls `build_overview(frame)` again independently
(`apps/api/src/prism_api/overview.py:229`) - the same full profile, computed from
scratch twice, concurrently, on the same frame. This directly contradicts the loading
screen's own copy: *"Reusing Overview's own deterministic profile — nothing is
recomputed twice."* That claim is false as the code stands.

**Not fixed this round.** This is a backend compute-path change (caching or
deduplicating `build_overview` across these two endpoints), not a presentation change,
and risks touching a path section 5 asks to leave alone (`detect_issues`/health scoring
feed Atlas's own explanations). Flagging it here with hard numbers, per the brief's
"measure... do not infer the cause or hide it," rather than silently patching
backend caching into a presentation-completion pass.

## Gates run fresh this round

All from a clean working tree at the time of running, after the fixes above.

- **Web**: `npm run lint` (0 warnings), `npm run typecheck` (clean), `npm run test:web`
  (**149/149 passed**, 19 files), `npm run build:web` (clean production build), `npm run
  a11y:baseline` (passed), `npm run boundaries` (passed), `npm run contract:check`
  (clean, generated contract already up to date).
- **Python**: `ruff check` with CI's exact scope (`apps/api/src packages
  tools/check_boundaries.py tools/generate_typescript_contracts.py tools/check_secrets.py
  tests`) - all checks passed. `mypy` with CI's exact flags
  (`--follow-imports=skip --allow-subclassing-any --allow-untyped-decorators
  --no-warn-return-any apps/api/src packages`) - no issues in 102 source files.
  `python tools/check_secrets.py` - passed.
- **Full native pytest selection** (CI's exact `tests/api tests/contracts tests/migration
  tests/overview tests/sql_lab`), run against a **fresh isolated
  `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`** (a new file under
  `.prism/verify-20261025b/pytest-isolated/`, never the shared default
  `.prism/runtime/analytical-history.sqlite`) - **780 passed, 7 skipped, 0 failed**.
  Two tests failed on a first pass against the pre-existing shared default store
  (`test_combined_sft_dataset_route_includes_synthetic_teacher_end_to_end`,
  `test_ancestors_never_cross_into_a_different_fingerprint_sharing_the_same_revision_
  number`); re-run in isolation confirmed both pass cleanly - this is the same
  known shared-store pollution class documented in round 1 against
  `acceptance-20261024.md`, now worked around the way the brief actually asks
  ("use fresh explicit test database paths; do not delete default databases to obtain a
  passing run") instead of clearing the shared default file, which round 1 had done and
  this round correctly avoided repeating.
- **MySQL parity** (CI's exact `phase-4-live-e2e` selection: `tests/sql_lab/
  test_mysql_connector_parity.py tests/api/test_durable_registry.py tests/api/
  test_atlas_promotion.py`): a disposable local MySQL 8.4 instance, reused from round 1's
  own isolated datadir (`.prism/mysql-disposable-20261025-0001/`, port 3310 - identity
  confirmed via `SELECT @@port, @@datadir` before use, never the machine's main MySQL),
  seeded with CI's exact fixture - **31/31 passed**. Instance stopped afterward to free
  memory.

## Verification method and its limits

All visual verification this round was done by resizing a real Chrome tab to the
reference's own 1586×992 and capturing against the real running stack: `next start`
(production build, not dev/HMR - chosen to stay inside the memory budget, same as round
1) on port 3050, talking to the real `prism-api` sidecar (standalone binary, not the full
Tauri wrapper) on port 8000, against a disposable dataset built from
`.prism/visual-acceptance-20261024/fixture.csv`. This is a faithful proxy for the
webview's own rendering (Tauri's webview renders the identical HTML/CSS/JS bundle) but
is **explicitly a browser verification, not a native-desktop one** - it says nothing
about native window chrome, native dialogs, or anything Tauri-specific.

**The native desktop app (`app.exe`) was not rebuilt this round.** Free system memory
measured at ~3.5 GB of 14.9 GB total before attempting it - the same memory-pressure
condition that stopped round 1's dev server. A Tauri release build compiles and links a
Rust binary, which is memory-heavy and was judged too likely to repeat that failure (or
be killed mid-build, which can leave `target/` in a worse state than not building at
all) for the remaining budget this round. Per the brief's own fallback ("stop
redundant task-owned processes safely... do not terminate unrelated user processes...
report any remaining verification blocker explicitly"): one orphaned, idle,
task-owned `prism-api.exe` (PID 38248, not listening on any port - a leftover from an
earlier round) was stopped first; no unrelated user process was touched; free memory
barely moved (3.55 GB → 3.46 GB), confirming the pressure is from other, non-task
processes this session must not touch. This is reported plainly as an open item, not
silently skipped - see "Remaining for the user" below.

## Remaining for the user

- **Native desktop rebuild and native screenshot verification** - blocked on memory this
  round (see above). The code changes are small, CSS/markup-only, and already verified
  in-browser; rebuilding `apps/desktop-shell` (`npx tauri build --no-bundle`, as round 1
  did successfully) when more memory is free would close this out.
- **The redundant `build_overview()` computation** on the Clean load path - measured and
  root-caused above, not fixed (backend compute-path change, out of scope for a
  presentation-completion pass).
- Everything round 1 already listed as open beyond this (native WebDriver automation,
  etc.) remains open; nothing here regressed it.

## Evidence

- `docs/clean-atlas-v1/evidence/milestone-20261025/clean-populated-after-dark-1586x992.png` -
  final populated 4-step comparison state (dark, 1586×992), compare against
  `references/05-clean-workspace-substantial-panels.png`.
- `.prism/verify-20261025b/handoff-rows-after-1586x992.png` - handoff-row redesign,
  empty-recipe state.
- `.prism/verify-20261025b/atlas-dock-turn-1586x992.png` - Atlas dock after a real local-
  model turn.
- `.prism/verify-20261025b/clean-light-1586x992.png`, `clean-light-400x844.png` - light
  theme and ~400px width checks.

## Build/source identity

- Source SHA this round built from: `5573abf` (branch `prism/clean-pattern-review-v1`,
  working tree carrying this round's + round 1's uncommitted changes until committed).
- Web production build: `apps/web/.next`, rebuilt twice this round (once for the
  round-1 CSS fixes, once for this round's handoff-row change), served via `next start`
  on port 3050.
- Native desktop binary: unchanged from round 1's build (does not include this round's
  or round 1's CSS/markup changes - see "Remaining for the user").
