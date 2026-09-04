"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AtlasRunResponse, CortexGraphState, CortexNode } from "@prism/api-contracts";
import { apiUrl } from "../config/api";

const terminal = new Set(["completed", "failed", "cancelled"]);

export function AtlasWorkspace({ datasetId }: { datasetId: string | undefined }) {
  const [objective, setObjective] = useState("Profile this dataset and identify the evidence needed for the next decision.");
  const [run, setRun] = useState<AtlasRunResponse | null>(null);
  const [graph, setGraph] = useState<CortexGraphState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const cancelStream = useRef<AbortController | null>(null);
  useEffect(() => () => cancelStream.current?.abort(), []);
  async function refresh(id: string) {
    const [runResponse, graphResponse] = await Promise.all([fetch(apiUrl(`/api/v1/atlas/runs/${id}`)), fetch(apiUrl(`/api/v1/atlas/runs/${id}/cortex`))]);
    if (runResponse.ok) setRun(await runResponse.json() as AtlasRunResponse);
    if (graphResponse.ok) setGraph(await graphResponse.json() as CortexGraphState);
  }
  async function watch(id: string) {
    cancelStream.current?.abort(); const controller = new AbortController(); cancelStream.current = controller;
    try {
      const response = await fetch(apiUrl(`/api/v1/atlas/runs/${id}/events`), { signal: controller.signal, headers: { accept: "text/event-stream" } });
      if (!response.body) throw new Error("Atlas event stream is unavailable.");
      const reader = response.body.pipeThrough(new TextDecoderStream()).getReader(); let buffer = "";
      for (;;) { const chunk = await reader.read(); if (chunk.done) break; buffer += chunk.value; const frames = buffer.split("\n\n"); buffer = frames.pop() ?? ""; for (const frame of frames) { if (frame.includes("event: atlas.run")) await refresh(id); } }
      await refresh(id);
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "Atlas stream failed."); }
  }
  async function start() {
    if (!datasetId) return; setError(null); setRun(null); setGraph(null);
    const response = await fetch(apiUrl("/api/v1/atlas/runs"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ dataset_id: datasetId, objective, idempotency_key: crypto.randomUUID() }) });
    if (!response.ok) { setError((await response.json() as { detail?: string }).detail ?? "Atlas run could not start."); return; }
    const created = await response.json() as AtlasRunResponse; setRun(created); await refresh(created.run_id); void watch(created.run_id);
  }
  async function cancel() { if (!run) return; await fetch(apiUrl(`/api/v1/atlas/runs/${run.run_id}/cancel`), { method: "POST" }); await refresh(run.run_id); }
  if (!datasetId) return <section className="atlas-state empty-state"><span className="eyebrow">ATLAS · LOCAL ORCHESTRATION</span><h1>Load a dataset before opening an investigation.</h1><p>Atlas plans against durable dataset metadata and never ships raw rows to a provider.</p></section>;
  const state = run?.plan.state ?? "ready";
  return <article className="atlas-workspace">
    <header className="atlas-heading"><div><span className="eyebrow">ATLAS · OPERATIONS DESK</span><h1>Make the analytical route inspectable.</h1><p>Plans are advisory until PRISM validates every declared tool. Evidence, objections, and events are durable.</p></div><span className={`migration-chip ${state === "failed" ? "unavailable" : "ready"}`} aria-live="polite">{state.replaceAll("_", " ")}</span></header>
    <section className="atlas-command" aria-label="Atlas investigation"><label htmlFor="atlas-objective">Investigation objective</label><textarea id="atlas-objective" value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={2000} /><div><button onClick={() => void start()} disabled={state === "running"}>Run investigation</button>{run && !terminal.has(run.plan.state ?? "") ? <button className="secondary" onClick={() => void cancel()}>Cancel run</button> : null}</div></section>
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    {run ? <><section className="atlas-run-grid"><PlanTimeline run={run} /><SpecialistRail run={run} /><CouncilInspector run={run} /></section><section className="atlas-answer" aria-live="polite"><span className="eyebrow">ATLAS · GROUNDED ANSWER</span><h2>{run.answer ?? "Atlas is collecting durable evidence."}</h2>{run.uncertainty ? <p><strong>Uncertainty:</strong> {run.uncertainty}</p> : null}</section>{graph ? <CortexV1 graph={graph} /> : null}</> : null}
  </article>;
}

function PlanTimeline({ run }: { run: AtlasRunResponse }) { return <section className="atlas-plan"><span className="eyebrow">PLAN · {run.plan.plan_id.slice(-8)}</span><h2>{run.plan.objective}</h2><ol>{(run.plan.steps ?? []).map((step) => <li key={step.step_id} data-state={step.state}><span className="plan-marker" /><div><strong>{step.title}</strong><small>{step.specialist} · {step.tool_name} · attempt {step.attempts}/{step.max_attempts}</small><p>{step.rationale}</p>{step.error ? <em>{step.error}</em> : null}</div></li>)}</ol></section>; }
function SpecialistRail({ run }: { run: AtlasRunResponse }) { const steps = run.plan.steps ?? []; const active = new Set(steps.map((step) => step.specialist)); return <aside className="atlas-specialists"><span className="eyebrow">SPECIALISTS</span>{[...active].map((specialist) => { const step = steps.find((item) => item.specialist === specialist); return <div key={specialist}><span className={`specialist-signal ${step?.state ?? "pending"}`} /><strong>{specialist}</strong><small>{step?.state ?? "pending"}</small></div>; })}</aside>; }
function CouncilInspector({ run }: { run: AtlasRunResponse }) { const council = run.council ?? []; return <aside className="atlas-council"><span className="eyebrow">COUNCIL · EVIDENCE</span>{council.length ? council.map((item) => <article key={`${item.specialist}-${item.conclusion}`}><strong>{item.specialist}</strong><p>{item.conclusion}</p>{(item.objections ?? []).map((objection) => <small key={objection}>Objection: {objection}</small>)}{(item.evidence ?? []).map((evidence) => <code key={evidence.evidence_id}>{evidence.evidence_id}</code>)}</article>) : <p>Conclusions will appear only after a real tool records evidence.</p>}</aside>; }

function CortexV1({ graph }: { graph: CortexGraphState }) {
  const [focus, setFocus] = useState<string | null>(null); const [zoom, setZoom] = useState(1); const nodes = useMemo(() => graph.nodes ?? [], [graph]); const edges = graph.edges ?? []; const positions = useMemo(() => Object.fromEntries(nodes.map((node, index) => [node.node_id, positionFor(node, index, nodes.length)])), [nodes]); const visible = (node: CortexNode) => !focus || node.node_id === focus || edges.some((edge) => (edge.source_node_id === focus && edge.target_node_id === node.node_id) || (edge.target_node_id === focus && edge.source_node_id === node.node_id));
  return <section className="cortex-v1" aria-label="Cortex real-state graph"><header><div><span className="eyebrow">CORTEX V1 · DURABLE STATE ONLY</span><h2>Run topology</h2><p>{nodes.length} real nodes · {edges.length} real relations · select a node to focus.</p></div><div className="cortex-controls"><button onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))} aria-label="Zoom in Cortex">+</button><button onClick={() => setZoom((value) => Math.max(0.7, value - 0.1))} aria-label="Zoom out Cortex">−</button><button onClick={() => setFocus(null)} disabled={!focus}>Reset focus</button></div></header><svg viewBox="0 0 800 420" role="img" aria-label="Cortex graph of this Atlas run" className="cortex-canvas"><g transform={`translate(400 210) scale(${zoom}) translate(-400 -210)`}>{edges.map((edge) => { const a = positions[edge.source_node_id]!, b = positions[edge.target_node_id]!; return <path key={edge.edge_id} className={focus && edge.source_node_id !== focus && edge.target_node_id !== focus ? "is-muted" : ""} d={`M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${Math.min(a.y, b.y) - 36} ${b.x} ${b.y}`} />; })}{nodes.map((node) => { const point = positions[node.node_id]!; return <g key={node.node_id} className={`${visible(node) ? "" : "is-muted"} state-${node.state}`} transform={`translate(${point.x} ${point.y})`} tabIndex={0} role="button" aria-label={`Focus ${node.label}`} onClick={() => setFocus(node.node_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setFocus(node.node_id); }}><circle r={node.kind === "run" ? 24 : 14} /><text y={node.kind === "run" ? 43 : 32}>{node.label.slice(0, 28)}</text></g>; })}</g></svg><ul className="cortex-legend"><li>Running / current</li><li>Recorded evidence</li><li>Blocked or cancelled</li></ul></section>;
}
function positionFor(node: CortexNode, index: number, total: number) { if (node.kind === "run") return { x: 400, y: 210 }; const angle = (index / Math.max(1, total - 1)) * Math.PI * 2; const radius = node.kind === "evidence" ? 170 : 110; return { x: 400 + Math.cos(angle) * radius, y: 210 + Math.sin(angle) * radius }; }
