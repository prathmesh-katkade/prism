"use client";

/**
 * Atlas docked inside Clean: the real `/api/v1/workspace-proposals` local-
 * model flow (the same one `WorkspaceProposalPanel` already exposes, reused
 * at the same contract rather than forked into a second mocked endpoint),
 * presented as a short-lived, per-dataset conversation with the character,
 * real dataset/step context chips, and starter questions that pre-fill the
 * same free-text intent - not a separate, fabricated capability.
 *
 * Conversation state (`turns`) is owned here and lives for as long as this
 * component stays mounted. The parent keeps it mounted (hidden, not
 * unmounted) while the Atlas/Step-settings tab is inactive specifically so
 * switching tabs never discards it - see clean-workspace.tsx.
 *
 * Persistence: each dataset's conversation is mirrored to this browser's
 * localStorage (`atlas-dock:<dataset_id>`), so it survives a page reload
 * or an app restart - real resumable state, not just in-memory. This is a
 * deliberately smaller, safer choice than backend persistence, investigated
 * rather than assumed: the only backend durable store available
 * (`AnalyticalObject` / `ObjectKind.CLEANING_PLAN`) already means "applied
 * transformation" to every existing lineage consumer, and adding a new
 * ObjectKind is a shared-schema change (rippling through the generated
 * TypeScript contract and every consumer) too large for this pass - see
 * docs/clean-atlas-v1/phase-3 status for the full account. localStorage is
 * per-browser-profile, not cross-device - named honestly, not hidden. A
 * turn that was still "pending" when the page closed cannot have survived
 * (its in-flight request is gone with the old page); it's restored as
 * "interrupted" rather than silently re-shown as if still loading.
 */
import { useEffect, useRef, useState } from "react";
import type { CleanPreviewResponse, CleanTransformationRequest, WorkspaceProposalResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { AtlasCharacter, type AtlasPose } from "./atlas-character";

const STARTER_QUESTIONS = ["What should I review first?", "Explain the current step", "Suggest a cleanup for this column"];
const HISTORY_LIMIT = 3;
const STORED_TURNS_LIMIT = 20;

type Turn = {
  id: string;
  intent: string;
  revision: number;
  status: "pending" | "done" | "error" | "cancelled" | "interrupted";
  response?: WorkspaceProposalResponse;
  error?: string;
  selectedChoice?: string;
};

const TURN_STATUSES = new Set(["pending", "done", "error", "cancelled", "interrupted"]);

function storageKey(datasetId: string): string { return `atlas-dock:${datasetId}`; }

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function validStoredResponse(value: unknown): value is WorkspaceProposalResponse {
  if (!isRecord(value) || !["ollama", "unavailable"].includes(String(value.provider)) || typeof value.explanation !== "string") return false;
  if (value.evidence !== undefined && (!Array.isArray(value.evidence) || !value.evidence.every((item) => typeof item === "string"))) return false;
  if (value.clean_operation !== undefined && (!isRecord(value.clean_operation) || typeof value.clean_operation.operation !== "string")) return false;
  if (value.clean_preview !== undefined) {
    const preview = value.clean_preview;
    if (!isRecord(preview) || typeof preview.operation !== "string" || !Number.isFinite(preview.affected_rows) || (preview.affected_rows as number) < 0
      || (preview.changed_rows_total !== undefined && (!Number.isFinite(preview.changed_rows_total) || (preview.changed_rows_total as number) < 0))
      || (preview.exception_rows_total !== undefined && (!Number.isFinite(preview.exception_rows_total) || (preview.exception_rows_total as number) < 0))
      || (preview.unresolved_values !== undefined && (!Array.isArray(preview.unresolved_values) || !preview.unresolved_values.every((item) => typeof item === "string")))) return false;
    if (preview.warnings !== undefined && (!Array.isArray(preview.warnings) || !preview.warnings.every((item) => typeof item === "string"))) return false;
  }
  if (value.clarification !== undefined && value.clarification !== null) {
    const clarification = value.clarification;
    if (!isRecord(clarification) || typeof clarification.question !== "string" || (clarification.column !== undefined && typeof clarification.column !== "string") || !Array.isArray(clarification.choices)
      || clarification.choices.length < 2 || clarification.choices.length > 6
      || !clarification.choices.every((choice) => isRecord(choice) && typeof choice.label === "string" && isRecord(choice.parameters)
        && ["%d/%m/%Y", "%m/%d/%Y"].includes(String(choice.parameters.date_format))
        && Object.keys(choice.parameters).every((key) => key === "date_format"))) return false;
  }
  return true;
}

/** A corrupt or unsupported entry (hand-edited localStorage, a future or
 * older app version's shape, truncated JSON that still parsed) must be
 * dropped, not rendered or crash the conversation - every field this
 * component actually reads is checked, not just that something parsed. */
function isValidTurn(value: unknown): value is Turn {
  if (typeof value !== "object" || value === null) return false;
  const turn = value as Record<string, unknown>;
  return typeof turn.id === "string" && turn.id.length > 0
    && typeof turn.intent === "string"
    && Number.isInteger(turn.revision) && (turn.revision as number) >= 0
    && typeof turn.status === "string" && TURN_STATUSES.has(turn.status)
    && (turn.status !== "done" || validStoredResponse(turn.response))
    && (turn.response === undefined || validStoredResponse(turn.response))
    && (turn.error === undefined || typeof turn.error === "string")
    && (turn.selectedChoice === undefined || (typeof turn.selectedChoice === "string" && isRecord(turn.response)
      && isRecord(turn.response.clarification) && Array.isArray(turn.response.clarification.choices)
      && turn.response.clarification.choices.some((choice: unknown) => isRecord(choice) && choice.label === turn.selectedChoice)));
}

function loadStoredTurns(datasetId: string): Turn[] {
  try {
    const raw = window.localStorage.getItem(storageKey(datasetId));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(isValidTurn).map((turn) =>
      // A pending request's connection is gone with the page that made it -
      // restore it as interrupted, never as still (falsely) in progress.
      turn.status === "pending" ? { ...turn, status: "interrupted" as const } : turn);
  } catch { return []; }
}

/** Returns false when persistence could not be guaranteed (storage
 * unavailable, full, or disabled) so the caller can make that visible
 * rather than silently keep working as if the conversation would survive
 * a reload. */
function saveStoredTurns(datasetId: string, turns: Turn[]): boolean {
  try { window.localStorage.setItem(storageKey(datasetId), JSON.stringify(turns.slice(-STORED_TURNS_LIMIT))); return true; }
  catch { return false; }
}

export function AtlasDockPanel({
  datasetId, datasetName, revision, focusLabel, operation, column, parameters, onReview,
}: {
  datasetId: string | undefined;
  datasetName: string;
  revision: number;
  focusLabel: string;
  operation: string | null;
  column: string | null;
  /** The actual parameters of the operation currently selected for review
   * (e.g. a category_mapping's values, a fill_missing's strategy) - without
   * this, Atlas only ever knows an operation's name and column, not what it
   * would actually do, so it can't explain the real proposed change. */
  parameters: Record<string, unknown> | null;
  onReview(proposal: WorkspaceProposalResponse): void;
}) {
  const [intent, setIntent] = useState("");
  const [turns, setTurns] = useState<Turn[]>(() => (typeof window !== "undefined" && datasetId ? loadStoredTurns(datasetId) : []));
  const [persistenceFailed, setPersistenceFailed] = useState(false);
  const [clarifyingTurnId, setClarifyingTurnId] = useState<string | null>(null);
  const [clarificationError, setClarificationError] = useState<{ turnId: string; message: string } | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const clarificationAbortRef = useRef<AbortController | null>(null);
  const clarificationRequestId = useRef(0);
  const revisionRef = useRef(revision);
  revisionRef.current = revision;
  const pending = turns.find((turn) => turn.status === "pending");

  // A conversation is about one dataset. Loading a different dataset
  // restores *that* dataset's own stored conversation (if any), rather
  // than either keeping the previous dataset's turns or discarding real,
  // persisted history just because the component didn't happen to mount
  // fresh on it.
  const datasetRef = useRef(datasetId);
  // The save effect below runs in the SAME effects pass as this one, in
  // declaration order, whenever datasetId changes - but `turns` in that
  // pass is still the OUTGOING dataset's turns (setTurns here only takes
  // effect on the next render). Without this guard, that one pass would
  // call saveStoredTurns(newDatasetId, oldDatasetsTurns) and overwrite the
  // new dataset's own stored conversation with the old one's.
  const skipNextSaveRef = useRef(false);
  useEffect(() => {
    if (datasetRef.current !== datasetId) {
      datasetRef.current = datasetId;
      skipNextSaveRef.current = true;
      setTurns(datasetId ? loadStoredTurns(datasetId) : []);
      abortRef.current?.abort();
      clarificationAbortRef.current?.abort();
      clarificationRequestId.current += 1;
      setClarifyingTurnId(null);
      setClarificationError(null);
    }
  }, [datasetId]);

  useEffect(() => {
    clarificationAbortRef.current?.abort();
    clarificationRequestId.current += 1;
    setClarifyingTurnId(null);
    setClarificationError(null);
  }, [revision]);

  // Mirror every change to this dataset's own storage slot - the actual
  // persistence; the effect above only ever reads it.
  useEffect(() => {
    if (skipNextSaveRef.current) { skipNextSaveRef.current = false; return; }
    if (datasetId) setPersistenceFailed(!saveStoredTurns(datasetId, turns));
  }, [datasetId, turns]);

  const dockPose: AtlasPose = pending ? "working" : turns.length ? "presenting" : intent.trim() ? "idle" : "waiting";

  async function ask(text: string) {
    if (!datasetId || text.trim().length < 3 || pending) return;
    const id = `turn_${Date.now()}_${turns.length}`;
    const askedAtRevision = revision;
    // A bounded slice of this same conversation's own prior turns - real
    // context for a follow-up question, never a transcript sent anywhere
    // else or retained past this one request. A turn asked about a revision
    // that no longer exists is excluded entirely, not sent as if its
    // explanation were still a current fact about this dataset - the same
    // staleness this component already marks visually for the analyst.
    const history = turns
      .filter((turn) => turn.status === "done" && turn.response && turn.revision === askedAtRevision)
      .slice(-HISTORY_LIMIT)
      .map((turn) => ({ intent: turn.intent, explanation: turn.response!.explanation }));
    setTurns((current) => [...current, { id, intent: text.trim(), revision: askedAtRevision, status: "pending" }]);
    setIntent("");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await fetch(apiUrl("/api/v1/workspace-proposals"), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({
          kind: "clean", dataset_id: datasetId, intent: text.trim(),
          expected_revision: askedAtRevision,
          ...(operation ? { selected_operation: operation } : {}),
          ...(column ? { selected_column: column } : {}),
          ...(operation && parameters && Object.keys(parameters).length ? { selected_parameters: parameters } : {}),
          ...(history.length ? { history } : {}),
        }),
        signal: controller.signal,
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Proposal request failed.");
      const body = await response.json() as WorkspaceProposalResponse;
      setTurns((current) => current.map((turn) => turn.id === id ? { ...turn, status: "done", response: body } : turn));
    } catch (reason) {
      if (reason instanceof DOMException && reason.name === "AbortError") {
        setTurns((current) => current.map((turn) => turn.id === id ? { ...turn, status: "cancelled" } : turn));
        return;
      }
      const message = reason instanceof Error ? reason.message : "The proposal is unavailable. Manual controls remain available.";
      setTurns((current) => current.map((turn) => turn.id === id ? { ...turn, status: "error", error: message } : turn));
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  function cancel() { abortRef.current?.abort(); }

  async function chooseClarification(turn: Turn, choiceIndex: number) {
    const response = turn.response;
    const choice = response?.clarification?.choices[choiceIndex];
    const operation = response?.clean_operation;
    if (!datasetId || !choice || !operation || turn.revision !== revision || clarifyingTurnId) return;
    // Clarifications come from the server's bounded date ambiguity rule.
    // Keep the client equally narrow: no arbitrary response parameters are
    // accepted as mutation authority, and every choice merely re-previews.
    const format = choice.parameters?.date_format;
    if (operation.operation !== "convert_type" || operation.target_type !== "datetime"
      || operation.column !== response?.clarification?.column
      || !["%d/%m/%Y", "%m/%d/%Y"].includes(String(format))
      || Object.keys(choice.parameters ?? {}).some((key) => key !== "date_format")) {
      setClarificationError({ turnId: turn.id, message: "This choice is no longer a valid date-format clarification. Ask Atlas again." });
      return;
    }
    const requestId = ++clarificationRequestId.current;
    const controller = new AbortController();
    clarificationAbortRef.current = controller;
    setClarifyingTurnId(turn.id);
    setClarificationError(null);
    const resumed: CleanTransformationRequest = { ...operation, date_format: format as string };
    delete resumed.review_token;
    try {
      const result = await fetch(apiUrl(`/api/v1/clean/datasets/${datasetId}/preview`), {
        method: "POST", headers: { "content-type": "application/json" }, signal: controller.signal,
        body: JSON.stringify(resumed),
      });
      if (!result.ok) throw new Error((await result.json() as { detail?: string }).detail ?? "Could not preview this date order.");
      const preview = await result.json() as CleanPreviewResponse;
      if (requestId !== clarificationRequestId.current || controller.signal.aborted || datasetRef.current !== datasetId || revisionRef.current !== turn.revision) return;
      if (preview.source_revision !== turn.revision) throw new Error("The dataset changed. Ask Atlas again against its current revision.");
      setTurns((current) => current.map((item) => item.id === turn.id && item.revision === turn.revision
        ? { ...item, selectedChoice: choice.label, response: { ...response, clean_operation: resumed, clean_preview: preview } }
        : item));
    } catch (reason) {
      if (!controller.signal.aborted && requestId === clarificationRequestId.current) setClarificationError({ turnId: turn.id, message: reason instanceof Error ? reason.message : "Could not preview this date order." });
    } finally {
      if (requestId === clarificationRequestId.current) setClarifyingTurnId(null);
      if (clarificationAbortRef.current === controller) clarificationAbortRef.current = null;
    }
  }

  function clearConversation() {
    if (!datasetId) return;
    setTurns([]);
    clarificationAbortRef.current?.abort();
    clarificationRequestId.current += 1;
    setClarifyingTurnId(null); setClarificationError(null);
    try { window.localStorage.removeItem(storageKey(datasetId)); } catch { /* nothing durable to clear if storage was already unavailable */ }
    setPersistenceFailed(false);
  }

  return <div className="atlas-dock" aria-label="Atlas assistant">
    <header className="atlas-dock-header">
      <AtlasCharacter pose={dockPose} size="large" />
      <div><strong>Atlas</strong><small>Your investigation assistant</small></div>
      {turns.length ? <button type="button" className="secondary atlas-dock-clear" aria-label="Clear conversation" title="Clear conversation" onClick={clearConversation}>Clear</button> : null}
    </header>
    <p className="atlas-dock-privacy">Only this PRISM context is shared.</p>
    {persistenceFailed ? <p className="query-error" role="alert">This conversation could not be saved — it will not survive a reload. Browser storage may be full or disabled.</p> : null}
    <ul className="atlas-dock-chips" aria-label="Current context">
      <li>{datasetName}</li>
      <li>Revision {revision}</li>
      <li>{focusLabel}</li>
      {column ? <li>{column}</li> : null}
    </ul>
    {!turns.length ? <div className="atlas-dock-starters">
      <span className="eyebrow">Starter questions</span>
      {STARTER_QUESTIONS.map((question) => <button key={question} type="button" className="secondary" disabled={!datasetId || Boolean(pending)} onClick={() => void ask(question)}>{question}</button>)}
    </div> : null}
    {turns.length ? <ol className="atlas-dock-turns" aria-label="Conversation" aria-live="polite">
      {turns.map((turn) => {
        const stale = turn.revision !== revision;
        return <li key={turn.id} className={stale ? "is-stale" : ""}>
          <p className="atlas-dock-ask">{turn.intent}</p>
          {stale ? <p className="atlas-dock-stale-note">This was asked about revision {turn.revision}; the dataset is now at revision {revision}. No longer current - ask again if still relevant.</p> : null}
          {turn.status === "pending" ? <div className="atlas-dock-message"><strong>Checking local model…</strong><button type="button" className="secondary" onClick={cancel}>Cancel</button></div> : null}
          {turn.status === "cancelled" ? <p className="quiet-note">Stopped waiting for a reply. PRISM also closed its own connection to the local model, which usually makes it stop generating too, but that isn't guaranteed — in-flight model computation may continue briefly.</p> : null}
          {turn.status === "interrupted" ? <p className="quiet-note">This was still waiting on a reply when the app last closed - that request is gone. Ask again if still relevant.</p> : null}
          {turn.status === "error" ? <div className="atlas-dock-error" role="alert"><p>{turn.error}</p><button type="button" className="secondary" disabled={Boolean(pending) || stale} onClick={() => void ask(turn.intent)}>Retry</button></div> : null}
          {turn.status === "done" && turn.response ? <div className="atlas-dock-message">
            <strong>{turn.response.provider === "ollama" ? turn.response.clean_operation || turn.response.sql_draft || turn.response.chart_spec ? "Atlas proposed (local model)" : "Atlas explained (local model)" : "Local model unavailable"}</strong>
            <p>{turn.response.explanation}</p>
            {turn.response.provider === "unavailable" ? <button type="button" className="secondary" disabled={Boolean(pending) || stale} onClick={() => void ask(turn.intent)}>Retry with local model</button> : null}
            {(turn.response.evidence ?? []).length ? <details className="atlas-dock-evidence"><summary>Inspect source evidence and provenance</summary><ul>{(turn.response.evidence ?? []).map((item) => <li key={item}>{item}</li>)}</ul></details> : null}
            {turn.response.clarification ? <fieldset className="atlas-dock-clarification" disabled={stale || Boolean(pending) || Boolean(clarifyingTurnId)}>
              <legend>Analyst decision required</legend>
              <p>{turn.response.clarification.question}</p>
              <div className="atlas-dock-choices">
                {turn.response.clarification.choices.map((choice, index) => <button type="button" className={turn.selectedChoice === choice.label ? "is-selected" : "secondary"} key={`${choice.label}-${index}`} onClick={() => void chooseClarification(turn, index)} aria-pressed={turn.selectedChoice === choice.label}>
                  {choice.label}
                </button>)}
              </div>
              {clarifyingTurnId === turn.id ? <p role="status">Previewing the selected date order…</p> : null}
              {turn.selectedChoice ? <p role="status">Previewed with {turn.selectedChoice}. Inspect the conversion warnings and changed rows in Step settings before Apply.</p> : null}
              {clarificationError?.turnId === turn.id && !stale ? <p className="query-error" role="alert">{clarificationError.message}</p> : null}
            </fieldset> : null}
            {turn.response.clean_preview ? (() => {
              const preview = turn.response.clean_preview!;
              const affected = preview.changed_rows_total ?? preview.affected_rows;
              const exceptionRows = preview.exception_rows_total ?? 0;
              const distinctValues = (preview.unresolved_values ?? []).length;
              const warningCount = preview.warnings?.length ?? 0;
              const clarificationPending = Boolean(turn.response?.clarification && !turn.selectedChoice);
              const checks = [
                { label: "Source revision current", detail: `Revision ${preview.source_revision}`, clear: !stale && preview.source_revision === revision },
                { label: "Review token issued", detail: preview.review_token ? "One-use preview token" : "Preview again", clear: Boolean(preview.review_token) },
                { label: "No conversion warnings", detail: warningCount ? `${warningCount} warning${warningCount === 1 ? "" : "s"}` : "No warnings", clear: warningCount === 0 },
                { label: "No unresolved review", detail: clarificationPending ? "Analyst decision required" : exceptionRows ? `${exceptionRows.toLocaleString()} rows to inspect` : distinctValues ? `${distinctValues.toLocaleString()} values to inspect` : "No unresolved values", clear: !clarificationPending && exceptionRows === 0 && distinctValues === 0 },
              ];
              return <div className="atlas-dock-computed">
                <span className="eyebrow">PRISM computed this deterministically</span>
                <p><strong>{affected.toLocaleString()}</strong> row{affected === 1 ? "" : "s"} would change.</p>
                <section className="atlas-dock-preview-checks" aria-label="Preview checks">
                  <header><span>Preview checks</span><strong>{checks.filter((check) => check.clear).length} / {checks.length} clear</strong></header>
                  <small>Measured checks, not model confidence.</small>
                  <ul>{checks.map((check) => <li key={check.label} className={check.clear ? "is-good" : "is-amber"}><span aria-hidden="true">{check.clear ? "✓" : "!"}</span><span>{check.label}</span><small>{check.detail}</small></li>)}</ul>
                </section>
                {exceptionRows > 0 && !turn.response?.clarification ? <div className="atlas-dock-ambiguity">
                  <p><strong className="is-amber">{exceptionRows.toLocaleString()}</strong> row{exceptionRows === 1 ? "" : "s"} didn't match anything in this proposal{distinctValues ? ` (${distinctValues.toLocaleString()} distinct value${distinctValues === 1 ? "" : "s"})` : ""} — review {exceptionRows === 1 ? "it" : "them"} before applying, or leave {exceptionRows === 1 ? "it" : "them"} unchanged.</p>
                  <button type="button" className="secondary" disabled={Boolean(pending)} onClick={() => void ask(`How should I handle the ${exceptionRows} row${exceptionRows === 1 ? "" : "s"} that didn't match in the last proposal?`)}>Ask Atlas how to handle {exceptionRows === 1 ? "it" : "them"}</button>
                </div> : null}
                {turn.selectedChoice && preview.warnings?.length ? <ul aria-label="Conversion warnings">{preview.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
              </div>;
            })() : null}
            {!stale && turn.response.provider === "ollama" && turn.response.clean_operation && (!turn.response.clarification || turn.selectedChoice) ? <button type="button" onClick={() => onReview(turn.response!)}>Review in Step settings</button> : null}
          </div> : null}
        </li>;
      })}
    </ol> : null}
    <form className="atlas-dock-input" onSubmit={(event) => { event.preventDefault(); void ask(intent); }}>
      <label>Ask Atlas<textarea value={intent} onChange={(event) => setIntent(event.target.value)} maxLength={500} placeholder="e.g. Standardize region labels" disabled={Boolean(pending)} /></label>
      <button type="submit" disabled={!datasetId || Boolean(pending) || intent.trim().length < 3}>{pending ? "Checking local model…" : "Ask Atlas"}</button>
    </form>
    {!datasetId ? <p className="quiet-note">Load a dataset to ask Atlas about it.</p> : null}
  </div>;
}
