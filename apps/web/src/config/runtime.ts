/**
 * Single detection point for "are we running inside the Tauri desktop shell,
 * or the normal browser/Render deployment". `__TAURI_INTERNALS__` is Tauri
 * v2's own runtime marker, injected into `window` only inside a real Tauri
 * webview -- never present for the plain web build, so this can't be spoofed
 * by an env var baked in at build time and stays correct even though
 * `apps/web`'s desktop and web builds otherwise share one bundle output.
 */
export function isTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}
