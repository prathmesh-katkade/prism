# PRISM desktop shell

Tauri v2 shell wrapping Prism's real native app (`apps/web`, which includes
Atlas as one of its workflow tabs — see below) plus `apps/api` as a sidecar.
See `DESKTOP_MIGRATION_PLAN.md` at the repo root for the phased plan this
workspace is built against; the architecture note below supersedes that
plan's original "Atlas shell + Prism panel" split.

## Status: Phase 1 complete. Phase 2 in progress — real Atlas wired up.

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
  notification.
- `sidecar.rs` (Phase 3 — spawn `apps/api` as a Tauri sidecar) and
  `ollama.rs` (Phase 4) don't exist yet — intentionally not scaffolded
  ahead of their phases.

### Run it

```sh
cd apps/desktop-shell
npx tauri dev        # starts the real Next.js dev server + debug window
npx tauri build       # static-exports apps/web, builds a release bundle
```

Linux build deps (only needed to build *on* Linux — the shipped targets are
Windows/macOS per the migration plan): `libwebkit2gtk-4.1-dev libgtk-3-dev
libayatana-appindicator3-dev librsvg2-dev patchelf`.

Without `apps/api` running, Atlas/Prism's own fetches to
`127.0.0.1:8000` fail — expected until Phase 3 wires the sidecar. The shell
itself should still render.

### Verified so far

- Phase 1: `cargo build` links clean against tray/global-shortcut/
  notification plugins; launched under Xvfb, tray + hotkey register without
  panicking, notification call doesn't crash with no notification daemon
  present.
- Phase 2: `apps/web`'s static export (`npm run build:desktop`) builds
  clean and embeds into the Tauri binary.
- **Not yet verified in this pass**: the real Atlas Cortex actually
  rendering inside the Tauri window (checking now), voice activation, and
  real Windows (WebView2)/macOS (WKWebView) builds — this container is
  Linux-only for all of the above.
