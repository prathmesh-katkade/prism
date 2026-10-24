"use client";

/**
 * The approved "review Atlas's cleaning plan" surface (reference #03): every
 * draft step the analyst has built up in Clean - whether added manually or
 * handed off from an Atlas proposal - presented together with a real reason,
 * a real example, and an explicit include/exclude decision, ending in one
 * explicit approval. This never invents a multi-step plan Atlas itself never
 * proposed: the "plan" is exactly the same `draftSteps` Clean's recipe pane
 * already builds and already runs through `recipe-draft/preview` for real,
 * per-step impacts - this screen is a different, fuller presentation of
 * that same real state, not a new capability layered on top of it.
 */
import React from "react";
import type { CleanRecipeStep, CleanTransformationRequest, OverviewColumn } from "@prism/api-contracts";
import { OPERATIONS } from "./clean-workspace";
import { AtlasCharacter } from "./atlas-character";

/** The one structural condition PRISM's own backend already treats as
 * requiring an analyst decision before it can run (see clean.py's date-
 * ambiguity check) - mirrored here, not reinvented, so this screen never
 * lets a genuinely ambiguous date parse slip through as "ready". */
export function needsClarification(request: CleanTransformationRequest): boolean {
  return request.operation === "convert_type" && request.target_type === "datetime" && !request.date_format?.trim();
}

function stepExample(request: CleanTransformationRequest): string | null {
  switch (request.operation) {
    case "category_mapping": {
      const entries = Object.entries(request.category_mapping ?? {});
      if (!entries.length) return null;
      return entries.slice(0, 2).map(([source, target]) => `"${source}" → "${target}"`).join("; ") + (entries.length > 2 ? ` (+${entries.length - 2} more)` : "");
    }
    case "rename_column": return request.new_name ? `"${request.column}" → "${request.new_name}"` : null;
    case "convert_type": return `${request.column} → ${request.target_type}${request.date_format ? ` (${request.date_format})` : ""}`;
    case "fill_missing": return `${request.column}: fill with ${request.fill_strategy}${request.fill_strategy === "constant" && request.fill_value ? ` "${request.fill_value}"` : ""}`;
    case "normalize_case": return `${request.column} → ${request.case} case`;
    case "trim_whitespace": return `Remove leading/trailing whitespace from ${request.column}`;
    case "drop_column": return `Remove column ${request.column}`;
    case "drop_missing_rows": return `Remove rows missing ${request.column}`;
    case "deduplicate_survivorship": return request.group_by_columns?.length ? `Group by ${request.group_by_columns.join(", ")}, ${request.survivorship_rule?.replaceAll("_", " ")}` : null;
    case "drop_duplicates": return "Remove exact duplicate rows";
    default: return null;
  }
}

export interface PlanReviewStep {
  step: CleanRecipeStep;
  index: number;
  affectedRows: number | null;
  reason: string | null;
}

export function PlanReviewScreen({
  steps, datasetName, revision, rowCount, columnCount, columns, onToggleStep, onInspectStep, onApprove, onClose, approving, approveError,
}: {
  steps: readonly PlanReviewStep[];
  datasetName: string;
  revision: number;
  rowCount: number;
  columnCount: number;
  columns: readonly OverviewColumn[];
  onToggleStep(index: number): void;
  onInspectStep(index: number): void;
  onApprove(): void;
  onClose(): void;
  approving: boolean;
  approveError: string | null;
}) {
  const decided = steps.map((entry) => ({ ...entry, blocked: needsClarification(entry.step.request) }));
  const included = decided.filter((entry) => entry.step.enabled && !entry.blocked);
  const needsInput = decided.filter((entry) => entry.blocked);
  const excluded = decided.filter((entry) => !entry.step.enabled && !entry.blocked);
  const touchedColumns = new Set<string>();
  for (const entry of included) {
    const request = entry.step.request;
    if (request.column) touchedColumns.add(request.column);
    for (const column of request.group_by_columns ?? []) touchedColumns.add(column);
  }
  const unchangedColumns = columns.filter((column) => !touchedColumns.has(column.name));

  return <article className="plan-review" aria-label="Review Atlas's cleaning plan">
    <header className="plan-review-header">
      <div><span className="eyebrow">CLEAN · PLAN REVIEW</span><h1>Review Atlas&apos;s cleaning plan</h1><p>{datasetName} · Pinned to revision {revision} · No changes applied</p></div>
      <button type="button" className="secondary" onClick={onClose}>Back to preview</button>
    </header>
    <div className="plan-review-body">
      <aside className="plan-review-rail" aria-label="Cleaning plan progress">
        <ol>
          <li className="is-complete"><span>1</span><div><strong>Inspect data</strong><small>{rowCount.toLocaleString()} rows · {columnCount} columns</small></div></li>
          <li className={steps.length ? "is-complete" : ""}><span>2</span><div><strong>Draft recipe</strong><small>{steps.length} step{steps.length === 1 ? "" : "s"} prepared for review</small></div></li>
          <li className="is-current" aria-current="step"><span>3</span><div><strong>Review decisions</strong><small>{included.length} included · {excluded.length + needsInput.length} excluded</small></div></li>
          <li><span>4</span><div><strong>Apply changes</strong><small>Pending explicit approval</small></div></li>
        </ol>
        <div className="plan-review-context"><span className="eyebrow">Context</span><p>{datasetName}</p><small>Revision {revision} · {rowCount.toLocaleString()} source rows</small></div>
      </aside>
      <ol className="plan-review-steps">
        {decided.map((entry) => {
          const spec = OPERATIONS.find((item) => item.value === entry.step.request.operation);
          const example = stepExample(entry.step.request);
          const isModelProposed = Boolean(entry.reason);
          return <li key={entry.step.step_id} className={entry.blocked ? "is-blocked" : entry.step.enabled ? "is-included" : "is-excluded"}>
            <div className="plan-step-head">
              <div className="plan-step-identity">
                <span className="plan-step-number">{entry.index + 1}</span>
                <h2>{spec?.label ?? entry.step.request.operation.replaceAll("_", " ")}</h2>
              </div>
              <div className="plan-step-tags">
                <span className={`health-pill ${isModelProposed ? "info" : ""}`}>{isModelProposed ? "Model proposal" : "Deterministic rule"}</span>
                {entry.affectedRows !== null ? <span className="health-pill good">Preview checked</span> : null}
                {entry.blocked ? <span className="health-pill risk">Needs clarification</span> : null}
              </div>
              <label className="clean-switch-row plan-step-include">
                <span>Include</span>
                <input type="checkbox" role="switch" aria-checked={entry.step.enabled && !entry.blocked} checked={entry.step.enabled && !entry.blocked} disabled={entry.blocked} onChange={() => onToggleStep(entry.index)} />
              </label>
            </div>
            <div className="plan-step-grid">
              <div>
                <span className="eyebrow">Why this step?</span>
                <p>{entry.reason ?? spec?.help ?? "Deterministic operation."}</p>
              </div>
              <div>
                <span className="eyebrow">Example</span>
                {example ? <code className="plan-step-example">{example}</code> : <p className="quiet-note">No example available for this operation.</p>}
              </div>
            </div>
            <div className="plan-step-foot">
              <span className="quiet-note">{entry.affectedRows !== null ? `${entry.affectedRows.toLocaleString()} row(s) affected` : "Recompute the draft preview to see impact"}</span>
              <button type="button" className="secondary" onClick={() => onInspectStep(entry.index)}>Inspect rows</button>
            </div>
            {entry.blocked ? <p className="plan-step-blocked-note" role="alert">Excluded until you decide. Ask Atlas for the date order, then this step can be included.</p> : null}
          </li>;
        })}
        {!decided.length ? <p className="quiet-note">No draft steps yet. Add a step in Clean, or hand off an Atlas proposal, before reviewing a plan.</p> : null}
      </ol>
      <aside className="plan-review-side">
        <div className="plan-review-atlas"><AtlasCharacter pose="presenting" size="large" /><p>Here&apos;s the cleaning plan built so far. Review each step and decide what to include.</p></div>
        <div className="plan-review-progress">
          <span className="eyebrow">Plan review</span>
          <div className="plan-review-bar"><span style={{ flex: Math.max(included.length, 0.001) }} className="is-ready" /><span style={{ flex: Math.max(excluded.length, 0.001) }} className="is-excluded" /><span style={{ flex: Math.max(needsInput.length, 0.001) }} className="is-needs-input" /></div>
          <div className="plan-review-counts"><div><strong className="is-good">{included.length}</strong><span>ready</span></div><div><strong>{excluded.length}</strong><span>excluded</span></div><div><strong className="is-amber">{needsInput.length}</strong><span>needs input</span></div></div>
        </div>
        <div className="plan-review-unchanged">
          <span className="eyebrow">What will stay unchanged</span>
          <ul>
            {unchangedColumns.slice(0, 4).map((column) => <li key={column.name}>{column.name} <small>(no changes)</small></li>)}
            {unchangedColumns.length > 4 ? <li><small>+{unchangedColumns.length - 4} more column(s)</small></li> : null}
            <li>Source revision <small>{revision} ({rowCount.toLocaleString()} rows · {columnCount} columns)</small></li>
          </ul>
        </div>
        <div className="plan-review-boundary">
          <span className="eyebrow">Review boundary</span>
          <p>Only included steps will be applied. A new dataset revision will be created.</p>
        </div>
      </aside>
    </div>
    {approveError ? <p className="query-error" role="alert">{approveError}</p> : null}
    <footer className="plan-review-footer">
      <span className="quiet-note">{included.length} included step{included.length === 1 ? "" : "s"} · {excluded.length + needsInput.length} excluded · Revision {revision}</span>
      <button type="button" className="secondary" onClick={onClose}>Back to preview</button>
      <button type="button" disabled={!included.length || approving} onClick={onApprove}>{approving ? "Applying…" : "Approve included steps"}</button>
    </footer>
  </article>;
}
