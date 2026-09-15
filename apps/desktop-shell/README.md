# PRISM desktop shell

Tauri v2 shell wrapping Prism's real native app (`apps/web`, which includes
Atlas as one of its workflow tabs — see below) plus `apps/api` as a sidecar.
See `DESKTOP_MIGRATION_PLAN.md` at the repo root for the phased plan this
workspace is built against; the architecture note below supersedes that
plan's original "Atlas shell + Prism panel" split.

## Status: Phase 1, 2 & 3 complete — sidecar spawns, works, and cleans up.

### The actual architecture (corrected from the original plan)

The migration plan assumed Atlas and Prism were two separate frontends to
merge into one shell. They aren't. `apps/web` is **one** Next.js SPA
(`prism-shell.tsx`) with a left-rail workflow switcher — `overview`,
`clean`, `visualize`, `sql-lab`, `ai-analyst`, ... and `atlas`, which can go
full-screen immersive (a real Three.js/`@react-three/fiber` 3D Cortex —
`atlas-cortex-3d.tsx`, `atlas-inspector-drawer.tsx`). There's nothing to
vendor or merge: the desktop shell just needs to run `apps/web` (static
export) + `apps/api` (FastAPI) as its content + sidecar. That collapses the
plan's Phase 2 ("Atlas as shell UI") and most of Phase 3 ("Prism as a
sidecar-backed module") into one story — the sidecar work in Phase 3 is
still real and still separate, but there's no second frontend to mount as
a "module" inside a first one.

(An earlier pass on this branch vendored the **wrong** Atlas — the separate
`prathmesh-katkade/Atlas` personal-assistant repo, since Atlas is a
confusingly overloaded name in this project: it's also a Streamlit voice
feature in `modules/atlas.py`, and a personal AI with Gmail/Calendar wires
in that other repo. Neither is this. That vendored copy has been removed
from `dist/`.)

### How the desktop build works

- `apps/web/next.config.ts` adds a `PRISM_BUILD_TARGET=desktop` mode:
  `output: "export"` (no Node server ships in the packaged app, only the
  FastAPI sidecar) and bakes in `NEXT_PUBLIC_PRISM_API_URL` defaulting to
  `http://127.0.0.1:8000`. The normal Render/staging web deployment is
  untouched — it still runs the default server build.
- `apps/web/package.json` → `npm run build:desktop` runs that export.
- `tauri.conf.json`: `devUrl` + `beforeDevCommand` (`npm run dev
  --workspace=@prism/web`) for `tauri dev`; `frontendDist` (`../../web/out`)
  + `beforeBuildCommand` (`npm run build:desktop --workspace=@prism/web`)
  for `tauri build`. `apps/web/out/` is gitignored — it's a build artifact,
  regenerated every time, never committed.
- `src-tauri/` — the Rust/Tauri project. `src/tray.rs` owns the system tray
  icon, the global summon/hide hotkey (`Ctrl+Shift+P`), and a startup
  notification. `src/sidecar.rs` spawns `apps/api` (packaged by
  `apps/api/build_sidecar.py`, a PyInstaller `--onefile` binary — `--onedir`
  was tried first and abandoned: its sibling `_internal/` payload doesn't
  reliably land next to Tauri's renamed `externalBin` executable across
  bundle formats) on app launch and kills it on `RunEvent::Exit`, which
  fires on every quit path (window close, tray Quit, Cmd+Q) exactly once.
- `apps/api/build_sidecar.py` — run it before `tauri build`/`tauri dev`
  needs a live sidecar; output lands in `src-tauri/binaries/` (gitignored,
  ~190MB, never committed). The editable workspace packages
  (`packages/*/python`) need their real source dirs on PyInstaller's
  `--paths` — hidden-imports alone can't see through their dynamic
  `MetaPathFinder`, which fails at runtime, not build time, so a clean
  PyInstaller exit code doesn't mean the binary actually works. Verify the
  built binary directly, don't trust the build log:
  ```sh
  cd apps/api && python build_sidecar.py
  ../desktop-shell/src-tauri/binaries/prism-api-<target-triple> &
  curl http://127.0.0.1:8000/api/v1/atlas/specialists
  ```
- `apps/api/desktop_entry.py` — the PyInstaller entry point (not the normal
  `uvicorn prism_api.main:app` dev/staging path). Sets
  `PRISM_ALLOWED_ORIGINS` for Tauri's real webview origins if the
  environment hasn't already — confirmed for real on this Linux build:
  `tauri://localhost`; `http://tauri.localhost` is Tauri v2's documented
  Windows/WebView2 origin, unverified here. Neither origin exists in
  `apps/api`'s own shared default (`packages/config/python`'s
  `allowed_origins`, which only knows about the `tauri dev`/Next.js dev
  server ports) — that default is correct for that context and deliberately
  left alone; the desktop-specific origins are additive, set only by this
  entry point.
- `ollama.rs` (Phase 4) doesn't exist yet — intentionally not scaffolded
  ahead of its phase.

### Run it

```sh
cd apps/api && python build_sidecar.py   # once, or after changing apps/api
cd ../desktop-shell
npx tauri dev        # starts the real Next.js dev server + debug window
npx tauri build --no-bundle   # static-exports apps/web, builds a release binary
```

Linux build deps (only needed to build *on* Linux — the shipped targets are
Windows/macOS per the migration plan): `libwebkit2gtk-4.1-dev libgtk-3-dev
libayatana-appindicator3-dev librsvg2-dev patchelf`.

**Use `npx tauri dev`/`npx tauri build`, never plain `cargo build`/`cargo
build --release`** — hit this directly: a plain cargo build ignores
`frontendDist` entirely and always tries `devUrl` (`http://localhost:3000`),
release profile included, so the window just shows "Could not connect to
localhost" unless a dev server happens to be running. Only the `tauri` CLI
sets the env var that switches between the two.

### Verified so far

- Phase 1: `cargo build` links clean against tray/global-shortcut/
  notification plugins; launched under Xvfb, tray + hotkey register without
  panicking, notification call doesn't crash with no notification daemon
  present.
- Phase 2: `apps/web`'s static export (`npm run build:desktop`) builds
  clean and embeds into the Tauri binary; the real Atlas Cortex renders
  inside the actual Tauri window (screenshotted, not assumed) and correctly
  shows a truthful "load a dataset first" empty state rather than faking
  data with no backend running.
- Phase 3: `apps/api/build_sidecar.py` produces a working ~190MB onefile
  binary (`sklearn`/`scipy`/`statsmodels` **and** `shap`'s numba/llvmlite
  JIT all verified working frozen, not just imported, by running a real
  upload → baseline → SHAP request through it). `npx tauri build` end to
  end: the sidecar auto-spawns on launch (confirmed via the real process
  tree, not just a log line), the UI goes from "ATLAS · STATUS UNKNOWN" to
  real data ("ATLAS · NO PRODUCTION MODEL", honestly, since nothing's been
  certified in this container) once it's up, and — the part worth
  documenting loudly since it silently regressed the actual "done when"
  bar — **quitting the app used to orphan the sidecar's real process,
  fixed and now confirmed clean**: `CommandChild::kill()` only SIGKILLs the
  PyInstaller `--onefile` bootloader Tauri directly spawned, not the real
  work process the bootloader execs as its own child, and SIGKILL can't be
  forwarded by anything. `sidecar::kill()` now sends SIGTERM first (which
  the bootloader *does* forward, confirmed both ways with a live process
  tree and manual `kill -9` vs `kill -TERM`), SIGKILL only as a fallback.
- **Not yet verified**: voice activation, and real Windows (WebView2)/macOS
  (WKWebView) builds — this container is Linux-only for all of the above.
  `http://tauri.localhost` (documented as WebView2's origin) is in
  `desktop_entry.py`'s CORS allowlist defensively but unverified; only
  `tauri://localhost` (Linux) has actually been confirmed.
