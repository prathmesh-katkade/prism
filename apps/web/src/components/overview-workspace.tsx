"use client";

import React, { useCallback, useEffect, useMemo, useState } from "react";
import type { AtlasOverviewAction, AtlasOverviewResponse, DatasetRowsResponse, OverviewColumn, OverviewProfileResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type OverviewState = "empty" | "uploading" | "ready" | "degraded" | "error";

function formatPercent(value: number): string {
  return `${value.toFixed(value % 1 === 0 ? 0 : 1)}%`;
}

export function OverviewWorkspace({ activeDatasetId, onSelectContext, onOpenWorkflow, onDatasetReady }: { activeDatasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void; onDatasetReady?(datasetId: string): void }) {
  const [state, setState] = useState<OverviewState>("empty");
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [rows, setRows] = useState<DatasetRowsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [atlas, setAtlas] = useState<AtlasOverviewResponse | null>(null);

  const loadRows = useCallback(async (id: string) => {
    const response = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/rows?offset=0&limit=20`));
    if (!response.ok) throw new Error("Preview rows are unavailable.");
    setRows(await response.json() as DatasetRowsResponse);
  }, []);

  const loadDataset = useCallback(async (id: string) => {
    setState("uploading"); setError(null); setAtlas(null); setRows(null);
    try {
      const profiled = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/profile`));
      if (!profiled.ok) throw new Error("This dataset's Overview profile could not be loaded.");
      const nextProfile = await profiled.json() as OverviewProfileResponse;
      setDatasetId(id); setProfile(nextProfile); setState("ready");
      onSelectContext({ objectId: id, label: nextProfile.dataset.source_name, type: "dataset", state: "ready", actions: [{ id: "trace-source", label: "Trace source" }, { id: "summarize-risks", label: "Summarize key risks" }], metadata: [`${nextProfile.quality.n_rows.toLocaleString()} rows`, `${nextProfile.quality.n_cols} columns`, `Health ${nextProfile.health.total}/100`] });
      await loadRows(id);
    } catch (reason) {
      setState("error"); setError(reason instanceof Error ? reason.message : "Overview could not profile this dataset.");
    }
  }, [loadRows, onSelectContext]);

  // Every other native workspace (SQL Lab, AI Analyst, Clean, Visualize) resolves the active
  // dataset through shared shell state rather than local component state, so it survives a tab
  // switch. Overview used to be the exception - unmounting on tab switch reset it to the upload
  // prompt even though the shell already knew which dataset was active. Restore it (including
  // after a Clean transformation elsewhere produces a new revision) whenever the shell's active
  // dataset differs from what this instance currently shows.
  useEffect(() => {
    if (activeDatasetId && activeDatasetId !== datasetId) void loadDataset(activeDatasetId);
  }, [activeDatasetId, datasetId, loadDataset]);

  const selectColumn = useCallback((column: OverviewColumn) => {
    onSelectContext({
      objectId: `column:${column.name}`, label: column.name, type: "column", state: "ready",
      actions: [
        { id: "atlas-explain-column", label: "Ask Atlas to explain this column" },
        { id: "compare-column", label: "Compare with another column" },
        { id: "open-clean", label: "Open Clean bridge" },
      ],
      metadata: [`${column.semantic_type} · ${column.unique_count.toLocaleString()} distinct values`, `${formatPercent(column.missing_pct)} missing`, `${column.health} health`],
    });
  }, [onSelectContext]);

  async function upload(file: File) {
    setState("uploading"); setError(null); setAtlas(null); setRows(null);
    try {
      const body = new FormData(); body.append("file", file);
      const uploaded = await fetch(apiUrl("/api/v1/overview/datasets"), { method: "POST", body });
      if (!uploaded.ok) throw new Error((await uploaded.json() as { detail?: string }).detail ?? "Dataset upload failed.");
      const dataset = await uploaded.json() as { dataset_id: string };
      onDatasetReady?.(dataset.dataset_id);
      await loadDataset(dataset.dataset_id);
    } catch (reason) {
      setState("error"); setError(reason instanceof Error ? reason.message : "Overview could not profile this dataset.");
    }
  }

  async function askAtlas(action: AtlasOverviewAction, column?: string, comparisonColumn?: string) {
    if (!datasetId) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/overview/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, column, comparison_column: comparisonColumn }) });
      if (!response.ok) throw new Error("Atlas could not ground that action in the current profile.");
      setAtlas(await response.json() as AtlasOverviewResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Atlas is unavailable."); setState("degraded"); }
  }

  const riskColumns = useMemo(() => profile?.columns.filter((column) => column.health !== "good") ?? [], [profile]);
  useEffect(() => { if (state === "degraded" && profile) setState("ready"); }, [profile, state]);

  if (state === "empty") return <section className="overview-state empty-state"><span className="overview-prism" /><span className="eyebrow">OVERVIEW · NATIVE WORKSPACE</span><h1>Start with the dataset, then follow the evidence.</h1><p>Upload a CSV or Excel file. PRISM profiles it server-side; the browser receives only summaries and a paginated preview.</p><input id="overview-upload" className="upload-input" aria-label="Choose dataset" type="file" accept=".csv,.txt,.xls,.xlsx" onChange={(event) => { const file = event.target.files?.[0]; if (file) void upload(file); }} /><label className="upload-control" htmlFor="overview-upload">Choose dataset</label><small>Phase 3 limit: 64 MB / 500,000 rows. The legacy Streamlit Overview remains available for parity.</small></section>;
  if (state === "uploading") return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Establishing the dataset profile</h2><p>Computing schema, quality, distributions, relationships, and provenance on the server.</p></section>;
  if (state === "error" || !profile) return <section className="overview-state error-state" role="alert"><h2>Overview could not establish a profile.</h2><p>{error}</p><button onClick={() => setState("empty")}>Choose another dataset</button><button className="secondary" onClick={() => setState("degraded")}>Show recovery guidance</button></section>;

  return <article className="overview-workspace">
    <header className="overview-heading"><div><span className="eyebrow">OVERVIEW · DATASET INTELLIGENCE</span><h1>{profile.dataset.source_name}</h1><p>{profile.quality.n_rows.toLocaleString()} rows · {profile.quality.n_cols} columns · server-profiled evidence · <code>{profile.provenance.source_fingerprint.slice(0, 12)}…</code></p></div><button className="secondary" onClick={() => setState("empty")}>Replace dataset</button></header>
    <section className="overview-scan" aria-label="Executive dataset scan"><article className={`health-meter health-${profile.health.total >= 80 ? "good" : profile.health.total >= 60 ? "warn" : "risk"}`}><span>DATA HEALTH</span><strong>{profile.health.total}</strong><small>/100 · explainable score</small></article><Metric label="Missing" value={formatPercent(profile.quality.total_missing_pct)} detail={`${profile.quality.total_missing_cells.toLocaleString()} cells`} /><Metric label="Duplicates" value={profile.quality.duplicate_rows.toLocaleString()} detail="exact row matches" /><Metric label="Outlier signals" value={Object.values(profile.quality.outliers).reduce((sum, item) => sum + Number(item.count), 0).toLocaleString()} detail="IQR / numeric columns" /></section>
    <section className="overview-section overview-risks"><div><span className="eyebrow">01 · EXECUTIVE SCAN</span><h2>What needs attention first</h2></div><div className="finding-list">{riskColumns.length ? riskColumns.slice(0, 5).map((column) => <button key={column.name} onClick={() => selectColumn(column)}><span className={`finding-dot ${column.health}`} /><strong>{column.name}</strong><small>{column.issues[0] ?? column.warnings[0]}</small></button>) : <p className="quiet-note">No column-level quality issues crossed the Overview thresholds.</p>}</div></section>
    <section className="overview-section"><div className="section-title"><div><span className="eyebrow">02 · COLUMN MAP</span><h2>Schema with health in context</h2></div><small>Select a column to populate the contextual inspector.</small></div><div className="column-grid">{profile.columns.map((column) => <button key={column.name} className={`column-card ${column.health}`} onClick={() => selectColumn(column)}><span>{column.semantic_type}</span><strong>{column.name}</strong><small>{column.unique_count.toLocaleString()} distinct · {formatPercent(column.missing_pct)} missing</small><div className="distribution" aria-label={`${column.name} top distribution`}>{column.distribution.slice(0, 8).map((bucket, index) => <i key={`${String(bucket.label)}-${index}`} style={{ height: `${Math.max(10, Math.min(100, bucket.count / Math.max(1, column.distribution[0]?.count ?? 1) * 100))}%` }} />)}</div></button>)}</div></section>
    <section className="overview-section relationship-grid"><div><span className="eyebrow">03 · RELATIONSHIPS</span><h2>Strongest measured relationships</h2>{profile.correlations.length ? <div className="relationship-list">{profile.correlations.slice(0, 5).map((pair) => <button key={`${pair.left}-${pair.right}`} onClick={() => onSelectContext({ objectId: `correlation:${pair.left}:${pair.right}`, label: `${pair.left} × ${pair.right}`, type: "finding", state: "ready", actions: [{ id: "compare-columns", label: "Ask Atlas to compare columns" }, { id: "open-visualize", label: "Open Visualize bridge" }], metadata: [`Pearson r ${pair.coefficient.toFixed(2)}`, "Correlation is not causation"] })}><strong>{pair.left} <span>×</span> {pair.right}</strong><small>Pearson r {pair.coefficient.toFixed(2)}</small></button>)}</div> : <p className="quiet-note">At least two numeric columns are needed to compute relationships.</p>}</div><div><span className="eyebrow">04 · NEXT BEST STEP</span><h2>Continue without pretending migrations are finished.</h2><div className="suggestion-list">{profile.suggestions.map((suggestion) => <button key={suggestion.workflow} onClick={() => onOpenWorkflow(suggestion.workflow)}><strong>{suggestion.workflow.replace("-", " ")}</strong><small>{suggestion.reason}</small></button>)}</div></div></section>
    <section className="overview-section atlas-actions"><div><span className="eyebrow">ATLAS · CONTEXTUAL, GROUNDED</span><h2>Ask about this evidence</h2><p>Atlas uses the profile above and states uncertainty; it does not initiate autonomous analysis in Phase 3.</p></div><div className="atlas-action-row">{(["explain_dataset", "diagnose_quality", "inspect_anomaly", "suggest_next_analysis", "trace_source", "summarize_risks"] as AtlasOverviewAction[]).map((action) => <button key={action} onClick={() => void askAtlas(action)}>{action.replaceAll("_", " ")}</button>)}</div>{atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS RESPONSE · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}</section>
    <section className="overview-section"><div className="section-title"><div><span className="eyebrow">05 · ROW SAMPLE</span><h2>Paginated data preview</h2></div><small>{rows ? `Showing ${rows.rows.length} of ${rows.total_rows.toLocaleString()} rows` : "Loading preview…"}</small></div>{rows ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr>{Object.keys(rows.rows[0] ?? {}).map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.rows.map((row, index) => <tr key={index}>{Object.entries(row).map(([key, value]) => <td key={key}>{value === null ? "—" : String(value)}</td>)}</tr>)}</tbody></table></div> : <p className="quiet-note">Preview unavailable; the profile remains available.</p>}</section>
  </article>;
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) { return <article className="overview-metric"><span>{label}</span><strong>{value}</strong><small>{detail}</small></article>; }
