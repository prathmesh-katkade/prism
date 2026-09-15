# PRISM desktop shell

Tauri v2 shell that wraps Atlas (main window UI) and Prism (sidecar-backed
panel) into one desktop app. See `DESKTOP_MIGRATION_PLAN.md` at the repo
root for the phased plan this workspace is built against.

## Status: Phase 1 complete — bare shell. Phase 2 paused, wrong Atlas source.

- `src-tauri/` — the Rust/Tauri project. `src/tray.rs` owns the system tray
  icon (Show/Hide + Quit menu), the global summon/hide hotkey
  (`Ctrl+Shift+P`), and a startup notification that proves the notification
  plugin is wired.
- `sidecar.rs` (Phase 3) and `ollama.rs` (Phase 4) don't exist yet —
  intentionally not scaffolded ahead of their phases.

### Phase 2 status: paused

`dist/` currently holds a vendored copy of the **`prathmesh-katkade/Atlas`**
repo's frontend (`index.html` + assets) — this turned out to be the wrong
source. The actual desktop-shell UI should come from Prism's own native
"Atlas" investigation UI (`apps/web/src/components/atlas-workspace.tsx`,
`atlas-command-center.tsx`, the `CortexV1` graph), redesigned to a dark HUD
look the user has already mocked up elsewhere — that source isn't in this
repo's history yet (checked `git log --all` on both branches). Don't build
further on the vendored `prathmesh-katkade/Atlas` copy in `dist/` until
that's sorted out.

What's still worth keeping from this pass, independent of which Atlas wins:

- **Two real WebKitGTK compatibility bugs**, found by actually running the
  vendored copy in the Tauri window (not guessed): `window.speechSynthesis`
  is entirely absent on Linux WebKitGTK, and an unguarded top-level
  `speechSynthesis.onvoiceschanged = ...` assignment threw and killed the
  *entire* inline script before `runBoot()`/`init()` ever ran — the app
  never got past its boot screen. Fixed with a feature-detection guard,
  matching the file's own existing `try { localStorage... } catch {}`
  idiom used everywhere else. A second latent bug (unguarded
  `sessionStorage` in the boot sequence) was fixed the same way, though it
  wasn't the one actually blocking rendering.
- **`tools/gen_atlas_core_mesh.py`** — a technique for a golden-angle
  phyllotaxis node scatter + sparse k-nearest-neighbour mesh + CSS
  `offset-path` signal pulses, verified to render correctly on both
  Chromium and WebKitGTK. Applicable to whichever Atlas's graph/core visual
  ends up being redesigned.

### Run it

```sh
cd apps/desktop-shell
npx tauri dev      # debug build + launch
npx tauri build     # release bundle for the current OS
```

Linux build deps (only needed to build *on* Linux — the shipped targets are
Windows/macOS per the migration plan): `libwebkit2gtk-4.1-dev libgtk-3-dev
libayatana-appindicator3-dev librsvg2-dev patchelf`.

### Verified so far

- `cargo build` produces a linked binary against the tray/global-shortcut/
  notification plugins with no errors.
- Launched under Xvfb (headless X server): window opens, renders the
  placeholder content, tray icon and global shortcut register without
  panicking, notification call doesn't crash even with no notification
  daemon present.
- **Not yet verified**: real Windows (WebView2) or macOS (WKWebView) builds
  — this container is Linux-only. That verification needs to happen in CI
  or on a Windows/macOS machine before Phase 1 is signed off across both
  target platforms.
