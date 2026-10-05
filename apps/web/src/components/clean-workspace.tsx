"use client";

import React, { useCallback, useEffect, useState } from "react";
import type { AtlasCleanResponse, CleanIssue, CleanOperation, CleanPreviewResponse, CleanRecipe, CleanRecipeDraftPreviewResponse, CleanRecipePreviewResponse, CleanRecipeStep, CleanRowInspection, CleanStateResponse, CleanTransformationRequest, ColumnValueCount, ColumnValueCountsResponse, DatasetRowsResponse, FillStrategy, OverviewProfileResponse, ValidationRule, ValidationRuleKind, ValidationRunResult } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";
import { WorkspaceProposalPanel } from "./workspace-proposal-panel";

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
  { value: "category_mapping", label: "Map category values", needsColumn: true },
  { value: "deduplicate_survivorship", label: "Resolve duplicate groups", needsColumn: false },
];
const SURVIVORSHIP_RULES: readonly { value: "first" | "last" | "most_complete" | "max_by_column"; label: string }[] = [
  { value: "first", label: "Keep the first row in each group" },
  { value: "last", label: "Keep the last row in each group" },
  { value: "most_complete", label: "Keep the row with the fewest missing values" },
  { value: "max_by_column", label: "Keep the row with the highest value in a column" },
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
  const [reviewView, setReviewView] = useState<"before" | "changes" | "after">("changes");
  const [reviewRowsView, setReviewRowsView] = useState<"affected" | "exceptions" | "validation">("affected");
  const [atlas, setAtlas] = useState<AtlasCleanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);

  const [manualOperation, setManualOperation] = useState<CleanOperation>("drop_duplicates");
  const [manualColumn, setManualColumn] = useState("");
  const [manualNewName, setManualNewName] = useState("");
  const [manualTargetType, setManualTargetType] = useState<"numeric" | "text" | "datetime" | "boolean">("numeric");
  const [manualDateFormat, setManualDateFormat] = useState("");
  const [manualNumberLocale, setManualNumberLocale] = useState<"standard" | "european">("standard");
  const [manualFillStrategy, setManualFillStrategy] = useState<FillStrategy>("median");
  const [manualFillValue, setManualFillValue] = useState("");
  const [manualCase, setManualCase] = useState<"lower" | "upper" | "title">("lower");

  const [columnValues, setColumnValues] = useState<ColumnValueCountsResponse | null>(null);
  const [categoryMapping, setCategoryMapping] = useState<Record<string, string>>({});
  const [categorySelected, setCategorySelected] = useState<ReadonlySet<string>>(new Set());
  const [categoryTarget, setCategoryTarget] = useState("");
  const [categoryCaseSensitive, setCategoryCaseSensitive] = useState(true);
  const [categoryPreserveUnmatched, setCategoryPreserveUnmatched] = useState(true);

  const [survivorshipColumns, setSurvivorshipColumns] = useState<ReadonlySet<string>>(new Set());
  const [survivorshipRule, setSurvivorshipRule] = useState<"first" | "last" | "most_complete" | "max_by_column">("first");
  const [survivorshipTiebreak, setSurvivorshipTiebreak] = useState("");

  const [recipes, setRecipes] = useState<CleanRecipe[]>([]);
  const [recipeName, setRecipeName] = useState("");
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [applyingRecipeId, setApplyingRecipeId] = useState<string | null>(null);
  const [recipePreview, setRecipePreview] = useState<CleanRecipePreviewResponse | null>(null);
  const [draftSteps, setDraftSteps] = useState<CleanRecipeStep[]>([]);
  const [draftPreview, setDraftPreview] = useState<CleanRecipeDraftPreviewResponse | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [editingRecipeId, setEditingRecipeId] = useState<string | null>(null);
  const [editingStepIndex, setEditingStepIndex] = useState<number | null>(null);

  useEffect(() => {
    if (!datasetId || !draftSteps.length) { setDraftPreview(null); return; }
    const controller = new AbortController();
    setDraftPreview(null); setDraftError(null);
    void fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/recipe-draft/preview`), {
      method: "POST", headers: { "content-type": "application/json" }, signal: controller.signal,
      body: JSON.stringify({ steps: draftSteps.map(({ request, enabled }) => ({ request, enabled })) }),
    }).then(async (response) => {
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Draft preview failed.");
      return response.json() as Promise<CleanRecipeDraftPreviewResponse>;
    }).then((body) => setDraftPreview(body)).catch((reason: unknown) => {
      if (!controller.signal.aborted) setDraftError(reason instanceof Error ? reason.message : "Draft preview failed.");
    });
    return () => controller.abort();
  }, [datasetId, draftSteps]);

  const loadRecipes = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/v1/clean/recipes"));
      if (response.ok) setRecipes(await response.json() as CleanRecipe[]);
    } catch { /* recipes are a convenience layer over manual operations, which stay usable without this list. */ }
  }, []);

  const [validationRules, setValidationRules] = useState<ValidationRule[]>([]);
  const [validationResults, setValidationResults] = useState<Record<string, ValidationRunResult>>({});
  const [validationRunning, setValidationRunning] = useState<string | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const [newRuleName, setNewRuleName] = useState("");
  const [newRuleKind, setNewRuleKind] = useState<ValidationRuleKind>("uniqueness");
  const [newRuleColumn, setNewRuleColumn] = useState("");
  const [newRuleBeforeColumn, setNewRuleBeforeColumn] = useState("");
  const [newRuleAfterColumn, setNewRuleAfterColumn] = useState("");

  const loadValidationRules = useCallback(async () => {
    try {
      const response = await fetch(apiUrl("/api/v1/clean/validation-rules"));
      if (response.ok) setValidationRules(await response.json() as ValidationRule[]);
    } catch { /* validation rules are a convenience; Clean stays usable without this list. */ }
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
      await loadValidationRules();
      setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Clean is unavailable."); setState("error");
    }
  }, [loadRows, loadRecipes, loadValidationRules]);

  useEffect(() => { if (datasetId) void refresh(datasetId); else { setState("empty"); setClean(null); setProfile(null); setRows(null); } }, [datasetId, refresh]);

  useEffect(() => {
    if (!datasetId || manualOperation !== "category_mapping" || !manualColumn) { setColumnValues(null); return; }
    let cancelled = false;
    setCategoryMapping({}); setCategorySelected(new Set()); setCategoryTarget("");
    fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/columns/${encodeURIComponent(manualColumn)}/values`))
      .then((response) => (response.ok ? response.json() as Promise<ColumnValueCountsResponse> : null))
      .then((body) => { if (!cancelled) setColumnValues(body); })
      .catch(() => { if (!cancelled) setColumnValues(null); });
    return () => { cancelled = true; };
  }, [datasetId, manualOperation, manualColumn]);

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
    setPendingRequest(request); setPreview(null); setRecipePreview(null); setError(null);
    setReviewView("changes"); setReviewRowsView("affected");
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
    if (manualOperation === "category_mapping" && Object.keys(categoryMapping).length === 0) return { request: null, reason: "Map at least one source value to a new value." };
    if (manualOperation === "deduplicate_survivorship") {
      if (survivorshipColumns.size === 0) return { request: null, reason: "Choose at least one column to group duplicates by." };
      if (survivorshipRule === "max_by_column" && !survivorshipTiebreak) return { request: null, reason: "Choose a column to keep the highest value from." };
    }
    const request: CleanTransformationRequest = { operation: manualOperation, ...(spec.needsColumn ? { column: manualColumn } : {}) };
    if (manualOperation === "rename_column") request.new_name = manualNewName.trim();
    if (manualOperation === "convert_type") {
      request.target_type = manualTargetType;
      if (manualTargetType === "datetime" && manualDateFormat.trim()) request.date_format = manualDateFormat.trim();
      if (manualTargetType === "numeric") request.number_locale = manualNumberLocale;
    }
    if (manualOperation === "fill_missing") { request.fill_strategy = manualFillStrategy; if (manualFillStrategy === "constant") request.fill_value = manualFillValue; }
    if (manualOperation === "normalize_case") request.case = manualCase;
    if (manualOperation === "category_mapping") { request.category_mapping = categoryMapping; request.case_sensitive = categoryCaseSensitive; request.preserve_unmatched = categoryPreserveUnmatched; }
    if (manualOperation === "deduplicate_survivorship") {
      request.group_by_columns = Array.from(survivorshipColumns);
      request.survivorship_rule = survivorshipRule;
      if (survivorshipRule === "max_by_column") request.survivorship_tiebreak_column = survivorshipTiebreak;
    }
    return { request, reason: null };
  }

  function assignCategoryMapping() {
    if (!categoryTarget.trim() || categorySelected.size === 0) return;
    setCategoryMapping((current) => {
      const next = { ...current };
      for (const value of categorySelected) next[value] = categoryTarget.trim();
      return next;
    });
    setCategorySelected(new Set()); setCategoryTarget("");
  }

  function removeCategoryMapping(sourceValue: string) {
    setCategoryMapping((current) => { const next = { ...current }; delete next[sourceValue]; return next; });
  }

  function toggleCategorySelected(value: string) {
    setCategorySelected((current) => { const next = new Set(current); if (next.has(value)) next.delete(value); else next.add(value); return next; });
  }

  function toggleSurvivorshipColumn(column: string) {
    setSurvivorshipColumns((current) => { const next = new Set(current); if (next.has(column)) next.delete(column); else next.add(column); return next; });
  }

  async function saveAsRecipe(request: CleanTransformationRequest) {
    if (!editingRecipeId && !recipeName.trim()) { setRecipeError("Name the recipe before saving it."); return; }
    setRecipeError(null);
    try {
      const steps = draftSteps.length ? draftSteps : [{ step_id: `step_${Date.now()}`, request, enabled: true }];
      const response = editingRecipeId
        ? await fetch(apiUrl(`/api/v1/clean/recipes/${editingRecipeId}/steps`), { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ steps }) })
        : await fetch(apiUrl("/api/v1/clean/recipes"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: recipeName.trim(), steps: steps.map(({ request: operation, enabled }) => ({ request: operation, enabled })) }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Saving the recipe failed.");
      setRecipeName(""); setDraftSteps([]); setEditingRecipeId(null); setEditingStepIndex(null); setRecipePreview(null);
      await loadRecipes();
    } catch (reason) { setRecipeError(reason instanceof Error ? reason.message : "Saving the recipe failed."); }
  }

  function addDraftStep(request: CleanTransformationRequest) {
    setDraftSteps((current) => [...current, { step_id: `draft_${Date.now()}_${current.length}`, request, enabled: true }]);
    setRecipePreview(null);
  }

  function editSavedRecipe(recipe: CleanRecipe) {
    setEditingRecipeId(recipe.recipe_id); setRecipeName(recipe.name);
    setManualMode(true);
    setDraftSteps(recipe.steps.map((step) => ({ ...step })));
    setRecipePreview(null); setEditingStepIndex(null); setRecipeError(null);
  }

  function loadDraftStep(index: number) {
    const request = draftSteps[index]?.request;
    if (!request) return;
    setEditingStepIndex(index); setManualMode(true); setSelectedIssue(null);
    setManualOperation(request.operation); setManualColumn(request.column ?? "");
    setManualNewName(request.new_name ?? ""); setManualTargetType(request.target_type ?? "numeric");
    setManualDateFormat(request.date_format ?? ""); setManualNumberLocale(request.number_locale ?? "standard");
    setManualFillStrategy(request.fill_strategy ?? "median"); setManualFillValue(request.fill_value ?? "");
    setManualCase(request.case ?? "lower"); setCategoryMapping(request.category_mapping ?? {});
    setCategoryCaseSensitive(request.case_sensitive ?? true);
    setCategoryPreserveUnmatched(request.preserve_unmatched ?? true);
    setSurvivorshipColumns(new Set(request.group_by_columns ?? []));
    setSurvivorshipRule(request.survivorship_rule ?? "first");
    setSurvivorshipTiebreak(request.survivorship_tiebreak_column ?? "");
  }

  function updateDraftStep(request: CleanTransformationRequest) {
    if (editingStepIndex === null) return;
    setDraftSteps((current) => current.map((step, index) => index === editingStepIndex ? { ...step, request } : step));
    setEditingStepIndex(null); setRecipePreview(null);
  }

  async function previewSavedRecipe(recipe: CleanRecipe) {
    if (!datasetId) return;
    setRecipeError(null); setRecipePreview(null); setPreview(null); setPendingRequest(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/recipes/${recipe.recipe_id}/preview`), { method: "POST" });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Previewing the recipe failed.");
      setRecipePreview(await response.json() as CleanRecipePreviewResponse);
    } catch (reason) { setRecipeError(reason instanceof Error ? reason.message : "Previewing the recipe failed."); }
  }

  async function applyRecipe(recipe: CleanRecipe) {
    if (!datasetId) return;
    if (!recipePreview || recipePreview.recipe_id !== recipe.recipe_id || recipePreview.recipe_version !== recipe.version) return;
    setApplyingRecipeId(recipe.recipe_id); setRecipeError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/recipes/${recipe.recipe_id}/apply`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ review_token: recipePreview.review_token }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Applying the recipe failed.");
      setManualMode(false); setSelectedIssue(null); setPreview(null); setPendingRequest(null); setRecipePreview(null);
      await refresh(datasetId);
    } catch (reason) { setRecipeError(reason instanceof Error ? reason.message : "Applying the recipe failed."); }
    finally { setApplyingRecipeId(null); }
  }

  async function createValidationRule() {
    if (!newRuleName.trim()) { setValidationError("Name the rule before saving it."); return; }
    if ((newRuleKind === "uniqueness" || newRuleKind === "nonnegative") && !newRuleColumn) { setValidationError("Choose a column for this rule."); return; }
    if (newRuleKind === "date_order" && (!newRuleBeforeColumn || !newRuleAfterColumn)) { setValidationError("Choose both a before-column and an after-column."); return; }
    setValidationError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/clean/validation-rules"), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: newRuleName.trim(), kind: newRuleKind,
          ...(newRuleKind !== "date_order" ? { column: newRuleColumn } : { before_column: newRuleBeforeColumn, after_column: newRuleAfterColumn }),
        }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Saving the rule failed.");
      setNewRuleName(""); setNewRuleColumn(""); setNewRuleBeforeColumn(""); setNewRuleAfterColumn("");
      await loadValidationRules();
    } catch (reason) { setValidationError(reason instanceof Error ? reason.message : "Saving the rule failed."); }
  }

  async function runValidationRule(rule: ValidationRule) {
    if (!datasetId) return;
    setValidationRunning(rule.rule_id); setValidationError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/validation-rules/${rule.rule_id}/run`), { method: "POST" });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Running the rule failed.");
      const result = await response.json() as ValidationRunResult;
      setValidationResults((current) => ({ ...current, [rule.rule_id]: result }));
    } catch (reason) { setValidationError(reason instanceof Error ? reason.message : "Running the rule failed."); }
    finally { setValidationRunning(null); }
  }

  async function deleteValidationRule(ruleId: string) {
    try {
      await fetch(apiUrl(`/api/v1/clean/validation-rules/${ruleId}`), { method: "DELETE" });
      setValidationResults((current) => { const next = { ...current }; delete next[ruleId]; return next; });
      await loadValidationRules();
    } catch { /* best-effort; the rule simply stays listed until the next successful delete. */ }
  }

  async function apply() {
    if (!datasetId || !pendingRequest || !preview) return;
    setApplying(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/apply`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...pendingRequest, review_token: preview.review_token }) });
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
      {recipePreview ? <section className="clean-recipe-draft" aria-label="Reviewed recipe steps">
        <span className="eyebrow">RECIPE · PREVIEW</span>
        <ol>{recipes.find((recipe) => recipe.recipe_id === recipePreview.recipe_id)?.steps.map((step, index) => <li key={step.step_id}>
          <span className="clean-step-number">{String(index + 1).padStart(2, "0")}</span>
          <div><strong>{step.request.operation.replaceAll("_", " ")}</strong><small>{step.enabled ? "reviewed" : "disabled"} · {recipePreview.step_impacts[index] ?? 0} affected</small></div>
        </li>)}</ol>
      </section> : null}
      <div className="section-title"><div><span className="eyebrow">ISSUES</span><h2>{clean.issues.length ? `${clean.issues.length} found` : "No issues detected"}</h2></div><span className={`health-pill ${clean.health.total >= 80 ? "good" : clean.health.total >= 60 ? "warn" : "risk"}`}>{clean.health.total}/100</span></div>
      <div className="finding-list">{clean.issues.map((issue) => <button key={issue.issue_id} className={!manualMode && issue.issue_id === selectedIssue?.issue_id ? "is-selected" : ""} onClick={() => void selectIssue(issue)}><span className={`finding-dot ${issue.severity === "high" ? "issue" : issue.severity === "medium" ? "warning" : "good"}`} /><strong>{issue.column ?? "Dataset"}</strong><small>{issue.description}</small></button>)}</div>

      <div className="section-title"><div><span className="eyebrow">OPERATIONS</span><h2>Build one</h2></div></div>
      <button className={manualMode ? "is-selected" : "secondary"} onClick={startManualOperation}>+ New manual operation</button>
      {manualMode ? <div className="clean-manual-form">
        <label>Operation<select aria-label="Operation" value={manualOperation} onChange={(event) => setManualOperation(event.target.value as CleanOperation)}>{OPERATIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        {manualSpec?.needsColumn ? <label>Column
          <input aria-label="Column" list="clean-column-options" value={manualColumn} onChange={(event) => setManualColumn(event.target.value)} placeholder="Search columns…" />
          <datalist id="clean-column-options">{(profile?.columns ?? []).map((column) => <option key={column.name} value={column.name} />)}</datalist>
        </label> : null}
        {manualOperation === "rename_column" ? <label>New name<input aria-label="New column name" value={manualNewName} onChange={(event) => setManualNewName(event.target.value)} /></label> : null}
        {manualOperation === "convert_type" ? <>
          <label>Target type<select aria-label="Target type" value={manualTargetType} onChange={(event) => setManualTargetType(event.target.value as typeof manualTargetType)}><option value="numeric">numeric</option><option value="text">text</option><option value="datetime">datetime</option><option value="boolean">boolean</option></select></label>
          {manualTargetType === "datetime" ? <label>Date format (optional)<input aria-label="Date format" value={manualDateFormat} onChange={(event) => setManualDateFormat(event.target.value)} placeholder="e.g. %d/%m/%Y — leave blank to auto-detect" /></label> : null}
          {manualTargetType === "numeric" ? <label>Number locale<select aria-label="Number locale" value={manualNumberLocale} onChange={(event) => setManualNumberLocale(event.target.value as typeof manualNumberLocale)}><option value="standard">standard (1,234.56)</option><option value="european">european (1.234,56)</option></select></label> : null}
        </> : null}
        {manualOperation === "fill_missing" ? <>
          <label>Fill strategy<select aria-label="Fill strategy" value={manualFillStrategy} onChange={(event) => setManualFillStrategy(event.target.value as FillStrategy)}><option value="mean">mean</option><option value="median">median</option><option value="mode">mode</option><option value="constant">constant</option><option value="forward_fill">forward fill</option></select></label>
          {manualFillStrategy === "constant" ? <label>Constant value<input aria-label="Constant fill value" value={manualFillValue} onChange={(event) => setManualFillValue(event.target.value)} /></label> : null}
        </> : null}
        {manualOperation === "normalize_case" ? <label>Case<select aria-label="Case" value={manualCase} onChange={(event) => setManualCase(event.target.value as typeof manualCase)}><option value="lower">lower</option><option value="upper">upper</option><option value="title">title</option></select></label> : null}
        {manualOperation === "category_mapping" ? <div className="clean-category-mapping">
          <label className="clean-inline-toggle"><input type="checkbox" checked={categoryCaseSensitive} onChange={(event) => setCategoryCaseSensitive(event.target.checked)} /> Case sensitive</label>
          <label className="clean-inline-toggle"><input type="checkbox" checked={categoryPreserveUnmatched} onChange={(event) => setCategoryPreserveUnmatched(event.target.checked)} /> Preserve unmatched values</label>
          {columnValues ? <>
            <p className="quiet-note">{columnValues.total_distinct.toLocaleString()} distinct value(s){columnValues.truncated ? ` (showing the top ${columnValues.values.length})` : ""}. Select source values, name what they should become, then assign.</p>
            <ul className="clean-value-list">{columnValues.values.map((item: ColumnValueCount) => <li key={item.value}><label><input type="checkbox" checked={categorySelected.has(item.value)} onChange={() => toggleCategorySelected(item.value)} /> <span>{item.value}</span> <small>{item.count.toLocaleString()} row(s){categoryMapping[item.value] ? ` → ${categoryMapping[item.value]}` : ""}</small></label></li>)}</ul>
            <label>Map selected to<input aria-label="Map selected values to" value={categoryTarget} onChange={(event) => setCategoryTarget(event.target.value)} placeholder="e.g. Bengaluru" /></label>
            <button type="button" className="secondary" disabled={categorySelected.size === 0 || !categoryTarget.trim()} onClick={assignCategoryMapping}>Assign mapping</button>
            {Object.keys(categoryMapping).length ? <ul className="clean-mapping-summary">{Object.entries(categoryMapping).map(([source, target]) => <li key={source}><code>{source}</code> → <code>{target}</code><button type="button" className="secondary" aria-label={`Remove mapping for ${source}`} onClick={() => removeCategoryMapping(source)}>×</button></li>)}</ul> : null}
          </> : <p className="quiet-note">Loading distinct values…</p>}
        </div> : null}
        {manualOperation === "deduplicate_survivorship" ? <div className="clean-survivorship">
          <p className="quiet-note">Group rows that share the same value in every selected column; keep one row per group.</p>
          <ul className="clean-value-list">{(profile?.columns ?? []).map((column) => <li key={column.name}><label><input type="checkbox" checked={survivorshipColumns.has(column.name)} onChange={() => toggleSurvivorshipColumn(column.name)} /> <span>{column.name}</span> <small>{column.semantic_type}</small></label></li>)}</ul>
          <label>Survivorship rule<select aria-label="Survivorship rule" value={survivorshipRule} onChange={(event) => setSurvivorshipRule(event.target.value as typeof survivorshipRule)}>{SURVIVORSHIP_RULES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          {survivorshipRule === "max_by_column" ? <label>Highest-value column<input aria-label="Tiebreak column" list="clean-column-options" value={survivorshipTiebreak} onChange={(event) => setSurvivorshipTiebreak(event.target.value)} placeholder="Search columns…" /></label> : null}
        </div> : null}
        <button disabled={!manualBuild.request} title={manualBuild.reason ?? undefined} onClick={() => manualBuild.request && void previewOperation(manualBuild.request)}>Preview</button>
        {manualBuild.reason ? <p className="quiet-note">{manualBuild.reason}</p> : null}
        <button className="secondary" disabled={!manualBuild.request} onClick={() => manualBuild.request && (editingStepIndex === null ? addDraftStep(manualBuild.request) : updateDraftStep(manualBuild.request))}>{editingStepIndex === null ? "Add step to draft" : `Update step ${editingStepIndex + 1}`}</button>
        <label>Recipe name<input aria-label="Recipe name" value={recipeName} onChange={(event) => setRecipeName(event.target.value)} placeholder="e.g. Standard monthly cleanup" /></label>
        <button className="secondary" disabled={!manualBuild.request && !draftSteps.length} title={!manualBuild.request && !draftSteps.length ? (manualBuild.reason ?? undefined) : "Save the ordered steps as a reusable, versioned recipe"} onClick={() => void saveAsRecipe(manualBuild.request ?? draftSteps[0]!.request)}>{editingRecipeId ? "Save recipe changes" : "Save as recipe"}</button>
      </div> : null}

      {draftSteps.length ? <section className="clean-recipe-draft" aria-label="Recipe draft editor"><span className="eyebrow">DRAFT RECIPE · {draftSteps.length} STEP(S)</span>
        <ol>{draftSteps.map((step, index) => <li key={step.step_id}><span className="clean-step-number">{String(index + 1).padStart(2, "0")}</span><div><strong>{step.request.operation.replaceAll("_", " ")}</strong><small>{step.request.column ?? "dataset"} · {step.enabled ? "draft" : "disabled"}{draftPreview ? ` · ${draftPreview.step_impacts[index] ?? 0} affected` : ""}</small></div><div className="clean-step-actions"><button aria-label={`Move step ${index + 1} up`} disabled={index === 0} onClick={() => setDraftSteps((current) => { const next = [...current]; [next[index - 1], next[index]] = [next[index]!, next[index - 1]!]; return next; })}>↑</button><button aria-label={`Move step ${index + 1} down`} disabled={index === draftSteps.length - 1} onClick={() => setDraftSteps((current) => { const next = [...current]; [next[index], next[index + 1]] = [next[index + 1]!, next[index]!]; return next; })}>↓</button><button aria-label={`Edit step ${index + 1}`} onClick={() => loadDraftStep(index)}>Edit</button><button aria-label={`${step.enabled ? "Disable" : "Enable"} step ${index + 1}`} onClick={() => setDraftSteps((current) => current.map((item, at) => at === index ? { ...item, enabled: !item.enabled } : item))}>{step.enabled ? "Disable" : "Enable"}</button><button aria-label={`Remove step ${index + 1}`} onClick={() => setDraftSteps((current) => current.filter((_, at) => at !== index))}>Remove</button></div></li>)}</ol>
        {draftError ? <p role="alert" className="query-error">{draftError}</p> : draftPreview ? <p className="quiet-note">Downstream preview recomputed from revision {draftPreview.source_revision}. Projected health {draftPreview.projected_health.total}/100.</p> : <p className="quiet-note">Recomputing downstream preview…</p>}
      </section> : null}

      <div className="section-title"><div><span className="eyebrow">RECIPES</span><h2>{recipes.length ? `${recipes.length} saved` : "None saved yet"}</h2></div></div>
      {recipes.length ? <ul className="clean-recipe-list">{recipes.map((recipe) => {
        const enabledCount = recipe.steps.filter((step) => step.enabled).length;
        return <li key={recipe.recipe_id}>
          <div><strong>{recipe.name}</strong><small>v{recipe.version} · {enabledCount}/{recipe.steps.length} step(s) enabled</small></div>
          <button className="secondary" disabled={applyingRecipeId === recipe.recipe_id} onClick={() => void previewSavedRecipe(recipe)}>Preview</button>
          <button className="secondary" onClick={() => editSavedRecipe(recipe)}>Edit steps</button>
          {recipePreview?.recipe_id === recipe.recipe_id ? <div className="clean-recipe-review"><small>Reviewed revision {recipePreview.source_revision} · {recipePreview.step_impacts.join(" / ")} affected row(s) by step</small><button disabled={applyingRecipeId === recipe.recipe_id} onClick={() => void applyRecipe(recipe)}>{applyingRecipeId === recipe.recipe_id ? "Applying…" : "Apply reviewed recipe"}</button><button className="secondary" onClick={() => setRecipePreview(null)}>Discard</button></div> : null}
        </li>;
      })}</ul> : <p className="quiet-note">Build an operation above and save it as a recipe to reuse it later, or on another dataset with the same schema.</p>}
      {recipeError ? <p className="query-error" role="alert">{recipeError}</p> : null}

      <div className="section-title"><div><span className="eyebrow">VALIDATION</span><h2>{validationRules.length ? `${validationRules.length} rule(s)` : "No rules saved"}</h2></div></div>
      {validationRules.length ? <ul className="clean-recipe-list">{validationRules.map((rule) => {
        const result = validationResults[rule.rule_id];
        return <li key={rule.rule_id} className="clean-validation-row">
          <div>
            <strong>{rule.name}</strong>
            <small>{rule.kind.replaceAll("_", " ")}{rule.column ? ` · ${rule.column}` : ""}{rule.before_column ? ` · ${rule.before_column} ≤ ${rule.after_column}` : ""}</small>
            {result ? <small className={result.passed ? "clean-validation-pass" : "clean-validation-fail"}>{result.passed ? "Passed" : `${result.violation_count.toLocaleString()} violation(s)`} · {result.total_checked.toLocaleString()} checked</small> : null}
          </div>
          <div className="clean-validation-actions">
            <button className="secondary" disabled={validationRunning === rule.rule_id} onClick={() => void runValidationRule(rule)}>{validationRunning === rule.rule_id ? "Running…" : "Run"}</button>
            <button className="secondary" aria-label={`Delete rule ${rule.name}`} onClick={() => void deleteValidationRule(rule.rule_id)}>×</button>
          </div>
        </li>;
      })}</ul> : <p className="quiet-note">No validation rules yet.</p>}
      <div className="clean-manual-form clean-new-rule">
        <label>New rule name<input aria-label="Validation rule name" value={newRuleName} onChange={(event) => setNewRuleName(event.target.value)} placeholder="e.g. Unique customer IDs" /></label>
        <label>Kind<select aria-label="Validation rule kind" value={newRuleKind} onChange={(event) => setNewRuleKind(event.target.value as ValidationRuleKind)}><option value="uniqueness">uniqueness</option><option value="nonnegative">nonnegative</option><option value="date_order">date order</option></select></label>
        {newRuleKind !== "date_order" ? <label>Rule column<input aria-label="Validation rule column" list="clean-column-options" value={newRuleColumn} onChange={(event) => setNewRuleColumn(event.target.value)} placeholder="Search columns…" /></label> : <>
          <label>Before column (earlier date)<input aria-label="Before column" list="clean-column-options" value={newRuleBeforeColumn} onChange={(event) => setNewRuleBeforeColumn(event.target.value)} placeholder="Search columns…" /></label>
          <label>After column (later date)<input aria-label="After column" list="clean-column-options" value={newRuleAfterColumn} onChange={(event) => setNewRuleAfterColumn(event.target.value)} placeholder="Search columns…" /></label>
        </>}
        <button type="button" className="secondary" onClick={() => void createValidationRule()}>Save rule</button>
        {validationError ? <p className="quiet-note">{validationError}</p> : null}
      </div>

      <div className="section-title"><span className="eyebrow">HISTORY</span></div>
      <ol className="clean-history">
        <li><button className={clean.dataset.revision === 0 ? "is-selected" : ""} onClick={() => void undoTo(0)}>Revision 0 · original</button></li>
        {clean.history.map((item) => <li key={item.transformation_id}><button className={clean.dataset.revision === item.resulting_revision ? "is-selected" : ""} onClick={() => void undoTo(item.resulting_revision)}>Revision {item.resulting_revision} · {item.operation.replaceAll("_", " ")}{item.column ? ` · ${item.column}` : ""}</button></li>)}
      </ol>
    </nav>
    <section className="clean-preview" aria-label="Data and transformation preview" tabIndex={0}>
      <header><span className="eyebrow">{clean.dataset.source_name}</span><h1>{clean.dataset.row_count.toLocaleString()} rows · {clean.dataset.column_count} columns · revision {clean.dataset.revision}</h1></header>
      {preview ? <>
        <div className="clean-review-tabs" role="tablist" aria-label="Review transformation"><button role="tab" aria-selected={reviewView === "before"} onClick={() => setReviewView("before")}>Before</button><button role="tab" aria-selected={reviewView === "changes"} onClick={() => setReviewView("changes")}>Changes</button><button role="tab" aria-selected={reviewView === "after"} onClick={() => setReviewView("after")}>After</button></div>
        {reviewView === "before" ? <><p className="quiet-note">Source revision {preview.source_revision ?? clean.dataset.revision} · fingerprint {(preview.source_fingerprint ?? clean.dataset.source_fingerprint).slice(0, 12)}… · first {preview.before_sample.length} row(s)</p><SampleTable rows={preview.before_sample} /></> : null}
        {reviewView === "after" ? <><p className="quiet-note">Projected result only. Nothing has been applied. First {preview.after_sample.length} row(s).</p><SampleTable rows={preview.after_sample} /></> : null}
        {reviewView === "changes" ? <>
          <p className="clean-preview-summary">{preview.operation.replaceAll("_", " ")} affects <strong>{(preview.changed_rows_total ?? preview.affected_rows).toLocaleString()}</strong> source row(s){(preview.affected_columns ?? []).length ? ` in ${(preview.affected_columns ?? []).join(", ")}` : ""}. Projected health: <strong>{preview.projected_health.total}/100</strong> (currently {clean.health.total}/100).</p>
          {(preview.warnings ?? []).length ? <ul className="clean-warnings">{(preview.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
          <div className="clean-review-tabs" role="tablist" aria-label="Inspect review results"><button role="tab" aria-selected={reviewRowsView === "affected"} onClick={() => setReviewRowsView("affected")}>Affected rows ({(preview.changed_rows_total ?? preview.affected_rows).toLocaleString()})</button><button role="tab" aria-selected={reviewRowsView === "exceptions"} onClick={() => setReviewRowsView("exceptions")}>Exceptions ({(preview.exception_rows_total ?? 0).toLocaleString()})</button><button role="tab" aria-selected={reviewRowsView === "validation"} onClick={() => setReviewRowsView("validation")}>Validation</button></div>
          {reviewRowsView === "affected" ? <InspectionTable rows={preview.changed_rows ?? []} total={preview.changed_rows_total ?? preview.affected_rows} /> : null}
          {reviewRowsView === "exceptions" ? <><p className="quiet-note">{(preview.unresolved_values ?? []).length} distinct unresolved value(s). These rows stay unchanged unless the selected operation explicitly makes them missing.</p><InspectionTable rows={preview.exception_rows ?? []} total={preview.exception_rows_total ?? 0} /></> : null}
          {reviewRowsView === "validation" ? <div className="clean-validation-review">{validationRules.length ? validationRules.map((rule) => {
            const result = validationResults[rule.rule_id];
            return <section key={rule.rule_id}><strong>{rule.name}</strong><p>{result ? `${result.violation_count} violation(s) at revision ${result.dataset_revision}` : "Not run. Use Run beside this rule in the recipe pane."}</p>{result?.sample_violations?.length ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Source row</th><th>Values</th></tr></thead><tbody>{result.sample_violations.map((row, index) => <tr key={index}><td><code>{result.violation_source_rows?.[index] ?? "unknown"}</code></td><td><code>{JSON.stringify(row)}</code></td></tr>)}</tbody></table></div> : null}</section>;
          }) : <p>No saved validation rules. Add one in the recipe pane and run it against the current dataset.</p>}</div> : null}
        </> : null}
      </> : recipePreview ? <>
        <p className="clean-preview-summary">Recipe version {recipePreview.recipe_version} reviewed against revision {recipePreview.source_revision}. Projected health: <strong>{recipePreview.projected_health.total}/100</strong>.</p>
        <div className="clean-diff"><div><span className="eyebrow">BEFORE</span><SampleTable rows={recipePreview.before_sample} /></div><div><span className="eyebrow">AFTER</span><SampleTable rows={recipePreview.after_sample} /></div></div>
        <p className="quiet-note">No dataset changes until Apply reviewed recipe.</p>
      </> : draftPreview ? <>
        <p className="clean-preview-summary">Draft recipe recalculated against revision {draftPreview.source_revision}. Projected health: <strong>{draftPreview.projected_health.total}/100</strong>. Save the recipe and preview its version before Apply.</p>
        <div className="clean-diff"><div><span className="eyebrow">BEFORE</span><SampleTable rows={draftPreview.before_sample} /></div><div><span className="eyebrow">AFTER</span><SampleTable rows={draftPreview.after_sample} /></div></div>
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
      {recipePreview ? <>
        <div className="inspector-heading"><div><span className="eyebrow">REVIEWED RECIPE</span><h2>Ready for your decision</h2></div></div>
        <p>Version {recipePreview.recipe_version} was reviewed against source revision {recipePreview.source_revision}. Apply the reviewed recipe in the recipe list, or discard its preview there. No data has changed.</p>
      </> : selectedIssue ? <>
        <div className="inspector-heading"><div><span className="eyebrow">SELECTED ISSUE</span><h2>{selectedIssue.column ?? "Dataset"}</h2></div></div>
        <p>{selectedIssue.description}</p>
        {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
        {pendingRequest ? <div className="inspector-actions"><button disabled={applying || !preview} onClick={() => void apply()}>{applying ? "Applying…" : "Apply transformation"}</button><button className="secondary" onClick={() => { setPreview(null); setPendingRequest(null); }}>Discard preview</button></div> : <p className="quiet-note">Atlas proposes a fix automatically when a safe deterministic one exists; otherwise this needs analyst judgment.</p>}
      </> : manualMode ? <>
        <div className="inspector-heading"><div><span className="eyebrow">MANUAL OPERATION</span><h2>{manualSpec?.label ?? manualOperation.replaceAll("_", " ")}</h2></div></div>
        {pendingRequest ? <div className="inspector-actions"><button disabled={applying || !preview} onClick={() => void apply()}>{applying ? "Applying…" : "Apply transformation"}</button><button className="secondary" onClick={() => { setPreview(null); setPendingRequest(null); }}>Discard preview</button></div> : <p className="quiet-note">Preview this operation on the left before it can be applied.</p>}
      </> : <p className="quiet-note">Select an issue from the navigator, or start a manual operation, to inspect it and preview a fix.</p>}
      {error ? <p className="query-error" role="alert">{error}</p> : null}
      <WorkspaceProposalPanel kind="clean" datasetId={datasetId} onReview={(proposal) => { if (proposal.clean_operation) { setManualMode(true); void previewOperation(proposal.clean_operation); } }} />
    </aside>
  </article>;
}

function SampleTable({ rows }: { rows: readonly Record<string, unknown>[] }) {
  if (!rows.length) return <p className="quiet-note">No rows.</p>;
  const columns = Object.keys(rows[0] ?? {});
  return <div className="data-table-wrap" tabIndex={0}><table><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{row[key] === null || row[key] === undefined ? "—" : String(row[key])}</td>)}</tr>)}</tbody></table></div>;
}

function InspectionTable({ rows, total }: { rows: readonly CleanRowInspection[]; total: number }) {
  if (!total) return <p className="quiet-note">No rows in this view.</p>;
  return <><p className="quiet-note">Showing {rows.length.toLocaleString()} of {total.toLocaleString()} source row(s){total > rows.length ? " (inspection sample limited to 100)" : ""}.</p><div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Source row</th><th>Status</th><th>Before</th><th>After</th></tr></thead><tbody>{rows.map((row) => <tr key={row.source_row}><td><code>{row.source_row}</code></td><td>{row.status.replaceAll("_", " ")}</td><td><code>{JSON.stringify(row.before)}</code></td><td><code>{row.after ? JSON.stringify(row.after) : "removed"}</code></td></tr>)}</tbody></table></div></>;
}
