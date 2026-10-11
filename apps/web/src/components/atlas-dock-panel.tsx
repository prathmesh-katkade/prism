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
import type { WorkspaceProposalResponse } from "@prism/api-contracts";
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
};

function storageKey(datasetId: string): string { return `atlas-dock:${datasetId}`; }

function loadStoredTurns(datasetId: string): Turn[] {
  try {
    const raw = window.localStorage.getItem(storageKey(datasetId));
    if (!raw) return [];
    const parsed = JSON.parse(raw) as Turn[];
    if (!Array.isArray(parsed)) return [];
    // A pending request's connection is gone with the page that made it -
    // restore it as interrupted, never as still (falsely) in progress.
    return parsed.map((turn) => turn.status === "pending" ? { ...turn, status: "interrupted" as const } : turn);
  } catch { return []; }
}

function saveStoredTurns(datasetId: string, turns: Turn[]): void {
  try { window.localStorage.setItem(storageKey(datasetId), JSON.stringify(turns.slice(-STORED_TURNS_LIMIT))); } catch { /* storage unavailable or full - the in-memory conversation still works this session */ }
}

export function AtlasDockPanel({
  datasetId, datasetName, revision, focusLabel, operation, column, onReview,
}: {
  datasetId: string | undefined;
  datasetName: string;
  revision: number;
  focusLabel: string;
  operation: string | null;
  column: string | null;
  onReview(proposal: WorkspaceProposalResponse): void;
}) {
  const [intent, setIntent] = useState("");
  const [turns, setTurns] = useState<Turn[]>(() => (typeof window !== "undefined" && datasetId ? loadStoredTurns(datasetId) : []));
  const abortRef = useRef<AbortController | null>(null);
  const pending = turns.find((turn) => turn.status === "pending");

  // A conversation is about one dataset. Loading a different dataset
  // restores *that* dataset's own stored conversation (if any), rather
  // than either keeping the previous dataset's turns or discarding real,
  // persisted history just because the component didn't happen to mount
  // fresh on it.
  const datasetRef = useRef(datasetId);
  useEffect(() => {
    if (datasetRef.current !== datasetId) {
      datasetRef.current = datasetId;
      setTurns(datasetId ? loadStoredTurns(datasetId) : []);
      abortRef.current?.abort();
    }
  }, [datasetId]);

  // Mirror every change to this dataset's own storage slot - the actual
  // persistence; the effect above only ever reads it.
  useEffect(() => {
    if (datasetId) saveStoredTurns(datasetId, turns);
  }, [datasetId, turns]);

  const dockPose: AtlasPose = pending ? "working" : turns.length ? "presenting" : intent.trim() ? "idle" : "waiting";

  async function ask(text: string) {
    if (!datasetId || text.trim().length < 3 || pending) return;
    const id = `turn_${Date.now()}_${turns.length}`;
    const askedAtRevision = revision;
    // A bounded slice of this same conversation's own prior turns - real
    // context for a follow-up question, never a transcript sent anywhere
    // else or retained past this one request.
    const history = turns
      .filter((turn) => turn.status === "done" && turn.response)
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

  return <div className="atlas-dock" aria-label="Atlas assistant">
    <header className="atlas-dock-header">
      <AtlasCharacter pose={dockPose} size="large" />
      <div><strong>Atlas</strong><small>Your investigation assistant</small></div>
    </header>
    <p className="atlas-dock-privacy">Only this PRISM context is shared.</p>
    <ul className="atlas-dock-chips" aria-label="Current context">
      <li>{datasetName}</li>
      <li>Revision {revision}</li>
      <li>{focusLabel}</li>
      {column ? <li>{column}</li> : null}
    </ul>
    <div className="atlas-dock-starters">
      <span className="eyebrow">Starter questions</span>
      {STARTER_QUESTIONS.map((question) => <button key={question} type="button" className="secondary" disabled={!datasetId || Boolean(pending)} onClick={() => void ask(question)}>{question}</button>)}
    </div>
    {turns.length ? <ol className="atlas-dock-turns" aria-label="Conversation" aria-live="polite">
      {turns.map((turn) => {
        const stale = turn.revision !== revision;
        return <li key={turn.id} className={stale ? "is-stale" : ""}>
          <p className="atlas-dock-ask">{turn.intent}</p>
          {stale ? <p className="atlas-dock-stale-note">This was asked about revision {turn.revision}; the dataset is now at revision {revision}. No longer current - ask again if still relevant.</p> : null}
          {turn.status === "pending" ? <div className="atlas-dock-message"><strong>Checking local model…</strong><button type="button" className="secondary" onClick={cancel}>Cancel</button></div> : null}
          {turn.status === "cancelled" ? <p className="quiet-note">Stopped waiting for a reply. PRISM also closed its own connection to the local model, which usually makes it stop generating too, but that isn't guaranteed — in-flight model computation may continue briefly.</p> : null}
          {turn.status === "interrupted" ? <p className="quiet-note">This was still waiting on a reply when the app last closed - that request is gone. Ask again if still relevant.</p> : null}
          {turn.status === "error" ? <p className="query-error" role="alert">{turn.error}</p> : null}
          {turn.status === "done" && turn.response ? <div className="atlas-dock-message">
            <strong>{turn.response.provider === "ollama" ? "Atlas proposed (local model)" : "Local model unavailable"}</strong>
            <p>{turn.response.explanation}</p>
            {(turn.response.evidence ?? []).length ? <ul>{(turn.response.evidence ?? []).map((item) => <li key={item}>{item}</li>)}</ul> : null}
            {turn.response.clean_preview ? (() => {
              const preview = turn.response.clean_preview!;
              const affected = preview.changed_rows_total ?? preview.affected_rows;
              const exceptionRows = preview.exception_rows_total ?? 0;
              const distinctValues = (preview.unresolved_values ?? []).length;
              return <div className="atlas-dock-computed">
                <span className="eyebrow">PRISM computed this deterministically</span>
                <p><strong>{affected.toLocaleString()}</strong> row{affected === 1 ? "" : "s"} would change.</p>
                {exceptionRows > 0 ? <div className="atlas-dock-ambiguity">
                  <p><strong className="is-amber">{exceptionRows.toLocaleString()}</strong> row{exceptionRows === 1 ? "" : "s"} didn't match anything in this proposal{distinctValues ? ` (${distinctValues.toLocaleString()} distinct value${distinctValues === 1 ? "" : "s"})` : ""} — review {exceptionRows === 1 ? "it" : "them"} before applying, or leave {exceptionRows === 1 ? "it" : "them"} unchanged.</p>
                  <button type="button" className="secondary" disabled={Boolean(pending)} onClick={() => void ask(`How should I handle the ${exceptionRows} row${exceptionRows === 1 ? "" : "s"} that didn't match in the last proposal?`)}>Ask Atlas how to handle {exceptionRows === 1 ? "it" : "them"}</button>
                </div> : null}
              </div>;
            })() : null}
            {!stale && turn.response.provider === "ollama" && turn.response.clean_operation ? <button type="button" onClick={() => onReview(turn.response!)}>Review in Step settings</button> : null}
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
