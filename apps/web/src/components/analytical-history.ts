import { apiUrl } from "../config/api";

/** Resolve the newest immutable object after a native workflow succeeds.
 * The existing Phase 8 contracts stay unchanged; this is deliberately a
 * read-only bridge to the lineage API, never a client-generated provenance id. */
export async function newestAnalyticalObjectId(datasetId: string, kind: string): Promise<string | undefined> {
  try {
    const response = await fetch(apiUrl(`/api/v1/lineage/datasets/${encodeURIComponent(datasetId)}/objects?kind=${encodeURIComponent(kind)}`));
    if (!response.ok) return undefined;
    const objects = await response.json() as { object_id?: string }[];
    return objects[0]?.object_id;
  } catch {
    return undefined;
  }
}
