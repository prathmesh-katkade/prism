"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AtlasCleanResponse, CleanIssue, CleanOperation, CleanPreviewResponse, CleanRecipe, CleanStateResponse, CleanTransformationRequest, DatasetRowsResponse, FillStrategy, OverviewProfileResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type CleanUiState = "empty" | "loading" | "ready" | "error";
const ROWS_PER_PAGE = 30;

const OPERATIONS: readonly { value: CleanOperation; label: string; needsColumn: boolean }[] = [
  { value: "drop_duplicates", label: "Drop duplicate rows", needsColumn: false },
  { value: "drop_column", label: "Drop column", needsColumn: true },
  { value: "rename_column", label: "Rename column", needsColumn: true },
  { value: "drop_missing_rows", label: "Drop rows missing this column", needsColumn: true },
  { value: "fill_missing", label: "Fill missing values", needsColumn: true },
  { value: "convert_type", label: "Convert column type", needsColumn: true },
  { value: "trim_whitespace", label: "Trim whitespace", needsColumn: true },
  { value: "normalize_case", label: "Normalize text case", needsColumn: true },
];

/** Phase 6A: issues → preview → apply, as a versioned, reversible transformation — never a silent mutation. */
export function CleanWorkspace({ datasetId, onSelectContext, onOpenWorkflow }: { datasetId: string | undefined; onSelectContext(state: InspectorObjectState): void; onOpenWorkflow(workflow: string): void }) {
  const [state, setState] = useState<CleanUiState>(datasetId ? "loading" : "empty");
  const [clean, setClean] = useState<CleanStateResponse | null>(null);
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [rows, setRows] = useState<DatasetRowsResponse | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<CleanIssue | null>(null);
  const [manualMode, setManualMode] = useState(false);
  const [pendingRequest, setPendingRequest] = useState<CleanTransformationRequest | null>(null);
  const [preview, setPreview] = useState<CleanPreviewResponse | null>(null);
  const [atlas, setAtlas] = useState<AtlasCleanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const [manualOperation, setManualOperation] = useState<CleanOperation>("drop_duplicates");
  const [manualColumn, setManualColumn] = useState("");
  const [manualNewName, setManualNewName] = useState("");
  const [manualTargetType, setManualTargetType] = useState<"numeric" | "text" | "datetime" | "boolean">("numeric");
  const [manualFillStrategy, setManualFillStrategy] = useState<FillStrategy>("median");
  const [manualFillValue, setManualFillValue] = useState("");
  const [manualCase, setManualCase] = useState<"lower" | "upper" | "title">("lower");

  const [recipes, setRecipes] = useState<CleanRecipe[]>([]);
  const [recipeName, setRecipeName] = useState("");
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [applyingRecipeId, setApplyingRecipeId] = useState<string | null>(null);

  const loadRecipes = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/v1/clean/recipes"));
      if (response.ok) setRecipes(await response.json() as CleanRecipe[]);
    } catch { /* recipes are a convenience layer over manual operations, which stay usable without this list. */ }
  }, []);

  const loadRows = useCallback(async (id: string, offset: number) => {
    try {
      const response = await fetch(apiUrl(`/api/v1/overview/datasets/${id}/rows?offset=${offset}&limit=${ROWS_PER_PAGE}`));
      if (response.ok) setRows(await response.json() as DatasetRowsResponse);
    } catch { /* the live table is a convenience; Clean stays usable from issues and preview alone without it. */ }
  }, []);

  const refresh = useCallback(async (id: string) => {
    setState("loading");
    try {
      const [stateResponse, profileResponse] = await Promise.all([
        fetch(apiUrl(`/api/v1/clean/datasets/${id}/state`)),
        fetch(apiUrl(`/api/v1/overview/datasets/${id}/profile`)),
      ]);
      if (!stateResponse.ok) throw new Error("Clean could not load the dataset's quality state.");
      setClean(await stateResponse.json() as CleanStateResponse);
      if (profileResponse.ok) setProfile(await profileResponse.json() as OverviewProfileResponse);
      await loadRows(id, 0);
      await loadRecipes();
      setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Clean is unavailable."); setState("error");
    }
  }, [loadRows, loadRecipes]);

  useEffect(() => { if (datasetId) void refresh(datasetId); else { setState("empty"); setClean(null); setProfile(null); setRows(null); } }, [datasetId, refresh]);

  async function selectIssue(issue: CleanIssue) {
    if (!datasetId) return;
    setManualMode(false); setSelectedIssue(issue); setPreview(null); setAtlas(null); setPendingRequest(null);
    onSelectContext({ objectId: issue.issue_id, label: issue.column ?? "Dataset-level issue", type: "finding", state: "ready", actions: [{ id: "atlas-explain-issue", label: "Ask Atlas to explain" }], metadata: [`${issue.affected_rows.toLocaleString()} affected rows`, `${issue.severity} severity`] });
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/atlas`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action: "explain_issue", issue_id: issue.issue_id }) });
      if (!response.ok) return;
      const body = await response.json() as AtlasCleanResponse;
      setAtlas(body);
      if (body.proposed_operation) await previewOperation(body.proposed_operation);
    } catch { /* Atlas explanation is optional context; the issue list stays usable without it. */ }
  }

  function startManualOperation() {
    setManualMode(true); setSelectedIssue(null); setAtlas(null); setPreview(null); setPendingRequest(null);
    onSelectContext({ objectId: "manual-operation", label: "Manual operation", type: "finding", state: "ready", actions: [], metadata: ["Not yet previewed"] });
  }

  async function previewOperation(request: CleanTransformationRequest) {
    if (!datasetId) return;
    setPendingRequest(request); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/preview`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Preview failed.");
      setPreview(await response.json() as CleanPreviewResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Preview failed."); }
  }

  function buildManualRequest(): { request: CleanTransformationRequest | null; reason: string | null } {
    const spec = OPERATIONS.find((item) => item.value === manualOperation);
    if (!spec) return { request: null, reason: "Choose an operation." };
    if (spec.needsColumn && !manualColumn) return { request: null, reason: "Choose a column first." };
    if (manualOperation === "rename_column" && !manualNewName.trim()) return { request: null, reason: "Enter a new column name." };
    if (manualOperation === "fill_missing" && manualFillStrategy === "constant" && !manualFillValue.trim()) return { request: null, reason: "Enter a constant value to fill with." };
    const request: CleanTransformationRequest = { operation: manualOperation, ...(spec.needsColumn ? { column: manualColumn } : {}) };
    if (manualOperation === "rename_column") request.new_name = manualNewName.trim();
    if (manualOperation === "convert_type") request.target_type = manualTargetType;
    if (manualOperation === "fill_missing") { request.fill_strategy = manualFillStrategy; if (manualFillStrategy === "constant") request.fill_value = manualFillValue; }
    if (manualOperation === "normalize_case") request.case = manualCase;
    return { request, reason: null };
  }

  async function saveAsRecipe(request: CleanTransformationRequest) {
    if (!recipeName.trim()) { setRecipeError("Name the recipe before saving it."); return; }
    setRecipeError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/clean/recipes"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: recipeName.trim(), steps: [{ request, enabled: true }] }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Saving the recipe failed.");
      setRecipeName("");
      await loadRecipes();
    } catch (reason) { setRecipeError(reason instanceof Error ? reason.message : "Saving the recipe failed."); }
  }

  async function applyRecipe(recipe: CleanRecipe) {
    if (!datasetId) return;
    setApplyingRecipeId(recipe.recipe_id); setRecipeError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/recipes/${recipe.recipe_id}/apply`), { method: "POST" });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Applying the recipe failed.");
      setManualMode(false); setSelectedIssue(null); setPreview(null); setPendingRequest(null);
      await refresh(datasetId);
    } catch (reason) { setRecipeError(reason instanceof Error ? reason.message : "Applying the recipe failed."); }
    finally { setApplyingRecipeId(null); }
  }

  async function apply() {
    if (!datasetId || !pendingRequest) return;
    setApplying(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/apply`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(pendingRequest) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Applying the transformation failed.");
      const applied = await response.json() as { transformation: { transformation_id: string; operation: string } };
      onSelectContext({ objectId: applied.transformation.transformation_id, analyticalObjectId: `clean_${applied.transformation.transformation_id}`, label: `Clean — ${applied.transformation.operation.replaceAll("_", " ")}`, type: "finding", state: "ready", actions: [], metadata: ["Immutable transformation record"] });
      setPreview(null); setPendingRequest(null); setSelectedIssue(null); setAtlas(null); setManualMode(false);
      await refresh(datasetId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Applying the transformation failed."); }
    finally { setApplying(false); }
  }

  async function undoTo(revision: number) {
    if (!datasetId) return;
    await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/undo`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ to_revision: revision }) });
    setPreview(null); setPendingRequest(null); setSelectedIssue(null); setAtlas(null); setManualMode(false);
    await refresh(datasetId);
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">CLEAN · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Clean operates on the same server-held dataset Overview and SQL Lab already use — there is nothing to clean until one is loaded.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  // error must be checked before the loading/null-data fallback: a failed
  // first load never populates `clean`, so `!clean` alone would keep
  // matching the loading branch forever and the error (with its retry
  // control) would never be reachable.
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>Clean could not load this dataset.</h2><p>{error}</p><button onClick={() => datasetId && void refresh(datasetId)}>Retry</button></section>;
  if (state === "loading" || !clean) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Scanning for quality issues</h2><p>Reusing Overview's own deterministic profile — nothing is recomputed twice.</p></section>;

  const manualBuild = manualMode ? buildManualRequest() : { request: null, reason: null };
  const manualSpec = OPERATIONS.find((item) => item.value === manualOperation);

  return <article className="clean-workspace three-pane">
    <nav className="clean-issues" aria-label="Data quality issue navigator and manual operation editor" tabIndex={0}>
      <div className="section-title"><div><span className="eyebrow">ISSUES</span><h2>{clean.issues.length ? `${clean.issues.length} found` : "No issues detected"}</h2></div><span className={`health-pill ${clean.health.total >= 80 ? "good" : clean.health.total >= 60 ? "warn" : "risk"}`}>{clean.health.total}/100</span></div>
      <div className="finding-list">{clean.issues.map((issue) => <button key={issue.issue_id} className={!manualMode && issue.issue_id === selectedIssue?.issue_id ? "is-selected" : ""} onClick={() => void selectIssue(issue)}><span className={`finding-dot ${issue.severity === "high" ? "issue" : issue.severity === "medium" ? "warning" : "good"}`} /><strong>{issue.column ?? "Dataset"}</strong><small>{issue.description}</small></button>)}</div>

      <div className="section-title"><span className="eyebrow">OPERATIONS</span><h2>Any supported transformation</h2></div>
      <button className={manualMode ? "is-selected" : "secondary"} onClick={startManualOperation}>+ New manual operation</button>
      {manualMode ? <div className="clean-manual-form">
        <label>Operation<select aria-label="Operation" value={manualOperation} onChange={(event) => setManualOperation(event.target.value as CleanOperation)}>{OPERATIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        {manualSpec?.needsColumn ? <label>Column
          <input aria-label="Column" list="clean-column-options" value={manualColumn} onChange={(event) => setManualColumn(event.target.value)} placeholder="Search columns…" />
          <datalist id="clean-column-options">{(profile?.columns ?? []).map((column) => <option key={column.name} value={column.name} />)}</datalist>
        </label> : null}
        {manualOperation === "rename_column" ? <label>New name<input aria-label="New column name" value={manualNewName} onChange={(event) => setManualNewName(event.target.value)} /></label> : null}
        {manualOperation === "convert_type" ? <label>Target type<select aria-label="Target type" value={manualTargetType} onChange={(event) => setManualTargetType(event.target.value as typeof manualTargetType)}><option value="numeric">numeric</option><option value="text">text</option><option value="datetime">datetime</option><option value="boolean">boolean</option></select></label> : null}
        {manualOperation === "fill_missing" ? <>
          <label>Fill strategy<select aria-label="Fill strategy" value={manualFillStrategy} onChange={(event) => setManualFillStrategy(event.target.value as FillStrategy)}><option value="mean">mean</option><option value="median">median</option><option value="mode">mode</option><option value="constant">constant</option><option value="forward_fill">forward fill</option></select></label>
          {manualFillStrategy === "constant" ? <label>Constant value<input aria-label="Constant fill value" value={manualFillValue} onChange={(event) => setManualFillValue(event.target.value)} /></label> : null}
        </> : null}
        {manualOperation === "normalize_case" ? <label>Case<select aria-label="Case" value={manualCase} onChange={(event) => setManualCase(event.target.value as typeof manualCase)}><option value="lower">lower</option><option value="upper">upper</option><option value="title">title</option></select></label> : null}
        <button disabled={!manualBuild.request} title={manualBuild.reason ?? undefined} onClick={() => manualBuild.request && void previewOperation(manualBuild.request)}>Preview</button>
        {manualBuild.reason ? <p className="quiet-note">{manualBuild.reason}</p> : null}
        <label>Recipe name<input aria-label="Recipe name" value={recipeName} onChange={(event) => setRecipeName(event.target.value)} placeholder="e.g. Standard monthly cleanup" /></label>
        <button className="secondary" disabled={!manualBuild.request} title={!manualBuild.request ? (manualBuild.reason ?? undefined) : "Save this operation as a reusable, versioned recipe"} onClick={() => manualBuild.request && void saveAsRecipe(manualBuild.request)}>Save as recipe</button>
      </div> : null}

      <div className="section-title"><div><span className="eyebrow">RECIPES</span><h2>{recipes.length ? `${recipes.length} saved` : "None saved yet"}</h2></div></div>
      {recipes.length ? <ul className="clean-recipe-list">{recipes.map((recipe) => {
        const enabledCount = recipe.steps.filter((step) => step.enabled).length;
        return <li key={recipe.recipe_id}>
          <div><strong>{recipe.name}</strong><small>v{recipe.version} · {enabledCount}/{recipe.steps.length} step(s) enabled</small></div>
          <button className="secondary" disabled={applyingRecipeId === recipe.recipe_id} onClick={() => void applyRecipe(recipe)}>{applyingRecipeId === recipe.recipe_id ? "Applying…" : "Apply"}</button>
        </li>;
      })}</ul> : <p className="quiet-note">Build an operation above and save it as a recipe to reuse it later, or on another dataset with the same schema.</p>}
      {recipeError ? <p className="query-error" role="alert">{recipeError}</p> : null}

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
      </> : <>
        <p className="quiet-note">{selectedIssue ? "Select an issue to preview a proposed fix before applying it." : manualMode ? "Fill in the operation on the left and select Preview — nothing is changed until you apply." : "This is the dataset as it stands at the current revision. Select an issue or start a manual operation to preview a fix."} Nothing is changed until you apply.</p>
        <div className="clean-table-toolbar">
          <span className="quiet-note">{rows ? `Rows ${rows.offset + 1}–${Math.min(rows.offset + rows.limit, rows.total_rows)} of ${rows.total_rows.toLocaleString()}` : "Loading rows…"}</span>
          <button className="secondary" disabled={!rows || rows.offset === 0} onClick={() => datasetId && rows && void loadRows(datasetId, Math.max(0, rows.offset - ROWS_PER_PAGE))}>Previous</button>
          <button className="secondary" disabled={!rows || rows.offset + rows.limit >= rows.total_rows} onClick={() => datasetId && rows && void loadRows(datasetId, rows.offset + ROWS_PER_PAGE)}>Next</button>
        </div>
        <SampleTable rows={rows?.rows ?? []} />
      </>}
    </section>
    <aside className="inspector clean-inspector" aria-label="Selected issue and transformation inspector">
      {selectedIssue ? <>
        <div className="inspector-heading"><div><span className="eyebrow">SELECTED ISSUE</span><h2>{selectedIssue.column ?? "Dataset"}</h2></div></div>
        <p>{selectedIssue.description}</p>
        {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
        {pendingRequest ? <div className="inspector-actions"><button disabled={applying || !preview} onClick={() => void apply()}>{applying ? "Applying…" : "Apply transformation"}</button><button className="secondary" onClick={() => { setPreview(null); setPendingRequest(null); }}>Discard preview</button></div> : <p className="quiet-note">Atlas proposes a fix automatically when a safe deterministic one exists; otherwise this needs analyst judgment.</p>}
      </> : manualMode ? <>
        <div className="inspector-heading"><div><span className="eyebrow">MANUAL OPERATION</span><h2>{manualSpec?.label ?? manualOperation.replaceAll("_", " ")}</h2></div></div>
        {pendingRequest ? <div className="inspector-actions"><button disabled={applying || !preview} onClick={() => void apply()}>{applying ? "Applying…" : "Apply transformation"}</button><button className="secondary" onClick={() => { setPreview(null); setPendingRequest(null); }}>Discard preview</button></div> : <p className="quiet-note">Preview this operation on the left before it can be applied.</p>}
      </> : <p className="quiet-note">Select an issue from the navigator, or start a manual operation, to inspect it and preview a fix.</p>}
      {error ? <p className="query-error" role="alert">{error}</p> : null}
    </aside>
  </article>;
}

function SampleTable({ rows }: { rows: readonly Record<string, unknown>[] }) {
  if (!rows.length) return <p className="quiet-note">No rows.</p>;
  const columns = Object.keys(rows[0] ?? {});
  return <div className="data-table-wrap" tabIndex={0}><table><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{row[key] === null || row[key] === undefined ? "—" : String(row[key])}</td>)}</tr>)}</tbody></table></div>;
}
