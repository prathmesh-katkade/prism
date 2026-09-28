# Statistical clarification checkpoint, 2026-09-28

Status: implemented and locally verified. The first release remains open.

## Supported calculation

Atlas now accepts a typed declaration for PRISM Stats Lab's independent t test, one-way ANOVA, chi-square test, or Pearson correlation. It checks both column names against the active uploaded dataset, requires the matching design declaration, and uses Stats Lab's deterministic method suggestion before execution. The model cannot nominate the executable statistical tool. The journal records the selected method and columns, design, active revision and source fingerprint, sample count, exclusions, full Stats Lab result and warnings, policy version, and a run-scoped evidence ID. The result remains visible in the investigation UI.

For a statistical objective without that declaration, Atlas persists one targeted question and enters a waiting state. The worker slot is released. An answer is accepted once after validation against the same dataset revision. Resume skips the completed profile. A changed dataset revision rejects the answer with 409. Waiting cancellation preserves completed evidence. An answered request retried with the same answer returns the same run.

## Real startup evidence

`verification/disposable-startup-result.json` contains the complete two-process uvicorn record. The second uploaded fixture contains five pairs `(1,2), (2,4), (3,6), (4,8), (5,10)`. Atlas run `atlas_17c6a83a2b3a47099c57e8c413b36042` waited on the first process, retained the same question after restart, then computed Pearson r=1.0, p=0.0 as reported by Stats Lab, five analyzed rows, zero exclusions, revision 0. The profile step had one attempt. These expected values can be checked directly from the fixture; the p value is Stats Lab's numerical output. The answer states that the association does not establish causality. The production-history backup SHA-256 stayed `03bbc35cb97e84abc1a92d54a9f5fbeb3592d5b208c6d0c01d397afdffcc6afc` before and after. The backup is local and untracked. `verification/startup-1.log`, `startup-2.log`, and `stat-disposable-startup.txt` retain raw launch output.

The desktop Playwright path waited, submitted the declaration, opened the stored statistical computation, and passed 1/1 against an isolated store. The mobile path at 390px passed 2/2 checks, including serious/critical axe violations equal to zero and horizontal overflow at most one pixel. See `verification/live-stat-final.txt`, `live-mobile-final.txt`, `atlas-stat-evidence.png`, and `atlas-stat-mobile.png`. The earlier failed Playwright selector run and corrected pass remain in their separate raw files.

## Gates and limits

Python: 606 passed, 7 skipped on an isolated SQLite URL. Web unit: 85 passed. Web lint, typecheck, production build, Ruff, mypy (90 source files), boundary check, secret check, and generated contract check passed. Raw Python, web, and build output is in `verification/stat-*-gates.txt` and `stat-web-build.txt`.

The current Stats Lab execution is synchronous. Atlas checks policy before dispatch and records a terminal result, but a running statistical calculation has no preemptive cancellation or independent runtime limit. The first release is therefore still blocked on those controls, actual specialist message provenance, final workflow acceptance cases, concurrency and p95 measurements, and full MySQL/live browser gates. Existing promotion pointers were not changed.
