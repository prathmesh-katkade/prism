# Phase 1 test policy

New code must pass formatting/lint, strict Python and TypeScript type checks, deterministic unit
and OpenAPI contract tests, dependency-boundary checks, a static accessibility baseline, and
secret scanning. Workflow migration adds Streamlit-versus-new parity fixtures before a release
channel can move from `legacy` to `shadow` or `enabled`.

Provider-backed Gemini evaluations and network corpus checks remain non-blocking scheduled
evidence because they are quota/network dependent.
