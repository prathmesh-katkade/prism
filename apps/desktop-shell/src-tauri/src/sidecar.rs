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
pub fn spawn(app: &AppHandle) -> tauri::Result<bool> {
    // Checked fresh on every launch (not cached/persisted) so starting or
    // stopping Ollama between runs is picked up automatically, per the
    // plan's own requirement -- see ollama.rs for why this is a real
    // HTTP probe of Ollama's API, not just a port check.
    let ollama_ready = crate::ollama::is_reachable();
    log::info!(
        "[ollama] {}",
        if ollama_ready {
            "reachable -- enabling Ollama-backed Atlas features"
        } else {
            "not reachable -- Atlas uses its deterministic fallback"
        }
    );

    // apps/api resolves its SQLite stores (analytical history, SQL Lab
    // history, Foundry jobs/exports, Atlas sandboxes) as `.prism/runtime/...`
    // *relative to the process's own working directory* when no override is
    // set - fine for `uvicorn` always launched from the repo root, but a
    // packaged sidecar's inherited cwd depends on how the app was launched
    // (Explorer double-click, a pinned taskbar icon, a shortcut with its own
    // "Start in" field) and isn't something this app controls. Pinning the
    // sidecar's cwd to Tauri's own stable, OS-appropriate app-data directory
    // makes all four of those stores land in one real, predictable place
    // every launch, regardless of how the app was opened.
    let data_dir = app
        .path()
        .app_data_dir()
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e)))?;
    std::fs::create_dir_all(&data_dir)
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e)))?;
    log::info!("[prism-api] working directory: {}", data_dir.display());

    let shell = app.shell();
    let mut command = shell
        .sidecar("prism-api")
        .map_err(|e| tauri::Error::Anyhow(anyhow::anyhow!(e)))?
        .current_dir(data_dir);
    if ollama_ready {
        // Flips a switch apps/api already has (PRISM_AI_PROVIDER, see
        // ai_analyst.py / atlas_candidate_runtime.py) rather than adding a
        // second, parallel notion of "local-first" -- unset, it already
        // defaults to the same deterministic path this falls back to.
        command = command.env("PRISM_AI_PROVIDER", "ollama");
    }
    let (mut rx, child) = command
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
    Ok(ollama_ready)
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
/// `Ok`: `CommandChild::kill()` terminates exactly the PID Tauri spawned,
/// which is PyInstaller's `--onefile` *bootloader* process, not the real
/// work it runs -- onefile self-extracts to a temp dir and execs the
/// actual Python process as a **child** of the bootloader. This is a real
/// problem on both platforms this app ships for, confirmed by actually
/// closing the window and checking what's left running, not assumed from
/// the Unix case alone:
///
/// - **Unix**: the bootloader forwards SIGTERM to its child and waits for
///   it before exiting; SIGKILL can't be forwarded at all (not catchable
///   by anything). `kill -9 <bootloader-pid>` left the real process alive;
///   `kill -TERM <bootloader-pid>` cleaned up both immediately. So:
///   SIGTERM first, give it a moment, SIGKILL only as a fallback.
/// - **Windows**: `CommandChild::kill()` calls `TerminateProcess` on the
///   bootloader only, same gap -- there is no SIGTERM-equivalent the
///   bootloader can forward here either way. Reproduced directly: closing
///   the window left the bootloader's PID gone but its child (parented to
///   it, confirmed via `Get-CimInstance Win32_Process`) still running and
///   still answering HTTP requests on port 8000. `taskkill /PID <pid> /T
///   /F` kills the bootloader's whole process tree in one call and is the
///   standard tool for exactly this gap -- there's no stdlib equivalent
///   without a Job Object, which is more code for the same result here.
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

    #[cfg(windows)]
    {
        let pid = child.pid();
        let status = std::process::Command::new("taskkill")
            .args(["/PID", &pid.to_string(), "/T", "/F"])
            .status();
        match status {
            Ok(s) if s.success() => return,
            Ok(s) => log::warn!("[prism-api] taskkill exited with {s}, falling back to killing the bootloader only"),
            Err(e) => log::warn!("[prism-api] failed to run taskkill ({e}), falling back to killing the bootloader only"),
        }
    }

    if let Err(e) = child.kill() {
        log::warn!("[prism-api] failed to kill sidecar: {e}");
    }
}
