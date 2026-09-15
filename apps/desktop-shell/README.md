# PRISM desktop shell

Tauri v2 shell that wraps Atlas (main window UI) and Prism (sidecar-backed
panel) into one desktop app. See `DESKTOP_MIGRATION_PLAN.md` at the repo
root for the phased plan this workspace is built against.

## Status: Phase 1 complete — bare shell

- `src-tauri/` — the Rust/Tauri project. `src/tray.rs` owns the system tray
  icon (Show/Hide + Quit menu), the global summon/hide hotkey
  (`Ctrl+Shift+P`), and a startup notification that proves the notification
  plugin is wired.
- `dist/` — placeholder window content. Phase 2 replaces this with Atlas's
  vendored frontend.
- `sidecar.rs` (Phase 3) and `ollama.rs` (Phase 4) don't exist yet —
  intentionally not scaffolded ahead of their phases.

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
