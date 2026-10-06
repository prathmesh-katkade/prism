# Clean Pattern Review v1 — acceptance matrix

Baseline snapshot: 2026-10-07, branch `prism/clean-pattern-review-v1`, branched
from verified `origin/main` at `bc72625` (tag `prism-native-v1.0`, CI success
confirmed via `gh run list` immediately before branching — not assumed).

| Area | Status | Evidence |
|---|---|---|
| Baseline gates | Passed | Fresh checkout, dependencies installed per `.github/workflows/ci.yml`'s own commands. Python: **1,312 passed, 7 skipped, 43 warnings in 176.15s**. Web: **106 passed across 16 files**. lint, typecheck, build, a11y, Ruff, mypy, boundaries, secrets, generated-contract check: all passed. No MySQL source configured for this baseline run (4 of the 7 skips). |
| ADR 0025 | Written | `docs/architecture/adr/0025-clean-pattern-review-v1-boundaries.md`, defines reuse of source identity/preview-apply/validation-rule infrastructure, new durable concepts (pattern findings/scans, review decisions), detector/sampling/extraction/context rules, and explicit deferrals, before any detector code exists. |
| Detectors | Not started | — |
| Interface (Patterns panel) | Not started | — |
| Evidence/sampling | Not started | — |
| Review decisions (accept/ignore/suppress) | Not started | — |
| Extraction/standardisation | Not started | — |
| Context-dependent patterns | Not started | — |
| Reusable validation (pattern rule kind) | Not started | — |
| Fixtures (business/scientific) | Not started | — |
| 100k performance | Not started | — |
| Visual/regression evidence | Not started | — |
| Final gates (incl. full MySQL-backed live suite) | Not started | — |
| Landing | Not started | No release claim. |

This file is updated as work proceeds; it is not a snapshot of a finished
feature.
