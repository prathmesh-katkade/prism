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
 * What this intentionally does NOT do, investigated rather than assumed:
 * persist this conversation across a reload/restart. The only durable
 * store available (`AnalyticalObject` / `ObjectKind.CLEANING_PLAN`) is
 * already used for *applied* Clean transformations; writing unapplied
 * proposals into the same bucket would corrupt what downstream lineage/
 * evidence consumers already assume CLEANING_PLAN means, and adding a new
 * ObjectKind is a shared-schema change (rippling through the generated
 * TypeScript contract and every consumer) too large for this pass. Named
 * here, not silently skipped - see docs/clean-atlas-v1/phase-3 status.
 */
import { useEffect, useRef, useState } from "react";
import type { WorkspaceProposalResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { AtlasCharacter, type AtlasPose } from "./atlas-character";

const STARTER_QUESTIONS = ["What should I review first?", "Explain the current step", "Suggest a cleanup for this column"];

type Turn = {
  id: string;
  intent: string;
  revision: number;
  status: "pending" | "done" | "error" | "cancelled";
  response?: WorkspaceProposalResponse;
  error?: string;
};

export function AtlasDockPanel({
  datasetId, datasetName, revision, focusLabel, column, onReview,
}: {
  datasetId: string | undefined;
  datasetName: string;
  revision: number;
  focusLabel: string;
  column: string | null;
  onReview(proposal: WorkspaceProposalResponse): void;
}) {
  const [intent, setIntent] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const pending = turns.find((turn) => turn.status === "pending");

  // A conversation is about one dataset. Loading a different dataset starts
  // a new one rather than showing the previous dataset's asks against it.
  const datasetRef = useRef(datasetId);
  useEffect(() => {
    if (datasetRef.current !== datasetId) { datasetRef.current = datasetId; setTurns([]); abortRef.current?.abort(); }
  }, [datasetId]);

  const dockPose: AtlasPose = pending ? "working" : turns.length ? "presenting" : intent.trim() ? "idle" : "waiting";

  async function ask(text: string) {
    if (!datasetId || text.trim().length < 3 || pending) return;
    const id = `turn_${Date.now()}_${turns.length}`;
    const askedAtRevision = revision;
    setTurns((current) => [...current, { id, intent: text.trim(), revision: askedAtRevision, status: "pending" }]);
    setIntent("");
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const response = await fetch(apiUrl("/api/v1/workspace-proposals"), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: "clean", dataset_id: datasetId, intent: text.trim() }),
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
          {turn.status === "cancelled" ? <p className="quiet-note">Cancelled.</p> : null}
          {turn.status === "error" ? <p className="query-error" role="alert">{turn.error}</p> : null}
          {turn.status === "done" && turn.response ? <div className="atlas-dock-message">
            <strong>{turn.response.provider === "ollama" ? "Atlas proposed (local model)" : "Local model unavailable"}</strong>
            <p>{turn.response.explanation}</p>
            {(turn.response.evidence ?? []).length ? <ul>{(turn.response.evidence ?? []).map((item) => <li key={item}>{item}</li>)}</ul> : null}
            {turn.response.clean_preview ? (() => {
              const preview = turn.response.clean_preview!;
              const affected = preview.changed_rows_total ?? preview.affected_rows;
              const exceptions = preview.exception_rows_total ?? 0;
              return <div className="atlas-dock-computed">
                <span className="eyebrow">PRISM computed this deterministically</span>
                <p><strong>{affected.toLocaleString()}</strong> row{affected === 1 ? "" : "s"} would change.</p>
                {exceptions > 0 ? <p className="atlas-dock-ambiguity"><strong className="is-amber">{exceptions.toLocaleString()}</strong> value{exceptions === 1 ? "" : "s"} didn't match anything in this proposal — review {exceptions === 1 ? "it" : "them"} before applying, or leave {exceptions === 1 ? "it" : "them"} unchanged.</p> : null}
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
