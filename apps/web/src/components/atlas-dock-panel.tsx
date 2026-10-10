"use client";

/**
 * Atlas docked inside Clean: the real `/api/v1/workspace-proposals` local-
 * model flow (the same one `WorkspaceProposalPanel` already exposes, reused
 * at the same contract rather than forked into a second mocked endpoint),
 * presented with the character, real dataset/step context chips, and a
 * handful of starter questions that just pre-fill the same free-text intent
 * - they are not a separate, fabricated capability.
 */
import { useState } from "react";
import type { WorkspaceProposalResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { AtlasCharacter, type AtlasPose } from "./atlas-character";

const STARTER_QUESTIONS = ["What should I review first?", "Explain the current step", "Suggest a cleanup for this column"];

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
  const [proposal, setProposal] = useState<WorkspaceProposalResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // The character's pose reflects this panel's own real request lifecycle,
  // not a decorative loop: waiting until there's something to ask, working
  // while the request is in flight, presenting once a result exists.
  const dockPose: AtlasPose = busy ? "working" : proposal ? "presenting" : intent.trim() ? "idle" : "waiting";

  async function ask(text: string) {
    if (!datasetId || text.trim().length < 3) return;
    setIntent(text); setBusy(true); setProposal(null); setError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/workspace-proposals"), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind: "clean", dataset_id: datasetId, intent: text.trim() }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Proposal request failed.");
      setProposal(await response.json() as WorkspaceProposalResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The proposal is unavailable. Manual controls remain available."); }
    finally { setBusy(false); }
  }

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
      {STARTER_QUESTIONS.map((question) => <button key={question} type="button" className="secondary" disabled={!datasetId || busy} onClick={() => void ask(question)}>{question}</button>)}
    </div>
    {proposal ? <div className="atlas-dock-message" aria-live="polite">
      <strong>{proposal.provider === "ollama" ? "Local model draft" : "Local model unavailable"}</strong>
      <p>{proposal.explanation}</p>
      {(proposal.evidence ?? []).length ? <ul>{(proposal.evidence ?? []).map((item) => <li key={item}>{item}</li>)}</ul> : null}
      {proposal.provider === "ollama" && proposal.clean_operation ? <button type="button" onClick={() => onReview(proposal)}>Review in Step settings</button> : null}
    </div> : null}
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    <form className="atlas-dock-input" onSubmit={(event) => { event.preventDefault(); void ask(intent); }}>
      <label>Ask Atlas<textarea value={intent} onChange={(event) => setIntent(event.target.value)} maxLength={500} placeholder="e.g. Standardize region labels" /></label>
      <button type="submit" disabled={!datasetId || busy || intent.trim().length < 3}>{busy ? "Checking local model…" : "Ask Atlas"}</button>
    </form>
    {!datasetId ? <p className="quiet-note">Load a dataset to ask Atlas about it.</p> : null}
  </div>;
}
