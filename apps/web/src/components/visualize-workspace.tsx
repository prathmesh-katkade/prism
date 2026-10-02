"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AtlasVisualizeResponse, ChartDrillDownResponse, OverviewProfileResponse, VisualizationDataResponse, VisualizationDatum, VisualizationSpec, VisualizationSuggestion, VizMark } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { newestAnalyticalObjectId } from "./analytical-history";
import type { InspectorObjectState } from "../state/shell-model";

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
  const [drilldown, setDrilldown] = useState<ChartDrillDownResponse | null>(null);
  const [drilldownLoading, setDrilldownLoading] = useState(false);
  const [drilldownError, setDrilldownError] = useState<string | null>(null);

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
      const analyticalObjectId = await newestAnalyticalObjectId(id, "visualization");
      onSelectContext({ objectId: `chart:${nextSpec.dimension ?? "distribution"}:${nextSpec.measure ?? ""}`, label: `${nextSpec.mark} chart`, type: "finding", state: "ready", actions: [{ id: "atlas-explain-chart", label: "Ask Atlas to explain this chart" }], metadata: [`${body.data.length} points shown`, body.truncated ? "truncated" : "complete"], ...(analyticalObjectId ? { analyticalObjectId } : {}) });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This chart could not be rendered."); }
  }, [onSelectContext]);

  useEffect(() => { if (datasetId && spec) void render(datasetId, spec); }, [datasetId, spec, render]);

  function updateSpec(patch: Partial<VisualizationSpec>) { if (spec) setSpec({ ...spec, ...patch }); setDrilldown(null); }

  async function selectMark(params: { dimensionValue?: string; xValue?: number; yValue?: number }) {
    if (!datasetId || !spec) return;
    setDrilldownLoading(true); setDrilldownError(null); setDrilldown(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/visualize/datasets/${datasetId}/drilldown`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ spec, offset: 0, limit: 50, ...(params.dimensionValue !== undefined ? { dimension_value: params.dimensionValue } : {}), ...(params.xValue !== undefined ? { x_value: params.xValue, y_value: params.yValue } : {}) }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Could not resolve this mark's contributing rows.");
      const body = await response.json() as ChartDrillDownResponse;
      setDrilldown(body);
      onSelectContext({
        objectId: `mark:${params.dimensionValue ?? `${params.xValue},${params.yValue}`}`, label: "Contributing rows", type: "finding", state: "ready", actions: [],
        metadata: [
          `${body.total_matching_rows.toLocaleString()} matching row(s)`,
          body.truncated ? `showing first ${body.rows.length} (truncated)` : "all shown",
          `filtered by ${Object.entries((body.filters_applied ?? {})).map(([k, v]) => `${k}=${v}`).join(", ")}`,
        ],
      });
    } catch (reason) { setDrilldownError(reason instanceof Error ? reason.message : "Could not resolve this mark's contributing rows."); }
    finally { setDrilldownLoading(false); }
  }

  async function askAtlas(action: "explain_chart" | "identify_anomaly" | "propose_alternative") {
    if (!datasetId || !spec) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/visualize/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, spec }) });
      if (!response.ok) return;
      setAtlas(await response.json() as AtlasVisualizeResponse);
    } catch { /* Atlas commentary is optional; the chart remains usable without it. */ }
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">VISUALIZE · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Visualize charts the same server-held dataset Overview and SQL Lab already use.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  // error must be checked before the loading/null-data fallback: a failed
  // first load never populates `profile`, so `!profile` alone would keep
  // matching the loading branch forever and the error (with its retry
  // control) would never be reachable. `!spec` stays a separate, later
  // check -- during a legitimate "loading" state spec is null too, so
  // folding it into this same unconditional check would misreport loading
  // as an error.
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>Visualize could not suggest a chart.</h2><p>{error}</p><button onClick={() => datasetId && void load(datasetId)}>Retry</button></section>;
  if (state === "loading" || !profile) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Choosing a chart for this data</h2><p>Chart selection is deterministic — the same intent and column types always suggest the same mark.</p></section>;
  if (!spec) return <section className="overview-state error-state" role="alert"><h2>Visualize could not suggest a chart.</h2><p>{error}</p><button onClick={() => datasetId && void load(datasetId)}>Retry</button></section>;

  const numeric = profile.columns.filter((c) => c.semantic_type === "numeric");
  // A scatter/relationship chart's X axis is itself numeric (e.g. "revenue"), so the
  // dimension picker must offer numeric columns too, not just categorical/datetime
  // ones -- restricting it to those would make a numeric X field unreachable from
  // this control even though render() already accepts and plots one.
  const dimensionCandidates = profile.columns.filter((c) => c.name !== spec.measure);
  const measureCandidates = numeric.filter((c) => c.name !== spec.dimension);

  return <article className="visualize-workspace three-pane">
    <nav className="viz-fields" aria-label="Data fields" tabIndex={0}>
      <div className="section-title"><span className="eyebrow">FIELDS</span><h2>{profile.dataset.source_name}</h2></div>
      <p className="quiet-note">{spec.mark === "scatter" ? "X FIELD" : "DIMENSION"}</p>
      <div className="finding-list">{dimensionCandidates.map((column) => <button key={column.name} className={column.name === spec.dimension ? "is-selected" : ""} onClick={() => updateSpec({ dimension: column.name })}><span className="finding-dot good" /><strong>{column.name}</strong><small>{column.semantic_type}</small></button>)}</div>
      <p className="quiet-note">{spec.mark === "scatter" ? "Y FIELD" : "MEASURE"}</p>
      <div className="finding-list">{measureCandidates.map((column) => <button key={column.name} className={column.name === spec.measure ? "is-selected" : ""} onClick={() => updateSpec({ measure: column.name })}><span className="finding-dot good" /><strong>{column.name}</strong><small>numeric</small></button>)}</div>
    </nav>
    <section className="viz-canvas" aria-label="Visual canvas" tabIndex={0}>
      <header><span className="eyebrow">{rationale}</span><h1>{spec.dimension ?? spec.measure} {spec.measure && spec.dimension ? `by ${spec.measure}` : ""}</h1></header>
      {data ? <ChartCanvas mark={spec.mark} data={data.data} onSelectMark={selectMark} /> : <p className="quiet-note">Rendering…</p>}
      {(data?.warnings ?? []).length ? <ul className="clean-warnings">{(data?.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
      {drilldownLoading ? <p className="quiet-note">Resolving contributing rows…</p> : null}
      {drilldownError ? <p className="query-error" role="alert">{drilldownError}</p> : null}
      {drilldown ? <div className="viz-drilldown">
        <p className="clean-preview-summary">
          <strong>{drilldown.total_matching_rows.toLocaleString()}</strong> contributing row(s){drilldown.truncated ? <> — showing the first <strong>{drilldown.rows.length}</strong> (truncated, not downloaded in full)</> : null}, filtered by {Object.entries((drilldown.filters_applied ?? {})).map(([key, value]) => `${key} = ${value}`).join(", ")}.
        </p>
        <DrillDownTable rows={drilldown.rows} />
      </div> : null}
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

type MarkSelection = { dimensionValue?: string; xValue?: number; yValue?: number };

export function ChartCanvas({ mark, data, onSelectMark }: { mark: VizMark; data: readonly VisualizationDatum[]; onSelectMark?(selection: MarkSelection): void }) {
  if (!data.length) return <p className="quiet-note">No data to chart.</p>;
  const width = 640, height = 280, padding = 32;
  const selectable = Boolean(onSelectMark) && mark !== "histogram";

  if (mark === "scatter") {
    const xs = data.map((d) => d.x ?? 0);
    const ys = data.map((d) => d.value);
    const xMin = Math.min(...xs), xMax = Math.max(...xs);
    const xSpan = xMax - xMin || 1;
    const yMin = Math.min(...ys, 0), yMax = Math.max(...ys, 1);
    const ySpan = yMax - yMin || 1;
    return <svg role="img" aria-label={`Scatter chart with ${data.length} points`} viewBox={`0 0 ${width} ${height}`} className="viz-svg">
      {data.map((point, index) => <circle key={index} className={selectable ? "viz-mark-selectable" : undefined} tabIndex={selectable ? 0 : undefined} role={selectable ? "button" : undefined} aria-label={selectable ? `Inspect point ${point.label}` : undefined} cx={padding + (((point.x ?? 0) - xMin) / xSpan) * (width - 2 * padding)} cy={height - padding - ((point.value - yMin) / ySpan) * (height - 2 * padding)} r={3} onClick={() => onSelectMark?.({ xValue: point.x ?? 0, yValue: point.value })} onKeyDown={(event) => { if (selectable && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onSelectMark?.({ xValue: point.x ?? 0, yValue: point.value }); } }}><title>{point.label}</title></circle>)}
    </svg>;
  }

  if (mark === "box") {
    const boxes = data.filter((d) => d.box);
    if (!boxes.length) return <p className="quiet-note">No numeric distribution is available to summarize per group.</p>;
    const allValues = boxes.flatMap((d) => [d.box!.whisker_low, d.box!.whisker_high, d.box!.q1, d.box!.q3, ...(d.box!.outliers ?? [])]);
    const yMin = Math.min(...allValues, 0), yMax = Math.max(...allValues, 1);
    const ySpan = yMax - yMin || 1;
    const scaleY = (v: number) => height - padding - ((v - yMin) / ySpan) * (height - 2 * padding);
    const slotWidth = (width - 2 * padding) / boxes.length;
    const boxWidth = Math.max(8, Math.min(40, slotWidth * 0.5));
    return <svg role="img" aria-label={`Box plot across ${boxes.length} groups`} viewBox={`0 0 ${width} ${height}`} className="viz-svg">
      {boxes.map((point, index) => {
        const box = point.box!;
        const cx = padding + index * slotWidth + slotWidth / 2;
        const top = scaleY(box.q3), bottom = scaleY(box.q1), median = scaleY(box.median);
        return <g key={index} className={selectable ? "viz-mark-selectable" : undefined} tabIndex={selectable ? 0 : undefined} role={selectable ? "button" : undefined} aria-label={selectable ? `Inspect group ${point.label}` : undefined} onClick={() => onSelectMark?.({ dimensionValue: point.label })} onKeyDown={(event) => { if (selectable && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onSelectMark?.({ dimensionValue: point.label }); } }}>
          <line x1={cx} x2={cx} y1={scaleY(box.whisker_high)} y2={top} />
          <line x1={cx} x2={cx} y1={bottom} y2={scaleY(box.whisker_low)} />
          <rect x={cx - boxWidth / 2} y={top} width={boxWidth} height={Math.max(1, bottom - top)} />
          <line x1={cx - boxWidth / 2} x2={cx + boxWidth / 2} y1={median} y2={median} className="viz-box-median" />
          {(box.outliers ?? []).map((outlier, outlierIndex) => <circle key={outlierIndex} cx={cx} cy={scaleY(outlier)} r={2} className="viz-box-outlier" />)}
          <title>{`${point.label}: median ${box.median.toLocaleString()}, Q1 ${box.q1.toLocaleString()}, Q3 ${box.q3.toLocaleString()}${(box.outliers ?? []).length ? `, ${(box.outliers ?? []).length} outlier(s)` : ""}`}</title>
        </g>;
      })}
    </svg>;
  }

  // A zero-anchored, signed scale: constant-value data (max===min) still gets a
  // non-zero span via the `|| 1` fallback, and a negative value draws below the
  // zero baseline instead of producing an invalid negative-height rect.
  const values = data.map((d) => d.value);
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1;
  const scaleY = (v: number) => height - padding - ((v - min) / span) * (height - 2 * padding);
  if (mark === "line") {
    const points = data.map((point, index) => `${padding + (index / Math.max(1, data.length - 1)) * (width - 2 * padding)},${scaleY(point.value)}`).join(" ");
    const lineSelectable = Boolean(onSelectMark);
    return <svg role="img" aria-label={`Line chart across ${data.length} categories`} viewBox={`0 0 ${width} ${height}`} className="viz-svg">
      <polyline points={points} fill="none" />
      {lineSelectable ? data.map((point, index) => <circle key={index} className="viz-mark-selectable" tabIndex={0} role="button" aria-label={`Inspect ${point.label}`} cx={padding + (index / Math.max(1, data.length - 1)) * (width - 2 * padding)} cy={scaleY(point.value)} r={4} onClick={() => onSelectMark?.({ dimensionValue: point.label })} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelectMark?.({ dimensionValue: point.label }); } }}><title>{`${point.label}: ${point.value}`}</title></circle>) : null}
    </svg>;
  }
  const barWidth = (width - 2 * padding) / data.length;
  const zeroY = scaleY(0);
  return <svg role="img" aria-label={`Bar chart with ${data.length} categories`} viewBox={`0 0 ${width} ${height}`} className="viz-svg">
    {data.map((point, index) => { const valueY = scaleY(point.value); const y = Math.min(valueY, zeroY); const barHeight = Math.max(1, Math.abs(valueY - zeroY)); return <g key={index} className={selectable ? "viz-mark-selectable" : undefined} tabIndex={selectable ? 0 : undefined} role={selectable ? "button" : undefined} aria-label={selectable ? `Inspect ${point.label}` : undefined} onClick={() => onSelectMark?.({ dimensionValue: point.label })} onKeyDown={(event) => { if (selectable && (event.key === "Enter" || event.key === " ")) { event.preventDefault(); onSelectMark?.({ dimensionValue: point.label }); } }}><rect x={padding + index * barWidth + 2} y={y} width={Math.max(1, barWidth - 4)} height={barHeight} /><title>{`${point.label}: ${point.value}`}</title></g>; })}
  </svg>;
}

function DrillDownTable({ rows }: { rows: readonly Record<string, unknown>[] }) {
  if (!rows.length) return <p className="quiet-note">No rows.</p>;
  const columns = Object.keys(rows[0] ?? {});
  return <div className="data-table-wrap" tabIndex={0}><table><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{row[key] === null || row[key] === undefined ? "—" : String(row[key])}</td>)}</tr>)}</tbody></table></div>;
}
