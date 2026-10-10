use tauri::AppHandle;
use tauri_plugin_notification::NotificationExt;
use tauri_plugin_updater::UpdaterExt;

/// Checks the configured update feed once per launch and, only when a newer
/// version is actually announced, surfaces it as a native notification --
/// there's no in-app "download in progress" UI yet, so this stays a check +
/// notice rather than driving an automatic download/install, which would be
/// surprising without one. `tauri.conf.json`'s `plugins.updater.endpoints`
/// is a placeholder GitHub Releases feed until a real release pipeline
/// publishes signed artifacts + a `latest.json` there; until then `check()`
/// simply reports no update (or a network error), and the notification
/// never fires.
pub fn check(app: &AppHandle) {
    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        let updater = match handle.updater() {
            Ok(updater) => updater,
            Err(error) => {
                log::warn!("Updater unavailable: {error}");
                return;
            }
        };
        match updater.check().await {
            Ok(Some(update)) => {
                log::info!("Prism update available: {}", update.version);
                let _ = handle
                    .notification()
                    .builder()
                    .title("Prism update available")
                    .body(format!("Version {} is available.", update.version))
                    .show();
            }
            Ok(None) => log::info!("Prism is up to date."),
            Err(error) => log::warn!("Update check failed: {error}"),
        }
    });
}
