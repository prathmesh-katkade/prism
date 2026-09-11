/**
 * Single typed configuration boundary for the PRISM API's base URL.
 *
 * Every component that talks to apps/api imports `apiUrl` from here instead of reading
 * `process.env.NEXT_PUBLIC_PRISM_API_URL` directly - the environment variable name and its
 * local-development fallback are declared exactly once, and staging/production deployments set
 * `NEXT_PUBLIC_PRISM_API_URL` to the deployed API's origin without touching any component.
 *
 * `NEXT_PUBLIC_*` is safe here: an API *origin* is not a secret (it's necessarily visible in
 * every request the browser makes anyway). No credential, key, or server-only secret is ever
 * read through this module or exposed via a `NEXT_PUBLIC_*` variable elsewhere in the app.
 */
export const API_BASE = process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000";

export function apiUrl(path: string): string {
  return new URL(path, API_BASE).toString();
}
