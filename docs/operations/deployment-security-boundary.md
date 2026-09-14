# Deployment security boundary

## Current support boundary

PRISM's native API has no built-in user identity, session, tenant isolation,
or RBAC. Atlas runs, SQL Lab, Foundry, certification, promotion, and rollback
routes are therefore available to any client that can reach the process.

The only supported deployment is a local desktop process declared with
`PRISM_DEPLOYMENT_MODE=local` (the default) and bound to `127.0.0.1`. Local
launch commands and test servers must keep that loopback binding.

`apps/api/src/prism_api/deployment_security.py` enforces the other half of
that contract. `staging`, `production`, and unknown modes fail during
`create_app()`, before the API can serve requests. The public API entry in
`render.yaml` declares `staging`, so it is deliberately blocked. This is an
honest release blocker rather than an unauthenticated internet deployment.

## Why a shared token is rejected

A static deployment token proves possession of one secret. It does not identify
a person, separate tenants, encode roles, scope promotion rights, provide a
revocable session, or support an attributable audit trail. Anyone holding it
would receive every privilege. PRISM therefore does not accept a shared bearer
token as permission to enable a public deployment.

## Requirement for staging and production

Before either non-local mode can be enabled, the request boundary needs:

1. OIDC or an equivalent identity provider with expiring, revocable sessions.
2. Server-side authorization on every protected route and resource ownership
   checks for datasets, runs, analytical objects, and SQL sources.
3. Separate roles or scopes for read access, analytical execution, Atlas runs,
   Foundry operations, certification, and production promotion/rollback.
4. CSRF protection for browser sessions, restrictive CORS and security headers,
   rate limits backed by shared infrastructure, and secure cookie handling.
5. An immutable audit record naming the authenticated actor for every mutation.
6. Integration tests proving cross-user and cross-tenant access is denied.

Only after those controls exist should `resolve_deployment_security()` permit a
non-local mode and the Render API be considered deployable.

## Local operation

Use the documented loopback launch form:

```text
python -m uvicorn prism_api.main:app --app-dir apps/api/src --host 127.0.0.1 --port 8000
```

Do not bind a local-mode process to `0.0.0.0`, a LAN address, or a public proxy.
`GET /api/v1/platform/ready` reports the `external_auth_boundary` as
`not_configured` with an explicit local-only detail so the limitation remains
visible in runtime evidence.
