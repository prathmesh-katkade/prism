# Contract-first API boundary

This is the new PRISM API foundation. It intentionally exposes only platform capability and
transport contracts in Phase 1. It must not import `../../app.py`, `../../modules/`, or the
historical `../../api/` prototype.

Run locally after installing its requirements:

```powershell
python -m uvicorn prism_api.main:app --app-dir apps/api/src --reload
```
