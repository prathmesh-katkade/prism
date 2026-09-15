mod sidecar;
mod tray;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let app = tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_notification::init())
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
            sidecar::spawn(app.handle())?;
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
