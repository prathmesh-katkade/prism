"use client";

import React, { useCallback, useEffect, useState } from "react";
import type {
  AtlasForecastAction,
  AtlasForecastResponse,
  ChangepointResult,
  DecompositionResult,
  ForecastPoint,
  ForecastResult,
  OverviewProfileResponse,
} from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type ForecastingUiState = "empty" | "loading" | "ready" | "error";
type Mode = "forecast" | "decompose" | "changepoints";
const MODES: readonly Mode[] = ["forecast", "decompose", "changepoints"];
const ATLAS_ACTIONS: readonly AtlasForecastAction[] = ["explain_method", "explain_trend", "explain_seasonality", "explain_changepoints", "explain_intervals"];

/** Phase 7B: series → validate → forecast/decompose/changepoints → chart + metrics + caveat → provenance/Atlas. */
export function ForecastingWorkspace({ datasetId, onSelectContext, onOpenWorkflow }: { datasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void }) {
  const [state, setState] = useState<ForecastingUiState>(datasetId ? "loading" : "empty");
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [datetimeCol, setDatetimeCol] = useState<string>("");
  const [numericCol, setNumericCol] = useState<string>("");
  const [mode, setMode] = useState<Mode>("forecast");
  const [horizon, setHorizon] = useState(12);
  const [maxChangepoints, setMaxChangepoints] = useState(5);
  const [forecastResult, setForecastResult] = useState<ForecastResult | null>(null);
  const [decompositionResult, setDecompositionResult] = useState<DecompositionResult | null>(null);
  const [changepointResult, setChangepointResult] = useState<ChangepointResult | null>(null);
  const [atlas, setAtlas] = useState<AtlasForecastResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async (id: string) => {
    setState("loading"); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/profile`));
      if (!response.ok) throw new Error("Forecasting needs a profiled dataset from Overview.");
      const next = await response.json() as OverviewProfileResponse;
      setProfile(next);
      const dtCol = next.columns.find((c) => c.semantic_type === "datetime")?.name ?? "";
      const numCol = next.columns.find((c) => c.semantic_type === "numeric")?.name ?? "";
      setDatetimeCol(dtCol); setNumericCol(numCol);
      setState("ready");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Forecasting is unavailable."); setState("error"); }
  }, []);

  useEffect(() => { if (datasetId) void load(datasetId); else { setState("empty"); setProfile(null); } }, [datasetId, load]);

  const run = useCallback(async () => {
    if (!datasetId || !datetimeCol || !numericCol) return;
    setRunning(true); setError(null); setAtlas(null);
    setForecastResult(null); setDecompositionResult(null); setChangepointResult(null);
    try {
      if (mode === "forecast") {
        const response = await fetch(apiUrl(`/api/v1/forecasting/datasets/${datasetId}/forecast`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ datetime_col: datetimeCol, numeric_col: numericCol, horizon }) });
        if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "This series could not be forecast.");
        const body = await response.json() as ForecastResult;
        setForecastResult(body);
        onSelectContext({ objectId: `forecast:${datetimeCol}:${numericCol}`, label: `Forecast — ${numericCol}`, type: "finding", state: "ready", actions: [{ id: "atlas-explain-method", label: "Ask Atlas to explain" }], metadata: [body.model_used, `${body.horizon} periods ahead`] });
      } else if (mode === "decompose") {
        const response = await fetch(apiUrl(`/api/v1/forecasting/datasets/${datasetId}/decompose`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ datetime_col: datetimeCol, numeric_col: numericCol }) });
        if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "This series could not be decomposed.");
        setDecompositionResult(await response.json() as DecompositionResult);
      } else {
        const response = await fetch(apiUrl(`/api/v1/forecasting/datasets/${datasetId}/changepoints`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ datetime_col: datetimeCol, numeric_col: numericCol, max_changepoints: maxChangepoints }) });
        if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Changepoint detection could not run.");
        setChangepointResult(await response.json() as ChangepointResult);
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This request failed."); }
    finally { setRunning(false); }
  }, [datasetId, datetimeCol, numericCol, mode, horizon, maxChangepoints, onSelectContext]);

  useEffect(() => { if (datasetId && datetimeCol && numericCol) void run(); }, [datasetId, datetimeCol, numericCol, mode]);

  async function askAtlas(action: AtlasForecastAction) {
    if (!datasetId || !datetimeCol || !numericCol) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/forecasting/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, datetime_col: datetimeCol, numeric_col: numericCol }) });
      if (!response.ok) return;
      setAtlas(await response.json() as AtlasForecastResponse);
    } catch { /* Atlas commentary is optional; the result remains usable without it. */ }
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">FORECASTING · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Forecasting projects the same server-held dataset Overview and SQL Lab already use.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  if (state === "loading" || !profile) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Preparing Forecasting</h2><p>Model selection is deterministic — Exponential Smoothing is tried first, SARIMAX is the fallback.</p></section>;
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>Forecasting could not load this dataset.</h2><p>{error}</p><button onClick={() => datasetId && void load(datasetId)}>Retry</button></section>;

  const datetimeColumns = profile.columns.filter((c) => c.semantic_type === "datetime");
  const numericColumns = profile.columns.filter((c) => c.semantic_type === "numeric");

  return <article className="forecasting-workspace three-pane">
    <nav className="forecasting-fields" aria-label="Series selection" tabIndex={0}>
      <div className="section-title"><span className="eyebrow">SERIES</span><h2>{profile.dataset.source_name}</h2></div>
      <label>Datetime column<select value={datetimeCol} onChange={(event) => setDatetimeCol(event.target.value)}>{datetimeColumns.length ? datetimeColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>) : <option value="">No datetime column detected</option>}</select></label>
      <label>Value column<select value={numericCol} onChange={(event) => setNumericCol(event.target.value)}>{numericColumns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label>
      <label>Analysis<select value={mode} onChange={(event) => setMode(event.target.value as Mode)}>{MODES.map((m) => <option key={m} value={m}>{m}</option>)}</select></label>
      {mode === "forecast" ? <label>Horizon (periods)<input type="number" min={1} max={365} value={horizon} onChange={(event) => setHorizon(Number(event.target.value) || 1)} onBlur={() => void run()} /></label> : null}
      {mode === "changepoints" ? <label>Max changepoints<input type="number" min={1} max={20} value={maxChangepoints} onChange={(event) => setMaxChangepoints(Number(event.target.value) || 1)} onBlur={() => void run()} /></label> : null}
      {!datetimeColumns.length ? <p className="quiet-note">No datetime column was detected in this dataset — Forecasting needs one to build a time series.</p> : null}
    </nav>
    <section className="forecasting-canvas" aria-label="Forecast canvas" tabIndex={0}>
      <header><span className="eyebrow">{mode.toUpperCase()}</span><h1>{numericCol} over {datetimeCol}</h1></header>
      {running ? <p className="quiet-note">Fitting…</p> : error ? <p className="quiet-note">{error}</p> : mode === "forecast" && forecastResult ? <>
        <ForecastChart result={forecastResult} />
        <p className="clean-preview-summary">{forecastResult.model_used}</p>
        <aside className="stat-evidence" aria-live="polite"><strong>Reliability caveat</strong><small>{forecastResult.caveat}</small></aside>
        {(forecastResult.warnings ?? []).length ? <ul className="clean-warnings">{(forecastResult.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
      </> : mode === "decompose" && decompositionResult ? <>
        <DecompositionChart result={decompositionResult} />
        <p className="clean-preview-summary">{decompositionResult.verdict}</p>
      </> : mode === "changepoints" && changepointResult ? <>
        <ChangepointChart result={changepointResult} />
        <p className="clean-preview-summary" style={{ whiteSpace: "pre-line" }}>{changepointResult.verdict}</p>
      </> : <p className="quiet-note">Choose a datetime column, a value column, and an analysis to begin.</p>}
    </section>
    <aside className="inspector forecasting-inspector" aria-label="Metrics, provenance, and Atlas">
      {mode === "forecast" && forecastResult ? <dl className="inspector-data">
        <div><dt>Frequency</dt><dd>{forecastResult.frequency}</dd></div>
        <div><dt>MAE (holdout)</dt><dd>{forecastResult.metrics.mae !== null && forecastResult.metrics.mae !== undefined ? forecastResult.metrics.mae.toFixed(3) : "—"}</dd></div>
        <div><dt>RMSE (holdout)</dt><dd>{forecastResult.metrics.rmse !== null && forecastResult.metrics.rmse !== undefined ? forecastResult.metrics.rmse.toFixed(3) : "—"}</dd></div>
        <div><dt>Revision</dt><dd>{forecastResult.provenance.dataset_revision}</dd></div>
        <div><dt>Source</dt><dd><code>{forecastResult.provenance.source_fingerprint.slice(0, 12)}…</code></dd></div>
      </dl> : mode === "decompose" && decompositionResult ? <dl className="inspector-data">
        <div><dt>Seasonal period</dt><dd>{decompositionResult.seasonal_period}</dd></div>
        <div><dt>Trend strength</dt><dd>{decompositionResult.trend_strength.toFixed(3)}</dd></div>
        <div><dt>Seasonal strength</dt><dd>{decompositionResult.seasonal_strength.toFixed(3)}</dd></div>
        <div><dt>Revision</dt><dd>{decompositionResult.provenance.dataset_revision}</dd></div>
      </dl> : mode === "changepoints" && changepointResult ? <dl className="inspector-data">
        <div><dt>Breaks found</dt><dd>{changepointResult.changepoints.length}</dd></div>
        <div><dt>Segments</dt><dd>{changepointResult.n_segments}</dd></div>
        <div><dt>Revision</dt><dd>{changepointResult.provenance.dataset_revision}</dd></div>
      </dl> : <p className="quiet-note">Run an analysis to see its metrics and provenance here.</p>}
      <div className="inspector-actions"><span className="eyebrow">ATLAS · EVIDENCE-AWARE</span>{ATLAS_ACTIONS.map((action) => <button key={action} onClick={() => void askAtlas(action)}>{action.replaceAll("_", " ")}</button>)}</div>
      {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong style={{ whiteSpace: "pre-line" }}>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
    </aside>
  </article>;
}

const CHART_WIDTH = 640, CHART_HEIGHT = 260, CHART_PADDING = 32;

function _scale(points: readonly ForecastPoint[], extra: readonly number[] = []) {
  const values = [...points.map((p) => p.value), ...extra];
  const min = Math.min(...values), max = Math.max(...values);
  const span = max - min || 1;
  return { min, max, span };
}

function _x(index: number, total: number): number {
  return CHART_PADDING + (total <= 1 ? 0 : (index / (total - 1)) * (CHART_WIDTH - 2 * CHART_PADDING));
}

function _y(value: number, min: number, span: number): number {
  return CHART_HEIGHT - CHART_PADDING - ((value - min) / span) * (CHART_HEIGHT - 2 * CHART_PADDING);
}

function ForecastChart({ result }: { result: ForecastResult }) {
  const allValues = [...result.observed.map((p) => p.value), ...result.forecast.map((p) => p.value), ...result.intervals.flatMap((i) => [i.lower, i.upper])];
  const min = Math.min(...allValues), max = Math.max(...allValues), span = max - min || 1;
  const total = result.observed.length + result.forecast.length;
  const observedPoints = result.observed.map((p, i) => `${_x(i, total)},${_y(p.value, min, span)}`).join(" ");
  const forecastStart = result.observed.length - 1;
  const forecastPoints = result.forecast.map((p, i) => `${_x(forecastStart + 1 + i, total)},${_y(p.value, min, span)}`).join(" ");
  const bandTop = result.intervals.map((iv, i) => `${_x(forecastStart + 1 + i, total)},${_y(iv.upper, min, span)}`);
  const bandBottom = result.intervals.map((iv, i) => `${_x(forecastStart + 1 + i, total)},${_y(iv.lower, min, span)}`).reverse();
  return <svg role="img" aria-label={`Forecast chart: ${result.observed.length} observed points and ${result.forecast.length} forecast points`} viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="viz-svg forecast-svg">
    <polygon points={[...bandTop, ...bandBottom].join(" ")} className="forecast-band" />
    <polyline points={observedPoints} className="forecast-observed" fill="none" />
    <polyline points={forecastPoints} className="forecast-forecast" fill="none" />
  </svg>;
}

function DecompositionChart({ result }: { result: DecompositionResult }) {
  const rows: readonly [string, readonly ForecastPoint[]][] = [["Observed", result.observed], ["Trend", result.trend], ["Seasonal", result.seasonal], ["Residual", result.resid]];
  return <div className="decomposition-grid">{rows.map(([label, points]) => {
    const { min, span } = _scale(points);
    const path = points.map((p, i) => `${_x(i, points.length)},${_y(p.value, min, span)}`).join(" ");
    return <div key={label} className="decomposition-row"><span className="eyebrow">{label.toUpperCase()}</span><svg role="img" aria-label={`${label} component`} viewBox={`0 0 ${CHART_WIDTH} 80`} className="viz-svg forecast-svg" style={{ height: 80 }}><polyline points={path} className="forecast-observed" fill="none" /></svg></div>;
  })}</div>;
}

function ChangepointChart({ result }: { result: ChangepointResult }) {
  const { min, span } = _scale(result.observed);
  const path = result.observed.map((p, i) => `${_x(i, result.observed.length)},${_y(p.value, min, span)}`).join(" ");
  const timestamps = result.observed.map((p) => p.timestamp);
  return <svg role="img" aria-label={`Series with ${result.changepoints.length} detected changepoint${result.changepoints.length === 1 ? "" : "s"}`} viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`} className="viz-svg forecast-svg">
    <polyline points={path} className="forecast-observed" fill="none" />
    {result.changepoints.map((cp) => {
      const index = timestamps.indexOf(cp.timestamp);
      if (index === -1) return null;
      const x = _x(index, result.observed.length);
      return <line key={cp.position} x1={x} x2={x} y1={CHART_PADDING} y2={CHART_HEIGHT - CHART_PADDING} className="changepoint-marker" />;
    })}
  </svg>;
}
