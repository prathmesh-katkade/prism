# Clean + Atlas visual corrections — 2026-10-27

Starting source: `14ed071`, `prism/clean-pattern-review-v1`. User confirmed this
session could take ownership. Existing generated screenshots, recordings and
`next-env.d.ts` changes were preserved and excluded from this checkpoint.

## Findings and corrections

- **Contradiction with the previous acceptance report:** the switches were not
  compact in the rendered page. Chrome MCP measured both at **34 × 36px**, with
  `min-height:36px` and `padding:7px 9px`. The generic inspector input selector
  overrode the intended switch geometry. Text-field styling now excludes
  checkboxes/radios, and switches explicitly reset padding/min-height. Measured
  after: **34 × 19px**, `min-height:0`, `padding:0`.
- Current-mapping and exception actions had no complete shared secondary-button
  treatment. Clean now scopes a consistent bordered, raised secondary treatment
  with hover, disabled and pressed states; mapping/exception actions use the
  existing icon component.
- The mapping summary now has aligned source/arrow/target columns, separators
  and a readable heading. Recipe rows and downstream-summary spacing are tighter;
  disclosure titles use readable sentence-case labels instead of tiny capitals.
- The inspector's operation form no longer adds a nested raised card. Settings
  use compact labels, switches and spacing. Impact counts are aligned as labelled
  rows; exception inspection remains explicit.
- Atlas user requests and responses are visually distinct. The computed section
  no longer adds another inset panel. Preview checks have a segmented strip
  derived from the existing four check outcomes, with the existing text list
  retained; it is not a confidence estimate. The composer uses the shared primary
  action. No model request/binding/proposal semantics changed.
- Corrected misleading loading copy claiming the profile was never computed
  twice. This pass does **not** implement backend profile caching/deduplication.

## Verification actually performed

Isolated API databases: `.prism/visual-audit-20261027/history.sqlite` and
`sql.sqlite`. Synthetic seven-row fixture, never a user dataset. Four draft
steps: category mapping, trim whitespace, ambiguous date conversion, drop
duplicates. Mapping preview: four changed rows, three unmatched rows. No Apply
was clicked. This differs from the reference's illustrative values and applied
first step; screenshots are composition evidence, not pixel-identical states.

- Browser MCP: measured switches before/after; explicit 1586 × 992 and 400 × 844
  viewports, both themes, no horizontal document overflow. An initial window
  resize request to 400 produced an actual 500px viewport; replaced it with
  explicit device emulation and verified `innerWidth === 400`.
- Keyboard: focused case-sensitive switch, pressed Space; checked became false,
  `:focus-visible` was true, and Apply disappeared until a new preview. No
  cleaning authorization behaviour weakened.
- Lint and TypeScript passed. Web tests: **149 passed across 19 files**. Initial
  run failed one text assertion for the deliberately renamed Impact heading;
  updated that assertion without removing its ordering/behaviour checks, then
  reran successfully.
- Accessibility baseline, dependency boundaries, contract generation check and
  local secret scan passed.
- Backend source/contracts were not changed. Full Python/MySQL/complete live
  suites were not rerun in this scoped presentation pass; prior results are not
  represented as fresh results.

Screenshots under `evidence/milestone-20261027/` are browser captures against the
real isolated API, not generated mockups or native captures:

- `clean-dark-1586x992.png`
- `clean-light-1586x992.png`
- `clean-dark-400x844.png`
- `clean-light-400x844.png`

## Limits

No claim of exact visual acceptance, complete release readiness or a percentage
improvement. The inspector still scrolls when all settings, checks and handoffs
are present. SQL Lab/Visualize restyling and backend duplicate profiling remain
separate work. The added Atlas check strip is covered by existing component
fixtures; a new real-model proposal was not run for this presentation change.

Native build/inspection result is recorded below after completion.

## Continuation — completion pass (same day)

Resumed from this exact checkpoint: the single-job `npx tauri build --no-bundle`
the interrupted session started had actually **finished** (`Finished release
profile... Built application at .../app.exe`, logged in
`.prism/visual-audit-20261027/desktop-build.log`) moments before this session
began — it was not still running, contrary to what the handoff note assumed.
Confirmed via file timestamp (`app.exe` written seconds before this session's
first command) and no `cargo`/`rustc`/`link.exe` process present. The dev
API/Next server were confirmed stopped, as stated. `next-env.d.ts` and all
pre-existing generated screenshots/recordings were left untouched.

### Further findings and fixes this pass

- **Root-caused the "secondary class without complete treatment" symptom**,
  rather than patching individual buttons further: a bare, unscoped
  `.secondary { background:transparent !important; ... }` rule sat inside the
  `.overview-workspace` CSS block (every sibling rule in that block is
  properly `.overview-*`-scoped; this one rule was missing its prefix — an
  accidental scope omission, not an intentional app-wide default).
  `!important` made it win over every other workspace's own `.secondary`
  styling regardless of selector specificity, which is why `Save recipe`,
  `Review full mapping`, `Recompute preview` and `Inspect exceptions`
  rendered fully transparent despite the new `.clean-workspace
  button.secondary` rule. **Fix**: removed the three `!important`s (refactor,
  not another override) so normal cascade/specificity applies. Audited every
  `className="secondary"` usage across all 14 consuming components for any
  *other* element-selector rule that would now newly out-specify the bare
  default once its `!important` was gone; found four real ones
  (`.workspace-proposal button`, `.report-item button`, `.viz-filter-chips
  button`, `.query-toolbar button`, `.query-toolbar-more-menu button`) and
  split each into a shared-layout rule plus a `:not(.secondary)`-gated color
  rule, preserving every non-conflicting property (padding, width, cursor,
  border) those buttons still need. Verified: `getComputedStyle()` confirmed
  `Save recipe` now renders the real raised gradient fill; spot-checked
  Visualize's "+ Add filter", SQL Lab's toolbar and its "⋮" more-menu
  (Format/Plan/Join checks/Find CTEs) and Reports render correctly, not
  regressed.
- **Measured, not assumed, the left-panel "sections fall below viewport
  sooner" complaint**: `getBoundingClientRect()` on the populated recipe nav
  showed it extending 107px past the 992px-tall viewport (History cut off).
  Tightened `.clean-recipe-tip`, `.clean-current-mapping`/
  `.clean-mapping-suggestion` margins/padding, mapping-list row padding, and
  `.clean-disclosure` summary min-height/padding — all modest, specific
  reductions justified by the measurement, not a blind density pass.
  Re-measured after: the nav now ends exactly at the 992px fold (0px
  overflow) in the same populated state — all five sections (Saved
  recipes/Issues/Validation/Patterns/History) visible without scrolling.
  Also trimmed `.clean-inspector-impact`, `.clean-review-card` and
  `.clean-preview-checks` margins/padding on the right panel; re-measured
  `scrollHeight` there: 1341px → 1316px (clientHeight 890px). The inspector
  **still scrolls** when operation settings, impact, the review card, preview
  checks and both handoff sections are all present for one step — this is
  real content volume (every one of those sections is substantive and
  real-data-backed), not wasted whitespace; not claiming it fits, per the
  brief's "do not hide necessary warnings merely to fit the image."
- **Atlas composition, verified against three real local-model turns** (not
  assumed from the unverified interrupted patch): restarted the sidecar with
  `PRISM_AI_PROVIDER=ollama` (confirmed `AI · LOCAL (OLLAMA)` in the header,
  not the deterministic fallback) and asked three real questions. Two came
  back as genuine safety refusals ("Local model unavailable — The local model
  response could not be used safely") and one as a real explanation-only
  response from `qwen2.5:3b` — consistent with this project's own prior,
  documented finding that small local models don't reliably produce
  structured output. All three render correctly: the user request in its own
  bordered box, the response/refusal without a redundant inset panel, the
  evidence-disclosure triangle preserved on every turn, no fabricated
  confidence anywhere. Confirmed no horizontal overflow at 1586×992 with
  three turns of real content, and `innerWidth === 400` (not the first
  session's reported `500px` resize bug — used `emulate` with an explicit
  viewport string this time) with the same three-turn conversation, both
  themes. Evidence: `atlas-dock-real-turns-{dark,light}-1586x992.png`,
  `atlas-dock-real-turns-dark-400x844.png`.
- **Keyboard**: re-confirmed the Space-toggles-switch/`:focus-visible`-paints
  behaviour independently against the rebuilt CSS (not assumed carried over
  from the interrupted session's own unverified claim) — same result, still
  correct.

### Native build and inspection — completed, not deferred

Rebuilt for real from this round's final source (`CARGO_BUILD_JOBS=1`, the
same job-limited approach the interrupted session had already proven safe
under this machine's memory pressure): clean `release` build in 2m13s,
`apps/desktop-shell/src-tauri/target/release/app.exe` (22.4MB, timestamped
this session).

Launched against isolated storage
(`.prism/visual-audit-20261027/native-{history,sql-lab}.sqlite`, confirmed
empty before use — never a real user database) and `PRISM_AI_PROVIDER=ollama`.
Confirmed the real sidecar auto-spawn chain via `Get-CimInstance
Win32_Process` parentage (`app.exe` → launcher → `prism-api.exe`), and via
`GET /api/v1/overview/datasets` returning `[]` against the fresh store, then
the one uploaded disposable fixture after seeding it.

**For the first time in this project's history** (every prior HANDOFF.md
entry back to 2026-10-12 documents raw native-window automation as not
landing reliably), real WebDriver-driven interaction succeeded end to end:
`tauri-driver` + the matching `msedgedriver` (both already present in
`.prism/native-driver/`, not newly installed this session) created a real
WebDriver session against the packaged `app.exe`. Verified real clicks
landing correctly (Clean tab, "Open Overview", "Data objects", the Overview
tab, "+ Add step", the Operation and Column comboboxes, "Apply suggested
grouping", "Preview") and `GET /screenshot` returning genuine native
WebView2-rendered frames — not a browser, not `PrintWindow` alone. Built the
same category-mapping comparison state used throughout this round's browser
verification, entirely through real native clicks, and captured it:
`evidence/milestone-20261027/native-clean-populated-webdriver-1366x800.png`.
A `PrintWindow`-based capture of the freshly-launched window
(`native-window-launch-printwindow.png`) is kept as a second, independent
confirmation method.

**Not achieved**: driving the dataset-upload flow itself natively. The
"Choose dataset" control invokes a native OS file picker (not a standard
HTML `<input type="file">` WebDriver can set directly), and driving a real
Windows file dialog via raw input was judged too failure-prone to attempt
inside this pass — the dataset used for the native comparison screenshot was
seeded directly through the sidecar's own upload endpoint (the same one the
UI's own control calls), which the frontend's own existing
most-recent-dataset fallback then picked up once the Clean tab was opened for
real. This is a real, named limitation, not silently worked around.

All WebDriver/launcher processes (`tauri-driver.exe`, `msedgedriver.exe`, the
earlier manually-launched `app.exe` instance) were cleanly stopped between
attempts to avoid orphaned sidecars holding port 8000; the final `app.exe`
left running for the owner is a normal launch, not WebDriver-attached, so it
behaves exactly like any user-launched instance.

### Gates re-run fresh after all changes above

Web: lint (0 warnings), typecheck, `test:web` (**149/149 passed**, 19 files),
production build, a11y baseline, boundaries, `contract:check` — all clean.
Backend: `ruff check` and `mypy` at CI's exact `phase-1-python` scope —
clean. `python tools/check_secrets.py` — passed. Backend source/contracts
were not touched this round either; the full Python/MySQL suites were not
rerun for the same reason the interrupted session gave (no backend change to
exercise) — this is a scoping decision carried forward consistently, not an
oversight.

### Build identity

- Source SHA this round builds from: `14ed071` (branch
  `prism/clean-pattern-review-v1`), working tree carrying this round's
  uncommitted changes until committed below.
- Native executable: `apps/desktop-shell/src-tauri/target/release/app.exe`,
  rebuilt this session, left running for the owner in the populated
  comparison state shown in
  `native-clean-populated-webdriver-1366x800.png`.
- Browser evidence (`clean-*-1586x992.png`, `clean-*-400x844.png`,
  `atlas-dock-real-turns-*.png`) is explicitly labelled separately from the
  native evidence above — matched-bundle `next start` + standalone sidecar,
  not the packaged window.
