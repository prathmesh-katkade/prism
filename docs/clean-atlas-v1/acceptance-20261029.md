# Clean layout correction and native verification — 2026-10-29

Continued from `42f6f266a6f98ed73343a70b75c454e54ba86f27`, `prism/clean-pattern-review-v1`,
building on the uncommitted CSS work already in the tree from the prior
session. This entry documents what changed this round, what was measured,
and what remains limited.

## 1. Root causes found and fixed (`apps/web/app/prism.css`)

The prior session's own fix (bounding `.clean-issues`/`.clean-preview`
height, converting the apply bar from `position:fixed` to `position:sticky`)
turned out to be incomplete under direct measurement, and introduced one new
regression. Three real, sequential bugs were found and fixed this round,
each confirmed via `getBoundingClientRect()` against a real 4-step draft at
1366×800, not assumed from the CSS alone:

- **Page-level overflow (68px) at the sticky fix's own starting point.**
  `.clean-issues`/`.clean-preview` sit in grid-row 2, below the 78px
  `.clean-dataset-header` row that only spans columns 1–2; giving them the
  same `calc(100vh - 102px)` height formula the inspector uses (which starts
  at row 1, no header above it) made them ~79px too tall, so the page itself
  needed an initial 68px scroll before anything settled into place. Fixed by
  bounding the **grid container's own height** (`height:calc(100vh - 91px)`,
  not just `min-height`) and sizing row 2 as `minmax(0,1fr)`, so each
  column's height now falls out of the grid's own row track.
- **Mapping table squeezed to 110px — worse than the bug being fixed.**
  Making `.clean-preview` a flex column so it could scroll independently
  triggered a real flexbox pitfall: a flex item with `overflow:auto` gets an
  *automatic minimum size of 0*, so `flex-shrink:1` let the mapping table
  get squeezed to 110px — below even its own 140px floor from before this
  session — to make the rest of the column fit. First patched with
  `flex-shrink:0` on the table wrappers, then removed again once the
  structural fix below made it unnecessary.
- **Sticky-bottom apply bar covering the affected-rows table's header.**
  `position:sticky;bottom:0` pins to the scrollport's visible bottom edge as
  soon as the container's content overflows it — even at `scrollTop: 0`,
  before any scrolling. Measured a 22px overlap hiding the affected-rows
  table's own header.

## 2. Structural fix: scrollable content and the approval footer are separate grid rows

Per the next round's explicit brief, `.clean-preview` is now a two-row grid,
not one scrolling flex column:

```
.clean-preview { display:grid; grid-template-rows:minmax(0,1fr) auto; }
```

- `.clean-preview-scroll` (new wrapper `<div>` around the existing review
  content in `clean-workspace.tsx`) — row 1, `minmax(0,1fr)`, its own
  `overflow-y:auto`. A plain block, not a flex container, so none of its
  children (the mapping table, the affected-rows table) are subject to
  flexbox's shrink-to-zero behaviour any more — each renders at its natural,
  max-height-bound size, and the wrapper scrolls for any excess.
- `.clean-apply-bar` — row 2, `auto`, normal flow. Can never overlap row 1's
  content because it occupies its own reserved track, not because of
  z-index or position tricks.

Measured at 1366×800 with a real `Review category mapping` state: the apply
bar renders at a fixed `707–784`→`723–800` depending on content, **always**
inside the viewport with zero overlap, while `.clean-preview-scroll` scrolls
independently from `186` to `711`. At 1586×992 (the reference size), the
same state fits with the mapping table, the unmatched-value warning, two
rows of the affected-rows table, and the footer all visible together,
without scrolling — closely matching
`references/05-clean-workspace-substantial-panels.png`.

A matching bug existed in the `@container prism-workspace (max-width:950px)`
stacked/mobile reset: it reset `height:auto;max-height:none` but not
`display` or `align-content` on the three-pane grid container, which still
carried its own fixed desktop height. Grid's default `align-content:stretch`
then divided that fixed height evenly across the four stacked panels
regardless of their real content, producing small boxes with their own
forced internal scrollbars — confirmed via `getComputedStyle` at 400×844:
`grid-template-rows` resolved to four specific pixel tracks summing to
exactly the container's old fixed height, not to each row's content.
Fixed with `display:block;height:auto;align-content:start` on the
container at that breakpoint; the page now scrolls as one stack (confirmed:
`docScrollHeight` 1792 at 400px width, full "Transformation recipe" list
and all five disclosure sections visible without a nested scrollbar).

## 3. Verified this round

- **1366×800** (normal desktop size): mapping table, unmatched-value
  warning and the top of the affected-rows table all visible together
  without scrolling; apply/discard always visible, never overlapping.
  `docScrollHeight === innerHeight` (no page-level scroll).
- **1586×992** (reference size), dark and light: closely matches
  `05-clean-workspace-substantial-panels.png` — all five left-rail sections,
  full mapping/impact/warning/affected-rows composition, inspector content
  down through preview checks, all visible together.
- **~400×844**, dark: no horizontal overflow; narrow-layout stretch bug
  (above) fixed and confirmed — full stacked content reachable by one
  page-level scroll, no nested cramped scrollboxes.
- **34×19px switches**: unchanged, reconfirmed.
- **Keyboard / preview invalidation**: toggling "Case sensitive" by
  keyboard focus + interaction correctly reverted the reviewed-mapping state
  to "Preview is stale — recompute before applying," exactly as before this
  round's structural changes — confirms the restructure didn't touch
  approval/preview-invalidation behaviour.
- **Atlas real-model proposal**: `PRISM_AI_PROVIDER=ollama`. The configured
  default model (`llama3.2:3b`) was not installed on this machine's Ollama
  — a genuine, reported "Local model unavailable" outcome, not fabricated.
  Retried with an actually-installed model (`qwen2.5:7b-instruct`) and
  captured a real, successful structured proposal: request → model
  explanation → "PRISM computed this deterministically, 1 row would
  change" → **4/4 preview checks clear** → evidence disclosure → "Review in
  Step settings" action. See
  `evidence/milestone-20261029/atlas-real-proposal-dark-1366x800.png`. No
  model bindings or validation were changed to obtain this.

## 4. Native build and verification — partially achieved, limitations documented

Rebuilt from this round's final source: `CARGO_BUILD_JOBS=1`,
`npx tauri build --no-bundle`, 3m01s. Frontend static export
(`apps/web/out`) regenerated fresh immediately before the Rust build and
confirmed to contain the `.clean-preview-scroll` class from this round's
fix. `apps/desktop-shell/src-tauri/target/release/app.exe`,
SHA-256 `12BBB64CFBF0C54A2FC4283E8CEF6C97A664CA57097B69B81F3F103702323E2A`.

Launched with `PRISM_DESKTOP_DATA_DIR` pointed at an isolated, confirmed-
empty directory (never a real user database); confirmed the real sidecar
auto-spawn chain (`app.exe` → `prism-api.exe`, parentage verified via
`Get-CimInstance Win32_Process`) and seeded the same disposable fixture via
the sidecar's own upload endpoint.

**Not achieved this round, and why — a real regression from the prior
session's own documented breakthrough**: `tauri-driver` could not establish
a WebDriver session. Root cause: the installed Edge browser auto-updated to
156.0.4314.50 at some point in the two days since the prior session, while
the cached `msedgedriver` in `.prism/native-driver/` is pinned at
155.0.4283.62 — a major-version mismatch that Chromium-based drivers refuse
silently (`RemoteDisconnected` on every session attempt). No newer driver
exists anywhere else on this machine, and this environment has no general
internet access to fetch one (DNS resolution for
`msedgedriver.azureedge.net` fails). This is an external environment
drift, not caused by this round's changes.

**Fallback actually used, clearly labelled as such**: Windows UI Automation
(`System.Windows.Automation`) driving the real packaged window directly —
genuine OS-level `Invoke` on real buttons (tab navigation, theme toggle),
not WebDriver, not a mock. This worked for simple buttons but **not** for
the styled `<select>` operation combobox: neither `ValuePattern.SetValue`
nor keyboard `SendKeys` (with the window confirmed foregrounded) changed its
value, and `PrintWindow` does not capture native OS popup overlays, so even
confirming whether the dropdown visually opened was not possible by this
method. Building the full 4-step native draft was therefore not achieved
this round.

What **was** captured, genuinely, from the real packaged executable with
real isolated data loaded:
- `native-clean-dark-1366x800.png` — real WebView2 rendering of the fixed
  layout (all five left-rail sections, correct three-pane structure) at the
  exact window size requested, resized via `MoveWindow`.
- `native-clean-light-1366x800.png` — real theme toggle via `Invoke`,
  confirming the warm charcoal/brass palette's light variant renders
  correctly natively too.

Both show only the 1-step (unselected-operation) state, not the 4-step
review composition the browser evidence shows — a real, named limitation,
not silently worked around. Keyboard navigation, mapping/exception
inspection, and preview-invalidation were **not** separately re-verified
natively this round (only in-browser, see §3); native dropdown interaction
remains blocked pending a matched `msedgedriver` build.

## 5. Gates run fresh this round

All commands run from this round's working tree (uncommitted CSS/TSX
changes included), with isolated storage for every database-backed check:

- `npm run lint` — clean (0 warnings, `--max-warnings=0`).
- `npm run typecheck` — clean.
- `npm run test:web` — **149/149 passed**, 19 files (includes
  `clean-workspace.test.tsx`'s 34 tests, which exercise the restructured
  JSX directly).
- `python tools/generate_typescript_contracts.py --check` — clean.
- `npm run a11y:baseline` — passed.
- `python tools/check_boundaries.py` — passed.
- `ruff check` at CI's exact `phase-1-python` scope
  (`apps/api/src packages tools/check_boundaries.py
  tools/generate_typescript_contracts.py tools/check_secrets.py tests`) —
  clean. (A repo-wide `ruff check .` surfaces pre-existing style issues in
  untracked `.prism/` scratch scripts and one pre-existing file outside
  this scope; neither is touched by this round's changes nor part of CI's
  actual lint scope.)
- `mypy` at CI's exact scope — clean, 102 source files.
- `python tools/check_secrets.py` — passed.
- `pytest tests/api tests/contracts tests/migration tests/overview
  tests/sql_lab` (phase-1-python's SQLite scope) — **780 passed, 7
  skipped** with an explicit isolated `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`.
  (The first, unisolated run showed 2 failures that reproduced even in full
  single-test isolation; traced to the documented persistent-default-DB
  contamination pattern already called out in `HANDOFF.md` — confirmed by
  rerunning both files alone with a fresh isolated DB, where all 33 tests in
  them passed. Not a regression from this round's changes, which touched no
  Python source.)
- **MySQL-backed** (`tests/sql_lab/test_mysql_connector_parity.py`,
  `tests/api/test_durable_registry.py`, `tests/api/test_atlas_promotion.py`)
  — **31 passed**, against a disposable local MySQL 8.0.40 instance
  (`.prism/mysql-disposable-20261029/`, freshly initialized this round,
  port 3307, seeded exactly as CI's own setup step does).
- `npm run test:e2e:live` (Playwright, real API + real Next server, no
  mocks) — **not completed**. Started with an isolated API port (8010,
  to avoid the native app's own sidecar on 8000) and an isolated history
  database; the harness's own memory-pressure safeguard killed it (and a
  separate, unrelated background search command) partway through because
  the machine was critically low on memory while the session was idle.
  This was the harness protecting the system, not a test failure - no
  pass/fail result exists to report, and it was not restarted, per the
  explicit instruction that accompanied the kill notification not to start
  it again without being asked. The orphaned servers it had spawned were
  stopped afterward to free memory. This remains an open gate, not a
  silently-skipped one: `npm run test:e2e:live` with
  `PRISM_LIVE_E2E_API_PORT=8010` and an isolated
  `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` is the exact command to rerun
  when memory allows.

Backend/contract source was not changed this round (only
`apps/web/app/prism.css` and `apps/web/src/components/clean-workspace.tsx`);
full Python/contract regeneration was not expected to differ and did not.

## 6. Remaining limitations, stated plainly

- Native WebDriver automation is blocked by an Edge/msedgedriver version
  mismatch this environment cannot currently resolve (no matching driver
  cached, no internet access to fetch one). The native evidence this round
  is therefore button-navigation and theme-toggle only, not a full 4-step
  native composition.
- The Atlas real-proposal evidence uses `qwen2.5:7b-instruct` (an
  installed, available model), not the configured default
  (`llama3.2:3b`, not installed) — both outcomes are reported honestly
  above, per the brief's explicit instruction not to fabricate or silently
  substitute a model without saying so.
- Dark/light/400px coverage this round is browser-only; native coverage is
  1366×800 dark and light only (see §4).

No merge or tag performed. This is a verification checkpoint for visual
review, matching the prior round's own practice.
