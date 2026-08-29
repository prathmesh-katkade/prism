"use client";

import React, { useCallback, useEffect, useState } from "react";
import type {
  AtlasMlAction,
  AtlasMlResponse,
  MlBaselineResult,
  MlFeatureSelectionResult,
  MlFeatureSuggestion,
  MlImbalanceInfo,
  MlShapResult,
  MlTaskType,
  OverviewProfileResponse,
} from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type MlUiState = "empty" | "loading" | "ready" | "error";
type Mode = "suggest" | "baseline" | "feature-selection" | "shap" | "imbalance";
const MODES: readonly Mode[] = ["suggest", "baseline", "feature-selection", "shap", "imbalance"];
const ATLAS_ACTIONS: readonly AtlasMlAction[] = ["explain_task_type", "compare_models", "explain_cross_validation", "explain_imbalance", "explain_feature_importance", "identify_overfitting"];

/** Phase 7C: target + features → task detection → baseline models/CV/feature-selection/SHAP/imbalance → verdict + leakage note + provenance/Atlas. Baseline exploration only, never a deployment pipeline. */
export function MlLabWorkspace({ datasetId, onSelectContext, onOpenWorkflow }: { datasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void }) {
  const [state, setState] = useState<MlUiState>(datasetId ? "loading" : "empty");
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [targetCol, setTargetCol] = useState("");
  const [featureCols, setFeatureCols] = useState<readonly string[]>([]);
  const [mode, setMode] = useState<Mode>("suggest");
  const [useSmote, setUseSmote] = useState(false);
  const [suggestions, setSuggestions] = useState<readonly MlFeatureSuggestion[]>([]);
  const [taskType, setTaskType] = useState<MlTaskType | null>(null);
  const [imbalance, setImbalance] = useState<MlImbalanceInfo | null>(null);
  const [baselineResult, setBaselineResult] = useState<MlBaselineResult | null>(null);
  const [featureSelectionResult, setFeatureSelectionResult] = useState<MlFeatureSelectionResult | null>(null);
  const [shapResult, setShapResult] = useState<MlShapResult | null>(null);
  const [atlas, setAtlas] = useState<AtlasMlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async (id: string) => {
    setState("loading"); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/profile`));
      if (!response.ok) throw new Error("ML Lab needs a profiled dataset from Overview.");
      const next = await response.json() as OverviewProfileResponse;
      setProfile(next);
      const target = next.columns[next.columns.length - 1]?.name ?? "";
      setTargetCol(target);
      setFeatureCols(next.columns.filter((c) => c.name !== target).map((c) => c.name));
      setState("ready");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "ML Lab is unavailable."); setState("error"); }
  }, []);

  useEffect(() => { if (datasetId) void load(datasetId); else { setState("empty"); setProfile(null); } }, [datasetId, load]);

  const refreshCheap = useCallback(async (id: string, target: string) => {
    if (!target) return;
    setError(null); setAtlas(null);
    try {
      const suggestResponse = await fetch(apiUrl(`/api/v1/ml/datasets/${id}/suggest-features?target_col=${encodeURIComponent(target)}`));
      if (suggestResponse.ok) setSuggestions((await suggestResponse.json() as { suggestions: MlFeatureSuggestion[] }).suggestions);
      const taskResponse = await fetch(apiUrl(`/api/v1/ml/datasets/${id}/detect-task?target_col=${encodeURIComponent(target)}`));
      if (taskResponse.ok) {
        const body = await taskResponse.json() as { task_type: MlTaskType };
        setTaskType(body.task_type);
        if (body.task_type === "classification") {
          const imbalanceResponse = await fetch(apiUrl(`/api/v1/ml/datasets/${id}/imbalance?target_col=${encodeURIComponent(target)}`));
          setImbalance(imbalanceResponse.ok ? await imbalanceResponse.json() as MlImbalanceInfo : null);
        } else { setImbalance(null); }
      }
    } catch { /* Cheap diagnostics are best-effort; the workspace stays usable without them. */ }
  }, []);

  useEffect(() => { if (datasetId && targetCol) void refreshCheap(datasetId, targetCol); }, [datasetId, targetCol, refreshCheap]);

  function toggleFeature(name: string) {
    setFeatureCols((previous) => previous.includes(name) ? previous.filter((c) => c !== name) : [...previous, name]);
  }

  async function applyFeature(suggestion: MlFeatureSuggestion) {
    if (!datasetId) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/ml/datasets/${datasetId}/apply-feature`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ suggestion }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "This feature could not be applied.");
      await load(datasetId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "This feature could not be applied."); }
  }

  async function runBaseline() {
    if (!datasetId || !targetCol || !featureCols.length) return;
    setRunning(true); setError(null); setAtlas(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/ml/datasets/${datasetId}/baseline`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ feature_cols: featureCols, target_col: targetCol, use_smote: useSmote }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "The baseline models could not be run.");
      const body = await response.json() as MlBaselineResult;
      setBaselineResult(body);
      onSelectContext({ objectId: `ml-baseline:${targetCol}`, label: `Baseline — ${targetCol}`, type: "finding", state: "ready", actions: [{ id: "atlas-compare-models", label: "Ask Atlas to compare models" }], metadata: [body.task_type, body.verdict] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The baseline models could not be run."); }
    finally { setRunning(false); }
  }

  async function runFeatureSelection() {
    if (!datasetId || !targetCol || featureCols.length < 2) return;
    setRunning(true); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/ml/datasets/${datasetId}/feature-selection`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ feature_cols: featureCols, target_col: targetCol }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Feature selection could not run.");
      setFeatureSelectionResult(await response.json() as MlFeatureSelectionResult);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Feature selection could not run."); }
    finally { setRunning(false); }
  }

  async function runShap() {
    if (!datasetId || !targetCol || !featureCols.length) return;
    setRunning(true); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/ml/datasets/${datasetId}/shap`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ feature_cols: featureCols, target_col: targetCol }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "SHAP explanation could not run.");
      setShapResult(await response.json() as MlShapResult);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "SHAP explanation could not run."); }
    finally { setRunning(false); }
  }

  async function askAtlas(action: AtlasMlAction) {
    if (!datasetId || !targetCol || !featureCols.length) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/ml/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, feature_cols: featureCols, target_col: targetCol }) });
      if (!response.ok) return;
      setAtlas(await response.json() as AtlasMlResponse);
    } catch { /* Atlas commentary is optional; the result remains usable without it. */ }
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">ML LAB · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>ML Lab explores baselines against the same server-held dataset Overview and SQL Lab already use. This is a baseline exploration tool, not a model-deployment pipeline.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  if (state === "loading" || !profile) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Preparing ML Lab</h2><p>Task detection is deterministic — dtype and cardinality decide classification vs. regression, never an LLM.</p></section>;
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>ML Lab could not load this dataset.</h2><p>{error}</p><button onClick={() => datasetId && void load(datasetId)}>Retry</button></section>;

  return <article className="mllab-workspace three-pane">
    <nav className="mllab-fields" aria-label="Target, features, and analysis" tabIndex={0}>
      <div className="section-title"><span className="eyebrow">TARGET</span><h2>{profile.dataset.source_name}</h2></div>
      <label>Target column<select value={targetCol} onChange={(event) => { const next = event.target.value; setTargetCol(next); setFeatureCols((previous) => previous.filter((name) => name !== next)); }}>{profile.columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label>
      {taskType ? <p className="quiet-note">Detected: {taskType}</p> : null}
      <label>Analysis<select value={mode} onChange={(event) => setMode(event.target.value as Mode)}>{MODES.map((m) => <option key={m} value={m}>{m}</option>)}</select></label>
      {mode === "baseline" && taskType === "classification" ? <label className="mllab-checkbox"><input type="checkbox" checked={useSmote} onChange={(event) => setUseSmote(event.target.checked)} /> Use SMOTE on training set</label> : null}
      <p className="quiet-note">FEATURES ({featureCols.length} selected)</p>
      <div className="mllab-feature-list">{profile.columns.filter((c) => c.name !== targetCol).map((c) => <label key={c.name} className="mllab-checkbox"><input type="checkbox" checked={featureCols.includes(c.name)} onChange={() => toggleFeature(c.name)} /> {c.name}</label>)}</div>
    </nav>
    <section className="mllab-results" aria-label="Analysis results" tabIndex={0}>
      <header><span className="eyebrow">{mode.toUpperCase().replaceAll("-", " ")}</span><h1>{targetCol}</h1></header>
      {error ? <p className="quiet-note">{error}</p> : mode === "suggest" ? <>
        <p className="clean-preview-summary">{suggestions.length} feature suggestion(s) for {targetCol}.</p>
        <div className="finding-list">{suggestions.map((suggestion, index) => <button key={index} onClick={() => void applyFeature(suggestion)}><span className="finding-dot good" /><strong>{suggestion.kind}{suggestion.column ? `: ${suggestion.column}` : suggestion.columns ? `: ${suggestion.columns.join(" × ")}` : ""}</strong><small>{suggestion.reason}</small></button>)}</div>
      </> : mode === "imbalance" ? imbalance ? <>
        <p className="clean-preview-summary">{imbalance.explanation}</p>
        <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Class</th><th>Count</th><th>%</th></tr></thead><tbody>{Object.keys(imbalance.counts).map((key) => <tr key={key}><td>{key}</td><td>{imbalance.counts[key]}</td><td>{imbalance.proportions_pct[key]}%</td></tr>)}</tbody></table></div>
      </> : <p className="quiet-note">{taskType === "regression" ? "Class imbalance applies to classification targets only." : "Loading imbalance diagnostics…"}</p> : mode === "baseline" ? <>
        <div className="inspector-actions"><button disabled={running || !featureCols.length} onClick={() => void runBaseline()}>{running ? "Running…" : "Run baseline models"}</button></div>
        {baselineResult ? <>
          <p className="clean-preview-summary">{baselineResult.verdict}</p>
          <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Model</th>{Object.keys(baselineResult.results.Baseline ?? {}).map((metric) => <th key={metric}>{metric}</th>)}</tr></thead><tbody>{Object.keys(baselineResult.results).map((name) => <tr key={name}><td>{name}</td>{Object.values(baselineResult.results[name] ?? {}).map((value, i) => <td key={i}>{value}</td>)}</tr>)}</tbody></table></div>
          {baselineResult.cv ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>CV ({baselineResult.cv.n_splits}-fold)</th>{Object.keys(baselineResult.cv.results.Baseline ?? {}).map((metric) => <th key={metric}>{metric}</th>)}</tr></thead><tbody>{Object.keys(baselineResult.cv.results).map((name) => <tr key={name}><td>{name}</td>{Object.values(baselineResult.cv?.results[name] ?? {}).map((value, i) => <td key={i}>{value.mean.toFixed(3)} ± {value.std.toFixed(3)}</td>)}</tr>)}</tbody></table></div> : baselineResult.cv_error ? <p className="quiet-note">CV unavailable: {baselineResult.cv_error}</p> : null}
          {baselineResult.confusion_matrix && baselineResult.confusion_labels ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Actual \ Predicted</th>{baselineResult.confusion_labels.map((label) => <th key={label}>{label}</th>)}</tr></thead><tbody>{baselineResult.confusion_matrix.map((row, i) => <tr key={i}><td>{baselineResult.confusion_labels?.[i]}</td>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div> : null}
          <aside className="stat-evidence" aria-live="polite"><strong>Leakage protection</strong><small>{baselineResult.leakage_note}</small></aside>
        </> : null}
      </> : mode === "feature-selection" ? <>
        <div className="inspector-actions"><button disabled={running || featureCols.length < 2} onClick={() => void runFeatureSelection()}>{running ? "Running…" : "Run feature selection"}</button></div>
        {featureSelectionResult ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Feature</th><th>Consensus votes</th><th>MI rank</th><th>L1 rank</th><th>RFE selected</th></tr></thead><tbody>{featureSelectionResult.ranking.map((row) => <tr key={row.feature} className={featureSelectionResult.recommended_features.includes(row.feature) ? "is-selected" : ""}><td>{row.feature}</td><td>{row.consensus_votes}/3</td><td>{row.mutual_info_rank}</td><td>{row.l1_rank}</td><td>{row.rfe_selected ? "yes" : "no"}</td></tr>)}</tbody></table></div> : null}
      </> : <>
        <div className="inspector-actions"><button disabled={running || !featureCols.length} onClick={() => void runShap()}>{running ? "Running…" : "Explain with SHAP"}</button></div>
        {shapResult ? <>
          <p className="clean-preview-summary">{shapResult.note}</p>
          <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Feature</th><th>Mean |SHAP|</th></tr></thead><tbody>{shapResult.global_importance.map((row) => <tr key={row.feature}><td>{row.feature}</td><td>{row.mean_abs_shap.toFixed(4)}</td></tr>)}</tbody></table></div>
        </> : null}
      </>}
    </section>
    <aside className="inspector mllab-inspector" aria-label="Provenance and Atlas">
      <dl className="inspector-data">
        <div><dt>Revision</dt><dd>{profile.dataset.revision}</dd></div>
        <div><dt>Source</dt><dd><code>{profile.dataset.source_fingerprint.slice(0, 12)}…</code></dd></div>
      </dl>
      <div className="inspector-actions"><span className="eyebrow">ATLAS · EVIDENCE-AWARE</span>{ATLAS_ACTIONS.map((action) => <button key={action} disabled={!featureCols.length} onClick={() => void askAtlas(action)}>{action.replaceAll("_", " ")}</button>)}</div>
      {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong style={{ whiteSpace: "pre-line" }}>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
    </aside>
  </article>;
}
