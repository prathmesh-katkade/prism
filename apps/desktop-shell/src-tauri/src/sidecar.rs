//! Spawns and kills the `prism-api` sidecar (apps/api, packaged as a
//! standalone binary by apps/api/build_sidecar.py). Prism's own React
//! frontend (apps/web) already talks to it directly over HTTP via
//! `apiUrl()` -- this module's only job is process lifecycle, not proxying.

use std::net::TcpStream;
use std::sync::Mutex;
use std::time::{Duration, Instant};
use tauri::{AppHandle, Manager};
use tauri_plugin_shell::process::CommandEvent;
use tauri_plugin_shell::ShellExt;

const SIDECAR_ADDR: &str = "127.0.0.1:8000";
const READY_TIMEOUT: Duration = Duration::from_secs(20);

#[derive(Default)]
pub struct SidecarState(pub Mutex<Option<tauri_plugin_shell::process::CommandChild>>);

/// Spawns the sidecar, streams its stdout/stderr into the Rust log (without
/// this, a sidecar that fails to start -- missing binary, port already in
/// use, a frozen-build import error -- fails silently and the app just
/// sits on "no connection" with no clue why), and blocks until it's
/// actually accepting connections or `READY_TIMEOUT` elapses.
///
/// That wait matters, confirmed for real: a PyInstaller `--onefile`
/// sidecar self-extracts to a temp dir and imports pandas/sklearn/numba
/// before it can bind the port, which took several real seconds under
/// this environment's software rendering -- easily long enough for
/// apps/web's own one-shot, no-retry startup fetches (e.g.
/// AtlasStatusBadge) to already have failed and settled into their
/// permanent "unknown" state before the sidecar was ready, with nothing to
/// prompt a retry short of a manual reload. This can't fix that race by
/// itself -- Tauri creates the window and starts loading its content
/// independently of when `setup()` (which calls this) returns, so a
/// slow sidecar can still lose the race -- but it turns an invisible
/// startup race into a logged, bounded, diagnosable one instead of a
/// silent one, and is worth fixing at the frontend's fetch-retry layer
/// separately if it proves to matter in practice on real hardware.
pub fn spawn(app: &AppHandle) -> tauri::Result<()> {
    let shell = app.shell();
    let (mut rx, child) = shell
        .sidecar("prism-api")
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e)))?
        .spawn()
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e)))?;

    tauri::async_runtime::spawn(async move {
        while let Some(event) = rx.recv().await {
            match event {
                CommandEvent::Stdout(line) | CommandEvent::Stderr(line) => {
                    log::info!("[prism-api] {}", String::from_utf8_lossy(&line).trim_end());
                }
                CommandEvent::Error(err) => log::error!("[prism-api] sidecar error: {err}"),
                CommandEvent::Terminated(payload) => {
                    log::warn!(
                        "[prism-api] exited: code={:?} signal={:?}",
                        payload.code,
                        payload.signal
                    );
                }
                _ => {}
            }
        }
    });

    *app.state::<SidecarState>().0.lock().unwrap() = Some(child);
    wait_until_ready();
    Ok(())
}

fn wait_until_ready() {
    let started = Instant::now();
    loop {
        if TcpStream::connect(SIDECAR_ADDR).is_ok() {
            log::info!(
                "[prism-api] ready after {:.1}s",
                started.elapsed().as_secs_f32()
            );
            return;
        }
        if started.elapsed() >= READY_TIMEOUT {
            log::warn!(
                "[prism-api] not accepting connections on {SIDECAR_ADDR} after {:.0}s, giving up waiting (app continues opening regardless)",
                READY_TIMEOUT.as_secs_f32()
            );
            return;
        }
        std::thread::sleep(Duration::from_millis(150));
    }
}

/// Kills the sidecar if still running. Called from the app's `RunEvent::Exit`
/// (see lib.rs) so this fires on every quit path -- window close, tray
/// Quit, Cmd+Q -- not just one of them.
///
/// Confirmed for real, not assumed safe because `child.kill()` returns
/// `Ok`: `CommandChild::kill()` sends SIGKILL to exactly the PID Tauri
/// spawned, which is PyInstaller's `--onefile` *bootloader* process, not
/// the real work it runs -- onefile self-extracts to a temp dir and execs
/// the actual Python process as a **child** of the bootloader, which it
/// forwards SIGTERM to and waits for before exiting. SIGKILL can't be
/// forwarded at all (it's not catchable by anything), so killing only the
/// bootloader with SIGKILL orphans its child, reparented to init, running
/// indefinitely. Reproduced directly: `kill -9 <bootloader-pid>` left the
/// real process alive; `kill -TERM <bootloader-pid>` cleaned up both
/// immediately. So: SIGTERM first, give it a moment, SIGKILL only as a
/// fallback if it's still alive after that.
pub fn kill(app: &AppHandle) {
    let Some(child) = app.state::<SidecarState>().0.lock().unwrap().take() else {
        return;
    };

    #[cfg(unix)]
    {
        let pid = child.pid();
        // SAFETY: plain libc calls with a PID we own (spawned via this same
        // CommandChild) and no pointer args.
        unsafe { libc::kill(pid as i32, libc::SIGTERM) };
        for _ in 0..20 {
            // signal 0 sends nothing; it only checks the PID still exists.
            let still_alive = unsafe { libc::kill(pid as i32, 0) } == 0;
            if !still_alive {
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        log::warn!("[prism-api] didn't exit within 2s of SIGTERM, sending SIGKILL");
    }

    if let Err(e) = child.kill() {
        log::warn!("[prism-api] failed to kill sidecar: {e}");
    }
}
