"use client";

import { useState } from "react";
import type { WorkspaceProposalResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";

type ProposalKind = "clean" | "chart" | "sql";

export function WorkspaceProposalPanel({ kind, datasetId, onReview }: { kind: ProposalKind; datasetId?: string | undefined; onReview(proposal: WorkspaceProposalResponse): void }) {
  const [intent, setIntent] = useState("");
  const [proposal, setProposal] = useState<WorkspaceProposalResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function requestProposal() {
    if (!datasetId || intent.trim().length < 3) return;
    setBusy(true); setProposal(null); setError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/workspace-proposals"), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ kind, dataset_id: datasetId, intent: intent.trim() }),
      });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Proposal request failed.");
      setProposal(await response.json() as WorkspaceProposalResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The proposal is unavailable. Manual controls remain available."); }
    finally { setBusy(false); }
  }

  return <section className="workspace-proposal" aria-label={`${kind} local model proposal`}>
    <span className="eyebrow">OPTIONAL LOCAL MODEL · REVIEW REQUIRED</span>
    <label>What would you like to do?<textarea value={intent} onChange={(event) => setIntent(event.target.value)} maxLength={500} placeholder={kind === "clean" ? "e.g. Standardize region labels" : kind === "chart" ? "e.g. Compare revenue by segment" : "e.g. Count rows by segment"} /></label>
    <button className="secondary" disabled={!datasetId || busy || intent.trim().length < 3} onClick={() => void requestProposal()}>{busy ? "Checking local model…" : "Request proposal"}</button>
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    {proposal ? <div className="workspace-proposal-result" aria-live="polite"><strong>{proposal.provider === "ollama" ? "Local model draft" : "Local model unavailable"}</strong><p>{proposal.explanation}</p><ul>{(proposal.evidence ?? []).map((item) => <li key={item}>{item}</li>)}</ul>{proposal.provider === "ollama" ? <><pre>{JSON.stringify(proposal.clean_operation ?? proposal.chart_spec ?? proposal.sql_draft, null, 2)}</pre><button onClick={() => onReview(proposal)}>Review in workspace</button></> : null}</div> : null}
  </section>;
}
