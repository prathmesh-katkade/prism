mod ollama;
mod sidecar;
mod tray;
mod updater;

use tauri_plugin_notification::NotificationExt;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .manage(sidecar::SidecarState::default())
        .setup(|app| {
            if cfg!(debug_assertions) {
                app.handle().plugin(
                    tauri_plugin_log::Builder::default()
                        .level(log::LevelFilter::Info)
                        .build(),
                )?;
            }
            tray::setup(app.handle())?;
            updater::check(app.handle());
            let ollama_ready = sidecar::spawn(app.handle())?;
            // Don't fail silently on which mode the user is in (the
            // plan's own bar for this): a native notification, not
            // buried in a log file, and re-evaluated on every launch --
            // see sidecar::spawn -- so switching Ollama on/off between
            // runs is reflected next time, not stuck on first impression.
            let _ = app
                .handle()
                .notification()
                .builder()
                .title("Prism")
                .body(if ollama_ready {
                    "Local AI ready — Atlas is using Ollama on this device."
                } else {
                    "Local AI not detected — Atlas is using its built-in deterministic analysis (no cloud calls)."
                })
                .show();
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application");

    // A plain `.run(...)` (as Phase 1/2 used) has no hook for cleanup on
    // exit; `.build()` + `.run(|_, event| ...)` does, and RunEvent::Exit
    // fires on every quit path (window close, tray Quit, Cmd+Q) so the
    // sidecar gets killed exactly once regardless of which one the user
    // takes -- not duplicated per-path, not missed on any of them.
    app.run(|app_handle, event| {
        if let tauri::RunEvent::Exit = event {
            sidecar::kill(app_handle);
        }
    });
}
