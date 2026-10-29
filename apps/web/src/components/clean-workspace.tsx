"use client";

import React, { useCallback, useEffect, useRef, useState } from "react";
import type { AtlasCleanResponse, CleanIssue, CleanOperation, CleanPreviewResponse, CleanRecipe, CleanRecipeDraftPreviewResponse, CleanRecipePreviewResponse, CleanRecipeStep, CleanRowInspection, CleanStateResponse, CleanTransformationRequest, ColumnValueCountsResponse, DatasetRowsResponse, FillStrategy, OverviewProfileResponse, PatternExceptionPage, PatternFamily, PatternFinding, PatternReviewDecision, PatternReviewDecisionKind, PatternVerifyJobStatus, ValidationRule, ValidationRuleKind, ValidationRunResult } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";
import { AtlasCharacter, type AtlasPose } from "./atlas-character";
import { AtlasDockPanel } from "./atlas-dock-panel";
import { Icon } from "./icons";
import { PlanReviewScreen, needsClarification } from "./plan-review";

type CleanUiState = "empty" | "loading" | "ready" | "error";
const ROWS_PER_PAGE = 30;

function closeStepMenu(event: React.MouseEvent<HTMLButtonElement>) {
  const menu = event.currentTarget.closest("details");
  menu?.removeAttribute("open");
  menu?.querySelector("summary")?.focus();
}

/** Groups a column's own already-fetched distinct values by trimmed,
 * case-insensitive spelling - real, deterministic text normalization over
 * data PRISM already has, never a model call or a fabricated suggestion.
 * The canonical spelling per group is whichever raw value has the most
 * rows (ties broken alphabetically), an explainable, inspectable rule. */
function suggestCategoryGroups(values: ReadonlyArray<{ value: string; count?: number }>): ReadonlyArray<{ canonical: string; variants: ReadonlyArray<{ value: string; count?: number }> }> {
  const byNormalized = new Map<string, { value: string; count?: number }[]>();
  for (const item of values) {
    const key = item.value.trim().toLowerCase();
    const bucket = byNormalized.get(key);
    if (bucket) bucket.push(item); else byNormalized.set(key, [item]);
  }
  const groups: { canonical: string; variants: ReadonlyArray<{ value: string; count?: number }> }[] = [];
  for (const variants of byNormalized.values()) {
    if (variants.length < 2) continue;
    const canonical = [...variants].sort((a, b) => (b.count ?? 0) - (a.count ?? 0) || a.value.localeCompare(b.value))[0]!.value;
    groups.push({ canonical, variants });
  }
  return groups;
}

export const OPERATIONS: readonly { value: CleanOperation; label: string; needsColumn: boolean; help: string }[] = [
  { value: "drop_duplicates", label: "Drop duplicate rows", needsColumn: false, help: "Remove rows that exactly duplicate an earlier row." },
  { value: "drop_column", label: "Drop column", needsColumn: true, help: "Remove this column from the dataset entirely." },
  { value: "rename_column", label: "Rename column", needsColumn: true, help: "Give this column a new name." },
  { value: "drop_missing_rows", label: "Drop rows missing this column", needsColumn: true, help: "Remove rows where this column has no value." },
  { value: "fill_missing", label: "Fill missing values", needsColumn: true, help: "Replace missing values using a chosen strategy." },
  { value: "convert_type", label: "Convert column type", needsColumn: true, help: "Reinterpret this column's values as a different type." },
  { value: "trim_whitespace", label: "Trim whitespace", needsColumn: true, help: "Remove leading and trailing whitespace from text values." },
  { value: "normalize_case", label: "Normalize text case", needsColumn: true, help: "Rewrite text values to a consistent letter case." },
  { value: "category_mapping", label: "Map category values", needsColumn: true, help: "Map source values to a standard set of values." },
  { value: "deduplicate_survivorship", label: "Resolve duplicate groups", needsColumn: false, help: "Group rows that share key values and keep one per group." },
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
  const cleanRef = useRef<CleanStateResponse | null>(null);
  cleanRef.current = clean; // always-fresh read for the recursive pollVerifyJob closure below, which is not re-created per render
  const [profile, setProfile] = useState<OverviewProfileResponse | null>(null);
  const [rows, setRows] = useState<DatasetRowsResponse | null>(null);
  const [selectedIssue, setSelectedIssue] = useState<CleanIssue | null>(null);
  const [manualMode, setManualMode] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<"settings" | "atlas">("settings");
  const gridRef = useRef<HTMLElement | null>(null);
  const recipePaneRef = useRef<HTMLElement | null>(null);
  const inspectorPaneRef = useRef<HTMLElement | null>(null);
  const [recipePaneWidth, setRecipePaneWidth] = useState<number | null>(null);
  const [inspectorPaneWidth, setInspectorPaneWidth] = useState<number | null>(null);
  const resizingPane = useRef<"recipe" | "inspector" | null>(null);
  const [pendingRequest, setPendingRequest] = useState<CleanTransformationRequest | null>(null);
  const [preview, setPreview] = useState<CleanPreviewResponse | null>(null);
  const [reviewView, setReviewView] = useState<"before" | "changes" | "after">("changes");
  const [reviewRowsView, setReviewRowsView] = useState<"affected" | "exceptions" | "validation">("affected");
  const [atlas, setAtlas] = useState<AtlasCleanResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applying, setApplying] = useState(false);
  const applyInFlight = useRef(false);
  const previewRequestId = useRef(0);
  // Set by loadRequestIntoForm just before a category_mapping operation/column
  // change it triggers; consumed once by the column-values effect below so a
  // reopened step's own real mapping survives that effect's reset-on-column-
  // change, instead of every row briefly - then permanently, until edited -
  // showing "Leave unchanged" while the preview above still reports the real
  // affected-row count.
  const pendingMappingRestore = useRef<Record<string, string> | null>(null);
  // Set by the Atlas dock's onReview handler just before loadRequestIntoForm
  // runs, from that proposal's own real response.explanation; consumed once
  // by the very next addDraftStep so the plan-review screen can show a
  // model-proposed step's actual stated reason instead of only the generic
  // operation help text every manual step already falls back to.
  const pendingStepReason = useRef<string | null>(null);
  const [stepReasons, setStepReasons] = useState<Record<string, string>>({});
  const [planReviewOpen, setPlanReviewOpen] = useState(false);

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
  // True once a preview existed and a parameter change has since invalidated
  // it, until a fresh preview is computed - distinct from "never previewed
  // yet", so the inspector can say "stale, recompute" rather than silently
  // falling back to the pre-preview "Preview this operation" copy.
  const [manualPreviewStale, setManualPreviewStale] = useState(false);

  const [recipes, setRecipes] = useState<CleanRecipe[]>([]);
  const [recipeName, setRecipeName] = useState("");
  const [showRecipeSave, setShowRecipeSave] = useState(false);
  const [recipeError, setRecipeError] = useState<string | null>(null);
  const [applyingRecipeId, setApplyingRecipeId] = useState<string | null>(null);
  const [recipePreview, setRecipePreview] = useState<CleanRecipePreviewResponse | null>(null);
  const [draftSteps, setDraftSteps] = useState<CleanRecipeStep[]>([]);
  const [draftPreview, setDraftPreview] = useState<CleanRecipeDraftPreviewResponse | null>(null);
  const [draftError, setDraftError] = useState<string | null>(null);
  const [editingRecipeId, setEditingRecipeId] = useState<string | null>(null);
  const [editingStepIndex, setEditingStepIndex] = useState<number | null>(null);
  const [approvingPlan, setApprovingPlan] = useState(false);
  const [approvePlanError, setApprovePlanError] = useState<string | null>(null);

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

  const [patternFindings, setPatternFindings] = useState<PatternFinding[]>([]);
  const [patternsLoading, setPatternsLoading] = useState(false);
  const [patternsError, setPatternsError] = useState<string | null>(null);
  const [selectedFinding, setSelectedFinding] = useState<PatternFinding | null>(null);
  const [exceptionPage, setExceptionPage] = useState<PatternExceptionPage | null>(null);
  const [exceptionsLoading, setExceptionsLoading] = useState(false);
  const exceptionRequestId = useRef(0);
  const [exploreColumn, setExploreColumn] = useState("");
  const [groupByColumn, setGroupByColumn] = useState("");
  const [groupValue, setGroupValue] = useState("");
  const [verifying, setVerifying] = useState(false);
  const [verifyProgress, setVerifyProgress] = useState<{ checked: number; total: number } | null>(null);
  const verifyJobId = useRef<string | null>(null);
  const verifyPollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const verifyRequestId = useRef(0);
  const [patternDecisions, setPatternDecisions] = useState<PatternReviewDecision[]>([]);
  const [acceptedFamilies, setAcceptedFamilies] = useState<ReadonlySet<string>>(new Set());
  const [missingValuePolicy, setMissingValuePolicy] = useState<"allow" | "reject">("allow");
  const [decisionBusy, setDecisionBusy] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);
  const [ruleNameForPattern, setRuleNameForPattern] = useState("");

  const loadPatterns = useCallback(async (id: string) => {
    setPatternsLoading(true); setPatternsError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${id}/patterns/discover`), { method: "POST" });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Pattern discovery failed.");
      setPatternFindings(await response.json() as PatternFinding[]);
    } catch (reason) {
      setPatternsError(reason instanceof Error ? reason.message : "Pattern discovery failed."); setPatternFindings([]);
    } finally { setPatternsLoading(false); }
  }, []);

  const loadPatternDecisions = useCallback(async (id: string) => {
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${id}/patterns/decisions`));
      if (response.ok) setPatternDecisions(await response.json() as PatternReviewDecision[]);
    } catch { /* decisions are a convenience list; Patterns stays usable without it. */ }
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
      void loadPatterns(id);
      void loadPatternDecisions(id);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Clean is unavailable."); setState("error");
    }
  }, [loadRows, loadRecipes, loadValidationRules, loadPatterns, loadPatternDecisions]);

  useEffect(() => {
    // Switching datasets must invalidate any in-flight verification: without
    // this, a poll loop started against the previous dataset would still
    // resolve and call setSelectedFinding with a finding computed against
    // data the workspace is no longer showing - a stale-source result
    // presented as if it were current. requestId invalidation already
    // guards every other branch inside pollVerifyJob; this is the one path
    // (switching datasets, not switching findings within one dataset) that
    // selectFinding()'s own reset doesn't cover.
    if (verifyPollTimer.current) clearTimeout(verifyPollTimer.current);
    verifyJobId.current = null; verifyRequestId.current += 1; setVerifying(false); setVerifyProgress(null);
    setSelectedFinding(null);
    // Same reasoning as the verify guard above, for Preview: a request fired
    // against the dataset being switched away from must not be allowed to
    // land here and present stale-dataset numbers as if they described the
    // one now showing.
    previewRequestId.current += 1;
    setPreview(null); setPendingRequest(null);
    if (datasetId) void refresh(datasetId); else { setState("empty"); setClean(null); setProfile(null); setRows(null); }
  }, [datasetId, refresh]);

  useEffect(() => {
    if (!datasetId || manualOperation !== "category_mapping" || !manualColumn) { setColumnValues(null); return; }
    let cancelled = false;
    // Reopening a draft/saved step (loadRequestIntoForm) just set categoryMapping
    // from that step's own real request a moment ago - this effect's dependency
    // array fires on the same operation/column transition and must not discard
    // it back to {}. Only a column the analyst is choosing fresh (never routed
    // through pendingMappingRestore) starts truly empty.
    const restore = pendingMappingRestore.current;
    pendingMappingRestore.current = null;
    setCategoryMapping(restore ?? {}); setCategorySelected(new Set()); setCategoryTarget("");
    fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/columns/${encodeURIComponent(manualColumn)}/values`))
      .then((response) => (response.ok ? response.json() as Promise<ColumnValueCountsResponse> : null))
      .then((body) => { if (!cancelled) setColumnValues(body); })
      .catch(() => { if (!cancelled) setColumnValues(null); });
    return () => { cancelled = true; };
  }, [datasetId, manualOperation, manualColumn]);

  async function selectIssue(issue: CleanIssue) {
    if (!datasetId) return;
    if (verifying) cancelVerify();
    setSelectedFinding(null);
    previewRequestId.current += 1; // a preview from whatever was selected before must not land against this issue
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
    if (verifying) cancelVerify();
    setSelectedFinding(null);
    previewRequestId.current += 1; // a preview request from whatever was selected before must not land here
    setManualMode(true); setSelectedIssue(null); setAtlas(null); setPreview(null); setPendingRequest(null);
    // A genuinely new step, not a continuation of whatever was last edited.
    // Without this, "+ Add step" right after finishing a previous step kept
    // the old editingStepIndex: the button still read "Update step N" and
    // would silently overwrite that step instead of adding a new one - the
    // same stale-index gap that let an unsaved, never-added step claim a
    // real position number ("STEP 3") in the first place.
    setEditingStepIndex(null); setManualPreviewStale(false);
    if (inspectorPaneRef.current) inspectorPaneRef.current.scrollTop = 0;
    onSelectContext({ objectId: "manual-operation", label: "Manual operation", type: "finding", state: "ready", actions: [], metadata: ["Not yet previewed"] });
  }

  /** Any parameter edit makes whatever preview request is in flight (or
   * already landed) describe a build that no longer exists. Bumping
   * previewRequestId unconditionally - not just when a preview has already
   * committed - is what actually matters: without it, a request fired
   * before this edit can still land afterward and pass previewOperation's
   * own staleness check (nothing told it anything changed), silently
   * restoring a preview for parameters the form no longer shows. If a
   * preview HAD already committed, also clear it and remember that it WAS
   * previewed so the inspector can say "stale, recompute" instead of the
   * generic pre-preview copy. */
  function invalidateManualPreview() {
    previewRequestId.current += 1;
    if (preview) { setPreview(null); setPendingRequest(null); setManualPreviewStale(true); }
  }

  async function previewOperation(request: CleanTransformationRequest) {
    if (!datasetId) return;
    // A later call (a newer step selected, a parameter changed again, a
    // fresh Atlas proposal handed off) must win even if an earlier call's
    // response arrives after it - guard the same way loadExceptionPage
    // already does, rather than let whichever response lands last silently
    // overwrite newer, correct preview data with a stale one.
    const requestId = ++previewRequestId.current;
    setPendingRequest(request); setPreview(null); setRecipePreview(null); setError(null); setManualPreviewStale(false);
    setReviewView("changes"); setReviewRowsView("affected");
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/preview`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request) });
      if (requestId !== previewRequestId.current) return;
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Preview failed.");
      const body = await response.json() as CleanPreviewResponse;
      // Parsing the body above is itself an async step - a parameter edit,
      // dataset switch, or discard can invalidate this request while it was
      // running, same as while the network fetch itself was in flight. The
      // check right after the fetch resolves is not enough on its own:
      // re-check immediately before the state that would make this preview
      // actionable actually commits.
      if (requestId !== previewRequestId.current) return;
      setPreview(body);
    } catch (reason) { if (requestId === previewRequestId.current) setError(reason instanceof Error ? reason.message : "Preview failed."); }
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
    const next = { ...categoryMapping };
    for (const value of categorySelected) next[value] = categoryTarget.trim();
    setCategoryMapping(next);
    // The unified mapping table's bulk-assign is reachable both before and
    // after a preview exists - recompute immediately in the same cases a
    // single-row edit (setMappingTarget) already does, rather than leave a
    // live preview showing numbers for a mapping that no longer matches.
    if (pendingRequest && pendingRequest.operation === "category_mapping") void previewOperation({ ...pendingRequest, category_mapping: next });
    else invalidateManualPreview();
    setCategorySelected(new Set()); setCategoryTarget("");
  }

  /** Editing a proposed value directly in the review table — not just the
   * inspector's bulk assign — must actually recompute the preview, never
   * just redraw a locally-held guess next to stale review data. */
  function updateMappingTarget(source: string, target: string) {
    if (!pendingRequest || pendingRequest.operation !== "category_mapping") return;
    const nextMapping: Record<string, string> = { ...(pendingRequest.category_mapping ?? {}) };
    if (target.trim()) nextMapping[source] = target.trim(); else delete nextMapping[source];
    setCategoryMapping(nextMapping);
    void previewOperation({ ...pendingRequest, category_mapping: nextMapping });
  }

  /** The one real entry point every row of the unified mapping table edits
   * through, whether or not a preview exists yet: with a live preview, the
   * edit recomputes it immediately (updateMappingTarget, unchanged); before
   * one exists, it just updates the mapping and marks any now-mismatched
   * preview stale, the same as every other parameter edit. */
  function setMappingTarget(source: string, target: string) {
    if (pendingRequest && pendingRequest.operation === "category_mapping") { updateMappingTarget(source, target); return; }
    invalidateManualPreview();
    setCategoryMapping((current) => {
      const next = { ...current };
      if (target.trim()) next[source] = target.trim(); else delete next[source];
      return next;
    });
  }

  function toggleCategorySelected(value: string) {
    setCategorySelected((current) => { const next = new Set(current); if (next.has(value)) next.delete(value); else next.add(value); return next; });
  }

  function toggleSurvivorshipColumn(column: string) {
    invalidateManualPreview();
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
      setRecipeName(""); setShowRecipeSave(false); setDraftSteps([]); setEditingRecipeId(null); setEditingStepIndex(null); setRecipePreview(null);
      await loadRecipes();
    } catch (reason) { setRecipeError(reason instanceof Error ? reason.message : "Saving the recipe failed."); }
  }

  function addDraftStep(request: CleanTransformationRequest) {
    const stepId = `draft_${Date.now()}_${draftSteps.length}`;
    setDraftSteps((current) => [...current, { step_id: stepId, request, enabled: true }]);
    setRecipePreview(null);
    // The step just became real (it's in draftSteps now), so the inspector
    // should show its actual position immediately - not "unsaved" until an
    // unrelated re-click, and never a position number before this point.
    setEditingStepIndex(draftSteps.length);
    // Atlas's own explanation for the proposal this step came from, if any -
    // see pendingStepReason's declaration for why this is a one-shot ref, not
    // a plain variable. A manually built step (never routed through Atlas's
    // "Review in Step settings") leaves this unset; the plan-review screen
    // falls back to the operation's own real, already-shown help text rather
    // than inventing a reason.
    // Captured into a local before clearing the ref: the updater below runs
    // after React finishes this batch, by which point `.current = null` would
    // already have landed, silently dropping every model-proposed step's
    // reason and making it indistinguishable from a manually built one.
    const reason = pendingStepReason.current;
    if (reason) {
      setStepReasons((current) => ({ ...current, [stepId]: reason }));
      pendingStepReason.current = null;
    }
  }

  function editSavedRecipe(recipe: CleanRecipe) {
    setEditingRecipeId(recipe.recipe_id); setRecipeName(recipe.name);
    setManualMode(true);
    setDraftSteps(recipe.steps.map((step) => ({ ...step })));
    setRecipePreview(null); setEditingStepIndex(null); setRecipeError(null);
  }

  /** Every field the manual-operation form can show, set from one real
   * request - the single place that keeps the editable form in sync with
   * whatever produced the request (a draft step being reselected, or an
   * Atlas proposal being handed off). A preview computed from `request`
   * without also calling this leaves the form showing stale values that
   * silently stop matching the preview the moment anyone touches Preview
   * or Add step again. */
  function loadRequestIntoForm(request: CleanTransformationRequest) {
    if (request.operation === "category_mapping") pendingMappingRestore.current = request.category_mapping ?? {};
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

  function loadDraftStep(index: number) {
    const request = draftSteps[index]?.request;
    if (!request) return;
    setEditingStepIndex(index); setManualMode(true); setSelectedIssue(null);
    if (inspectorPaneRef.current) inspectorPaneRef.current.scrollTop = 0;
    loadRequestIntoForm(request);
    // Selecting a step in the recipe list must show that step's own real
    // preview in the centre panel immediately, not whatever preview (if
    // any) a previously selected step left behind there.
    void previewOperation(request);
  }

  function updateDraftStep(request: CleanTransformationRequest) {
    if (editingStepIndex === null) return;
    setDraftSteps((current) => current.map((step, index) => index === editingStepIndex ? { ...step, request } : step));
    setEditingStepIndex(null); setRecipePreview(null);
  }

  async function previewSavedRecipe(recipe: CleanRecipe) {
    if (!datasetId) return;
    previewRequestId.current += 1; // switching to a recipe preview must outrun any manual preview still in flight
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

  function toggleDraftStepEnabled(index: number) {
    setDraftSteps((current) => current.map((item, at) => at === index ? { ...item, enabled: !item.enabled } : item));
  }

  /** The plan review's one explicit approval. Deliberately reuses the exact
   * recipe create → preview → apply chain the recipe pane's own named,
   * saved recipes already run through (apply_recipe's atomic, transactional,
   * revision-bound publication of every enabled step) rather than inventing
   * a second apply path - an ad hoc, auto-named recipe is still a real one,
   * with the same validation and provenance guarantees. */
  async function approvePlan() {
    if (!datasetId || !draftSteps.length) return;
    setApprovingPlan(true); setApprovePlanError(null);
    try {
      const name = `Atlas plan — ${new Date().toISOString()}`;
      const created = await fetch(apiUrl("/api/v1/clean/recipes"), {
        method: "POST", headers: { "content-type": "application/json" },
        // A step the plan-review screen shows as "excluded until you decide"
        // (needsClarification) must never reach the backend as enabled just
        // because its own, unrelated enabled flag still happens to be true -
        // the same real condition PlanReviewScreen renders the forced-off
        // toggle from, recomputed here rather than trusted secondhand from a
        // view the approval itself doesn't read.
        body: JSON.stringify({ name, steps: draftSteps.map(({ request, enabled }) => ({ request, enabled: enabled && !needsClarification(request) })) }),
      });
      if (!created.ok) throw new Error((await created.json() as { detail?: string }).detail ?? "Could not record this plan as a recipe.");
      const recipe = await created.json() as CleanRecipe;
      const previewed = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/recipes/${recipe.recipe_id}/preview`), { method: "POST" });
      if (!previewed.ok) throw new Error((await previewed.json() as { detail?: string }).detail ?? "Could not re-review this plan before applying.");
      const preview = await previewed.json() as CleanRecipePreviewResponse;
      const applied = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/recipes/${recipe.recipe_id}/apply`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ review_token: preview.review_token }) });
      if (!applied.ok) throw new Error((await applied.json() as { detail?: string }).detail ?? "Applying this plan failed.");
      setPlanReviewOpen(false); setDraftSteps([]); setDraftPreview(null); setStepReasons({});
      setManualMode(false); setSelectedIssue(null); setPreview(null); setPendingRequest(null); setEditingStepIndex(null);
      await refresh(datasetId);
    } catch (reason) { setApprovePlanError(reason instanceof Error ? reason.message : "Applying this plan failed."); }
    finally { setApprovingPlan(false); }
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
    if (!datasetId || !pendingRequest || !preview?.review_token || applyInFlight.current) return;
    applyInFlight.current = true;
    setApplying(true);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/apply`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ ...pendingRequest, review_token: preview.review_token }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Applying the transformation failed.");
      const applied = await response.json() as { transformation: { transformation_id: string; operation: string } };
      onSelectContext({ objectId: applied.transformation.transformation_id, analyticalObjectId: `clean_${applied.transformation.transformation_id}`, label: `Clean — ${applied.transformation.operation.replaceAll("_", " ")}`, type: "finding", state: "ready", actions: [], metadata: ["Immutable transformation record"] });
      previewRequestId.current += 1; // the dataset just moved to a new revision; nothing previewed against the old one may land now
      setPreview(null); setPendingRequest(null); setSelectedIssue(null); setAtlas(null); setManualMode(false);
      await refresh(datasetId);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Applying the transformation failed."); }
    finally { applyInFlight.current = false; setApplying(false); }
  }

  function selectFinding(finding: PatternFinding) {
    previewRequestId.current += 1; // a preview from whatever was selected before must not land against this finding
    setManualMode(false); setSelectedIssue(null); setRecipePreview(null); setPreview(null); setPendingRequest(null); setAtlas(null);
    if (verifyPollTimer.current) clearTimeout(verifyPollTimer.current);
    verifyJobId.current = null; verifyRequestId.current += 1; setVerifying(false); setVerifyProgress(null);
    exceptionRequestId.current += 1; setExceptionPage(null); setExceptionsLoading(false);
    setSelectedFinding(finding); setAcceptedFamilies(new Set()); setMissingValuePolicy("allow"); setDecisionError(null);
    onSelectContext({
      objectId: finding.finding_id, label: finding.column, type: "finding", state: "ready", actions: [],
      metadata: [finding.detector_kind.replaceAll("_", " "), finding.verified ? "verified · full scan" : `sample of ${finding.rows_examined.toLocaleString()}`],
    });
  }

  async function scanColumn(column: string) {
    if (!datasetId || !column) return;
    setPatternsError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/patterns/columns/${encodeURIComponent(column)}/scan`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ column, ...(groupByColumn ? { group_by_column: groupByColumn, group_value: groupValue } : {}) }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Scanning this column failed.");
      const findings = await response.json() as PatternFinding[];
      if (findings.length) {
        selectFinding(findings[0]!);
        setPatternFindings((current) => [...findings, ...current.filter((item) => item.column !== column || !findings.some((found) => found.detector_kind === item.detector_kind))]);
      } else {
        setSelectedFinding(null);
        setPatternsError(`No pattern detector found usable evidence in ${column}.`);
      }
    } catch (reason) { setPatternsError(reason instanceof Error ? reason.message : "Scanning this column failed."); }
  }

  async function verifyFinding() {
    if (!datasetId || !selectedFinding) return;
    const requestId = ++verifyRequestId.current;
    const column = selectedFinding.column;
    setVerifying(true); setVerifyProgress(null); setPatternsError(null);
    try {
      const started = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/patterns/columns/${encodeURIComponent(column)}/verify/start`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          column, detector_kind: selectedFinding.detector_kind,
          ...(selectedFinding.group_by_column ? { group_by_column: selectedFinding.group_by_column, group_value: selectedFinding.group_value } : {}),
        }),
      });
      if (requestId !== verifyRequestId.current) return; // a newer action superseded this one; discard
      if (!started.ok) throw new Error((await started.json() as { detail?: string }).detail ?? "Verification failed.");
      const initial = await started.json() as PatternVerifyJobStatus;
      verifyJobId.current = initial.job_id;
      await pollVerifyJob(datasetId, column, initial.job_id, requestId);
    } catch (reason) {
      if (requestId === verifyRequestId.current) { setPatternsError(reason instanceof Error ? reason.message : "Verification failed."); setVerifying(false); }
    }
  }

  async function pollVerifyJob(datasetId: string, column: string, jobId: string, requestId: number): Promise<void> {
    if (requestId !== verifyRequestId.current) return; // superseded by a newer selection/verify/cancel
    let body: PatternVerifyJobStatus;
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/patterns/columns/${encodeURIComponent(column)}/verify/jobs/${jobId}`));
      if (requestId !== verifyRequestId.current) return;
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Verification failed.");
      body = await response.json() as PatternVerifyJobStatus;
    } catch (reason) {
      if (requestId === verifyRequestId.current) { setPatternsError(reason instanceof Error ? reason.message : "Verification failed."); setVerifying(false); }
      return;
    }
    if (requestId !== verifyRequestId.current) return;
    setVerifyProgress({ checked: body.rows_checked, total: body.rows_total });
    if (body.state === "running") {
      verifyPollTimer.current = setTimeout(() => void pollVerifyJob(datasetId, column, jobId, requestId), 300);
      return;
    }
    setVerifying(false);
    if (body.state === "succeeded" && body.finding) {
      const current = cleanRef.current?.dataset;
      // A revision/apply can land on this same dataset while the job was
      // still running (selectFinding and the datasetId-change effect only
      // guard against switching findings or datasets, not an apply to the
      // SAME dataset mid-poll). The finding is never dishonest - it always
      // carries the exact revision/fingerprint it was computed against -
      // but presenting it as the current answer here, unlabelled, would be.
      // Reject it the same way the existing exceptions endpoint rejects a
      // stale reviewed_source_revision, rather than silently accepting it.
      if (current && (body.finding.source_revision !== current.revision || body.finding.source_fingerprint !== current.source_fingerprint)) {
        setPatternsError("The dataset changed while this was verifying. Re-scan the column to verify the current revision.");
      } else {
        exceptionRequestId.current += 1; setExceptionPage(null);
        setSelectedFinding(body.finding);
      }
    } else if (body.state === "failed") {
      setPatternsError(body.error ?? "Verification failed.");
    } // "cancelled": the prior sample finding stays displayed as-is; nothing to apply.
  }

  function cancelVerify() {
    const datasetIdForCancel = datasetId;
    const column = selectedFinding?.column;
    const jobId = verifyJobId.current;
    if (verifyPollTimer.current) clearTimeout(verifyPollTimer.current);
    if (datasetIdForCancel && column && jobId) {
      void fetch(apiUrl(`/api/v1/clean/datasets/${datasetIdForCancel}/patterns/columns/${encodeURIComponent(column)}/verify/jobs/${jobId}/cancel`), { method: "POST" });
    }
    verifyRequestId.current += 1;
    setVerifying(false); setVerifyProgress(null);
  }

  async function loadExceptionPage(offset: number) {
    if (!datasetId || !selectedFinding) return;
    const finding = selectedFinding;
    const requestId = ++exceptionRequestId.current;
    setExceptionsLoading(true); setPatternsError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/patterns/columns/${encodeURIComponent(finding.column)}/exceptions`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ detector_kind: finding.detector_kind, reviewed_source_revision: finding.source_revision,
          reviewed_source_fingerprint: finding.source_fingerprint, verified: finding.verified,
          group_by_column: finding.group_by_column, group_value: finding.group_value, offset, limit: 10 }),
      });
      if (requestId !== exceptionRequestId.current) return;
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Exception rows could not be loaded.");
      setExceptionPage(await response.json() as PatternExceptionPage);
    } catch (reason) {
      if (requestId === exceptionRequestId.current) setPatternsError(reason instanceof Error ? reason.message : "Exception rows could not be loaded.");
    } finally { if (requestId === exceptionRequestId.current) setExceptionsLoading(false); }
  }

  async function saveDecision(kind: PatternReviewDecisionKind, options?: { revokesDecisionId?: string }) {
    if (!datasetId || !selectedFinding) return;
    if (kind === "accept_family" && acceptedFamilies.size === 0) { setDecisionError("Select at least one family to accept first."); return; }
    setDecisionBusy(true); setDecisionError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/patterns/decisions`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          column: selectedFinding.column, decision: kind,
          ...(kind === "accept_family" ? { family_signatures: Array.from(acceptedFamilies) } : {}),
          detector_kind: selectedFinding.detector_kind,
          reviewed_source_revision: selectedFinding.source_revision, reviewed_source_fingerprint: selectedFinding.source_fingerprint,
          ...(options?.revokesDecisionId ? { revokes_decision_id: options.revokesDecisionId } : {}),
        }),
      });
      if (response.status === 409) throw new Error("The dataset changed since this finding was reviewed. Re-scan the column before deciding.");
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Saving the decision failed.");
      setAcceptedFamilies(new Set());
      await loadPatternDecisions(datasetId);
    } catch (reason) { setDecisionError(reason instanceof Error ? reason.message : "Saving the decision failed."); }
    finally { setDecisionBusy(false); }
  }

  async function savePatternValidationRule() {
    if (!datasetId || !selectedFinding) return;
    if (acceptedFamilies.size === 0) { setDecisionError("Select at least one family to accept before saving a rule."); return; }
    if (!ruleNameForPattern.trim()) { setDecisionError("Name the rule before saving it."); return; }
    setDecisionBusy(true); setDecisionError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/clean/validation-rules"), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          name: ruleNameForPattern.trim(), kind: "pattern_family", column: selectedFinding.column,
          accepted_family_signatures: Array.from(acceptedFamilies), missing_value_policy: missingValuePolicy,
          ...(selectedFinding.group_by_column ? { group_by_column: selectedFinding.group_by_column, group_value: selectedFinding.group_value } : {}),
        }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Saving the rule failed.");
      setRuleNameForPattern("");
      await loadValidationRules();
      await saveDecision("accept_family");
    } catch (reason) { setDecisionError(reason instanceof Error ? reason.message : "Saving the rule failed."); }
    finally { setDecisionBusy(false); }
  }

  function previewExtraction(family?: PatternFamily) {
    if (!selectedFinding) return;
    let request: CleanTransformationRequest | null = null;
    if (selectedFinding.detector_kind === "identifier_structure" && family) {
      request = { operation: "extract_identifier_components", column: selectedFinding.column, family_signature: family.family_signature };
    } else if (selectedFinding.detector_kind === "numeric_unit") {
      request = { operation: "extract_numeric_unit", column: selectedFinding.column };
    } else if (selectedFinding.detector_kind === "delimited_compound" && family) {
      const match = /^delim:(.+):parts:(\d+)$/.exec(family.family_signature);
      const delimiter = match?.[1];
      const parts = match?.[2];
      if (delimiter && parts) request = { operation: "split_delimited", column: selectedFinding.column, delimiter, max_parts: Number(parts) };
    }
    if (request) void previewOperation(request);
    else setDecisionError("This finding does not support an extraction operation.");
  }

  async function undoTo(revision: number) {
    if (!datasetId) return;
    await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/undo`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ to_revision: revision }) });
    previewRequestId.current += 1; // the dataset just moved to a different revision; nothing previewed against the old one may land now
    setPreview(null); setPendingRequest(null); setSelectedIssue(null); setAtlas(null); setManualMode(false);
    await refresh(datasetId);
  }

  if (state === "empty") return <section className="overview-state empty-state"><span className="eyebrow">CLEAN · NATIVE WORKSPACE</span><h1>Load a dataset in Overview first.</h1><p>Clean operates on the same server-held dataset Overview and SQL Lab already use — there is nothing to clean until one is loaded.</p><button onClick={() => onOpenWorkflow("overview")}>Open Overview</button></section>;
  // error must be checked before the loading/null-data fallback: a failed
  // first load never populates `clean`, so `!clean` alone would keep
  // matching the loading branch forever and the error (with its retry
  // control) would never be reachable.
  if (state === "error") return <section className="overview-state error-state" role="alert"><h2>Clean could not load this dataset.</h2><p>{error}</p><button onClick={() => datasetId && void refresh(datasetId)}>Retry</button></section>;
  if (state === "loading" || !clean) return <section className="overview-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Scanning for quality issues</h2><p>Loading the dataset profile and checking for quality issues. Larger datasets may take longer.</p></section>;

  const manualBuild = manualMode ? buildManualRequest() : { request: null, reason: null };
  const manualSpec = OPERATIONS.find((item) => item.value === manualOperation);
  // "New step" only while nothing has been built yet for a brand-new (not
  // yet in the list) step: a real position number belongs to a step that
  // is actually in the recipe (an applied step, or a draft step being
  // re-opened by editingStepIndex), never to one still being built in the
  // inspector that hasn't been added yet - being previewable isn't being
  // saved, and showing "STEP 3" for an unsaved, uncommitted step claimed a
  // position that didn't exist in the recipe list above it.
  const manualStepNumber = editingStepIndex !== null ? clean.history.length + editingStepIndex + 1 : null;

  function resizeCleanPane(side: "recipe" | "inspector", proposedWidth: number) {
    const grid = gridRef.current;
    if (!grid) return;
    const otherWidth = side === "recipe" ? (inspectorPaneRef.current?.getBoundingClientRect().width ?? 320) : (recipePaneRef.current?.getBoundingClientRect().width ?? 340);
    const largest = Math.max(270, Math.min(440, grid.getBoundingClientRect().width - otherWidth - 370));
    const width = Math.round(Math.max(270, Math.min(largest, proposedWidth)));
    if (side === "recipe") setRecipePaneWidth(width);
    else setInspectorPaneWidth(width);
  }

  function onPanePointerMove(side: "recipe" | "inspector", event: React.PointerEvent<HTMLDivElement>) {
    if (resizingPane.current !== side || !gridRef.current) return;
    const bounds = gridRef.current.getBoundingClientRect();
    resizeCleanPane(side, side === "recipe" ? event.clientX - bounds.left : bounds.right - event.clientX);
  }

  function onPaneKeyDown(side: "recipe" | "inspector", event: React.KeyboardEvent<HTMLDivElement>) {
    const delta = event.key === "ArrowRight" ? 16 : event.key === "ArrowLeft" ? -16 : 0;
    if (!delta) return;
    event.preventDefault();
    const current = side === "recipe" ? (recipePaneRef.current?.getBoundingClientRect().width ?? 340) : (inspectorPaneRef.current?.getBoundingClientRect().width ?? 320);
    resizeCleanPane(side, current + (side === "recipe" ? delta : -delta));
  }
  // The small launcher icon reflects whether there's real step context for
  // Atlas to work from right now - it never claims "working" unless the
  // dock panel itself is actually mid-request (that pose lives there).
  const atlasPose: AtlasPose = manualMode || selectedIssue || selectedFinding ? "idle" : "waiting";

  /** The one mapping table, used identically before and after a preview
   * exists - previously these were two visually different surfaces (a
   * chip-select-and-bulk-assign list pre-preview, a separate inline-
   * editable table post-preview). Every row edits through setMappingTarget,
   * which already does the right thing (recompute immediately if a preview
   * is live, just update and mark stale otherwise) regardless of which
   * state this renders in. */
  function renderMappingTable(values: ReadonlyArray<{ value: string; count?: number }>, review = false) {
    return <>
      {!review ? <div className="clean-mapping-bulk">
        <ul className="clean-value-chips">{values.map((item) => <li key={item.value}><label className={categorySelected.has(item.value) ? "is-selected" : categoryMapping[item.value] ? "is-mapped" : ""}><input type="checkbox" checked={categorySelected.has(item.value)} onChange={() => toggleCategorySelected(item.value)} /> <span>{item.value}</span>{item.count !== undefined ? <small>{item.count.toLocaleString()}</small> : null}</label></li>)}</ul>
        <label>Map selected to<input aria-label="Map selected values to" value={categoryTarget} onChange={(event) => setCategoryTarget(event.target.value)} placeholder="e.g. Bengaluru" /></label>
        <button type="button" className="secondary" disabled={categorySelected.size === 0 || !categoryTarget.trim()} onClick={assignCategoryMapping}>Assign mapping to selected</button>
      </div> : null}
      <div className={`data-table-wrap clean-mapping-review${review ? " is-review" : ""}`} tabIndex={0}><table><thead><tr><th>Source value</th><th>Proposed value</th><th>Rows</th><th>Status</th></tr></thead><tbody>{values.map((item) => {
        const target = categoryMapping[item.value] ?? "";
        const mapped = Boolean(target);
        return <tr key={item.value}>
          <td>{item.value}</td>
          <td><input key={`${item.value}:${target}`} className="clean-mapping-target-input" list="clean-mapping-target-options" aria-label={`Proposed value for ${item.value}`} defaultValue={target} placeholder={categoryPreserveUnmatched ? "Leave unchanged" : "Needs a value…"} onBlur={(event) => { if (event.target.value !== target) setMappingTarget(item.value, event.target.value); }} /></td>
          <td>{item.count === undefined ? "—" : item.count.toLocaleString()}</td>
          <td>{mapped ? <span className="health-pill good">Will change</span> : categoryPreserveUnmatched ? <span className="health-pill info">Preserved</span> : <span className="health-pill warn">Needs decision</span>}</td>
        </tr>;
      })}</tbody></table><datalist id="clean-mapping-target-options">{Array.from(new Set(Object.values(categoryMapping))).map((value) => <option key={value} value={value} />)}</datalist></div>
      {review ? <details className="clean-mapping-bulk-disclosure"><summary>Bulk assign source values</summary><div className="clean-mapping-bulk">
        <ul className="clean-value-chips">{values.map((item) => <li key={item.value}><label className={categorySelected.has(item.value) ? "is-selected" : categoryMapping[item.value] ? "is-mapped" : ""}><input type="checkbox" checked={categorySelected.has(item.value)} onChange={() => toggleCategorySelected(item.value)} /> <span>{item.value}</span>{item.count !== undefined ? <small>{item.count.toLocaleString()}</small> : null}</label></li>)}</ul>
        <label>Map selected to<input aria-label="Map selected values to" value={categoryTarget} onChange={(event) => setCategoryTarget(event.target.value)} placeholder="e.g. Bengaluru" /></label>
        <button type="button" className="secondary" disabled={categorySelected.size === 0 || !categoryTarget.trim()} onClick={assignCategoryMapping}>Assign mapping to selected</button>
      </div></details> : null}
    </>;
  }

  if (planReviewOpen) return <PlanReviewScreen
    steps={draftSteps.map((step, index) => ({ step, index, affectedRows: draftPreview?.step_impacts[index] ?? null, reason: stepReasons[step.step_id] ?? null }))}
    datasetName={clean.dataset.source_name}
    revision={clean.dataset.revision}
    rowCount={clean.dataset.row_count}
    columnCount={clean.dataset.column_count}
    columns={profile?.columns ?? []}
    onToggleStep={toggleDraftStepEnabled}
    onInspectStep={(index) => { setPlanReviewOpen(false); loadDraftStep(index); }}
    onApprove={() => void approvePlan()}
    onClose={() => setPlanReviewOpen(false)}
    approving={approvingPlan}
    approveError={approvePlanError}
  />;

  return <article ref={gridRef} className="clean-workspace three-pane" style={{ "--clean-recipe-width": recipePaneWidth ? `${recipePaneWidth}px` : undefined, "--clean-inspector-width": inspectorPaneWidth ? `${inspectorPaneWidth}px` : undefined } as React.CSSProperties}>
    <header className="clean-dataset-header">
      <div><span className="eyebrow">Source: {clean.dataset.source_name}</span><h1>{preview?.operation === "category_mapping" ? "Review category mapping" : "Clean dataset"}</h1><p>{clean.dataset.row_count.toLocaleString()} rows · {clean.dataset.column_count} columns · revision {clean.dataset.revision}</p></div>
      {/* Unlike a numbered, gated wizard, every stage here is freely reachable at
          any time and never claims a later workspace is "done" - there is no
          dataset-wide notion of Clean/SQL/Visualize/Report completion to report
          honestly, only this revision's own applied-or-not state shown elsewhere. */}
      <div className="clean-header-actions"><nav className="clean-workflow-strip" aria-label="Workflow"><ol>
        <li className="is-current"><span className="step-circle">1</span><span className="step-label">Clean</span></li>
        <li><button type="button" onClick={() => onOpenWorkflow("sql-lab")}><span className="step-circle">2</span><span className="step-label">SQL Lab</span></button></li>
        <li><button type="button" onClick={() => onOpenWorkflow("visualize")}><span className="step-circle">3</span><span className="step-label">Visualize</span></button></li>
        <li><button type="button" onClick={() => onOpenWorkflow("reports")}><span className="step-circle">4</span><span className="step-label">Reports</span></button></li>
      </ol></nav><button type="button" className={`atlas-launcher ${inspectorTab === "atlas" ? "is-active" : ""}`} aria-controls="clean-atlas-panel" aria-pressed={inspectorTab === "atlas"} onClick={() => setInspectorTab("atlas")}><AtlasCharacter pose={atlasPose} size="small" /><span><strong>Atlas</strong><small>Ask about this step</small></span></button></div>
    </header>
    <nav ref={recipePaneRef} className="clean-issues" aria-label="Data quality issue navigator and manual operation editor" tabIndex={0}>
      <div className="section-title"><div><h2>Transformation recipe</h2><p className="clean-recipe-subtitle">{clean.history.length || draftSteps.length || recipePreview || (preview && pendingRequest) ? `${clean.history.length + (recipePreview ? (recipes.find((recipe) => recipe.recipe_id === recipePreview.recipe_id)?.steps.length ?? 0) : draftSteps.length ? draftSteps.length : (preview && pendingRequest) ? 1 : 0)} step(s)` : "Empty"}</p></div></div>
      <ol className="clean-recipe-unified" aria-label="Unified transformation recipe">
        {clean.history.map((item, index) => <li key={item.transformation_id} className="is-applied">
          <i aria-hidden="true" /><span className="clean-step-number">{String(index + 1).padStart(2, "0")}</span>
          <div className="clean-step-body"><strong>{item.operation.replaceAll("_", " ")}<span className="clean-step-status is-applied">Applied</span></strong><small>{item.column ?? "dataset"} · revision {item.resulting_revision}</small></div>
        </li>)}
        {recipePreview ? recipes.find((recipe) => recipe.recipe_id === recipePreview.recipe_id)?.steps.map((step, index) => <li key={step.step_id} className={step.enabled ? "is-preview" : ""}>
          <i aria-hidden="true" /><span className="clean-step-number">{String(clean.history.length + index + 1).padStart(2, "0")}</span>
          <div className="clean-step-body"><strong>{step.request.operation.replaceAll("_", " ")}<span className={`clean-step-status ${step.enabled ? "is-reviewed" : "is-disabled"}`}>{step.enabled ? "Preview" : "Disabled"}</span></strong><small>{step.request.column ?? "dataset"} · {recipePreview.step_impacts[index] ?? 0} affected</small></div>
        </li>) : draftSteps.length ? draftSteps.map((step, index) => {
          const isReviewedStep = step.enabled && editingStepIndex === index && Boolean(preview && pendingRequest)
            && JSON.stringify(step.request) === JSON.stringify(pendingRequest);
          return <li key={step.step_id} className={`${step.enabled ? isReviewedStep ? "is-preview" : "is-draft" : ""} ${editingStepIndex === index ? "is-selected" : ""}`.trim()}>
          <i aria-hidden="true" />
          <button type="button" className="clean-step-select" aria-current={editingStepIndex === index ? "step" : undefined} onClick={() => loadDraftStep(index)}>
            <span className="clean-step-number">{String(clean.history.length + index + 1).padStart(2, "0")}</span>
            <span className="clean-step-body">
              <strong>{step.request.operation.replaceAll("_", " ")}<span className={`clean-step-status ${step.enabled ? isReviewedStep ? "is-reviewed" : "is-draft" : "is-disabled"}`}>{step.enabled ? isReviewedStep ? "Review" : "Draft" : "Disabled"}</span></strong>
              <small>{step.request.column ?? "dataset"}{draftPreview ? ` · ${draftPreview.step_impacts[index] ?? 0} affected` : ""}</small>
            </span>
          </button>
          <details className="clean-step-menu">
            <summary aria-label={`More actions for step ${index + 1}`}>⋯</summary>
            <div className="clean-step-menu-items">
              <button aria-label={`Move step ${index + 1} up`} disabled={index === 0} onClick={(event) => { closeStepMenu(event); setDraftSteps((current) => { const next = [...current]; [next[index - 1], next[index]] = [next[index]!, next[index - 1]!]; return next; }); }}>Move up</button>
              <button aria-label={`Move step ${index + 1} down`} disabled={index === draftSteps.length - 1} onClick={(event) => { closeStepMenu(event); setDraftSteps((current) => { const next = [...current]; [next[index], next[index + 1]] = [next[index + 1]!, next[index]!]; return next; }); }}>Move down</button>
              <button aria-label={`${step.enabled ? "Disable" : "Enable"} step ${index + 1}`} onClick={(event) => { closeStepMenu(event); setDraftSteps((current) => current.map((item, at) => at === index ? { ...item, enabled: !item.enabled } : item)); }}>{step.enabled ? "Disable" : "Enable"}</button>
              <button aria-label={`Remove step ${index + 1}`} onClick={(event) => { closeStepMenu(event); setDraftSteps((current) => current.filter((_, at) => at !== index)); }}>Remove</button>
            </div>
          </details>
        </li>;
        }) : (preview && pendingRequest) ? <li className="is-preview is-selected">
          <i aria-hidden="true" /><span className="clean-step-number">{String(clean.history.length + 1).padStart(2, "0")}</span>
          <div className="clean-step-body"><strong>{OPERATIONS.find((item) => item.value === pendingRequest.operation)?.label ?? pendingRequest.operation.replaceAll("_", " ")}<span className="clean-step-status is-reviewed">Preview</span></strong><small>{(preview.changed_rows_total ?? preview.affected_rows).toLocaleString()} affected · unsaved step</small></div>
        </li> : null}
      </ol>
      {!clean.history.length && !draftSteps.length && !recipePreview && !(preview && pendingRequest) ? <p className="quiet-note">No steps yet. Select an issue, or start a manual operation below, to build this dataset's recipe.</p> : null}
      {draftError ? <p role="alert" className="query-error">{draftError}</p> : draftSteps.length && draftPreview ? <p className="quiet-note clean-recipe-note">Downstream preview recomputed from revision {draftPreview.source_revision}. Projected health {draftPreview.projected_health.total}/100.</p> : null}

      <div className="clean-recipe-actions">
        <button className={manualMode ? "is-selected" : "secondary"} onClick={startManualOperation}>+ Add step</button>
        <button className="secondary" disabled={!draftSteps.length && !manualBuild.request} title={!draftSteps.length && !manualBuild.request ? "Build at least one draft step first." : "Save the draft recipe"} onClick={() => editingRecipeId ? void saveAsRecipe(manualBuild.request ?? draftSteps[0]!.request) : setShowRecipeSave(true)}>{editingRecipeId ? "Save recipe changes" : "Save recipe"}</button>
        {draftSteps.length > 1 ? <button type="button" className="secondary" onClick={() => setPlanReviewOpen(true)}>Review plan</button> : null}
      </div>
      {showRecipeSave && !editingRecipeId ? <form className="clean-recipe-save-form" onSubmit={(event) => { event.preventDefault(); if (manualBuild.request || draftSteps.length) void saveAsRecipe(manualBuild.request ?? draftSteps[0]!.request); }}>
        <label className="clean-recipe-name">Recipe name<input aria-label="Recipe name" autoFocus value={recipeName} onChange={(event) => setRecipeName(event.target.value)} placeholder="e.g. Standard monthly cleanup" /></label>
        <div><button type="submit">Save named recipe</button><button type="button" className="secondary" onClick={() => { setShowRecipeSave(false); setRecipeError(null); }}>Cancel</button></div>
      </form> : null}
      {draftSteps.length ? <p className="clean-recipe-tip">Disable a step to preview downstream changes without removing it.</p> : null}

      {manualOperation === "category_mapping" && manualMode && columnValues && !Object.keys(categoryMapping).length ? (() => {
        const groups = suggestCategoryGroups(columnValues.values);
        if (!groups.length) return null;
        return <div className="clean-mapping-suggestion">
          <span className="eyebrow">Suggested mapping <span className="health-pill">Rule-based</span></span>
          <p>{groups.length} group{groups.length === 1 ? "" : "s"} found by matching trimmed, case-insensitive spelling. Review each proposed group.</p>
          <ul>{groups.slice(0, 3).map((group) => <li key={group.canonical}>{group.variants.map((v) => v.value).join(", ")}<span aria-hidden="true">→</span><strong>{group.canonical}</strong></li>)}</ul>
          {groups.length > 3 ? <small>+{groups.length - 3} more group{groups.length - 3 === 1 ? "" : "s"}</small> : null}
          <button type="button" className="secondary" onClick={() => {
            const next = { ...categoryMapping };
            for (const group of groups) for (const variant of group.variants) if (variant.value !== group.canonical) next[variant.value] = group.canonical;
            setCategoryMapping(next);
            if (pendingRequest && pendingRequest.operation === "category_mapping") void previewOperation({ ...pendingRequest, category_mapping: next });
            else invalidateManualPreview();
          }}>Apply suggested grouping</button>
        </div>;
      })() : null}

      {manualOperation === "category_mapping" && Object.keys(categoryMapping).length ? <div className="clean-current-mapping">
        <span className="eyebrow">Current mapping</span>
        <p>{Object.keys(categoryMapping).length} source value{Object.keys(categoryMapping).length === 1 ? "" : "s"} mapped to {new Set(Object.values(categoryMapping)).size} target{new Set(Object.values(categoryMapping)).size === 1 ? "" : "s"}.</p>
        <ul>{Object.entries(categoryMapping).slice(0, 5).map(([source, target]) => <li key={source}><code>{source}</code><span aria-hidden="true">→</span><code>{target}</code></li>)}</ul>
        {Object.keys(categoryMapping).length > 5 ? <small>+{Object.keys(categoryMapping).length - 5} more</small> : null}
        <button type="button" className="secondary" onClick={() => { setManualMode(true); setSelectedIssue(null); setSelectedFinding(null); }}><Icon name="layers" className="clean-action-icon" />Review full mapping</button>
      </div> : manualOperation === "category_mapping" && manualMode ? <div className="clean-current-mapping is-empty">
        <span className="eyebrow">Current mapping</span>
        <p>No values mapped yet. Select source values in the inspector and assign a target to build the mapping here.</p>
      </div> : null}

      <details className="clean-disclosure">
        <summary>Saved recipes <span className="health-pill">{recipes.length}</span></summary>
        {recipes.length ? <ul className="clean-recipe-list">{recipes.map((recipe) => {
        const enabledCount = recipe.steps.filter((step) => step.enabled).length;
        return <li key={recipe.recipe_id}>
          <div><strong>{recipe.name}</strong><small>v{recipe.version} · {enabledCount}/{recipe.steps.length} step(s) enabled</small><ol className="clean-saved-steps" aria-label={`${recipe.name} steps`}>{recipe.steps.map((step, index) => <li key={step.step_id}><span className="clean-step-number">{String(index + 1).padStart(2, "0")}</span><span>{OPERATIONS.find((item) => item.value === step.request.operation)?.label ?? step.request.operation.replaceAll("_", " ")}<small>{step.request.column ?? "dataset"}{recipePreview?.recipe_id === recipe.recipe_id ? ` · ${recipePreview.step_impacts[index] ?? 0} affected` : ""}</small></span><span className={`clean-step-status ${step.enabled ? "is-draft" : "is-disabled"}`}>{step.enabled ? recipePreview?.recipe_id === recipe.recipe_id ? "Preview" : "Saved" : "Disabled"}</span></li>)}</ol></div>
          <button className="secondary" disabled={applyingRecipeId === recipe.recipe_id} onClick={() => void previewSavedRecipe(recipe)}>Preview</button>
          <button className="secondary" onClick={() => editSavedRecipe(recipe)}>Edit steps</button>
          {recipePreview?.recipe_id === recipe.recipe_id ? <div className="clean-recipe-review"><small>Reviewed revision {recipePreview.source_revision} · {recipePreview.step_impacts.join(" / ")} affected row(s) by step</small><button disabled={applyingRecipeId === recipe.recipe_id} onClick={() => void applyRecipe(recipe)}>{applyingRecipeId === recipe.recipe_id ? "Applying…" : "Apply reviewed recipe"}</button><button className="secondary" onClick={() => setRecipePreview(null)}>Discard</button></div> : null}
        </li>;
      })}</ul> : <p className="quiet-note">Build an operation in the inspector and save it as a recipe to reuse it later, or on another dataset with the same schema.</p>}
      </details>
      {recipeError ? <p className="query-error" role="alert">{recipeError}</p> : null}

      <details className="clean-disclosure">
        <summary>Issues <span className={`health-pill ${clean.health.total >= 80 ? "good" : clean.health.total >= 60 ? "warn" : "risk"}`}>{clean.issues.length ? clean.issues.length : clean.health.total + "/100"}</span></summary>
      <div className="finding-list">{clean.issues.map((issue) => <button key={issue.issue_id} className={!manualMode && issue.issue_id === selectedIssue?.issue_id ? "is-selected" : ""} onClick={() => void selectIssue(issue)}><span className={`finding-dot ${issue.severity === "high" ? "issue" : issue.severity === "medium" ? "warning" : "good"}`} /><strong>{issue.column ?? "Dataset"}</strong><small>{issue.description}</small></button>)}</div>
      </details>

      <details className="clean-disclosure">
        <summary>Validation <span className="health-pill">{validationRules.length ? `${validationRules.length} rule(s)` : "none"}</span></summary>
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
      <details className="clean-validation-editor"><summary>Add validation rule</summary><div className="clean-manual-form clean-new-rule">
        <label>New rule name<input aria-label="Validation rule name" value={newRuleName} onChange={(event) => setNewRuleName(event.target.value)} placeholder="e.g. Unique customer IDs" /></label>
        <label>Kind<select aria-label="Validation rule kind" value={newRuleKind} onChange={(event) => setNewRuleKind(event.target.value as ValidationRuleKind)}><option value="uniqueness">uniqueness</option><option value="nonnegative">nonnegative</option><option value="date_order">date order</option></select></label>
        {newRuleKind !== "date_order" ? <label>Rule column<input aria-label="Validation rule column" list="clean-column-options" value={newRuleColumn} onChange={(event) => setNewRuleColumn(event.target.value)} placeholder="Search columns…" /></label> : <>
          <label>Before column (earlier date)<input aria-label="Before column" list="clean-column-options" value={newRuleBeforeColumn} onChange={(event) => setNewRuleBeforeColumn(event.target.value)} placeholder="Search columns…" /></label>
          <label>After column (later date)<input aria-label="After column" list="clean-column-options" value={newRuleAfterColumn} onChange={(event) => setNewRuleAfterColumn(event.target.value)} placeholder="Search columns…" /></label>
        </>}
        <button type="button" className="secondary" onClick={() => void createValidationRule()}>Save rule</button>
        {validationError ? <p className="quiet-note">{validationError}</p> : null}
      </div></details>
      </details>

      <details className="clean-disclosure">
        <summary>Patterns <span className="health-pill">{patternsLoading ? "…" : patternFindings.length || "none"}</span></summary>
      <div className="clean-manual-form clean-pattern-controls">
        <label>Group by (optional)<select aria-label="Group pattern discovery by column" value={groupByColumn} onChange={(event) => { setGroupByColumn(event.target.value); setGroupValue(""); }}>
          <option value="">No grouping</option>
          {(profile?.columns ?? []).map((column) => <option key={column.name} value={column.name}>{column.name}</option>)}
        </select></label>
        {groupByColumn ? <label>Group value<input aria-label="Group value" value={groupValue} onChange={(event) => setGroupValue(event.target.value)} placeholder="e.g. US" /></label> : null}
        <label>Explore a column<input aria-label="Column to explore for patterns" list="clean-column-options" value={exploreColumn} onChange={(event) => setExploreColumn(event.target.value)} placeholder="Search columns…" /></label>
        <button type="button" className="secondary" disabled={!exploreColumn} onClick={() => void scanColumn(exploreColumn)}>Scan column</button>
      </div>
      {patternsError ? <p className="query-error" role="alert">{patternsError}</p> : null}
      {patternFindings.length ? <div className="finding-list">{patternFindings.map((finding) => <button key={finding.finding_id} className={selectedFinding?.finding_id === finding.finding_id ? "is-selected" : ""} onClick={() => selectFinding(finding)}>
        <span className="finding-dot good" />
        <strong>{finding.column}{finding.group_value ? ` · ${finding.group_value}` : ""}</strong>
        <small>{finding.detector_kind.replaceAll("_", " ")} · {(finding.families ?? []).length ? `${(finding.families ?? []).length} famil${(finding.families ?? []).length === 1 ? "y" : "ies"}, top ${(finding.families ?? [])[0]!.matching_count} of ${finding.rows_examined}` : `${finding.exception_count} exception(s)`}{finding.verified ? " · verified" : ""}</small>
      </button>)}</div> : !patternsLoading ? <p className="quiet-note">No format-family evidence surfaced in a bounded sample. Try the column explorer above for a deliberate look, or choose a grouping column.</p> : null}
      </details>

      <details className="clean-disclosure">
        <summary>History <span className="health-pill">{clean.history.length + 1}</span></summary>
      <ol className="clean-history">
        <li><button className={clean.dataset.revision === 0 ? "is-selected" : ""} onClick={() => void undoTo(0)}>Revision 0 · original</button></li>
        {clean.history.map((item) => <li key={item.transformation_id}><button className={clean.dataset.revision === item.resulting_revision ? "is-selected" : ""} onClick={() => void undoTo(item.resulting_revision)}>Revision {item.resulting_revision} · {item.operation.replaceAll("_", " ")}{item.column ? ` · ${item.column}` : ""}</button></li>)}
      </ol>
      </details>
    </nav>
    <section className="clean-preview" aria-label="Data and transformation preview">
    <div className="clean-preview-scroll" tabIndex={0}>
      {preview ? <>
        <div className="clean-review-tabs" role="tablist" aria-label="Review transformation"><button role="tab" aria-selected={reviewView === "before"} onClick={() => setReviewView("before")}>Before</button><button role="tab" aria-selected={reviewView === "changes"} onClick={() => setReviewView("changes")}>Changes</button><button role="tab" aria-selected={reviewView === "after"} onClick={() => setReviewView("after")}>After</button></div>
        {reviewView === "before" ? <><p className="quiet-note">Source revision {preview.source_revision ?? clean.dataset.revision} · fingerprint {(preview.source_fingerprint ?? clean.dataset.source_fingerprint).slice(0, 12)}… · first {preview.before_sample.length} row(s)</p><SampleTable rows={preview.before_sample} /></> : null}
        {reviewView === "after" ? <><p className="quiet-note">Projected result only. Nothing has been applied. First {preview.after_sample.length} row(s).</p><SampleTable rows={preview.after_sample} /></> : null}
        {reviewView === "changes" ? <>
          <p className="clean-preview-summary">{preview.operation.replaceAll("_", " ")} affects <strong>{(preview.changed_rows_total ?? preview.affected_rows).toLocaleString()}</strong> row(s){(preview.affected_columns ?? []).length ? ` in ${(preview.affected_columns ?? []).join(", ")}` : ""}. Projected health <strong>{preview.projected_health.total}/100</strong> (currently {clean.health.total}/100).</p>
          <div className="clean-impact-summary"><div><strong>{(preview.changed_rows_total ?? preview.affected_rows).toLocaleString()}</strong><span>affected rows</span></div><div><strong>{Object.keys(pendingRequest?.category_mapping ?? {}).length.toLocaleString()}</strong><span>mapped labels</span></div><div><strong>{(preview.exception_rows_total ?? 0).toLocaleString()}</strong><span>{preview.operation === "category_mapping" && pendingRequest?.preserve_unmatched !== false ? "unmatched rows" : "exceptions"}</span></div></div>
          {preview.operation === "category_mapping" && pendingRequest ? renderMappingTable(columnValues?.values ?? Object.keys(pendingRequest.category_mapping ?? {}).map((value) => ({ value })), true) : null}
          {(preview.warnings ?? []).length ? <ul className="clean-warnings">{(preview.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
          <div className="clean-review-tabs is-underline" role="tablist" aria-label="Inspect review results"><button role="tab" aria-selected={reviewRowsView === "affected"} onClick={() => setReviewRowsView("affected")}>Affected rows ({(preview.changed_rows_total ?? preview.affected_rows).toLocaleString()})</button><button role="tab" aria-selected={reviewRowsView === "exceptions"} onClick={() => setReviewRowsView("exceptions")}>Exceptions ({(preview.exception_rows_total ?? 0).toLocaleString()})</button><button role="tab" aria-selected={reviewRowsView === "validation"} onClick={() => setReviewRowsView("validation")}>Validation</button></div>
          {reviewRowsView === "affected" ? <InspectionTable rows={preview.changed_rows ?? []} total={preview.changed_rows_total ?? preview.affected_rows} /> : null}
          {reviewRowsView === "exceptions" ? <><p className="quiet-note">{(preview.unresolved_values ?? []).length} distinct {preview.operation === "category_mapping" && pendingRequest?.preserve_unmatched !== false ? "unmapped value(s). They and missing cells remain unchanged in this preview." : "unresolved value(s). These rows stay unchanged unless the selected operation explicitly makes them missing."}</p><InspectionTable rows={preview.exception_rows ?? []} total={preview.exception_rows_total ?? 0} preservedUnmatched={preview.operation === "category_mapping" && pendingRequest?.preserve_unmatched !== false} /></> : null}
          {reviewRowsView === "validation" ? <div className="clean-validation-review">{validationRules.length ? validationRules.map((rule) => {
            const result = validationResults[rule.rule_id];
            return <section key={rule.rule_id}><strong>{rule.name}</strong><p>{result ? `${result.violation_count} violation(s) at revision ${result.dataset_revision}` : "Not run. Use Run beside this rule in the recipe pane."}</p>{result?.sample_violations?.length ? <div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Source row</th><th>Values</th></tr></thead><tbody>{result.sample_violations.map((row, index) => <tr key={index}><td><code>{result.violation_source_rows?.[index] ?? "unknown"}</code></td><td><code>{JSON.stringify(row)}</code></td></tr>)}</tbody></table></div> : null}</section>;
          }) : <p>No saved validation rules. Add one in the recipe pane and run it against the current dataset.</p>}</div> : null}
        </> : null}
      </> : recipePreview ? <>
        <p className="clean-preview-summary">Recipe version {recipePreview.recipe_version} reviewed against revision {recipePreview.source_revision}. Projected health: <strong>{recipePreview.projected_health.total}/100</strong>.</p>
        <div className="clean-diff"><div><span className="eyebrow">BEFORE</span><SampleTable rows={recipePreview.before_sample} /></div><div><span className="eyebrow">AFTER</span><SampleTable rows={recipePreview.after_sample} /></div></div>
        <p className="quiet-note">No dataset changes until Apply reviewed recipe.</p>
      </> : manualMode && manualOperation === "category_mapping" ? <div className="clean-centre-editor">
        <div className="section-title"><div><span className="eyebrow">MAPPING EDITOR</span><h2>Map source values to targets</h2></div></div>
        {columnValues ? <>
          <p className="quiet-note">{columnValues.total_distinct.toLocaleString()} distinct value(s) in {manualColumn || "the selected column"}{columnValues.truncated ? ` (showing the top ${columnValues.values.length})` : ""}. Select several and assign them all at once, or type a value directly into a row. Operation-wide settings (case sensitivity, unmatched values) are on the right.</p>
          {renderMappingTable(columnValues.values)}
        </> : <p className="quiet-note">{manualColumn ? "Loading distinct values…" : "Choose a column on the right to see its distinct values here."}</p>}
      </div> : manualMode && manualOperation === "deduplicate_survivorship" ? <div className="clean-centre-editor">
        <div className="section-title"><div><span className="eyebrow">GROUPING COLUMNS</span><h2>Choose columns that define a duplicate</h2></div></div>
        <p className="quiet-note">Group rows that share the same value in every selected column; keep one row per group, chosen by the survivorship rule on the right.</p>
        <ul className="clean-value-list">{(profile?.columns ?? []).map((column) => <li key={column.name}><label><input type="checkbox" checked={survivorshipColumns.has(column.name)} onChange={() => toggleSurvivorshipColumn(column.name)} /> <span>{column.name}</span> <small>{column.semantic_type}</small></label></li>)}</ul>
      </div> : draftPreview ? <>
        <p className="clean-preview-summary">Draft recipe recalculated against revision {draftPreview.source_revision}. Projected health: <strong>{draftPreview.projected_health.total}/100</strong>. Save the recipe and preview its version before Apply.</p>
        <div className="clean-diff"><div><span className="eyebrow">BEFORE</span><SampleTable rows={draftPreview.before_sample} /></div><div><span className="eyebrow">AFTER</span><SampleTable rows={draftPreview.after_sample} /></div></div>
      </> : selectedFinding ? <>
        <p className="clean-preview-summary">
          <strong>{selectedFinding.column}</strong> — {selectedFinding.detector_kind.replaceAll("_", " ")} (detector v{selectedFinding.detector_version})
          {selectedFinding.group_by_column ? <> · grouped by <strong>{selectedFinding.group_by_column} = {selectedFinding.group_value}</strong></> : null}
        </p>
        <p className="quiet-note" aria-live="polite">
          {selectedFinding.verified
            ? `Verified against all ${selectedFinding.total_rows.toLocaleString()} row(s) — ${selectedFinding.sampling_method === "full_scan" ? "a completed full scan" : "sample"}.`
            : `Provisional: sampled ${selectedFinding.rows_examined.toLocaleString()} of ${selectedFinding.total_rows.toLocaleString()} row(s). This is not yet a dataset-wide fact.`}
          {" "}{selectedFinding.missing_count.toLocaleString()} missing, {(selectedFinding.nonmatching_count ?? 0).toLocaleString()} nonmatching, and {selectedFinding.exception_count.toLocaleString()} exception row(s) out of {selectedFinding.rows_examined.toLocaleString()} examined. Nonmatching values are outside this detector's convention; exceptions are unusual values within its scope.
        </p>
        {selectedFinding.insufficient_evidence ? <p className="quiet-note">Not enough evidence to describe a convention here — examined values are too varied, or too few, to support one.</p> : null}
        {(selectedFinding.families ?? []).length ? <ul className="pattern-family-list" aria-label="Candidate format families">
          {(selectedFinding.families ?? []).map((family) => <li key={family.family_signature}>
            <label className="clean-inline-toggle">
              <input type="checkbox" checked={acceptedFamilies.has(family.family_signature)} onChange={() => setAcceptedFamilies((current) => { const next = new Set(current); if (next.has(family.family_signature)) next.delete(family.family_signature); else next.add(family.family_signature); return next; })} />
              <span><strong>{family.label}</strong> — {family.matching_count.toLocaleString()} of {selectedFinding.rows_examined.toLocaleString()} examined</span>
            </label>
            <small>e.g. {(family.example_values ?? []).length ? (family.example_values ?? []).join(", ") : "no examples captured"}</small>
            <button type="button" className="secondary" onClick={() => previewExtraction(family)}>Preview extraction for this family</button>
          </li>)}
        </ul> : <p className="quiet-note">No family met the minimum-evidence threshold (at least 2 matching rows).</p>}
        {selectedFinding.detector_kind === "numeric_unit" ? <button type="button" className="secondary" onClick={() => previewExtraction()}>Preview value/unit extraction</button> : null}
        <div className="clean-review-tabs" role="tablist" aria-label="Pattern exceptions"><button role="tab" aria-selected>Exceptions ({selectedFinding.exception_count.toLocaleString()})</button></div>
        {selectedFinding.exception_count ? <><p className="quiet-note">Showing {exceptionPage ? `${exceptionPage.offset + 1}–${exceptionPage.offset + (exceptionPage.rows ?? []).length}` : `1–${(selectedFinding.exception_examples ?? []).length}`} of {selectedFinding.exception_count.toLocaleString()} exception row(s).</p><div className="data-table-wrap" tabIndex={0}><table><thead><tr><th>Source row</th><th>Value</th></tr></thead><tbody>
          {exceptionPage ? (exceptionPage.rows ?? []).map((row) => <tr key={row.source_row}><td><code>{row.source_row}</code></td><td><code>{row.value}</code></td></tr>) : (selectedFinding.exception_examples ?? []).map((value, index) => <tr key={index}><td><code>{(selectedFinding.exception_source_rows ?? [])[index] ?? "—"}</code></td><td><code>{value}</code></td></tr>)}
        </tbody></table></div><div className="clean-table-toolbar"><button type="button" className="secondary" disabled={exceptionsLoading || !exceptionPage || exceptionPage.offset === 0} onClick={() => void loadExceptionPage(Math.max(0, (exceptionPage?.offset ?? 0) - 10))}>Previous exceptions</button><button type="button" className="secondary" disabled={exceptionsLoading || (exceptionPage ? exceptionPage.offset + (exceptionPage.rows ?? []).length >= exceptionPage.total : (selectedFinding.exception_examples ?? []).length >= selectedFinding.exception_count)} onClick={() => void loadExceptionPage(exceptionPage ? exceptionPage.offset + (exceptionPage.rows ?? []).length : (selectedFinding.exception_examples ?? []).length)}>{exceptionsLoading ? "Loading…" : "Next exceptions"}</button></div></> : <p className="quiet-note">No exceptions in the examined rows.</p>}
        <p className="quiet-note">Source revision {selectedFinding.source_revision} · fingerprint {selectedFinding.source_fingerprint.slice(0, 12)}…</p>
      </> : <>
        <p className="quiet-note">{selectedIssue ? "Select an issue to preview a proposed fix before applying it. Nothing is changed until you apply." : manualMode ? "Fill in the operation on the right and select Preview. Nothing is changed until you apply." : "This is the dataset as it stands at the current revision. Select an issue or start a manual operation to preview a fix. Nothing is changed until you apply."}</p>
        <div className="clean-table-toolbar">
          <span className="quiet-note">{rows ? `Rows ${rows.offset + 1}–${Math.min(rows.offset + rows.limit, rows.total_rows)} of ${rows.total_rows.toLocaleString()}` : "Loading rows…"}</span>
          <button className="secondary" disabled={!rows || rows.offset === 0} onClick={() => datasetId && rows && void loadRows(datasetId, Math.max(0, rows.offset - ROWS_PER_PAGE))}>Previous</button>
          <button className="secondary" disabled={!rows || rows.offset + rows.limit >= rows.total_rows} onClick={() => datasetId && rows && void loadRows(datasetId, rows.offset + ROWS_PER_PAGE)}>Next</button>
        </div>
        <SampleTable rows={rows?.rows ?? []} />
      </>}
    </div>
      {preview && pendingRequest ? <div className="clean-apply-bar"><span>Nothing changes until Apply. Review source revision {preview.source_revision ?? clean.dataset.revision} and the rows above.</span><button disabled={applying || !preview.review_token} onClick={() => void apply()}>{applying ? "Applying…" : "Apply reviewed change"}</button><button className="secondary" onClick={() => { previewRequestId.current += 1; setPreview(null); setPendingRequest(null); }}>Discard preview</button></div> : null}
    </section>
    <div className="clean-pane-separator is-recipe" role="separator" tabIndex={0} aria-label="Resize recipe panel" aria-orientation="vertical" aria-valuemin={270} aria-valuemax={440} aria-valuenow={recipePaneWidth ?? 340} onKeyDown={(event) => onPaneKeyDown("recipe", event)} onPointerDown={(event) => { resizingPane.current = "recipe"; event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={(event) => onPanePointerMove("recipe", event)} onPointerUp={(event) => { resizingPane.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { resizingPane.current = null; }} />
    <div className="clean-pane-separator is-inspector" role="separator" tabIndex={0} aria-label="Resize inspector panel" aria-orientation="vertical" aria-valuemin={270} aria-valuemax={440} aria-valuenow={inspectorPaneWidth ?? 320} onKeyDown={(event) => onPaneKeyDown("inspector", event)} onPointerDown={(event) => { resizingPane.current = "inspector"; event.currentTarget.setPointerCapture(event.pointerId); }} onPointerMove={(event) => onPanePointerMove("inspector", event)} onPointerUp={(event) => { resizingPane.current = null; event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { resizingPane.current = null; }} />
    <aside ref={inspectorPaneRef} className="inspector clean-inspector" aria-label="Selected issue and transformation inspector">
      <div className="clean-inspector-tabs" role="tablist" aria-label="Inspector view">
        <button type="button" role="tab" aria-selected={inspectorTab === "atlas"} className={inspectorTab === "atlas" ? "is-selected" : ""} onClick={() => setInspectorTab("atlas")}><AtlasCharacter pose={atlasPose} size="small" />Atlas</button>
        <button type="button" role="tab" aria-selected={inspectorTab === "settings"} className={inspectorTab === "settings" ? "is-selected" : ""} onClick={() => setInspectorTab("settings")}>Step settings</button>
      </div>
      {/* Both tabs stay mounted (hidden via the `hidden` attribute, not
          conditionally rendered) so switching tabs never discards Atlas's
          in-session conversation state or any Step-settings form state. */}
      <div id="clean-atlas-panel" role="tabpanel" aria-label="Atlas assistant" hidden={inspectorTab !== "atlas"}>
        <AtlasDockPanel
          datasetId={datasetId}
          datasetName={clean.dataset.source_name}
          revision={clean.dataset.revision}
          focusLabel={manualMode ? (manualSpec?.label ?? manualOperation.replaceAll("_", " ")) : selectedIssue ? (selectedIssue.column ?? "Dataset issue") : selectedFinding ? selectedFinding.column : "No step selected"}
          operation={manualMode ? manualOperation : null}
          column={manualMode ? manualColumn || null : selectedIssue?.column ?? selectedFinding?.column ?? null}
          parameters={(() => {
            const source = pendingRequest ?? (manualMode ? manualBuild.request : null);
            if (!source) return null;
            const excluded = new Set(["operation", "column", "review_token"]); // already sent as their own fields
            const entries = Object.entries(source).filter(([key, value]) => !excluded.has(key) && value !== undefined && value !== null);
            return entries.length ? Object.fromEntries(entries) : null;
          })()}
          onReview={(proposal) => {
            if (!proposal.clean_operation) return;
            setManualMode(true); setSelectedIssue(null); setEditingStepIndex(null); setInspectorTab("settings");
            pendingStepReason.current = proposal.explanation;
            // Loads the form fields AND the preview from the same request,
            // so Step settings shows exactly what Atlas proposed, not
            // whatever the form last held - fixing a real gap where the
            // preview matched the proposal but the editable fields didn't.
            loadRequestIntoForm(proposal.clean_operation);
            void previewOperation(proposal.clean_operation);
          }}
        />
      </div>
      <div hidden={inspectorTab !== "settings"}>
      {recipePreview ? <>
        <div className="inspector-heading"><div><span className="eyebrow">REVIEWED RECIPE</span><h2>Ready for your decision</h2></div></div>
        <p>Version {recipePreview.recipe_version} was reviewed against source revision {recipePreview.source_revision}. Apply the reviewed recipe in the recipe list, or discard its preview there. No data has changed.</p>
      </> : selectedFinding ? <>
        <div className="inspector-heading"><div><span className="eyebrow">PATTERN REVIEW</span><h2>{selectedFinding.column}</h2></div></div>
        {pendingRequest ? <>
          <p>Reviewing a proposed extraction. Nothing has changed yet.</p>
          <p className="quiet-note">Review the affected rows and exceptions, then use the actions below the review.</p>
        </> : <>
          <p>{selectedFinding.verified ? "Verified across every examined row." : "Based on a bounded sample — not yet a dataset-wide fact."} Accepting a family records a reviewed decision; it never changes data on its own.</p>
          <div className="inspector-actions">
            <button type="button" disabled={verifying} onClick={() => void verifyFinding()}>{verifying ? (verifyProgress ? `Verifying ${verifyProgress.checked.toLocaleString()} of ${verifyProgress.total.toLocaleString()}…` : "Verifying…") : "Verify all rows"}</button>
            {verifying ? <button type="button" className="secondary" onClick={cancelVerify}>Cancel</button> : null}
          </div>
          <label>Missing-value policy<select aria-label="Missing value policy" value={missingValuePolicy} onChange={(event) => setMissingValuePolicy(event.target.value as "allow" | "reject")}>
            <option value="allow">Allow missing values</option>
            <option value="reject">Missing counts as a violation</option>
          </select></label>
          <div className="inspector-actions">
            <button type="button" disabled={decisionBusy || acceptedFamilies.size === 0} onClick={() => void saveDecision("accept_family")}>Accept {acceptedFamilies.size > 0 ? `${acceptedFamilies.size} ` : ""}selected famil{acceptedFamilies.size === 1 ? "y" : "ies"}</button>
            <button type="button" className="secondary" disabled={decisionBusy} onClick={() => void saveDecision("ignore_revision")}>Ignore this revision</button>
            <button type="button" className="secondary" disabled={decisionBusy} onClick={() => void saveDecision("suppress_rule")}>Suppress this rule</button>
          </div>
          <label>Save as reusable rule<input aria-label="Pattern validation rule name" value={ruleNameForPattern} onChange={(event) => setRuleNameForPattern(event.target.value)} placeholder="e.g. Invoice ID format" /></label>
          <button type="button" className="secondary" disabled={decisionBusy || acceptedFamilies.size === 0} onClick={() => void savePatternValidationRule()}>Save selected families as a validation rule</button>
          {decisionError ? <p className="query-error" role="alert">{decisionError}</p> : null}
        </>}
        <div className="section-title"><span className="eyebrow">DECISIONS FOR THIS COLUMN</span></div>
        {patternDecisions.filter((entry) => entry.column === selectedFinding.column).length ? <ul className="clean-recipe-list">
          {patternDecisions.filter((entry) => entry.column === selectedFinding.column).map((entry) => <li key={entry.decision_id}>
            <div><strong>{entry.decision.replaceAll("_", " ")}</strong><small>{entry.revoked ? "revoked" : "active"} · {new Date(entry.created_at).toLocaleString()}{(entry.family_signatures ?? []).length ? ` · ${(entry.family_signatures ?? []).join(", ")}` : ""}</small></div>
            {!entry.revoked ? <button type="button" className="secondary" disabled={decisionBusy} onClick={() => void saveDecision("ignore_revision", { revokesDecisionId: entry.decision_id })}>Revoke</button> : null}
          </li>)}
        </ul> : <p className="quiet-note">No decisions recorded yet for this column.</p>}
      </> : selectedIssue ? <>
        <div className="inspector-heading"><div><span className="eyebrow">SELECTED ISSUE</span><h2>{selectedIssue.column ?? "Dataset"}</h2></div></div>
        <p>{selectedIssue.description}</p>
        {atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}
        {pendingRequest ? <p className="quiet-note">Review the affected rows and exceptions, then use the actions below the review.</p> : <p className="quiet-note">Atlas proposes a fix automatically when a safe deterministic one exists; otherwise this needs analyst judgment.</p>}
      </> : manualMode ? <>
        <div className="inspector-heading"><div><span className="eyebrow">{manualStepNumber ? `STEP ${manualStepNumber}` : "NEW STEP · UNSAVED"}</span><h2>{manualSpec?.label ?? manualOperation.replaceAll("_", " ")}</h2></div></div>
        <div className="clean-manual-form clean-step-form">
        <label>Operation<select aria-label="Operation" value={manualOperation} onChange={(event) => { invalidateManualPreview(); setManualOperation(event.target.value as CleanOperation); }}>{OPERATIONS.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
        {manualSpec?.help ? <p className="clean-field-help">{manualSpec.help}</p> : null}
        {manualSpec?.needsColumn ? <label>Column{(() => { const type = profile?.columns?.find((c) => c.name === manualColumn)?.semantic_type; return type ? ` · ${manualColumn} (${type})` : ""; })()}
          <input aria-label="Column" list="clean-column-options" value={manualColumn} onChange={(event) => { invalidateManualPreview(); setManualColumn(event.target.value); }} placeholder="Search columns…" />
          <datalist id="clean-column-options">{(profile?.columns ?? []).map((column) => <option key={column.name} value={column.name} />)}</datalist>
        </label> : null}
        {manualOperation === "rename_column" ? <label>New name<input aria-label="New column name" value={manualNewName} onChange={(event) => { invalidateManualPreview(); setManualNewName(event.target.value); }} /></label> : null}
        {manualOperation === "convert_type" ? <>
          <label>Target type<select aria-label="Target type" value={manualTargetType} onChange={(event) => { invalidateManualPreview(); setManualTargetType(event.target.value as typeof manualTargetType); }}><option value="numeric">numeric</option><option value="text">text</option><option value="datetime">datetime</option><option value="boolean">boolean</option></select></label>
          {manualTargetType === "datetime" ? <label>Date format (optional)<input aria-label="Date format" value={manualDateFormat} onChange={(event) => { invalidateManualPreview(); setManualDateFormat(event.target.value); }} placeholder="e.g. %d/%m/%Y — leave blank to auto-detect" /></label> : null}
          {manualTargetType === "numeric" ? <label>Number locale<select aria-label="Number locale" value={manualNumberLocale} onChange={(event) => { invalidateManualPreview(); setManualNumberLocale(event.target.value as typeof manualNumberLocale); }}><option value="standard">standard (1,234.56)</option><option value="european">european (1.234,56)</option></select></label> : null}
        </> : null}
        {manualOperation === "fill_missing" ? <>
          <label>Fill strategy<select aria-label="Fill strategy" value={manualFillStrategy} onChange={(event) => { invalidateManualPreview(); setManualFillStrategy(event.target.value as FillStrategy); }}><option value="mean">mean</option><option value="median">median</option><option value="mode">mode</option><option value="constant">constant</option><option value="forward_fill">forward fill</option></select></label>
          {manualFillStrategy === "constant" ? <label>Constant value<input aria-label="Constant fill value" value={manualFillValue} onChange={(event) => { invalidateManualPreview(); setManualFillValue(event.target.value); }} /></label> : null}
        </> : null}
        {manualOperation === "normalize_case" ? <label>Case<select aria-label="Case" value={manualCase} onChange={(event) => { invalidateManualPreview(); setManualCase(event.target.value as typeof manualCase); }}><option value="lower">lower</option><option value="upper">upper</option><option value="title">title</option></select></label> : null}
        {manualOperation === "category_mapping" ? <div className="clean-parameters">
          <span className="eyebrow">Parameters</span>
          <label className="clean-switch-row"><span>Case sensitive</span><input type="checkbox" role="switch" aria-checked={categoryCaseSensitive} checked={categoryCaseSensitive} onChange={(event) => { invalidateManualPreview(); setCategoryCaseSensitive(event.target.checked); }} /></label>
          <label className="clean-switch-row"><span>Preserve unmatched values</span><input type="checkbox" role="switch" aria-checked={categoryPreserveUnmatched} checked={categoryPreserveUnmatched} onChange={(event) => { invalidateManualPreview(); setCategoryPreserveUnmatched(event.target.checked); }} /></label>
          {Object.keys(categoryMapping).length ? <p className="clean-field-help">{Object.keys(categoryMapping).length} source value{Object.keys(categoryMapping).length === 1 ? "" : "s"} mapped. Edit the mapping in the centre panel.</p> : <p className="clean-field-help">Select and map source values in the centre panel.</p>}
        </div> : null}
        {manualOperation === "deduplicate_survivorship" ? <>
          <label>Survivorship rule<select aria-label="Survivorship rule" value={survivorshipRule} onChange={(event) => { invalidateManualPreview(); setSurvivorshipRule(event.target.value as typeof survivorshipRule); }}>{SURVIVORSHIP_RULES.map((item) => <option key={item.value} value={item.value}>{item.label}</option>)}</select></label>
          {survivorshipRule === "max_by_column" ? <label>Highest-value column<input aria-label="Tiebreak column" list="clean-column-options" value={survivorshipTiebreak} onChange={(event) => { invalidateManualPreview(); setSurvivorshipTiebreak(event.target.value); }} placeholder="Search columns…" /></label> : null}
          <p className="clean-field-help">{survivorshipColumns.size ? `${survivorshipColumns.size} grouping column${survivorshipColumns.size === 1 ? "" : "s"} selected.` : "Choose grouping columns in the centre panel."} Edit in the centre panel.</p>
        </> : null}
        <button className="secondary" disabled={!manualBuild.request} title={manualBuild.reason ?? undefined} onClick={() => manualBuild.request && void previewOperation(manualBuild.request)}>{preview || manualPreviewStale ? "Recompute preview" : "Preview"}</button>
        {preview ? <p className="quiet-note is-good">Preview is up to date with revision {clean.dataset.revision}.</p> : manualPreviewStale ? <p className="quiet-note is-amber">Preview is stale — recompute before applying.</p> : null}
        {manualBuild.reason ? <p className="quiet-note">{manualBuild.reason}</p> : null}
      </div>

      {preview && pendingRequest ? (() => {
        const affected = preview.changed_rows_total ?? preview.affected_rows;
        const exceptions = preview.exception_rows_total ?? 0;
        const preservesUnmatched = pendingRequest.operation === "category_mapping" && pendingRequest.preserve_unmatched !== false;
        return <>
          <div className="clean-inspector-impact">
            <span className="eyebrow">Impact in this revision</span>
            <div><strong>{affected.toLocaleString()}</strong><span>affected row{affected === 1 ? "" : "s"}</span></div>
            {exceptions > 0 ? <div><strong className="is-amber">{exceptions.toLocaleString()}</strong><span>{preservesUnmatched ? "unmatched" : "exception"} row{exceptions === 1 ? "" : "s"}</span></div> : null}
          </div>
          <div className="clean-review-card">
            <strong>{exceptions > 0 ? preservesUnmatched ? "Unmatched values preserved" : "Inspect exceptions" : "Ready to apply"}</strong>
            <p>{exceptions > 0 ? preservesUnmatched ? `${exceptions.toLocaleString()} unmatched row${exceptions === 1 ? " stays" : "s stay"} unchanged. Inspect them to confirm this is intended.` : `${exceptions.toLocaleString()} exception row${exceptions === 1 ? "" : "s"} to inspect before applying.` : "Nothing further to resolve for this preview."}</p>
            {exceptions > 0 ? <button type="button" className="secondary" onClick={() => setReviewRowsView("exceptions")}><Icon name="alert" className="clean-action-icon" />Inspect exceptions</button> : null}
          </div>
          <div className="clean-preview-checks" aria-label="Preview checks">
            <span className="eyebrow">PREVIEW CHECKS</span>
            <p><span className={preview.source_revision === clean.dataset.revision ? "is-good" : "is-amber"}>●</span> Source revision {preview.source_revision} {preview.source_revision === clean.dataset.revision ? "is current" : "changed — preview again"}</p>
            <p><span className={preview.review_token && !manualPreviewStale ? "is-good" : "is-amber"}>●</span> {preview.review_token && !manualPreviewStale ? "Reviewed parameters have a one-use token" : "Parameters need a fresh preview"}</p>
            <p><span className={exceptions ? "is-amber" : "is-good"}>●</span> {exceptions ? `${exceptions.toLocaleString()} ${preservesUnmatched ? "unmatched" : "exception"} row${exceptions === 1 ? "" : "s"} to inspect` : "No exception rows in this preview"}</p>
            {preview.warnings?.length ? <p><span className="is-amber">●</span> {preview.warnings.length} warning{preview.warnings.length === 1 ? "" : "s"} in the review</p> : null}
          </div>
        </>;
      })() : null}
      <div className="clean-manual-form">
        <button className="secondary" disabled={!manualBuild.request} onClick={() => manualBuild.request && (editingStepIndex === null ? addDraftStep(manualBuild.request) : updateDraftStep(manualBuild.request))}>{manualStepNumber ? `Update step ${manualStepNumber}` : "Add step to draft"}</button>
        {pendingRequest ? <p className="quiet-note">Review the affected rows and exceptions, then use the actions below the review.</p> : <p className="quiet-note">Preview this operation before it can be applied.</p>}
      </div>
      </> : <p className="quiet-note">Select an issue from the navigator, or start a manual operation, to inspect it and preview a fix.</p>}
      {error ? <p className="query-error" role="alert">{error}</p> : null}
      {(() => {
        const previewPending = Boolean(preview && pendingRequest);
        const blockedReason = previewPending ? "Apply or discard this preview first." : null;
        return <div className="inspector-actions clean-next-workspace"><span className="eyebrow">NEXT WORKSPACE</span>
          <button type="button" className="clean-handoff-row secondary" disabled={previewPending} title={blockedReason ?? undefined} onClick={() => onOpenWorkflow("sql-lab")}>
            <Icon name="database" className="clean-handoff-icon" />
            <span className="clean-handoff-copy"><strong>Use this revision in SQL Lab</strong><small>{blockedReason ?? "Query this revision directly."}</small></span>
            <Icon name="arrow" className="clean-handoff-chevron" />
          </button>
          <button type="button" className="clean-handoff-row secondary" disabled={previewPending} title={blockedReason ?? undefined} onClick={() => onOpenWorkflow("visualize")}>
            <Icon name="layers" className="clean-handoff-icon" />
            <span className="clean-handoff-copy"><strong>Visualize this revision</strong><small>{blockedReason ?? "Chart this revision's data."}</small></span>
            <Icon name="arrow" className="clean-handoff-chevron" />
          </button>
        </div>;
      })()}
      <div className="inspector-actions clean-report-context"><span className="eyebrow">REPORT CONTEXT</span>
        <p className="quiet-note">No report linked.</p>
        <button type="button" className="clean-handoff-row secondary" onClick={() => onOpenWorkflow("reports")}>
          <Icon name="panel" className="clean-handoff-icon" />
          <span className="clean-handoff-copy"><strong>Open Reports</strong><small>Link this transformation to a saved report.</small></span>
          <Icon name="arrow" className="clean-handoff-chevron" />
        </button>
      </div>
      </div>
    </aside>
  </article>;
}

function SampleTable({ rows }: { rows: readonly Record<string, unknown>[] }) {
  if (!rows.length) return <p className="quiet-note">No rows.</p>;
  const columns = Object.keys(rows[0] ?? {});
  return <div className="data-table-wrap" tabIndex={0}><table><thead><tr>{columns.map((key) => <th key={key}>{key}</th>)}</tr></thead><tbody>{rows.map((row, index) => <tr key={index}>{columns.map((key) => <td key={key}>{row[key] === null || row[key] === undefined ? "—" : String(row[key])}</td>)}</tr>)}</tbody></table></div>;
}

const ROW_STATUS_TONE: Record<CleanRowInspection["status"], "good" | "warn" | "risk"> = { changed: "good", removed: "warn", unresolved: "risk", newly_missing: "risk" };

function InspectionTable({ rows, total, preservedUnmatched = false }: { rows: readonly CleanRowInspection[]; total: number; preservedUnmatched?: boolean }) {
  if (!total) return <p className="quiet-note">No rows in this view.</p>;
  const columns = Array.from(new Set(rows.flatMap((row) => [...Object.keys(row.before), ...Object.keys(row.after ?? {})])));
  return <><p className="quiet-note">Showing {rows.length.toLocaleString()} of {total.toLocaleString()} source row(s){total > rows.length ? " (inspection sample limited to 100)" : ""}.</p><div className="data-table-wrap" tabIndex={0}><table className="clean-inspection-grid"><thead><tr><th>Source row</th><th>Status</th>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.map((row) => <tr key={row.source_row}><td><code>{row.source_row}</code></td><td><span className={`health-pill ${preservedUnmatched && row.status === "unresolved" ? "info" : ROW_STATUS_TONE[row.status]}`}>{preservedUnmatched && row.status === "unresolved" ? "preserved" : row.status.replaceAll("_", " ")}</span></td>{columns.map((column) => {
    const before = row.before[column]; const after = row.after?.[column];
    return <td key={column} className={String(before ?? "") !== String(after ?? "") ? "is-changed" : undefined}><code className="clean-cell-before">{before == null ? "—" : String(before)}</code>{row.after && String(before ?? "") !== String(after ?? "") ? <code className="clean-cell-after">→ {after == null ? "—" : String(after)}</code> : null}</td>;
  })}</tr>)}</tbody></table></div></>;
}
