# Contract-first API boundary

This is the new PRISM API foundation. It intentionally exposes only platform capability and
transport contracts in Phase 1. It must not import `../../app.py`, `../../modules/`, or the
historical `../../api/` prototype.

Run locally after installing its requirements:

```powershell
python -m uvicorn prism_api.main:app --app-dir apps/api/src --reload
```

By default this creates a fresh, isolated durable-history file at
`.prism/runtime/analytical-history.sqlite` **relative to your current working
directory** — launching the same checkout from a different directory (or a
different git worktree) silently produces a different, disconnected store.
Copy `apps/api/.env.example` to `apps/api/.env`, set
`PRISM_ANALYTICAL_HISTORY_DATABASE_URL` there to an absolute path (or your
managed database URL), and pass `--env-file apps/api/.env` so every launch of
this checkout resolves to the same store on purpose, not by cwd accident:

```powershell
python -m uvicorn prism_api.main:app --app-dir apps/api/src --env-file apps/api/.env --reload
```
