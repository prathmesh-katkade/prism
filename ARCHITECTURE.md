# PRISM platform architecture

## Dependency direction

`apps/web` and `apps/desktop-shell` depend on TypeScript shared packages and the public HTTP
contract only. `apps/api` depends on Python shared packages and exposes the canonical OpenAPI
document. Legacy Streamlit remains isolated at the repository root and is not an import target
for new applications.

```text
web / desktop -> api-contracts + design-system + HTTP/SSE -> api
api -> api-contracts + analytical-schemas + atlas-interfaces + config
legacy Streamlit -> existing modules (reference-only)
```

No application may import another application's implementation, and no new application may
import `app.py`, `modules/`, or the legacy `api/` prototype.
