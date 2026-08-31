"use client";

import { useEffect, useMemo, useState } from "react";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";
import type { AnalyticalObjectShape, FreshnessShape } from "./evidence-inspector";

const KINDS = ["all", "analysis", "query_result", "cleaning_plan", "visualization", "forecast", "ml_model", "evidence"] as const;

export function HistoryWorkspace({ onSelectContext }: { onSelectContext(state: InspectorObjectState): void }) {
  const [objects, setObjects] = useState<readonly AnalyticalObjectShape[]>([]);
  const [freshness, setFreshness] = useState<Record<string, FreshnessShape>>({});
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<(typeof KINDS)[number]>("all");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    async function load() {
      setError(null);
      try {
        const response = await fetch(apiUrl(`/api/v1/lineage/history?limit=200${kind === "all" ? "" : `&kind=${encodeURIComponent(kind)}`}`));
        if (!response.ok) throw new Error("Analytical history could not be loaded.");
        const next = await response.json() as AnalyticalObjectShape[];
        const assessments = await Promise.all(next.map(async (object) => {
          const assessment = await fetch(apiUrl(`/api/v1/lineage/objects/${object.object_id}/freshness`));
          return [object.object_id, assessment.ok ? await assessment.json() as FreshnessShape : undefined] as const;
        }));
        if (!live) return;
        setObjects(next);
        setFreshness(Object.fromEntries(assessments.filter((entry): entry is readonly [string, FreshnessShape] => entry[1] !== undefined)));
      } catch (reason) { if (live) setError(reason instanceof Error ? reason.message : "Analytical history is unavailable."); }
    }
    void load();
    return () => { live = false; };
  }, [kind]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return needle ? objects.filter((object) => `${object.kind} ${object.object_id} ${object.provenance.dataset.dataset_id}`.toLowerCase().includes(needle)) : objects;
  }, [objects, query]);
  const current = filtered.filter((object) => freshness[object.object_id]?.state === "current").length;
  const stale = filtered.filter((object) => ["stale", "superseded"].includes(freshness[object.object_id]?.state ?? "")).length;

  return <article className="history-workspace" aria-label="Analytical history workspace">
    <header className="desk-heading"><div><span className="eyebrow">HISTORY · EVIDENCE · LINEAGE</span><h1>Analytical history</h1><p>An append-only research record. Freshness is evaluated against the active DatasetStore revision at read time.</p></div><dl className="inspector-data"><div><dt>Shown</dt><dd>{filtered.length}</dd></div><div><dt>Current</dt><dd>{current}</dd></div><div><dt>Stale</dt><dd>{stale}</dd></div></dl></header>
    <div className="history-controls"><label>Search<input aria-label="Search analytical history" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Object, dataset, or kind" /></label><label>Kind<select aria-label="Filter analytical history by kind" value={kind} onChange={(event) => setKind(event.target.value as typeof kind)}>{KINDS.map((item) => <option key={item} value={item}>{item.replaceAll("_", " ")}</option>)}</select></label></div>
    {error ? <p role="alert" className="query-error">{error}</p> : null}
    {!error && !filtered.length ? <p className="quiet-note">No analytical objects match this view yet.</p> : <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Object</th><th>Dataset revision</th><th>State</th><th>Created</th><th /></tr></thead><tbody>{filtered.map((object) => { const state = freshness[object.object_id]?.state ?? "unknown"; return <tr key={object.object_id}><td><strong>{object.kind.replaceAll("_", " ")}</strong><small><code>{object.object_id}</code></small></td><td>{object.provenance.dataset.dataset_id} · r{object.provenance.dataset.revision}</td><td><span className={`freshness-badge freshness-${state}`}>{state}</span></td><td>{new Date(object.provenance.created_at).toLocaleString()}</td><td><button onClick={() => onSelectContext({ objectId: object.object_id, analyticalObjectId: object.object_id, label: "Analytical evidence", type: "finding", state: "ready", actions: [], metadata: [] })}>Inspect</button></td></tr>; })}</tbody></table></div>}
  </article>;
}
