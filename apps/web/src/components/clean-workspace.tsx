"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AtlasCleanResponse, CleanIssue, CleanPreviewResponse, CleanStateResponse, CleanTransformationRequest } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type CleanUiState = "empty" | "loading" | "ready" | "error";

/** Phase 6A: issues → preview → apply, as a versioned, reversible transformation — never a silent mutation. */
export function CleanWorkspace({ datasetId, onSelectContext, onOpenWorkflow }: { datasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void }) {
  const [state, setState] = useState<CleanUiState>(datasetId ? "loading" : "empty");
  const [clean, setClean] = useState<CleanStateResponse | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<CleanIssue | null>(null);
  const [pendingRequest, setPendingRequest] = useState<CleanTransformationRequest | null>(null);
  const [preview, setPreview] = useState<CleanPreviewResponse | null>(null);
  const [atlas, setAtlas] = useState<AtlasCleanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const refresh = useCallback(async (id: string) => {
    setState("loading");
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${id}/state`));
      if (!response.ok) throw new Error("Clean could not load the dataset's quality state.");
      setClean(await response.json() as CleanStateResponse);
      setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Clean is unavailable."); setState("error");
    }
  }, []);

  useEffect(() => { if (datasetId) void refresh(datasetId); else { setState("empty"); setClean(null); } }, [datasetId, refresh]);

  async function selectIssue(issue: CleanIssue) {
    if (!datasetId) return;
    setSelectedIssue(issue); setPreview(null); setAtlas(null); setPendingRequest(null);
    onSelectContext({ objectId: issue.issue_id, label: issue.column ?? "Dataset-level issue", type: "finding", state: "ready", actions: [{ id: "atlas-explain-issue", label: "Ask Atlas to explain" }], metadata: [`${issue.affected_rows.toLocaleString()} affected rows`, `${issue.severity} severity`] });
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "explain_issue", issue_id: issue.issue_id }) });
      if (!response.ok) return;
      const body = await response.json() as AtlasCleanResponse;
      setAtlas(body);
      if (body.proposed_operation) await previewOperation(body.proposed_operation);
    } catch { /* Atlas explanation is optional context; the issue list stays usable without it. */ }
  }

  async function previewOperation(request: CleanTransformationRequest) {
    if (!datasetId) return;
    setPendingRequest(request);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/preview`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Preview failed.");
      setPreview(await response.json() as CleanPreviewResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Preview failed."); }
  }

  async function apply() {
    if (!datasetId || !pendingRequest) return;
    setApplying(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/apply`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(pendingRequest) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Applying the transformation failed.");
      setPreview(null); setPendingRequest(null); setSelectedIssue(null); setAtlas(null);
      await refresh(datasetId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Applying the transformation failed."); }
    finally { setApplying(false); }
  }

  async function undoTo(revision: number) {
    if (!datasetId) return;
    await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/undo`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ to_revision: revision }) });
    setPreview(null); setPendingRequest(null); setSelectedIssue(null); setAtlas(null);
    await refresh(datasetId);
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">CLEAN · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Clean operates on the same server-held dataset Overview and SQL Lab already use — there is nothing to clean until one is loaded.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  if (state === "loading" || !clean) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Scanning for quality issues</h2><p>Reusing Overview's own deterministic profile — nothing is recomputed twice.</p></section>;
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>Clean could not load this dataset.</h2><p>{error}</p><button onClick={() => datasetId && void refresh(datasetId)}>Retry</button></section>;

  return <article className="clean-workspace three-pane">
    <nav className="clean-issues" aria-label="Data quality issue navigator" tabIndex={0}>
      <div className="section-title"><div><span className="eyebrow">ISSUES</span><h2>{clean.issues.length ? `${clean.issues.length} found` : "No issues detected"}</h2></div><span className={`health-pill ${clean.health.total >= 80 ? "good" : clean.health.total >= 60 ? "warn" : "risk"}`}>{clean.health.total}/100</span></div>
      <div className="finding-list">{clean.issues.map((issue) => <button key={issue.issue_id} className={issue.issue_id === selectedIssue?.issue_id ? "is-selected" : ""} onClick={() => void selectIssue(issue)}><span className={`finding-dot ${issue.severity === "high" ? "issue" : issue.severity === "medium" ? "warning" : "good"}`} /><strong>{issue.column ?? "Dataset"}</strong><small>{issue.description}</small></button>)}</div>
      <div className="section-title"><span className="eyebrow">HISTORY</span></div>
      <ol className="clean-history">
        <li><button className={clean.dataset.revision === 0 ? "is-selected" : ""} onClick={() => void undoTo(0)}>Revision 0 · original</button></li>
        {clean.history.map((item) => <li key={item.transformation_id}><button className={clean.dataset.revision === item.resulting_revision ? "is-selected" : ""} onClick={() => void undoTo(item.resulting_revision)}>Revision {item.resulting_revision} · {item.operation.replaceAll("_", " ")}{item.column ? ` · ${item.column}` : ""}</button></li>)}
      </ol>
    </nav>
    <section className="clean-preview" aria-label="Data and transformation preview" tabIndex={0}>
      <header><span className="eyebrow">{clean.dataset.source_name}</span><h1>{clean.dataset.row_count.toLocaleString()} rows · {clean.dataset.column_count} columns · revision {clean.dataset.revision}</h1></header>
      {preview ? <>
        <p className="clean-preview-summary">{preview.operation.replaceAll("_", " ")} affects <strong>{preview.affected_rows.toLocaleString()}</strong> row(s){(preview.affected_columns ?? []).length ? ` in ${(preview.affected_columns ?? []).join(", ")}` : ""}. Projected health: <strong>{preview.projected_health.total}/100</strong> (currently {clean.health.total}/100).</p>
        {(preview.warnings ?? []).length ? <ul className="clean-warnings">{(preview.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
        <div className="clean-diff"><div><span className="eyebrow">BEFORE</span><SampleTable rows={preview.before_sample} /></div><div><span className="eyebrow">AFTER</span><SampleTable rows={preview.after_sample} /></div></div>
      </> : <p className="quiet-note">Select an issue to preview a proposed fix before applying it. Nothing is changed until you apply.</p>}
    </section>
    <aside className="inspector clean-inspector" aria-label="Selected issue and transformation inspector">
      {selectedIssue ? <>
        <div className="inspector-heading"><div><span className="eyebrow">SELECTED ISSUE</span><h2>{selectedIssue.column ?? "Dataset"}</h2></div></div>
        <p>{selectedIssue.description}</p>
        {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
        {pendingRequest ? <div className="inspector-actions"><button disabled={applying || !preview} onClick={() => void apply()}>{applying ? "Applying…" : "Apply transformation"}</button><button className="secondary" onClick={() => { setPreview(null); setPendingRequest(null); }}>Discard preview</button></div> : <p className="quiet-note">Atlas proposes a fix automatically when a safe deterministic one exists; otherwise this needs analyst judgment.</p>}
      </> : <p className="quiet-note">Select an issue from the navigator to inspect it and preview a fix.</p>}
      {error ? <p className="query-error" role="alert">{error}</p> : null}
    </aside>
  </article>;
}

function SampleTable({ rows }: { rows: readonly Record<string, unknown>[] }) {
  if (!rows.length) return <p className="quiet-note">No rows.</p>;
  const columns = Object.keys(rows[0] ?? {});
  return <div className="data-table-wrap"><table><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{row[key] === null || row[key] === undefined ? "—" : String(row[key])}</td>)}</tr>)}</tbody></table></div>;
}
