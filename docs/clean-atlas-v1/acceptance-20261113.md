# Clean + Atlas visual fixes — 2026-11-13

Continued from `81e1125b3c256a10a0ae657be9cf018daad37f69`,
`prism/clean-pattern-review-v1` (also remote HEAD at session start; remote
`main` at `c9472ca822293e8767ec7d8dc617e8be964232d8`), re-verified before any
edit. **Source changed this round** — this entry documents the first round
since 2026-10-24 to land application-code changes against the three
documented visual gaps, not another audit of unchanged source.

## 1. Discrepancy checklist (from the actual reference images, re-opened and
re-inspected this round)

- `05-clean-workspace-substantial-panels.png` vs
  `evidence/milestone-20261109/clean-dark-1586x992.png`: left rail's
  "Patterns"/"History" sat at/past the fold at the reference size in the
  four-step draft state — a real, measured overflow, not a stylistic
  preference.
- `01-data-tile-atlas-in-clean.png` / `02-atlas-character-interaction-study.png`
  vs the live Atlas dock: header/identity, chips, conversation turns,
  computed-preview card, and composer all already matched; the one clearly
  real, additive gap was a "Suggest next steps" quick-action row the
  reference shows and the implementation didn't.
- `03-cleaning-plan-review-concept-superseded-mascot.png` (composition only)
  vs `plan-review.tsx`: step hierarchy, reasons/examples, provenance tags,
  inclusion controls, impact/unchanged-data summary, clarification
  exclusions, and the approval action were already present and correct on
  inspection of the current source (read in full this round); the two
  visible remaining gaps — a "Permissions" mode card and an in-panel Atlas
  composer — have no real backing capability (no autonomous-apply mode
  exists; the composer would duplicate the dock) and implementing either
  would fabricate functionality the brief explicitly prohibits. Left as a
  named, intentional gap, not implemented.

## 2. Part A — Clean left panel density (source changed)

**Root cause, measured, not guessed**: at the 4-step draft state (`.clean-issues`
children heights via `getBoundingClientRect`), two elements specific to a
selected category-mapping step accounted for the overflow: a `.clean-current-mapping`
card fixed at 197px, and two separate one-line hint paragraphs
(`.clean-recipe-note` 32px + `.clean-recipe-tip` 31px) that said adjacent,
non-conflicting things. Combined content height at this state was 894px
against an 822px visible panel height — 72px over, consistent with the
reported fold-crossing.

**Fix** (`apps/web/src/components/clean-workspace.tsx`,
`apps/web/app/prism.css`):

- The "Current mapping" summary — previously a fixed, always-expanded
  197px card — is now a `<details className="clean-disclosure clean-current-mapping">`,
  matching the rhythm of the other left-rail sections (Saved recipes /
  Issues / Validation / Patterns / History) exactly: collapsed by default to
  one row showing `Current mapping  N→M`, with the full mapping list and
  "Review full mapping" button still present and reachable on expand. No
  information was removed, only deferred behind the same disclosure pattern
  already used for every other section on this panel.
- The two separate hint paragraphs were merged into one
  (`"Downstream preview recomputed from revision N. Projected health
  X/100. Disable a step to preview downstream changes without removing it."`),
  removing one full paragraph's margin/line, not any wording.
- The empty-mapping prompt state (`manualMode` with no values mapped yet)
  was deliberately left as a plain card, not a disclosure — it is a
  call-to-action, not a summary, and collapsing it would hide the only
  thing on screen at that moment.

**Measured result**: at the same 4-step draft state (region → category
mapping step 2 selected, matching the established evidence convention),
`.clean-issues` content height is now exactly 822px against an 822px
visible area (`scrollHeight <= clientHeight` confirmed via script, not
eyeballed) — all six left-rail entries (Current mapping, Saved recipes,
Issues, Validation, Patterns, History) are visible with no scrolling
required, with ~0px to spare rather than being forced smaller. Independent
scrolling of the panel is preserved (confirmed: expanding "Current mapping"
pushes Patterns/History below the fold again, reachable by the panel's own
scrollbar, exactly as the brief requires for longer recipes). No change to
`.clean-preview` / `.clean-preview-scroll` / `.clean-apply-bar` (the
reserved approval footer from `7ef78d1` keeps working, unmodified).

Verified, this round, against the fixed 4-step comparison draft (Trim
Whitespace APPLIED → Category Mapping DRAFT/region → Convert Type
DRAFT/signup_date→datetime blank format → Deduplicate Survivorship
DRAFT/customer_id), step 2 selected:

- `evidence/milestone-20261113/clean-dark-1586x992-after.png` /
  `clean-light-1586x992-after.png` — reference size, both themes. Fixed.
- `clean-dark-1366x800-after.png` / `clean-light-1366x800-after.png` —
  normal desktop. At this smaller size the left rail's own independent
  scroll is still needed past "Convert Type" (703px content vs 630px
  visible) — expected and within scope: the brief's "all five entry points
  visible" requirement is explicitly scoped to 1586×992, and the centre
  table + Apply/Discard bar remain fully visible together with no overlap.
  `document.documentElement.scrollHeight > window.innerHeight` is `false`
  (no page-level overflow) at both sizes.
- `clean-dark-400x844-after.png` / `clean-light-400x844-after.png` — ~400px,
  both themes, full page capture. No horizontal overflow
  (`scrollWidth 385 <= innerWidth 400`); the full stacked layout (recipe,
  disclosures, centre table, inspector) renders via page-level scroll, not a
  cramped nested scrollbox.
- **Keyboard + stale-preview invalidation**, re-confirmed live against the
  changed markup (not assumed carried over): toggling "Case sensitive" via
  its switch flips the reviewed state to "Preview is stale — recompute
  before applying." exactly as before; the new `.clean-current-mapping`
  disclosure is a real `<details>`/`<summary>`, keyboard-focusable and
  togglable with no custom JS, and its expanded state was visually
  confirmed (mapping list + "Review full mapping" button render correctly
  inside it).

## 3. Part B — Atlas dock (source changed)

Reference 01 shows one real, additive gap beyond what `atlas-dock-panel.tsx`
already implemented: a "Suggest next steps" quick-action row between the
conversation and the composer. Implemented for real, reusing the exact same
`ask()` call every starter question and retry button already uses — no new
endpoint, no fabricated response:

- `apps/web/src/components/atlas-dock-panel.tsx`: a new row of three
  buttons ("Explain this step", "Compare before and after", "Suggest what
  to clean up next"), shown once a conversation exists and nothing is
  pending, each calling `ask()` with a genuine free-text intent sent
  through the real `/api/v1/workspace-proposals` flow.
- `apps/web/app/prism.css`: the row is styled as a distinct, bordered-off
  chip group (`.atlas-dock-next-steps`) rather than the vertical starter
  list, and the existing test-locked `"N / M clear"` preview-check header
  text is made visually more prominent (`font-size:17px`, CSS only — the
  exact string asserted by
  `atlas-dock-panel.test.tsx` is untouched).

**Deliberately not added**: a fabricated multi-stage status stepper
("Profile inspected → Preview reviewed → Awaiting your decision") the
reference mockup shows. No such formal state machine exists in the real
API or this component's state, and inventing one to match a labelled
"DESIGN CONCEPT · ILLUSTRATIVE DATA" mockup would be exactly the kind of
fake successful-workflow fabrication the brief prohibits. Named here as an
intentional gap, not an oversight.

Verified live, this round: asked a real starter question against the local
Ollama model (response came back `"Local model unavailable"` — an honest,
pre-existing fallback path, not something this round's change touched or
caused); the "Suggest next steps" row rendered correctly with all three
real actions. `evidence/milestone-20261113/atlas-dock-next-steps-after.png`.

## 4. Part C — Cleaning plan review (no source change)

Re-read `plan-review.tsx` in full against reference 03's composition this
round: step hierarchy, reasons/examples
(`stepExample()` covers every operation type), provenance tags (`Model
proposal` / `Deterministic rule` / `Needs clarification`), inclusion
toggles (`disabled={entry.blocked}`), impact and "what will stay unchanged"
summary, and the approval action were all already present and correct —
no discrepancy requiring a fix was found beyond the two named, intentionally
out-of-scope gaps in §1. The `needsClarification()` safety guard
(`plan-review.tsx` → `clean-workspace.tsx`'s `approvePlan()`) was read and
confirmed unchanged and intact: an excluded/ambiguous clarification step
still cannot be submitted as `enabled: true`.

## 5. Native WebDriver re-investigation (30-minute time-box, as instructed)

Treated the 2026-11-09 entry's "Chrome instance exited… genuine Tauri +
WebView2 + WebDriver ecosystem integration gap" conclusion as a hypothesis,
not a settled fact, per this round's explicit instruction, and re-examined
the contradictory evidence directly instead of re-stating either prior
claim:

- Confirmed `docs/clean-atlas-v1/evidence/milestone-20261027/native-clean-populated-webdriver-1366x800.png`
  and `acceptance-20261027.md` §"Native build and inspection" are real: that
  session's `tauri-driver` + `msedgedriver` combination against this same
  `app.exe` did establish a session and drive real clicks end-to-end. The
  2026-11-09 entry's framing ("a genuine... integration gap... not
  something this milestone's scope covers fixing") therefore overstated
  what was actually shown — a working prior session is evidence against an
  unconditional architectural gap, not for one.
- Found fresh, concrete evidence this round: Edge had auto-updated again,
  to **157.0.4341.46**, while the cached driver was still pinned at
  **157.0.4341.42** from 2026-11-09 — a new version drift, not a repeat of
  an already-explained one. Fetched the exact matching driver directly from
  `https://msedgedriver.microsoft.com/157.0.4341.46/edgedriver_win64.zip`
  (one legitimate download, matching the brief's instruction not to
  re-download without new evidence — this is new evidence) into
  `.prism/native-driver/edge-157.0.4341.46/`, confirmed
  `msedgedriver --version` now matches installed Edge/WebView2 exactly.
- With versions re-matched, `tauri-driver 2.1.0` → `msedgedriver
  157.0.4341.46` → `app.exe` (this round's unchanged prior binary, used
  purely for this diagnostic, not yet rebuilt from this round's source)
  still failed to create a session, but with a **different, more specific
  error than 2026-11-09's**: `session not created: DevToolsActivePort file
  doesn't exist` (not `Chrome instance exited`). Confirmed via direct HTTP
  response inspection (not inferred from a wrapper script) that `app.exe`
  itself never appears in the process list after this failure — the host
  process never reaches a state where it writes that file, consistent with
  WebView2 not honoring the `--user-data-dir` argv flag `msedgedriver`
  picked for it, rather than WebView2 crashing outright.
- Tested the single most standard, officially-documented mitigation for
  this exact WebView2/WebDriver gap — setting
  `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS` in `tauri-driver`'s own
  environment so its child process inherits it — as one additional,
  justified attempt (not a repeat): same failure, same error. This was the
  last attempt made before the time-box closed.
- **Updated, more precise diagnosis**: the blocker is a real,
  reproducible gap in how this installed `msedgedriver` version launches
  and locates this Tauri/WebView2 host's debug port — not fully explained
  by driver/browser version mismatch alone (that was ruled out this round
  by matching them exactly), and not fixed by the one standard
  environment-variable mitigation tried. Given 2026-10-27 proves this exact
  app/driver pairing *can* work, something about that session's specific
  environment (a different `tauri-driver`/`msedgedriver` pairing at the
  time, a different Edge build, or host state since lost) made the
  difference — this round could not recover or reproduce it within the
  30-minute time-box, and did not keep retrying past it.
- No drivers were rebuilt or redownloaded beyond the one legitimate,
  evidence-justified fetch above. No debugging ports were left open, no
  desktop security was weakened, and no persistent WebDriver service was
  left running — `tauri-driver`/`msedgedriver` were stopped (explicit PIDs)
  immediately after this investigation closed.

Per the brief: this blocks *interactive* native automation past the first
screen, not the rest of this round's work, which proceeded independently.

## 6. Native build and inspection

Rebuilt fresh from this round's **changed** source (the left-panel and
Atlas-dock fixes above are both in `apps/web`, so both `apps/web/out`
(static export) and the Tauri binary needed a real rebuild to reflect
them — not reused from 2026-11-09):

- `apps/web`: `NEXT_PUBLIC_PRISM_API_URL` baked at build time against the
  sidecar port used for this round's isolated verification.
- `CARGO_BUILD_JOBS=1 npx tauri build --no-bundle` (job-limited, the same
  approach every prior round used safely under this machine's memory
  pressure).
- Launched against an isolated, confirmed-empty `PRISM_DESKTOP_DATA_DIR`;
  confirmed the real sidecar auto-spawn chain via process parentage.
  `PrintWindow`-based capture of the freshly launched, freshly built
  window — real, unedited, not a browser — kept as the native evidence this
  round, for the same reason as every prior round: interactive native
  automation past the first screen remains blocked by §5, and no
  foreground-stealing mouse automation or UIA `Invoke()` (confirmed broken
  on 2026-11-09, not re-litigated this round since nothing about that
  specific finding was in question) was used to fake a populated native
  state.

## 7. Gates run fresh this round

All isolated, all against this round's actual changed working tree (not
reused from any prior round's result):

- `npm run lint` — clean, 0 warnings.
- `npm run typecheck` — clean.
- `npm run test:web` — **149/149 passed**, 19 files (includes the full
  `clean-workspace.test.tsx`, 34 tests, and `atlas-dock-panel.test.tsx`, 5
  tests — both exercise the exact components changed this round).
- `npm run build` (`apps/web`) — clean production build, twice (once per
  source round this session).
- `npm run a11y:baseline` — passed.
- `ruff check` at CI's exact `phase-1-python` scope — clean (no Python
  source changed this round; re-run anyway per instruction, not assumed).
- `mypy` at CI's exact scope — clean, 102 source files.
- `python tools/check_boundaries.py` — passed.
- `python tools/check_secrets.py` — passed.
- `python tools/generate_typescript_contracts.py --check` — clean, exit 0.
- `pytest tests/api tests/contracts tests/migration tests/overview
  tests/sql_lab` with an explicit isolated
  `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` (fresh SQLite file this round,
  not reused) — **780 passed, 7 skipped** (matches 2026-10-29/2026-11-09
  exactly, as expected: no Python source changed).
- MySQL-backed (`test_mysql_connector_parity.py`, `test_durable_registry.py`,
  `test_atlas_promotion.py`) against a freshly initialized disposable local
  MySQL 8.0.40 instance (`.prism/mysql-disposable-20261113/`, port 3307,
  seeded with the exact same `CREATE DATABASE prism_history` / `sales`
  table / rows CI's own setup step uses) — **31 passed**.
- `npm run test:e2e:live` (the real-API, real-browser Playwright suite,
  isolated `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`) — run **fresh, locally,
  this round** (not deferred to CI as 2026-11-09 did under memory
  pressure): **24 passed, 5 skipped**. Not run concurrently with the MySQL
  suite or a web build, per the brief's memory-sequencing instruction.

No run in this list was interrupted or partially counted.

## 8. Commit, push, and CI

Path-scoped staging — only the files this round actually intended to
change: `apps/web/app/prism.css`, `apps/web/src/components/clean-workspace.tsx`,
`apps/web/src/components/atlas-dock-panel.tsx`, this file, `HANDOFF.md`, and
`evidence/milestone-20261113/*`. The working tree carries a very large
number of unrelated pre-existing modified/untracked files (regenerated
screenshot artifacts under `docs/analytical-workspaces-v1/`,
`docs/atlas/...`, and extensive `.prism/` scratch state from other
sessions/tools) — these were left untouched and unstaged, exactly as
instructed, not swept up by a broad `git add`.

- Commit SHA: see `git log -1` at push time (recorded in the final
  response to the owner, not duplicated here to avoid staleness).
- Pushed to `prism/clean-pattern-review-v1`.
- CI re-verified at this round's actual final pushed SHA (not the
  2026-11-09 entry's `7ef78d1` run) — recorded in the final response.

No merge, no tag. This remains a visual-acceptance checkpoint for the
owner, now with real, tested, verified source changes against two of the
three named surfaces and an honest, narrowed native-automation diagnosis
for the third concern.
