//! System tray icon and the global summon/hide hotkey.
//!
//! Phase 1 scope only: prove the plumbing (tray, menu, hotkey, notification)
//! works end to end. No sidecar/Ollama awareness lives here — that's
//! sidecar.rs and ollama.rs in later phases.

use tauri::{
    menu::{Menu, MenuItem},
    tray::TrayIconBuilder,
    AppHandle, Manager, WebviewWindow,
};
use tauri_plugin_global_shortcut::{Code, GlobalShortcutExt, Modifiers, Shortcut, ShortcutState};
use tauri_plugin_notification::NotificationExt;

/// Ctrl+Shift+P — summons the main window if hidden, hides it if focused.
fn summon_shortcut() -> Shortcut {
    Shortcut::new(Some(Modifiers::CONTROL | Modifiers::SHIFT), Code::KeyP)
}

fn toggle_main_window(window: &WebviewWindow) {
    let is_visible = window.is_visible().unwrap_or(false);
    let is_focused = window.is_focused().unwrap_or(false);
    if is_visible && is_focused {
        let _ = window.hide();
    } else {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Registers the tray icon (with a Show/Hide + Quit menu) and the global
/// summon hotkey. Call once from the app's `setup` hook.
pub fn setup(app: &AppHandle) -> tauri::Result<()> {
    let show_hide = MenuItem::with_id(app, "toggle", "Show/Hide Prism", true, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "Quit Prism", true, None::<&str>)?;
    let menu = Menu::with_items(app, &[&show_hide, &quit])?;

    TrayIconBuilder::new()
        .icon(
            app.default_window_icon()
                .cloned()
                .expect("app icon must be bundled"),
        )
        .menu(&menu)
        .show_menu_on_left_click(true)
        .on_menu_event(|app, event| match event.id.as_ref() {
            "toggle" => {
                if let Some(window) = app.get_webview_window("main") {
                    toggle_main_window(&window);
                }
            }
            "quit" => app.exit(0),
            _ => {}
        })
        .build(app)?;

    let summon = summon_shortcut();
    app.plugin(
        tauri_plugin_global_shortcut::Builder::new()
            .with_handler(move |app, shortcut, event| {
                if shortcut == &summon && event.state() == ShortcutState::Pressed {
                    if let Some(window) = app.get_webview_window("main") {
                        toggle_main_window(&window);
                    }
                }
            })
            .build(),
    )?;
    app.global_shortcut()
        .register(summon_shortcut())
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e)))?;

    // Prove the notification plumbing works without requiring the user to
    // touch anything — fires once, right after the tray/hotkey are live.
    let _ = app
        .notification()
        .builder()
        .title("Prism")
        .body("Desktop shell ready — tray icon and Ctrl+Shift+P are live.")
        .show();

    Ok(())
}
