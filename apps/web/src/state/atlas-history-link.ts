/**
 * Atlas historical-run deep-link contract (Phase 11C).
 *
 * `dataset_id` and `run_id` already exist as page query parameters
 * (see `prism-shell.tsx`) and keep their exact current meaning everywhere
 * else in the shell: `dataset_id` loads a dataset into the native
 * workspaces, and `run_id` seeds `AtlasWorkspace`'s *live* per-dataset run
 * restore. Neither of those is touched here.
 *
 * This module adds exactly two new, purely additive query keys that layer
 * a second, independent meaning onto `run_id` -- addressing a run inside
 * the Atlas Command Center's system-wide "Run activity" history browser,
 * which (unlike the live restore) is never scoped to the current dataset:
 *
 *   atlas_panel=history   Opts into history mode. Absent by default, so
 *                         every existing `dataset_id`/`run_id` link keeps
 *                         behaving exactly as it always has -- this key is
 *                         the explicit, backward-compatible switch that
 *                         means "treat `run_id` as a Command Center history
 *                         target" rather than only a live-restore target.
 *   atlas_focus=<id>      Optional. A single real Cortex `node_id`, or a
 *                         plan `step_id`, to select once that run's actual
 *                         `GET /runs/{run_id}/cortex` graph has loaded.
 *                         Applied only if the id is really present in that
 *                         server response -- never synthesized, and never a
 *                         synthetic client-side group id.
 *
 * Both new keys are opaque identifiers only (never raw rows, prompts, or
 * model output), matching the privacy boundary the rest of Atlas's URL
 * surface already holds to.
 */
export type AtlasHistoryQuery = { runId: string | null; focusId: string | null };

const NO_HISTORY_QUERY: AtlasHistoryQuery = { runId: null, focusId: null };

export function parseAtlasHistoryQuery(search: string): AtlasHistoryQuery {
  const params = new URLSearchParams(search);
  if (params.get("atlas_panel")?.trim() !== "history") return NO_HISTORY_QUERY;
  const runId = params.get("run_id")?.trim();
  if (!runId) return NO_HISTORY_QUERY;
  const focusId = params.get("atlas_focus")?.trim();
  return { runId, focusId: focusId || null };
}

/**
 * Builds a shareable investigation link for one expanded historical run.
 * Every other query parameter already on the page (for example a
 * `dataset_id` the operator is also working in) survives unchanged; only
 * the three keys this contract owns are set. Pure string construction --
 * no network access, no page mutation.
 */
export function buildAtlasHistoryLink(currentHref: string, runId: string, focusId: string | null): string {
  const url = new URL(currentHref);
  url.searchParams.set("run_id", runId);
  url.searchParams.set("atlas_panel", "history");
  if (focusId) url.searchParams.set("atlas_focus", focusId);
  else url.searchParams.delete("atlas_focus");
  return url.toString();
}
