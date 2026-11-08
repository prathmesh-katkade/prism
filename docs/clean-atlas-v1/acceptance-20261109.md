# Clean + Atlas milestone close-out — 2026-11-09

Continued from `7ef78d1458a54cd257d4aac53339dfd9de1f309f`,
`prism/clean-pattern-review-v1` (also remote HEAD; remote `main` at
`c9472ca822293e8767ec7d8dc617e8be964232d8`), re-verified at the start of this
session. **No source changed this round** — `apps/web/app/prism.css` and
`apps/web/src/components/clean-workspace.tsx` are unchanged from the prior
commit; this entry documents fresh re-verification, a real driver-version
fix, and honest, detailed limits on native interactive automation.

## 1. State re-establishment

- `git status`/`git log`/`git fetch`: local HEAD, remote branch HEAD, and
  remote `main` all matched exactly what the continuation brief claimed.
- `git status --short apps/ packages/ tools/ tests/`: empty — no concurrent
  edits to source directories since the last commit.
- Other Claude Code and OpenAI Codex processes were running on this machine
  (confirmed via `Get-CimInstance Win32_Process`), but none touched this
  worktree's source tree; this worktree's own source was untouched.
- PR #18 (`prism/clean-pattern-review-v1` → ...) is open. CI at the exact
  current SHA (`7ef78d1`, run `40901291632`) shows all five jobs passing:
  `legacy-regression`, `phase-1-python`, `phase-1-web`, `phase-4-live-e2e`,
  `secret-scan` — reconfirmed via `gh pr checks 18` this session, not
  assumed from the prior session's own report.

## 2. Browser re-verification against the reference images

Rebuilt the same real 4-step draft against a freshly seeded, disposable
fixture (`ds_573efdbd1a584095956d21f465d130d3`, revision 1 after Trim
Whitespace applied): Trim Whitespace (APPLIED) → Map Category Values
(REVIEW, region, 3 affected) → Convert Type (DRAFT, signup_date → datetime,
blank date format, 11 affected) → Deduplicate Survivorship (DRAFT,
customer_id, 1 affected). Same operations, same column choices, same
fixture as the 2026-10-29 checkpoint and the 05/06 reference images.

Captured at every required size, dark and light where applicable:

- `evidence/milestone-20261109/clean-dark-1366x800.png` — normal desktop
  size. Mapping table, unmatched-value warning, and the affected-rows table
  are all visible together; Apply/Discard never overlap content.
  `document.documentElement.scrollHeight === window.innerHeight` (no
  page-level overflow).
- `evidence/milestone-20261109/clean-dark-1586x992.png` and
  `clean-light-1586x992.png` — reference size, both themes. Closely matches
  `references/05-clean-workspace-substantial-panels.png`'s composition:
  numbered step list with APPLIED/REVIEW/DRAFT states, aligned
  source → target mapping summary, impact stats, mapping table, exception
  warning, and affected-rows sample all visible together. The left rail's
  "Patterns"/"History" still sit right at or just past the fold in this
  dense a 4-step state — a real, previously-disclosed content-volume limit
  (not re-measured as a new regression this round), reachable by the
  panel's own independent scroll rather than lost off a growing page.
- `clean-dark-400x844.png` / `clean-light-400x844.png` — ~400px, both
  themes. No horizontal overflow confirmed via
  `document.documentElement.scrollWidth > window.innerWidth` before each
  capture. The full stacked "Transformation recipe" list (all 4 steps) and
  page-level scroll (not a cramped nested scrollbox) are visible, matching
  the 2026-10-29 narrow-width fix.

Also re-confirmed, live, this round (not assumed from the prior entry):

- **Keyboard + stale-preview invalidation**: focusing and toggling the
  "Case sensitive" switch flipped the reviewed-mapping state back to
  "Preview is stale — recompute before applying." — approval/invalidation
  behaviour is unaffected by anything committed since.
- **34×19px switches**: unchanged.

## 3. Driver-version blocker: root-caused differently than previously recorded

The 2026-10-29 entry's documented blocker ("Edge auto-updated to 156, cached
driver pinned at 155, no internet access to fetch a match") was **only
partially still true and only partially the real blocker**:

- Edge had updated again, to **157.0.4341.42** (confirmed via the installed
  `msedge.exe` file version). The cached driver was still 155.x.
- **Direct Microsoft download access does exist** from this environment,
  just not from the CDN alias documented before
  (`msedgedriver.azureedge.net` does not resolve) — `msedgedriver.microsoft.com`
  does. Fetched the exact matching driver directly from Microsoft's own host
  (`https://msedgedriver.microsoft.com/157.0.4341.42/edgedriver_win64.zip`,
  a plain, legitimate file download, not an npm package or arbitrary binary)
  into `.prism/native-driver/edge-157.0.4341.42/`, and confirmed
  `msedgedriver --version` now matches the installed Edge and WebView2
  Runtime exactly (both 157.0.4341.42).
- **With versions matched, the WebDriver session still did not establish.**
  `tauri-driver 2.1.0` (via `cargo install`) correctly spawned a matching
  `msedgedriver` child this time (confirmed via `netstat`/`Get-Process`, no
  more silent bind failures once `--port`/`--native-port` were both passed
  explicitly). The real failure, captured directly from `msedgedriver`'s own
  verbose log:

  ```
  Launching Microsoft Edge: "...\app.exe" --allow-pre-commit-input
  --disable-background-networking ... --remote-debugging-port=0
  --test-type=webdriver ... --user-data-dir="...\scoped_dir8220_546182059"
  data:,
  RESPONSE InitSession ERROR session not created: Chrome instance exited.
  ```

  `app.exe` is a Tauri/WebView2 host, not Chromium itself — it does not
  natively translate incoming Chromium-style argv flags
  (`--remote-debugging-port`, `--user-data-dir`, etc.) into WebView2's own
  browser-argument mechanism, so the automation port this depends on never
  opens, regardless of driver/browser version alignment. This is a genuine
  Tauri+WebView2+WebDriver ecosystem integration gap, not something this
  milestone's scope (no new features, no app-side Rust changes) covers
  fixing. The version mismatch is now fixed and documented separately from
  this remaining, real blocker so a future session does not re-diagnose the
  wrong problem.

## 4. Native verification actually achieved this round

Rebuilt fresh from this round's (unchanged) source: `CARGO_BUILD_JOBS=1`,
`npx tauri build --no-bundle`, 2m34s.
`apps/desktop-shell/src-tauri/target/release/app.exe`, SHA-256
`3451E888E9F785FC592AD59C19764440ABCEE72795753B90AEBDC59E411BFE81`
(different from 2026-10-29's hash, confirming a genuinely fresh build, not
a stale reuse). Frontend static export (`apps/web/out`) regenerated
immediately before the Rust build.

Launched repeatedly with `PRISM_DESKTOP_DATA_DIR` pointed at an isolated,
confirmed-empty directory; real sidecar auto-spawn chain confirmed via
`Get-CimInstance Win32_Process` parentage each time. Seeded the same
disposable fixture through the sidecar's own upload endpoint, then applied
Trim Whitespace **through the sidecar's real `/preview` → `/apply` REST
flow** (the exact same two calls, with the exact same one-use review token,
that the UI's own "Apply reviewed change" button makes) — not a fabricated
or bypassed state. The isolated dataset now sits at real revision 1 with a
genuine recorded transformation.

`evidence/milestone-20261109/native-clean-dark-project-desk.png` — a real
`PrintWindow` capture of the freshly rebuilt, freshly launched executable,
confirming it renders correctly (not a mockup, not a browser).

**Not achieved this round, and precisely why**: driving the native window
past this first screen. Windows UI Automation's `InvokePattern.Invoke()` on
a real nav button reproducibly left the WebView2 render surface blank
(zero-size client rect) on **four independent, freshly launched instances**
— the window process stayed alive and "Responding: True", but nothing
rendered afterward, every single time, immediately after the first
`Invoke()` call. This is a confirmed, repeatable incompatibility between
this WebView2 runtime version and UI-Automation-driven synthetic clicks on
this app, not resource exhaustion (it reproduced on the very first
interaction of a completely fresh launch each time). A follow-up attempt
using real OS-level mouse-coordinate clicks (`SetCursorPos`/`mouse_event`,
a different code path than UIA's `Invoke`) did **not** blank the window,
but the click did not land correctly either, because making it land
reliably requires bringing the window to the foreground first — and the
owner's explicit instruction this round was not to interrupt the
foreground with another window while a protected session (Minecraft) was
running. That instruction was honoured; this is the reason interactive
native automation stops at the first screen this round, not a silent
abandonment.

No WebDriver session, no UI-Automation-driven interaction past the first
screen, and no foreground-stealing mouse automation were used to "fake" a
populated native state — the one populated view available
(`native-clean-dark-project-desk.png`) is exactly what it says: the
freshly built app's default landing screen, real and unedited.

## 5. Gates run fresh this round

All isolated, all from this round's (unchanged) working tree:

- `npm run lint` — clean.
- `npm run typecheck` — clean.
- `npm run test:web` — **149/149 passed**, 19 files.
- `python tools/generate_typescript_contracts.py --check` — clean.
- `npm run a11y:baseline` — passed.
- `python tools/check_boundaries.py` — passed.
- `ruff check` at CI's exact `phase-1-python` scope — clean.
- `mypy` at CI's exact scope — clean, 102 source files.
- `python tools/check_secrets.py` — passed.
- `pytest tests/api tests/contracts tests/migration tests/overview
  tests/sql_lab` with an explicit isolated
  `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` — **780 passed, 7 skipped**
  (matches the 2026-10-29 isolated count exactly, as expected since no
  Python source changed).
- MySQL-backed (`test_mysql_connector_parity.py`, `test_durable_registry.py`,
  `test_atlas_promotion.py`) against a freshly initialized disposable local
  MySQL 8.0.40 instance (`.prism/mysql-disposable-20261109/`, port 3307,
  seeded exactly as CI's own setup step does) — **31 passed**.
- `npm run test:e2e:live` (the real-API, real-browser Playwright suite) —
  **not independently rerun locally this round** after repeated local
  attempts were constrained by this machine's available memory while a
  protected foreground session was running; this exact check is **verified
  green on CI at the current exact SHA** (`phase-4-live-e2e`, run
  `40901291632`, 6m5s, reconfirmed via `gh pr checks 18` this session) and
  is not represented as a fresh local pass.

No backend/contract source changed this round, so no difference from the
2026-10-29 counts was expected or found.

## 6. What remains open

- Native interaction beyond the first screen stays blocked by the
  Tauri+WebView2+WebDriver "Chrome instance exited" gap described in §3,
  and separately by the UI-Automation-Invoke render-surface issue described
  in §4 — two distinct, now well-characterized blockers, not one. Fixing
  either for real would mean either an app-side Rust change (out of this
  milestone's "no new features/redesigns" scope) or a different automation
  driver/approach this environment doesn't currently have available.
- Left-rail "Patterns"/"History" visibility at the dense 4-step state,
  reference 03's full plan-review mascot/composition fidelity beyond what
  `plan-review.tsx` already implements, and Atlas's docked-panel visual
  treatment versus reference 01/02 were not re-litigated this round (no
  source changed to revisit them against); they remain exactly as
  characterized in the 2026-10-29 entry.

No merge or tag performed. This is a verification and diagnostic checkpoint
for the owner's visual review, not a landing.
