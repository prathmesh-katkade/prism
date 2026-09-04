"use client";

import { useEffect, useRef, useState } from "react";
import type { AiAnalystResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { newestAnalyticalObjectId } from "./analytical-history";
import type { InspectorObjectState } from "../state/shell-model";

export function AiAnalyst({ datasetId, resultRunId, onSqlDraft, onSelectContext }: { datasetId: string | undefined; resultRunId: string | undefined; onSqlDraft(sql: string): void; onSelectContext(state: InspectorObjectState): void }) {
  const [question, setQuestion] = useState("What can this dataset support with confidence?");
  const [answer, setAnswer] = useState("");
  const [response, setResponse] = useState<AiAnalystResponse | null>(null);
  const [state, setState] = useState("ready");
  const [error, setError] = useState<string | null>(null);
  const requestId = useRef<string | null>(null);
  const controller = useRef<AbortController | null>(null);
  useEffect(() => () => controller.current?.abort(), []);

  async function ask() {
    controller.current?.abort();
    const aborter = new AbortController(); controller.current = aborter;
    setAnswer(""); setResponse(null); setError(null); setState("context_selecting"); requestId.current = null;
    try {
      const stream = await fetch(apiUrl("/api/v1/ai-analyst/stream"), { method: "POST", headers: { "content-type": "application/json", accept: "text/event-stream" }, signal: aborter.signal, body: JSON.stringify({ question, ...(datasetId ? { dataset_id: datasetId } : {}), ...(resultRunId ? { result_run_id: resultRunId } : {}) }) });
      if (!stream.ok || !stream.body) throw new Error("AI Analyst stream could not start.");
      const reader = stream.body.pipeThrough(new TextDecoderStream()).getReader(); let buffer = "";
      for (;;) {
        const next = await reader.read(); if (next.done) break;
        buffer += next.value; const frames = buffer.split("\n\n"); buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const event = parseEvent(frame); if (event.id) requestId.current = event.id;
          if (event.event === "atlas.state") setState(String(event.data.state ?? "working"));
          if (event.event === "atlas.token") { setState("responding"); setAnswer((current) => current + String(event.data.token ?? "")); }
          if (event.event === "atlas.tool_wait") setState("sql_review_required");
          if (event.event === "atlas.complete") { const completed = event.data as unknown as AiAnalystResponse; setResponse(completed); setAnswer(completed.answer); setState("complete"); if (completed.outcome === "answered") { void newestAnalyticalObjectId(completed.context.dataset_id, "evidence").then((analyticalObjectId) => onSelectContext({ objectId: completed.request_id, ...(analyticalObjectId ? { analyticalObjectId } : {}), label: "AI Analyst evidence", type: "finding", state: "ready", actions: [], metadata: [completed.provider, "Evidence-grounded"] })); } }
          if (event.event === "atlas.failure") { setError(String(event.data.detail ?? "AI Analyst failed.")); setState("degraded"); }
          if (event.event === "atlas.cancelled") setState("cancelled");
        }
      }
    } catch (reason) { if (aborter.signal.aborted) setState("cancelled"); else { setError(reason instanceof Error ? reason.message : "AI Analyst failed."); setState("degraded"); } }
  }
  async function cancel() { controller.current?.abort(); if (requestId.current) await fetch(apiUrl(`/api/v1/ai-analyst/runs/${requestId.current}/cancel`), { method: "POST" }).catch(() => undefined); setState("cancelled"); }

  return <article className="ai-analyst"><header className="ai-heading"><div><span className="eyebrow">AI ANALYST · EVIDENCE-FIRST</span><h1>Ask what the evidence can actually support.</h1><p>Atlas selects compact server-held context, records provenance, and routes executable work through SQL Lab.</p></div><span className={`migration-chip ${state === "degraded" ? "unavailable" : "ready"}`}>{state.replaceAll("_", " ")}</span></header><section className="ai-question" aria-label="AI Analyst question"><label htmlFor="ai-question">Research question</label><textarea id="ai-question" value={question} onChange={(event) => setQuestion(event.target.value)} maxLength={4000} /><div><button onClick={() => void ask()} disabled={state === "context_selecting" || state === "responding"}>Ask Atlas</button>{["context_selecting", "routing", "responding", "sql_review_required"].includes(state) ? <button className="secondary" onClick={() => void cancel()}>Cancel</button> : null}</div></section>{resultRunId ? <p className="ai-evidence-banner">Using SQL Lab result <code>{resultRunId.slice(0, 16)}…</code> as evidence; raw result rows stay server-held.</p> : null}{error ? <p className="query-error" role="alert">{error}</p> : null}{answer ? <section className="ai-answer" aria-live="polite"><span className="eyebrow">ATLAS RESPONSE</span><h2>{answer}</h2>{response ? <><p><strong>Uncertainty:</strong> {response.uncertainty}</p><p><strong>Highest-value next step:</strong> {response.recommended_next_step}</p>{(response.limiting_factors ?? []).length ? <ul>{(response.limiting_factors ?? []).map((factor) => <li key={factor}>{factor}</li>)}</ul> : null}</> : null}</section> : null}{response ? <section className="ai-evidence"><span className="eyebrow">EVIDENCE & PROVENANCE</span><div>{response.evidence.map((item, index) => <article key={`${item.kind}-${item.label}-${item.provenance_ref}-${index}`}><strong>{item.label}</strong><p>{item.value}</p><small>{item.provenance_ref}</small></article>)}</div><p>Prompt {response.context.prompt_version} · config {response.context.config_version} · provider {response.provider} · {response.context.raw_sample_rows} raw sample rows sent.</p></section> : null}{response?.sql_draft ? <section className="ai-sql-draft"><span className="eyebrow">SQL DRAFT · REVIEW REQUIRED</span><pre>{response.sql_draft}</pre><p>This is editable and unexecuted. SQL Lab remains the sole safety and execution boundary.</p><button onClick={() => onSqlDraft(response.sql_draft ?? "")}>Open draft in SQL Lab</button></section> : null}</article>;
}

function parseEvent(frame: string): { event: string; id?: string; data: Record<string, unknown> } {
  const fields = new Map(frame.split("\n").map((line) => { const [key, ...value] = line.split(":"); return [key, value.join(":").trim()] as const; }));
  const id = fields.get("id");
  const base = { event: fields.get("event") ?? "message", data: JSON.parse(fields.get("data") ?? "{}") as Record<string, unknown> };
  return id === undefined ? base : { ...base, id };
}
