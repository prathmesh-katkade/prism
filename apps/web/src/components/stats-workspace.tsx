"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AtlasStatsAction, AtlasStatsResponse, OverviewProfileResponse, StatSuggestionResponse, StatTestResult } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type StatsUiState = "empty" | "loading" | "ready" | "error";
const ATLAS_ACTIONS: readonly AtlasStatsAction[] = ["explain_test", "explain_assumptions", "explain_effect_size", "recommend_next_step"];

/** Phase 7A: variables → deterministic test suggestion → assumptions → run → statistic/effect size/interpretation → provenance/Atlas. */
export function StatsWorkspace({ datasetId, onSelectContext, onOpenWorkflow }: { datasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void }) {
  const [state, setState] = useState<StatsUiState>(datasetId ? "loading" : "empty");
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [colA, setColA] = useState<string>("");
  const [colB, setColB] = useState<string>("");
  const [suggestion, setSuggestion] = useState<StatSuggestionResponse | null>(null);
  const [result, setResult] = useState<StatTestResult | null>(null);
  const [atlas, setAtlas] = useState<AtlasStatsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  const load = useCallback(async (id: string) => {
    setState("loading"); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/profile`));
      if (!response.ok) throw new Error("Stats needs a profiled dataset from Overview.");
      const next = await response.json() as OverviewProfileResponse;
      setProfile(next);
      const first = next.columns[0]?.name ?? "";
      const second = next.columns.find((c) => c.name !== first)?.name ?? "";
      setColA(first); setColB(second);
      setState("ready");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Stats is unavailable."); setState("error"); }
  }, []);

  useEffect(() => { if (datasetId) void load(datasetId); else { setState("empty"); setProfile(null); setSuggestion(null); setResult(null); } }, [datasetId, load]);

  const fetchSuggestion = useCallback(async (id: string, a: string, b: string) => {
    setSuggestion(null); setResult(null); setAtlas(null); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/stats/datasets/${id}/suggest?column_a=${encodeURIComponent(a)}&column_b=${encodeURIComponent(b)}`));
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "No test could be suggested for these columns.");
      setSuggestion(await response.json() as StatSuggestionResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "No test could be suggested for these columns."); }
  }, []);

  useEffect(() => { if (datasetId && colA && colB && colA !== colB) void fetchSuggestion(datasetId, colA, colB); }, [datasetId, colA, colB, fetchSuggestion]);

  async function run() {
    if (!datasetId || !suggestion?.test) return;
    setRunning(true); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/stats/datasets/${datasetId}/run`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ test: suggestion.test, col_a: suggestion.col_a, col_b: suggestion.col_b, numeric_col: suggestion.numeric_col, cat_col: suggestion.cat_col }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "The test could not be run.");
      const body = await response.json() as StatTestResult;
      setResult(body);
      onSelectContext({ objectId: `stat:${suggestion.test}:${suggestion.col_a}:${suggestion.col_b}`, label: `${suggestion.test} — ${suggestion.col_a} × ${suggestion.col_b}`, type: "finding", state: "ready", actions: [{ id: "atlas-explain-test", label: "Ask Atlas to explain" }], metadata: [`p=${body.p_value.toFixed(4)}`, body.significant ? "significant" : "not significant"] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The test could not be run."); }
    finally { setRunning(false); }
  }

  async function askAtlas(action: AtlasStatsAction) {
    if (!datasetId || !colA || !colB) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/stats/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, col_a: colA, col_b: colB }) });
      if (!response.ok) return;
      setAtlas(await response.json() as AtlasStatsResponse);
    } catch { /* Atlas commentary is optional; the result remains usable without it. */ }
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">STATS · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Stats Lab tests the same server-held dataset Overview and SQL Lab already use.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  if (state === "loading" || !profile) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Preparing Stats Lab</h2><p>Test selection is deterministic — the same column types and sample size always suggest the same test.</p></section>;
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>Stats Lab could not load this dataset.</h2><p>{error}</p><button onClick={() => datasetId && void load(datasetId)}>Retry</button></section>;

  return <article className="stats-workspace three-pane">
    <nav className="stats-fields" aria-label="Variable selection" tabIndex={0}>
      <div className="section-title"><span className="eyebrow">VARIABLES</span><h2>{profile.dataset.source_name}</h2></div>
      <label>Variable A<select value={colA} onChange={(event) => setColA(event.target.value)}>{profile.columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label>
      <label>Variable B<select value={colB} onChange={(event) => setColB(event.target.value)}>{profile.columns.map((c) => <option key={c.name} value={c.name}>{c.name}</option>)}</select></label>
      {colA === colB ? <p className="quiet-note">Choose two different columns to compare.</p> : suggestion ? <p className="quiet-note">{suggestion.error ? suggestion.error : suggestion.test ? `Suggested: ${suggestion.test}.` : "Choosing a test…"}</p> : <p className="quiet-note">Choosing a test…</p>}
    </nav>
    <section className="stats-results" aria-label="Test results" tabIndex={0}>
      <header><span className="eyebrow">{suggestion?.test ? suggestion.test.toUpperCase() : "NO TEST"}</span><h1>{colA} × {colB}</h1></header>
      {!suggestion || suggestion.error || !suggestion.test ? <p className="quiet-note">{suggestion?.error ?? "Select two columns to see a recommended test."}</p> : !result ? <>
        <p className="clean-preview-summary">{suggestion.reason}</p>
        <div className="inspector-actions"><button disabled={running} onClick={() => void run()}>{running ? "Running…" : "Run test"}</button></div>
      </> : <>
        <p className="clean-preview-summary">{result.interpretation}</p>
        <aside className="stat-evidence" aria-live="polite"><strong>{result.significant ? "Evidence found" : "Insufficient evidence"}</strong><small>{result.evidence_statement}</small></aside>
        {Object.keys(result.means ?? {}).length ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Group</th><th>n</th><th>Mean</th></tr></thead><tbody>{Object.keys(result.groups ?? {}).map((name) => <tr key={name}><td>{name}</td><td>{result.groups?.[name]}</td><td>{result.means?.[name]?.toFixed(3) ?? "—"}</td></tr>)}</tbody></table></div> : null}
        {(result.warnings ?? []).length ? <ul className="clean-warnings">{(result.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
        <div className="inspector-actions"><button className="secondary" onClick={() => { setResult(null); setAtlas(null); }}>Run a different test</button></div>
      </>}
    </section>
    <aside className="inspector stats-inspector" aria-label="Assumptions, provenance, and Atlas">
      {result ? <dl className="inspector-data">
        <div><dt>Statistic</dt><dd>{result.statistic.toFixed(4)}</dd></div>
        <div><dt>p-value</dt><dd>{result.p_value < 0.0001 ? "p<0.0001" : result.p_value.toFixed(4)}</dd></div>
        <div><dt>{result.effect_size_name}</dt><dd>{result.effect_size.toFixed(3)} ({result.effect_size_label})</dd></div>
        <div><dt>Revision</dt><dd>{result.provenance.dataset_revision}</dd></div>
        <div><dt>Source</dt><dd><code>{result.provenance.source_fingerprint.slice(0, 12)}…</code></dd></div>
      </dl> : <p className="quiet-note">Run a test to see its statistic, effect size, and provenance here.</p>}
      <div className="inspector-actions"><span className="eyebrow">ATLAS · EVIDENCE-AWARE</span>{ATLAS_ACTIONS.map((action) => <button key={action} onClick={() => void askAtlas(action)}>{action.replaceAll("_", " ")}</button>)}</div>
      {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
      {error ? <p className="query-error" role="alert">{error}</p> : null}
    </aside>
  </article>;
}
