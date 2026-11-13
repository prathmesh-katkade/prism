# Clean + Atlas milestone close-out — 2026-11-13 (round 2)

Continued from `91826c31d0823e9e73f18fd99afff855001b17ee`,
`prism/clean-pattern-review-v1` (also remote HEAD at session start; remote
`main` unchanged at `c9472ca822293e8767ec7d8dc617e8be964232d8`), re-verified
before any edit. This entry corrects a misstatement in
`acceptance-20261113.md`, adds real native-interactive evidence (not just a
landing-screen `PrintWindow` capture), inspects the actual model
configuration and skip reasons, and adds test coverage for the quick
actions added that round.

## Correction

`acceptance-20261113.md` described itself as "the first round since
2026-10-24 to land application-code changes." That overstated the prior
gap: `7ef78d1` (2026-10-29) and `42f6f26` (2026-10-27) both contain real
source changes (the grid-based approval-footer fix and the root-cause
`.secondary` `!important` fix, respectively). Only the 2026-11-09 round
(`81e1125`) made no source change. Corrected in `HANDOFF.md` below.

## 1. Native interactive evidence (real, not a landing screen)

The 2026-11-13 (round 1) entry's native evidence was a `PrintWindow`
capture of the app's default landing screen only, honestly labelled as
such because interactive native automation was blocked. This round, the
owner granted a short foreground window (Minecraft was not running), so
real OS-level mouse/keyboard automation (`SetCursorPos`/`SendInput`-family
Win32 calls via PowerShell — not the UI-Automation `Invoke` pattern
confirmed broken on 2026-11-09, and not the sandboxed desktop "computer
use" feature, which this session does not have enabled) drove the actual
rebuilt `app.exe` end to end:

- **Real native file upload, for the first time this project has
  recorded.** Every prior round's HANDOFF entry back to 2026-10-27 lists
  driving the dataset-upload control as a named, unachieved gap (it opens
  a real Windows "Open" file dialog, a separate top-level window, not
  reachable by clicking inside the app's own WebView2 surface). This round,
  real keystrokes typed the fixture's path into that dialog's focused
  "File name" field and pressed Enter — a genuine native upload, not API
  seeding standing in for it. (API seeding was also used once, earlier in
  this round, purely to verify the sidecar was healthy before touching the
  UI — clearly a separate, disposable dataset from the one actually used
  for the native evidence below.)
- **Built the full real four-step fixture natively**: Trim Whitespace
  (APPLIED, real `/preview`→`/apply` round trip, found one genuine
  trailing-space row the fixture's visible text doesn't show), Category
  Mapping (DRAFT, real "Apply suggested grouping" click, 3→3 mapping),
  Convert Type (DRAFT, signup_date → datetime, blank date format — the real
  ambiguous-date clarification state: "5 distinct value(s)... match more
  than one plausible date reading"), Deduplicate Survivorship (DRAFT,
  customer_id). All four steps added via real clicks and real native
  `<select>` keyboard interaction (see "What didn't work at first" below),
  not scripted DOM manipulation.
- **Captured with step 2 selected**, matching the established
  before/after convention:
  `evidence/milestone-20261113b/native-clean-4step-dark-1382x839.png`.
  Confirms, in the real native build (not the browser): the `.clean-issues`
  left rail fits without scrolling at this window size, the collapsed
  "Current mapping 3→3" disclosure renders correctly, and the merged
  downstream-preview/disable-a-step hint line renders as one paragraph —
  the exact two Part A fixes from the first 2026-11-13 round, now confirmed
  in the shipped executable, not just the dev build.
- **Expanded "Current mapping" to answer the brief's visual-hierarchy
  question directly** (does collapsing it "preserve useful visual
  hierarchy and depth, or merely hide content to fit?"):
  `evidence/milestone-20261113b/native-clean-mapping-expanded-with-atlas-dark-1382x839.png`
  shows the full source→target list and "Review full mapping" button
  rendering correctly on expand, with the real Atlas dock conversation, the
  centre panel's mapping table, impact stats, and exception warning, and
  the Apply/Discard footer all visible together in the same frame —
  recipe, mapping, impact, exceptions, Atlas, and approval are legible
  together, not competing for space.
- **Plan review, rendered and visually compared against reference 03's
  composition, not read from TSX alone**:
  `evidence/milestone-20261113b/native-plan-review-dark-1382x839-{top,bottom}.png`.
  Confirms live: the 4-step progress rail with per-step status ("2 ready /
  0 excluded / 1 needs input"), provenance tags ("Deterministic rule" /
  "Preview checked" / "Needs clarification"), per-step Why-this-step/Example
  two-column grid, the exact real exclusion-reason text for the ambiguous
  Convert Type step ("Excluded until you decide. Ask Atlas for the date
  order, then this step can be included."), the right-side Atlas message,
  "What will stay unchanged" list, "Review boundary" text, and the footer
  ("2 included steps · 1 excluded · Revision 1" · "Back to preview" /
  "Approve included steps"). Returned via "Back to preview" without
  applying — nothing in the dataset was mutated by this inspection.
- **Reference's unsupported permissions mode and workflow stepper**: not
  present in the real screen, as expected — these remain named,
  intentional differences (§2 of `acceptance-20261113.md`), re-confirmed
  this round by direct visual comparison rather than re-asserted from
  memory. No backend state was invented to draw either.

### What didn't work at first, and the real fix (not a workaround)

Early clicks in this round silently landed on an unrelated Chrome window,
not Prism, because `SetForegroundWindow` does not actually bring a
background process's window to the foreground on Windows unless the
caller satisfies the OS's foreground-lock check — confirmed directly
(`GetForegroundWindow()` returned the Chrome window's handle right after a
call to force it to Prism's handle). Fixed with the standard, documented
workaround (a synthetic ALT keypress immediately before `SetForegroundWindow`,
which satisfies the same check a real user keystroke would), with a hard
check afterward that throws rather than clicking blind if it still didn't
take. Once fixed, every click in this round was verified landing on the
correct window. Native `<select>` elements also required full word prefixes
(`"res"`, not a repeated `"r"`) to reach entries sharing a first letter — a
genuine behavior difference from browser testing worth recording, not a
bug in the app.

No debugging ports were opened, no desktop security was changed, and the
window was returned to a collapsed, non-applied, non-mutating state before
being left for the owner.

## 2. Model configuration and quick-action behavior (inspected, not assumed)

The 2026-11-13 (round 1) entry only showed "Local model unavailable" and
did not say why. This round traced it to a real, specific cause and
verified the quick actions' request/pending/error/context behavior both in
the real native app and with new unit tests.

**Root cause of the default "Local model unavailable"**: `apps/api/src/prism_api/workspace_proposals.py:187`
defaults `PRISM_OLLAMA_MODEL` to an **empty string** when unset, while the
three other call sites that read this same variable
(`ai_analyst.py`, `atlas_bench_live.py`, `atlas_candidate_runtime.py`) default
to `"llama3.2:3b"`. Neither this round's desktop launch nor the 2026-11-13
round 1 launch set `PRISM_OLLAMA_MODEL`, so every Atlas-dock proposal this
project has shown in its default configuration has gone through this empty
value. This is a real, named inconsistency, not fixed here: changing a
model-selection default is exactly the kind of model-binding change this
engagement's brief has repeatedly ruled out making silently, and it isn't
this pass's call to make. Reported for the owner's own decision.

**With an explicit, isolated test configuration** (a separate sidecar
instance, not the one backing the native app above, so the native
evidence's own dataset was never touched by this): `PRISM_AI_PROVIDER=ollama
PRISM_OLLAMA_MODEL=qwen2.5:7b-instruct` against the same fixture, called
directly via `POST /api/v1/workspace-proposals` —

- The model is actually installed and reachable (`GET /api/tags` lists it
  among 11 installed models) and responded in realistic local-inference
  time (7.6s, then 1.7s) — this is not a connectivity or missing-model
  problem.
- Both calls were rejected by PRISM's own existing safety check at
  `workspace_proposals.py:234-241`: the model's explanation claimed "no
  missing values" while the real profile shows `amount` at 9.1% missing.
  The code comment there says this exact contradiction "occurred in a real
  desktop Ollama run" before — this is a known, intentional guard working
  as designed, not something this round broke or needs to fix.
- A second model (`qwen3:8b`) was tried once for comparison: it hit the
  10-second default timeout (`PRISM_OLLAMA_TIMEOUT_SECONDS`) rather than
  the contradiction guard — a different, also-real cause (`qwen3:8b` is
  larger and slower than `qwen2.5:7b-instruct` on this machine).
- **No successful (non-"unavailable") proposal was produced this round**
  despite two real, explicitly-configured, clearly-labelled attempts. This
  is reported honestly rather than retried indefinitely or faked: with
  this fixture, this local hardware, and these two models, the "Local
  model unavailable" state is what actually happens, not a configuration
  mistake on this round's part.

**Quick-action behavior**, verified live in the real native app (asking
"What should I review first?" then "Explain this step") and newly covered
by unit tests added this round (`apps/web/src/components/atlas-dock-panel.test.tsx`,
now 9 tests, up from 7):

- `"shows next-step quick actions after a turn completes, and each submits
  its own real intent"` — confirms the row is absent before any turn, each
  of the three buttons sends its own distinct, correct intent string
  through the same real `ask()`/`/workspace-proposals` call as any other
  turn, not a stub.
- `"hides the next-step quick actions while a request is pending, and
  keeps conversation context across them"` — confirms the row disappears
  the instant a request is in flight (matching the real native screenshots
  above, where it was absent during "Checking local model…"), and that a
  follow-up quick-action request carries the prior turn's intent and
  explanation as real `history`, not a blank slate — directly the
  "preserves context" requirement.

Both new tests pass; the full suite is reported in §4.

## 3. Release build configuration (inspected, confirmed correct)

The round-1 report built the native app once; this round inspected what
was actually baked into that build rather than assuming it. The frontend
static export the Tauri build packages
(`apps/web/out/_next/static/chunks/*.js`) contains the literal string
`127.0.0.1:8000` — the normal packaged sidecar port
(`apps/web/next.config.ts`'s own default,
`NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000"`), not the `:8010`
isolated-verification port used earlier in this engagement for manual
browser testing. The review executable does not depend on a temporary test
server; this was verified by inspecting the built artifact's own contents,
not by re-reading the build command.

## 4. Gates run fresh this round

- `npx vitest run apps/web/src/components/atlas-dock-panel.test.tsx` — **9
  passed** (2 new, 7 pre-existing), confirming the new tests don't regress
  anything already covered.
- `npm run test:web` — re-run in full after adding the new tests: **151
  passed**, 19 files (149 prior + 2 new).
- `npm run lint` / `npm run typecheck` — clean.
- **Live e2e skip inspection**: this round changed no application source
  (only a unit test file and docs — see §2), so the brief's own "don't
  rerun expensive unchanged suites without a reason" applied, and this
  suite's CI result at the current exact HEAD had already been verified
  green earlier the same day (§6 of `acceptance-20261113.md`: all 5 jobs,
  including `phase-4-live-e2e`, passing at `91826c3`). A fresh local run
  was still attempted anyway, as independent confirmation, with honest
  results reported rather than discarded:
  - **Attempt 1** (isolated storage, a non-conflicting API port): 23 of 24
    failed, 5 skipped, in 10 minutes against a normal ~2.8-minute run. The
    failures span every unrelated surface this suite covers (SQL Lab,
    History, Pattern Review, 100k-row tests, none of which this round or
    round 1 touched) — not a plausible real regression from a left-panel
    CSS/markup change and a new Atlas quick-actions row. This was run
    while this round's own native-app sidecar and two isolated
    model-configuration test sidecars (§2) were still live, and system
    free memory had dropped to ~2.3–2.8GB; this result is recorded as
    **resource-contended and not trustworthy**, not as a real regression.
  - **Attempt 2** (same isolated config, after stopping the model-test
    sidecars, free memory back to ~4GB): the harness's own background-task
    memory guard killed this run before it finished, reporting the system
    was critically low on memory session-wide (not specific to this
    command). Per that guard's own instruction, it was not restarted.
  - **Conclusion**: no fresh local pass/fail count for this suite is
    reported this round, honestly, because none was obtained cleanly. The
    only trustworthy evidence for this suite today is the already-verified
    CI result at the unchanged HEAD and this morning's own clean local run
    (24 passed, 5 skipped, recorded in `acceptance-20261113.md` §7) — nothing
    source-level has changed since either to cast doubt on it. The 5 skip
    names and reasons below come from reading the spec files' own
    conditional-skip logic directly, not from a run, so they stand
    independent of either attempt above:
  - `analytical-workspaces-proposals-live.spec.ts` —
    `test.skip(process.env.PRISM_AI_PROVIDER !== "ollama", "Live
    local-model provider is opt-in.")`.
  - `atlas-specialist-review-workflow-live.spec.ts` — same
    `PRISM_AI_PROVIDER !== "ollama"` gate ("Requires PRISM_AI_PROVIDER=ollama
    for a genuine specialist review.").
  - `analytical-workspaces-restart-live.spec.ts` — opt-in only when
    `PRISM_LIVE_RESTART_PROOF=1` is set; needs a second, independently
    started API process to complete, not a single `npm test` invocation.
  - `pattern-review-restart-live.spec.ts` — unconditionally
    `test.skip(true, ...)`: the first half of the same two-process restart
    proof, by design never runs to completion in one invocation.
  - `pattern-review-verify-cancellation-live.spec.ts` — opt-in only when
    `PRISM_PATTERN_VERIFY_TEST_DELAY_MS` is set to a nonzero value, to
    inject an artificial delay for a cancellation-timing race test.
  - **None of these 5 is a gap in Clean/Atlas visual-acceptance
    coverage**: two are opt-in live-model tests unrelated to this round's
    surfaces, two are halves of a multi-process restart proof this suite
    doesn't run end-to-end by design, and one needs an injected timing
    delay not relevant here.
- **Python skip inspection** (`pytest tests/api tests/contracts
  tests/migration tests/overview tests/sql_lab`, isolated
  `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`): exactly 7 skips, all inspected
  individually, none masking an untested Clean/Atlas visual-acceptance
  requirement:
  - `test_atlas_base_model_trust.py::test_verify_rejects_a_license_not_on_the_allowlist[]`
    — "empty license is rejected by the contract's min_length, not this
    function": the empty-string case is caught by schema validation before
    reaching the function this test targets — a real, different layer
    already enforces it, not a gap.
  - `test_atlas_candidate_trust.py::test_verify_rejects_an_executable_file_masquerading_as_an_allowed_type`
    — "Windows does not expose POSIX execute permission bits for this
    guard": this guard and its test are POSIX-specific; CI's
    `phase-1-python`/`legacy-regression` jobs run on `ubuntu-latest`, where
    this test actually executes. A Windows dev-machine limitation, not a
    CI gap.
  - `test_atlas_candidate_trust.py::test_verify_rejects_a_symlink_escaping_the_workspace`
    — "symlinks are not available in this environment": same reasoning —
    runs for real on CI's Linux runner.
  - Four `test_mysql_connector_parity.py` tests — "Phase 4 MySQL parity
    source is not configured": these are exactly the tests the separate
    MySQL-backed run (§ below) runs with `PRISM_PHASE4_MYSQL_URL` set; they
    are not silently missing, they are deferred to, and covered by, that
    run.
  - **None of these 7 skips represents an untested mandatory
    Clean/Atlas visual-acceptance requirement.** All are either
    environment-specific (covered on the real CI runner) or intentionally
    deferred to a separate run that was itself actually executed.
- MySQL-backed tests (disposable local instance, same seeding as CI):
  **31 passed** (unchanged from the first 2026-11-13 round — no backend
  source changed between the two rounds).

## 5. Commit, push, and CI

- Commit: adds the two new `atlas-dock-panel.test.tsx` tests, this file,
  and `evidence/milestone-20261113b/*`. Path-scoped staging only.
- HANDOFF.md corrected (the "first... since October 24" misstatement) and
  given a pointer to this entry.
- Pushed to `prism/clean-pattern-review-v1`.
- CI re-verified at this round's actual final pushed SHA — recorded in the
  final response to the owner, not duplicated here to avoid staleness.

No merge, no tag. `main` remains unchanged pending the owner's own visual
acceptance decision.
