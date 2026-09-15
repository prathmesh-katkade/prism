"""PyInstaller entry point for the desktop sidecar build of apps/api.

Not used by the normal `uvicorn prism_api.main:app` dev/staging path (see
render.yaml) -- this exists only so PyInstaller has a single importable
script to freeze, and so the frozen binary needs no arguments to behave
correctly as a Tauri sidecar (Rust just spawns it and waits for
127.0.0.1:8000 to answer; see src-tauri/src/sidecar.rs).

PRISM_DEPLOYMENT_MODE defaults to "local" already (deployment_security.py)
-- that's correct for a desktop sidecar and is left alone here. What a
desktop sidecar genuinely needs that the shared default doesn't provide is
CORS for Tauri's webview origin, which is never `http://127.0.0.1:3000`/
`http://localhost:3000` (those are only `tauri dev`'s Next.js dev server).
Set explicitly rather than trusting a caller to remember it, and only if
the environment hasn't already set its own PRISM_ALLOWED_ORIGINS.
"""

from __future__ import annotations

import os

if "PRISM_ALLOWED_ORIGINS" not in os.environ:
    # tauri://localhost is this session's own confirmed value on Linux
    # WebKitGTK; http://tauri.localhost is Tauri v2's documented Windows/
    # WebView2 origin. Neither has been verified on macOS/WKWebView in this
    # container -- if Phase 3 sign-off on macOS finds a third value, add it
    # here rather than widening to a wildcard.
    os.environ["PRISM_ALLOWED_ORIGINS"] = (
        '["tauri://localhost","http://tauri.localhost","http://127.0.0.1:3000","http://localhost:3000"]'
    )

import uvicorn  # noqa: E402

from prism_api.main import app  # noqa: E402

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")
