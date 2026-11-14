# Clean + Atlas milestone close-out — 2026-11-14

Continued from `a7b8eae95e91f066e4386c9e2dcb05b33b80579c`,
`prism/clean-pattern-review-v1` (also remote HEAD at session start; remote
`main` unchanged at `c9472ca822293e8767ec7d8dc617e8be964232d8`), re-verified
before any edit. This entry resolves the health-score labelling ambiguity,
makes Atlas configuration failures actionable, closes the test-evidence
gap with real log-based causality (not a restated hypothesis), and
delivers a final native review package built through the same real
native-interactive method proven working last round.

## 1. Health-score ambiguity — resolved by labelling scope, not by changing numbers

Traced both values to their actual code paths rather than assuming either
was wrong:

- **Left recipe panel's number** (`draftPreview.projected_health.total`) comes
  from `POST /datasets/{id}/recipe-draft/preview`, which runs *every enabled
  draft step in sequence* (`_preview_recipe_steps` in `clean.py`) and reports
  the health of the resulting frame. This is the health **across the whole
  draft recipe**.
- **Centre panel's number** (`preview.projected_health.total`) comes from
  `POST /datasets/{id}/preview`, which runs *only the one operation in the
  request* against the dataset's current revision. This is the health **for
  that one selected step in isolation**.

Both were correct for what they measure; neither was stale. The screenshot's
93 (draft-wide) vs 92 (step-alone) is exactly what's expected once a later
draft step (Deduplicate Survivorship) recovers a bit more health than the
selected step alone would - not a bug, and not something to "fix" by making
the numbers agree.

**Fix: label the scope in the text itself** (`apps/web/src/components/clean-workspace.tsx`):

- Left panel / draft-recipe-wide previews: `"Projected health across the
  full draft recipe: N/100"` (two call sites: the merged recipe-note line,
  and the centre-panel draft-preview summary).
- Single selected-step preview: `"Projected health for this step alone
  N/100 (currently M/100)"`.
- Saved-recipe-wide preview: `"Projected health across this recipe's
  included steps: N/100"`.

No computed value changed - only the words around each one, so the
distinction matches what the UI actually measures.

**Mapped-label / unmatched-row / unmatched-distinct-value counts**: verified
already clearly distinguished, both in source and live in the rebuilt app
(see `native-clean-full-review-dark-1586x992.png`): the `clean-impact-summary`
stat tiles say "mapped labels" (3, a count of configured mapping rules) and
"unmatched rows" (8, a row count) as two separate tiles; the exceptions-tab
and the server-generated banner both separately say "N distinct value(s)"
(7, a distinct-source-value count, legitimately different from the 8-row
count since one unmatched value - "Bangalore" - appears in two rows). No
mislabeling found; no change needed here.

**Regression test added** (`apps/web/src/components/clean-workspace.test.tsx`):
`"labels the single-step preview's projected health distinctly from the
full draft recipe's, when the two legitimately differ"` - feeds genuinely
different health totals (92 vs 93) through the two real code paths and
asserts both scope-labelled strings render together, so a future change
can't silently reunify them into one ambiguous number.

## 2. Atlas configuration failures — made actionable, not collapsed

**Confirmed the actual configuration flow** (`apps/api/src/prism_api/workspace_proposals.py`),
including desktop sidecar startup: `PRISM_OLLAMA_MODEL` defaults to an
empty string at line 187 (the one call site, of four across the codebase,
that doesn't default to `llama3.2:3b`) - confirmed by reading the source,
not assumed from the prior round's finding.

**New, distinct failure causes** (previously all collapsed into one generic
"could not be used safely" message via a single broad `except` clause):

- `httpx.ConnectError` → `"Could not reach the local Ollama service. Start
  Ollama, then retry, or use manual controls."` - no model name (none was
  ever confirmed to exist), since nothing ran at all.
- `httpx.TimeoutException` → `"The local model ({model}) did not respond
  within {timeout}s. Retry, allow more time (PRISM_OLLAMA_TIMEOUT_SECONDS),
  or use manual controls."` - names the attempted model when one was
  resolved before the timeout.
- The pre-existing contradiction guard, 404-not-installed case, and the
  remaining generic "response could not be used safely" catch-all now all
  also carry the attempted model name (`model=` on every `_unavailable(...)`
  call after model resolution), not just on success.
- No secrets or stack traces are exposed in any of these messages - only
  the model name (operational, not sensitive) and the timeout value.
- The existing contradiction guard and fail-closed behaviour are untouched;
  this only adds cause-specific messages ahead of the same safety net.

**Frontend**: the dock's "Local model unavailable" header now shows the
attempted model in parentheses when the backend identifies one -
`apps/web/src/components/atlas-dock-panel.tsx`. Falls back to the bare
message when no model was ever resolved (provider misconfigured, or
nothing installed).

**New tests**: 3 backend (`tests/api/test_workspace_proposals.py` - timeout
names the model and says "did not respond within"; `ConnectError` is
distinct from both timeout and rejection and names no model; a malformed
response is distinct from a timeout and still names the model) and 2
frontend (`atlas-dock-panel.test.tsx` - names the model when known, falls
back when not). All pass.

**Real, observed outcome, exercised in isolated test storage** (three
separate isolated sidecar instances, never the one backing the native
evidence below):

- Default configuration (no `PRISM_OLLAMA_MODEL` set, the same as every
  desktop launch to date): auto-discovery picks `qwen2.5:3b` (first
  installed match in the preferred list). Asking it twice against the real
  fixture produced **one genuine success** (a correct explanation naming
  `amount` as the column with the most missing data, no contradiction) and
  **one genuine contradiction-guard rejection** on a different intent -
  reported exactly as observed, not retried further to chase a cleaner
  story.
- Explicit `qwen2.5:7b-instruct`: reachable and responds in realistic time,
  reproducibly rejected by the contradiction guard (model claims no
  missing values against a profile that shows 9.1% missing in `amount`) -
  a real, pre-existing, intentional safety case, not something this round
  changed.
- Pointing at an unreachable Ollama URL: produces the new, distinct
  "Could not reach the local Ollama service" message with no model name -
  confirmed live, not just in a unit test.

**Persistent-model decision needed from the owner** (prepared, not decided
here - see §5's final question): whether to set `PRISM_OLLAMA_MODEL`
persistently to `qwen2.5:3b` (the model auto-discovery already lands on by
default today, confirmed to sometimes succeed, sometimes correctly
rejected depending on the question) or leave auto-discovery as-is. Nothing
was hardcoded or silently changed either way.

## 3. Test-evidence gap — closed with real causality, not a restated hypothesis

**Inspected the actual failure logs first**, per instruction, rather than
re-asserting the "resource contention" hypothesis from the prior round's
closing notes. `apps/web/test-results/*/error-context.md` from the
2026-11-13 23-failed run were still on disk. The chronologically **first**
failure's captured page snapshot shows, verbatim: `status "Could not reach
the Atlas promotion status endpoint.": ATLAS · STATUS UNKNOWN`, `status
"Could not reach the platform readiness endpoint.": AI · STATUS UNKNOWN`,
and `heading "Overview could not establish a profile."` / `paragraph:
"Failed to fetch"`. Checked how many of the 21 failures that produced an
`error-context.md` share this exact signature: **21 of 21**. This is the
sidecar being completely unreachable from the browser for every single
test, not 23 independent regressions, and not something this round's
Clean/Atlas-dock source changes could cause (they touch no networking or
CORS configuration) - established from the logs themselves, not inferred.

**Stopped only task-owned services** before the controlled re-run: checked
for processes bound to every port this round's own testing had used
(8000/8010/8020/8021/8030/8031/8040/8041/3060-3063/3100) - none were still
listening, so there was nothing task-owned left to stop. The large number
of unrelated `node`/`msedgewebview2` processes still running on the
machine belong to a different, concurrent session and were left
untouched, consistent with "preserve unrelated changes."

**Ran the relevant live suite once, under controlled resources and
isolated storage** (`PRISM_LIVE_E2E_API_PORT` left at its default alongside
a fresh isolated `PRISM_ANALYTICAL_HISTORY_DATABASE_URL`, nothing else
running): **24 passed, 5 skipped, in 2.8 minutes** - the same count CI
itself already produces, and the same duration the suite takes when
nothing is competing for memory. Reported alongside, not instead of, the
earlier 23-failed run, with the precise, now evidence-backed explanation
above for why that earlier run failed broadly across unrelated surfaces.

**The 5 skip names and reasons**, read directly from each spec's own
conditional-skip logic (not from a run, so they stand regardless of either
attempt above):

- `analytical-workspaces-proposals-live.spec.ts` and
  `atlas-specialist-review-workflow-live.spec.ts` - both
  `test.skip(process.env.PRISM_AI_PROVIDER !== "ollama", ...)`: opt-in
  live-model tests, not exercised by a default `npm run test:e2e:live`
  invocation.
- `analytical-workspaces-restart-live.spec.ts` - opt-in only with
  `PRISM_LIVE_RESTART_PROOF=1`, needing a second independently-started API
  process.
- `pattern-review-restart-live.spec.ts` - unconditionally skipped; it is
  the first half of the same two-process restart proof, by design never
  completed in a single invocation.
- `pattern-review-verify-cancellation-live.spec.ts` - opt-in only with a
  nonzero `PRISM_PATTERN_VERIFY_TEST_DELAY_MS`, an injected-delay
  cancellation-timing test.

**None of these 5 is a gap in mandatory Clean/Atlas visual-acceptance
coverage** - all five are intentionally opt-in or two-process mechanics
unrelated to this milestone's surfaces.

**Regression and full gates re-run after this round's source edits**:

- `npx vitest run apps/web/src/components/clean-workspace.test.tsx
  apps/web/src/components/atlas-dock-panel.test.tsx` - focused regression,
  both files pass in full (35 + 9).
- `npm run test:web` (full suite) - **154 passed**, 19 files (151 prior +
  3 new).
- `npm run lint` / `npm run typecheck` - clean.
- `ruff check` / `mypy` at CI's exact `phase-1-python` scope - clean (mypy
  needed one real fix this round: `payload["model"]`'s dict value is typed
  `object`, requiring an explicit `cast(str, ...)` at each new call site -
  fixed, re-verified clean).
- `check_boundaries.py` / `check_secrets.py` / contract-check - all clean.
- **Isolated-DB pytest, explicitly labelled as the established subset**
  (`tests/api tests/contracts tests/migration tests/overview
  tests/sql_lab` - not the full repository test tree): **782 passed, 7
  skipped** (780 + 2 new; the 7 skips unchanged and already individually
  catalogued in `acceptance-20261113b.md` §4 - none touch Clean/Atlas
  either).
- MySQL-backed (disposable local 8.0.40 instance, fresh this round, CI's
  exact seeding): **31 passed**.

No run in this round was interrupted or counted as passed while
incomplete.

## 4. Final native review package

**Rebuilt because application source changed**, both layers the brief
named:

- The sidecar binary (`apps/api/build_sidecar.py` → PyInstaller
  `--onefile`, ~212MB) - required because `workspace_proposals.py` changed
  and that file is bundled as the desktop's `externalBin`, not run from
  source on the desktop path. Smoke-tested the frozen binary directly
  (real Ollama calls against it, not just a clean PyInstaller exit code)
  before trusting it in the full app.
- The Tauri app (`CARGO_BUILD_JOBS=1 npx tauri build --no-bundle`) - fresh
  SHA-256 `BB020752...`, confirming a genuine rebuild, not a stale reuse.

**Built via the same real native-interactive method proven last round**
(OS-level mouse/keyboard through PowerShell, not UI-Automation `Invoke`,
not the sandboxed "computer use" feature - that remains unavailable in
this session): a real native file upload (the proven method, not API
seeding) into the freshly rebuilt app, then the full real four-step
fixture (Trim Whitespace applied, Category Mapping, ambiguous Convert
Type, Deduplicate Survivorship), step 2 selected - matching the exact
fixture and selected step used throughout this engagement for
before/after comparison.

**Captured, all native (not browser) - labelled accordingly**:

- `native-clean-4step-dark-reference-1382x839.png` /
  `native-clean-4step-light-reference-1382x839.png` - reference-size, both
  themes. Both new health-scope labels ("...across the full draft recipe:
  93/100" and "...for this step alone 92/100 (currently 92/100)") confirmed
  rendering correctly in the rebuilt app, directly resolving the
  screenshot ambiguity that opened this round. Warm charcoal/brass palette
  preserved in both themes; nothing hidden to force a fit - the panel
  genuinely fits at this size, as established last round.
- `native-clean-normal-desktop-dark-1366x800.png` - the native window
  resized (via `SetWindowPos`, a new technique this round) to the normal
  desktop size. The Apply/Discard footer sits at the edge of the visible
  area at this smaller size - the same, already-disclosed limitation from
  every prior round's 1366×800 evidence, reachable by the panel's own
  scroll, not a new regression.
- `native-atlas-dock-real-result-dark-1382x839.png` - the Atlas dock
  showing the actual observed result from §2 ("Atlas proposed
  (qwen2.5:3b)" with its real explanation naming the real current
  mapping), not a fabricated success.
- `native-plan-review-ambiguous-excluded-dark-1382x839.png` - the plan
  review screen with the ambiguous Convert Type step genuinely excluded
  ("Needs clarification" tag, `Include` toggle off, the real exclusion
  text), matching reference 03's composition.
- `native-clean-full-review-dark-1586x992.png` - everything from this
  round together in one frame at the full reference size: the corrected
  health labels, the collapsed "Current mapping" disclosure from last
  round's fix, and the Atlas dock's real result, all visible and legible
  together without hiding anything to force a fit.

**Remaining differences vs the approved references** (named, not claimed
as replicated): the references' "Permissions" mode card and multi-stage
workflow stepper remain unsupported - no real backend state exists to draw
either honestly, unchanged from every prior round's finding.

No foreground-stealing automation was used on another application; the
owner's prior-round authorization for this exact method was treated as
still standing per this round's own brief ("real native interaction now
works through the documented alternative"), and Minecraft was confirmed
not running before any native interaction began.

## 5. Commit, push, and CI

Path-scoped staging only: the four changed source files
(`clean-workspace.tsx`, `clean-workspace.test.tsx`, `atlas-dock-panel.tsx`,
`atlas-dock-panel.test.tsx`), the backend fix and its tests
(`workspace_proposals.py`, `test_workspace_proposals.py`), this file,
`HANDOFF.md`, and `evidence/milestone-20261114/*`. The rebuilt sidecar
binary and desktop executable are build artifacts (gitignored), not
committed. The large pre-existing dirty/untracked tree from other
sessions was left untouched.

- Commit SHA, push status, and CI result at the final SHA: recorded in the
  final response to the owner (not duplicated here to avoid staleness).

No merge, no tag. `main` remains unchanged pending the owner's own visual
acceptance decision.
