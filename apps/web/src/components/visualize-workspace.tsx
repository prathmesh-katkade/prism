"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AtlasVisualizeResponse, OverviewProfileResponse, VisualizationDataResponse, VisualizationSpec, VisualizationSuggestion, VizMark } from "@prism/api-contracts";
import type { InspectorObjectState } from "../state/shell-model";

const API_BASE = process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000";
function apiUrl(path: string): string { return new URL(path, API_BASE).toString(); }

type VizUiState = "empty" | "loading" | "ready" | "error";
const MARKS: readonly VizMark[] = ["bar", "line", "scatter", "histogram", "box"];

/** Phase 6B: intent → deterministic mark suggestion → server-aggregated data → renderer-agnostic spec. */
export function VisualizeWorkspace({ datasetId, onSelectContext, onOpenWorkflow }: { datasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void }) {
  const [state, setState] = useState<VizUiState>(datasetId ? "loading" : "empty");
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [spec, setSpec] = useState<VisualizationSpec | null>(null);
  const [rationale, setRationale] = useState<string>("");
  const [data, setData] = useState<VisualizationDataResponse | null>(null);
  const [atlas, setAtlas] = useState<AtlasVisualizeResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (id: string) => {
    setState("loading"); setError(null);
    try {
      const profiled = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/profile`));
      if (!profiled.ok) throw new Error("Visualize needs a profiled dataset from Overview.");
      const nextProfile = await profiled.json() as OverviewProfileResponse;
      setProfile(nextProfile);
      const suggested = await fetch(apiUrl(`/api/v1/visualize/datasets/${id}/suggest`), { method: "POST" });
      if (!suggested.ok) throw new Error("No chartable columns were found for this dataset.");
      const suggestion = await suggested.json() as VisualizationSuggestion;
      setSpec(suggestion.spec); setRationale(suggestion.rationale);
      setState("ready");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Visualize is unavailable."); setState("error"); }
  }, []);

  useEffect(() => { if (datasetId) void load(datasetId); else { setState("empty"); setProfile(null); setSpec(null); setData(null); } }, [datasetId, load]);

  const render = useCallback(async (id: string, nextSpec: VisualizationSpec) => {
    setAtlas(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/visualize/datasets/${id}/render`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(nextSpec) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "This chart could not be rendered.");
      const body = await response.json() as VisualizationDataResponse;
      setData(body);
      onSelectContext({ objectId: `chart:${nextSpec.dimension ?? "distribution"}:${nextSpec.measure ?? ""}`, label: `${nextSpec.mark} chart`, type: "finding", state: "ready", actions: [{ id: "atlas-explain-chart", label: "Ask Atlas to explain this chart" }], metadata: [`${body.data.length} points shown`, body.truncated ? "truncated" : "complete"] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This chart could not be rendered."); }
  }, [onSelectContext]);

  useEffect(() => { if (datasetId && spec) void render(datasetId, spec); }, [datasetId, spec, render]);

  function updateSpec(patch: Partial<VisualizationSpec>) { if (spec) setSpec({ ...spec, ...patch }); }

  async function askAtlas(action: "explain_chart" | "identify_anomaly" | "propose_alternative") {
    if (!datasetId || !spec) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/visualize/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, spec }) });
      if (!response.ok) return;
      setAtlas(await response.json() as AtlasVisualizeResponse);
    } catch { /* Atlas commentary is optional; the chart remains usable without it. */ }
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">VISUALIZE · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Visualize charts the same server-held dataset Overview and SQL Lab already use.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  if (state === "loading" || !profile) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Choosing a chart for this data</h2><p>Chart selection is deterministic — the same intent and column types always suggest the same mark.</p></section>;
  if (state === "error" || !spec) return <section className="overview-state error-state" role="alert"><h2>Visualize could not suggest a chart.</h2><p>{error}</p><button onClick={() => datasetId && void load(datasetId)}>Retry</button></section>;

  const categorical = profile.columns.filter((c) => c.semantic_type === "categorical" || c.semantic_type === "datetime");
  const numeric = profile.columns.filter((c) => c.semantic_type === "numeric");

  return <article className="visualize-workspace three-pane">
    <nav className="viz-fields" aria-label="Data fields" tabIndex={0}>
      <div className="section-title"><span className="eyebrow">FIELDS</span><h2>{profile.dataset.source_name}</h2></div>
      <p className="quiet-note">DIMENSIONS</p>
      <div className="finding-list">{categorical.map((column) => <button key={column.name} className={column.name === spec.dimension ? "is-selected" : ""} onClick={() => updateSpec({ dimension: column.name })}><span className="finding-dot good" /><strong>{column.name}</strong><small>{column.semantic_type}</small></button>)}</div>
      <p className="quiet-note">MEASURES</p>
      <div className="finding-list">{numeric.map((column) => <button key={column.name} className={column.name === spec.measure ? "is-selected" : ""} onClick={() => updateSpec({ measure: column.name })}><span className="finding-dot good" /><strong>{column.name}</strong><small>numeric</small></button>)}</div>
    </nav>
    <section className="viz-canvas" aria-label="Visual canvas" tabIndex={0}>
      <header><span className="eyebrow">{rationale}</span><h1>{spec.dimension ?? spec.measure} {spec.measure && spec.dimension ? `by ${spec.measure}` : ""}</h1></header>
      {data ? <ChartCanvas mark={spec.mark} data={data.data} /> : <p className="quiet-note">Rendering…</p>}
      {(data?.warnings ?? []).length ? <ul className="clean-warnings">{(data?.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
    </section>
    <aside className="inspector viz-inspector" aria-label="Chart inspector">
      <div className="inspector-heading"><span className="eyebrow">ENCODING</span></div>
      <label>Mark<select value={spec.mark} onChange={(event) => updateSpec({ mark: event.target.value as VizMark })}>{MARKS.map((mark) => <option key={mark} value={mark}>{mark}</option>)}</select></label>
      <label>Aggregation<select value={spec.aggregation} onChange={(event) => updateSpec({ aggregation: event.target.value as VisualizationSpec["aggregation"] })}><option value="count">count</option><option value="sum">sum</option><option value="mean">mean</option><option value="median">median</option><option value="none">none</option></select></label>
      <div className="inspector-actions"><span className="eyebrow">ATLAS · EVIDENCE-AWARE</span><button onClick={() => void askAtlas("explain_chart")}>Explain this chart</button><button onClick={() => void askAtlas("identify_anomaly")}>Identify anomalies</button><button onClick={() => void askAtlas("propose_alternative")}>Trust check</button></div>
      {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
      {data ? <dl className="inspector-data"><div><dt>Source</dt><dd><code>{data.provenance.source_fingerprint.slice(0, 12)}…</code></dd></div><div><dt>Revision</dt><dd>{data.provenance.dataset_revision}</dd></div><div><dt>Points shown</dt><dd>{data.data.length}</dd></div></dl> : null}
      {error ? <p className="query-error" role="alert">{error}</p> : null}
    </aside>
  </article>;
}

function ChartCanvas({ mark, data }: { mark: VizMark; data: readonly { label: string; value: number }[] }) {
  if (!data.length) return <p className="quiet-note">No data to chart.</p>;
  const width = 640, height = 280, padding = 32;
  const max = Math.max(...data.map((d) => d.value), 1);
  const min = mark === "scatter" ? Math.min(...data.map((d) => d.value)) : 0;
  const span = max - min || 1;
  if (mark === "scatter") {
    const xValues = data.map((_, index) => index);
    const xMax = Math.max(...xValues, 1);
    return <svg role="img" aria-label={`Scatter chart with ${data.length} points`} viewBox={`0 0 ${width} ${height}`} className="viz-svg">{data.map((point, index) => <circle key={index} cx={padding + (index / xMax) * (width - 2 * padding)} cy={height - padding - ((point.value - min) / span) * (height - 2 * padding)} r={3} />)}</svg>;
  }
  if (mark === "line") {
    const points = data.map((point, index) => `${padding + (index / Math.max(1, data.length - 1)) * (width - 2 * padding)},${height - padding - (point.value / span) * (height - 2 * padding)}`).join(" ");
    return <svg role="img" aria-label={`Line chart across ${data.length} categories`} viewBox={`0 0 ${width} ${height}`} className="viz-svg"><polyline points={points} fill="none" /></svg>;
  }
  const barWidth = (width - 2 * padding) / data.length;
  return <svg role="img" aria-label={`Bar chart with ${data.length} categories`} viewBox={`0 0 ${width} ${height}`} className="viz-svg">
    {data.map((point, index) => { const barHeight = (point.value / span) * (height - 2 * padding); return <g key={index}><rect x={padding + index * barWidth + 2} y={height - padding - barHeight} width={Math.max(1, barWidth - 4)} height={barHeight} /><title>{`${point.label}: ${point.value}`}</title></g>; })}
  </svg>;
}
