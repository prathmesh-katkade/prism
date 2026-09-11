# Phase 1 · Unit 03 — CI and coexistence gates

**Objective:** Turn the Phase 1 rules into deterministic merge gates.

**Delivered:** Python/Node CI jobs for linting, typing, API contracts, generated contract freshness,
dependency boundaries, secret scanning, accessibility baseline, and migration-parity hooks.

**Validation:** New Python suite passed 5/5; legacy Auto Cleaner evaluation passed 8/8; legacy
modules compiled and Streamlit 1.50.0 was present.

**Risk:** The local environment is Python 3.9; CI remains the Python 3.11 promotion gate. Full
interactive Streamlit browser smoke testing is not represented by this command-line check.

**Rollback:** Revert the additive CI jobs and foundation paths; the previous legacy CI job remains.
