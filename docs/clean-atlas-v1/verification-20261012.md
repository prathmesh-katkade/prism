# Clean + Atlas continuation verification — 2026-10-12

Starting feature SHA: `282bbbde23c7c427655d75f0b70da1e6223d1dd0`.
Starting remote main: `c9472ca822293e8767ec7d8dc617e8be964232d8`.
This record covers the intentional, uncommitted date-clarification work carried over from Claude and the subsequent GUI and release work. The source SHA and final release status must be filled from the final commit and CI run; the starting SHA is not the new build identity.

## Visual evidence and reference comparison

- Approved composition: [`../clean-pattern-review-v1/references/clean-approved.png`](../clean-pattern-review-v1/references/clean-approved.png); approved palette: [`../clean-pattern-review-v1/references/palette-a-charcoal-brass.png`](../clean-pattern-review-v1/references/palette-a-charcoal-brass.png).
- Populated browser evidence, with two actual draft steps and a category-mapping preview: [`evidence/current-browser-audit/clean-current-1586x992.png`](evidence/current-browser-audit/clean-current-1586x992.png).
- Equal-size side-by-side: [`evidence/current-browser-audit/clean-reference-current-side-by-side.png`](evidence/current-browser-audit/clean-reference-current-side-by-side.png). Panel crops: [`left`](evidence/current-browser-audit/clean-left-panel-close-up.png), [`right`](evidence/current-browser-audit/clean-right-panel-close-up.png).
- Dark/light and 400px captures for Clean, SQL Lab, Visualize, Reports and Pattern Review are in `evidence/current-browser-audit/`. These are browser evidence. The packaged desktop app requires a separate native capture after rebuilding.
- The [connected browser walkthrough](evidence/current-browser-audit/clean-atlas-connected-browser-walkthrough.webm) records the real eight-row upload, two Clean draft steps, mapping review and navigation through SQL Lab, Visualize, Reports and Pattern Review. It is a browser recording, not a native desktop recording. The full live test suite supplies the stronger apply/save/refresh proof.

The reference uses illustrative counts and suggested mapping text. Current values are calculated from the eight-row fixture; its deterministic mappings are labelled as the current mapping, not AI suggestions. The app keeps Atlas available as a real inspector tab and header launcher. Current centre review shows a scrollable mapping table, exceptions and the first affected source rows together at 1586×992. The approved image has six mapping labels and five affected rows visible; the current seven-label fixture and warning allow fewer affected rows above the fixed Apply bar. The right inspector includes a real Preview checks card absent from the concept image. No exact pixel identity is claimed.

The capture was repeated after the final narrow-layout fix. At 400 by 844 pixels, the source/title and workflow controls occupy separate rows; the review, Apply/Discard actions and step inspector appear in document order without a fixed bar covering the recipe. [`Clean narrow top`](evidence/current-browser-audit/clean-dark-400x844.png) and [`Clean narrow Apply`](evidence/current-browser-audit/clean-dark-400x844-apply.png) were inspected. The screenshot script rejects document-level horizontal overflow in all five workspaces. The table itself scrolls horizontally for individual columns. The browser captures used device-pixel ratio 1 and are not native desktop captures.

At 1440 by 900 pixels, the last visual audit exposed an affected-row table starting below the fixed desktop Apply bar. The mapping table's scroll window now adapts to viewport height: the final [`1440 by 900 capture`](evidence/current-browser-audit/clean-current-1440x900.png) shows the first affected source row and mapping review together. At 1586 by 992 pixels, the larger mapping window remains. At 3440 by 1369 pixels, measured browser content is centered at x=780 with a 2060px workspace, 360px recipe, 1368px review and 330px inspector; computed title size is 30px and document scroll width equals viewport width. [`Wide capture`](evidence/current-browser-audit/clean-current-3440x1369.png) and [`metrics`](evidence/current-browser-audit/clean-browser-wide-metrics.json) show broad side margins. This is browser evidence only; actual Windows scaling and native window dimensions could not be confirmed after the Computer Use denial.

## Changes at this checkpoint

- Preserved and completed the bounded date-order clarification contract. Choosing day-first or month-first issues a typed Clean re-preview; it cannot apply a mutation. The original proposal and selected choice remain inspectable. Stale responses, changed source revisions and malformed stored turns are rejected.
- Added the Clean header Atlas launcher, preview checks, and keyboard/pointer pane resizing. Kept the existing single inspector and the step-number/editing-index fixes.
- Corrected a multi-step flow: an existing downstream draft preview no longer hides the editor for a new mapping or duplicate-survivorship step.
- Collapsed bulk mapping controls during review and bounded mapping-table scrolling so affected source rows stay visible. Raised dark-theme muted/state contrast and styled Atlas's cancel action to satisfy real axe checks. Narrow Clean panes use a zero-minimum grid track and wrap long titles/actions.
- Added an absolute `PRISM_DESKTOP_DATA_DIR` override for isolated packaged-app smoke sessions. With the variable unset, desktop storage stays at Tauri's existing OS app-data location.
- Corrected the narrow Clean header after inspecting the 400px screenshot: the container breakpoint now wins the CSS cascade, the title and workflow no longer overlap, and the Apply bar follows the review pane in document flow. The desktop Apply bar remains fixed.
- Bounded the desktop mapping-table scroll window by viewport height, keeping an affected source row visible above the Apply bar at 1440 by 900 pixels without hiding the mapping review.

## Connected proof and performance

The full live browser suite exercised sample discovery, full verification, decision persistence, extraction preview/apply, correct-source handoff, chart inspection and report refresh through real FastAPI. A separate two-invocation SQLite proof created a report, a Pattern Review acceptance and a saved validation rule, then stopped that API process. A second API process using the same isolated database reopened the report and rule, showed two exact exception rows on a compatible new dataset, and returned HTTP 422 for an incompatible schema. The first second-invocation test found its saved rule inside a collapsed Validation disclosure; the test now opens that disclosure before asserting visibility. Both restart tests then passed. Logs: `.prism/final-restart-seed-20261012.log`, `.prism/final-restart-proof-20261012.log` (failed attempt), `.prism/final-restart-proof-fixed-20261012.log`.

An opt-in, server-side delayed verification of 20,000 rows was cancelled after 6,000 rows. The terminal job state was `cancelled`, no verified finding was published, and the browser observed a 500ms cancel response. The delay is test-only and absent from normal suites. Log: `.prism/final-cancellation-proof-20261012.log`.

The final-source 100,000-row SQLite browser run measured sample discovery 19,656ms, full verification 914ms, exception-page retrieval/render 418ms, extraction preview 17,875ms and apply 32,502ms. The disposable-MySQL run measured 20,143ms, 911ms, 910ms, 16,336ms and 30,982ms respectively. These are end-to-end local browser/API wall times at 1440 by 900 pixels on an AMD Ryzen 5 9600X (6 cores, 12 logical processors), with no warmup or threshold; they do not isolate API CPU from browser rendering. The MySQL server used a new disposable data directory on port 3311. The extraction paths remain the largest measured latency. Raw timings are in `.prism/final3-live-sqlite-20261012.log` and `.prism/final3-live-mysql-20261012.log`.

The packaged `app.exe` was built from the feature source and launched with `PRISM_DESKTOP_DATA_DIR` and `PRISM_ANALYTICAL_HISTORY_DATABASE_URL` pointing to `.prism/desktop-user-test-20261012`, never the owner's installed data. Dataset `ds_de379f05f8c44dfca7d30c872029bd3c`, eight rows, revision 0 and fingerprint `d4a9de1eb577fc3677fbd0763e473f637662bcf78e0ff293a4a3eb8c12b611bf` remained identical across a real stop/start of the app and its sidecar API. Evidence: [`before`](evidence/restart-before-20261012.json) and [`after`](evidence/restart-after-20261012.json). The app remains open on the isolated user-test data. Native window inspection and screenshot through Computer Use were rejected by automatic approval review with “Computer Use was not approved to use app”; browser images are clearly labelled browser evidence. Native visual acceptance remains open.

## Fresh verification and failed attempts retained

| Gate | Result | Conditions / notes |
|---|---|---|
| Web lint and typecheck | Passed | Final source logs `.prism/final2-lint-20261012.log`, `.prism/final2-typecheck-20261012.log`. |
| Web unit tests | 139 passed, 19 files | `.prism/final2-web-tests-20261012.log`. |
| Accessibility baseline | Passed | `.prism/final2-a11y-20261012.log`. |
| Web production build | Passed | Next.js 16.3.3; `.prism/final2-web-build-20261012.log`. |
| Ruff | Passed | Repository CI scope, `.venv`; `.prism/final2-ruff-20261012.log`. |
| mypy | Passed, 102 source files | Repository CI arguments; `.prism/final2-mypy-20261012.log`. |
| Full pytest | 1,381 passed, 7 skipped, 43 warnings | Final source, isolated SQLite at `.prism/final2-full-pytest-20261012.sqlite`; `.prism/final2-full-pytest-20261012.log`. The seven skips: one invalid-license contract case superseded by field validation; two Windows filesystem capability guards; four MySQL parity cases without the Phase 4 source in this SQLite run. MySQL parity was run separately. |
| Boundaries / local secrets / generated contracts | Passed | Final-source `.prism/final2-*` logs; contract generator run, then check. |
| Desktop/mobile visual Playwright | 14 passed | Final source run `.prism/final2-visual-20261012.log`. Initial contrast failures and fix remain in earlier logs. |
| Disposable MySQL Python parity groups | 31 passed, 1 warning | Final source against fresh `prism_history_parity_final`; MySQL 8.4.9 on port 3311 under `.prism/mysql-disposable-20261012-0430`, confirmed via `@@datadir`; `.prism/final3-mysql-python-parity-20261012.log`. |
| Full SQLite live browser | 24 passed, 5 skipped | Final source, fresh isolated SQLite database; `.prism/final3-live-sqlite-20261012.log`. |
| Full MySQL live browser | 24 passed, 5 skipped | Final source, fresh `prism_history_final5` database on verified disposable MySQL port 3311; `.prism/final3-live-mysql-20261012.log`. |
| Packaged desktop build/restart | Built and genuinely restarted; final rebuild pending | Isolated user-test dataset persisted. Native visual inspection rejected by automatic approval review. |

The first system-Python invocations of Ruff, mypy and contract check failed for missing dependencies. They were rerun successfully from `.venv`; no assertions or gates were weakened. The first visual and SQLite-live failures above are retained as evidence of the fixes. A MySQL live rerun against a reused history database failed two strict locators because saved names were duplicated; a new disposable database passed all 24 tests, and the final-source run uses another new database. The first independent Pattern Review restart proof found the saved rule inside its collapsed disclosure; the test now opens it and both restart proofs pass. No test assertion was removed. The five normal live-suite skips are: two genuine-Ollama opt-ins, two independent-process restart opt-ins and one server-delay cancellation opt-in; the restart and cancellation proofs were run separately.

## Release status

Not released at the time of this entry. Final packaged rebuild, native desktop visual approval, exact-SHA CI and main integration remain mandatory. Production history, the dirty canonical checkout, generated Atlas evidence and unrelated work are untouched.
