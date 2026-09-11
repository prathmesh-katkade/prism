"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { AtlasFeedbackEvent, AtlasMemoryRecord, AtlasResourceSnapshot, AtlasRunResponse, AtlasSpecialistIdentity, CortexGraphState, CortexNode } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { buildSpecialistActivity, EvidencePanel, GuardrailPanel, PipelineStepper, RunMemoryTrace, ToolTimeline } from "./atlas-run-activity";

const terminal = new Set(["completed", "failed", "cancelled"]);

export function AtlasWorkspace({ datasetId }: { datasetId: string | undefined }) {
  const [objective, setObjective] = useState("Profile this dataset and identify the evidence needed for the next decision.");
  const [run, setRun] = useState<AtlasRunResponse | null>(null);
  const [graph, setGraph] = useState<CortexGraphState | null>(null);
  const [memories, setMemories] = useState<AtlasMemoryRecord[]>([]);
  const [resources, setResources] = useState<AtlasResourceSnapshot | null>(null);
  const [roster, setRoster] = useState<AtlasSpecialistIdentity[]>([]);
  const [runMemories, setRunMemories] = useState<AtlasMemoryRecord[]>([]);
  const [runFeedback, setRunFeedback] = useState<AtlasFeedbackEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const cancelStream = useRef<AbortController | null>(null);
  useEffect(() => () => cancelStream.current?.abort(), []);
  useEffect(() => {
    let cancelled = false;
    fetch(apiUrl("/api/v1/atlas/specialists"))
      .then((response) => (response.ok ? (response.json() as Promise<AtlasSpecialistIdentity[]>) : []))
      .then((identities) => { if (!cancelled) setRoster(identities); })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, []);
  // Real per-run memory trace: memories bounded to a recent window (no
  // dedicated run_id filter exists on GET /memories yet, so a bounded
  // fetch is filtered client-side by source_ref === run_id -- the exact
  // rule the backend's own Cortex graph builder uses) plus feedback via
  // the dedicated GET /feedback/runs/{run_id} route (an exact match).
  // Refetched only when the run identity or its terminal state changes,
  // not on every SSE tick.
  useEffect(() => {
    if (!run) return;
    let cancelled = false;
    Promise.all([
      fetch(apiUrl("/api/v1/atlas/memories?limit=100")).then((response) => (response.ok ? (response.json() as Promise<AtlasMemoryRecord[]>) : [])),
      fetch(apiUrl(`/api/v1/atlas/feedback/runs/${run.run_id}`)).then((response) => (response.ok ? (response.json() as Promise<AtlasFeedbackEvent[]>) : [])),
    ])
      .then(([memoryRecords, feedbackEvents]) => {
        if (cancelled) return;
        setRunMemories(memoryRecords);
        setRunFeedback(feedbackEvents);
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [run?.run_id, run?.plan.state]);
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
    if (!datasetId) return; setError(null); setRun(null); setGraph(null); setRunMemories([]); setRunFeedback([]);
    const response = await fetch(apiUrl("/api/v1/atlas/runs"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ dataset_id: datasetId, objective, idempotency_key: crypto.randomUUID() }) });
    if (!response.ok) { setError((await response.json() as { detail?: string }).detail ?? "Atlas run could not start."); return; }
    const created = await response.json() as AtlasRunResponse; setRun(created); await refresh(created.run_id); void watch(created.run_id);
  }
  async function cancel() { if (!run) return; await fetch(apiUrl(`/api/v1/atlas/runs/${run.run_id}/cancel`), { method: "POST" }); await refresh(run.run_id); }
  async function refreshPulse() {
    const [memoryResponse, resourceResponse] = await Promise.all([fetch(apiUrl("/api/v1/atlas/memories?limit=8")), fetch(apiUrl("/api/v1/atlas/resources/snapshot"))]);
    if (memoryResponse.ok) setMemories(await memoryResponse.json() as AtlasMemoryRecord[]);
    if (resourceResponse.ok) setResources(await resourceResponse.json() as AtlasResourceSnapshot);
  }
  if (!datasetId) return <section className="atlas-state empty-state"><span className="eyebrow">ATLAS · LOCAL ORCHESTRATION</span><h1>Load a dataset before opening an investigation.</h1><p>Atlas plans against durable dataset metadata and never ships raw rows to a provider.</p></section>;
  const state = run?.plan.state ?? "ready";
  return <article className="atlas-workspace">
    <header className="atlas-heading"><div><span className="eyebrow">ATLAS · OPERATIONS DESK</span><h1>Make the analytical route inspectable.</h1><p>Plans are advisory until PRISM validates every declared tool. Evidence, objections, and events are durable.</p></div><span className={`migration-chip ${state === "failed" ? "unavailable" : "ready"}`} aria-live="polite">{state.replaceAll("_", " ")}</span></header>
    <section className="atlas-command" aria-label="Atlas investigation"><label htmlFor="atlas-objective">Investigation objective</label><textarea id="atlas-objective" value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={2000} /><div><button onClick={() => void start()} disabled={state === "running"}>Run investigation</button>{run && !terminal.has(run.plan.state ?? "") ? <button className="secondary" onClick={() => void cancel()}>Cancel run</button> : null}</div></section>
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    {run ? <>
      <PipelineStepper run={run} />
      <section className="atlas-run-grid"><PlanTimeline run={run} /><SpecialistRail run={run} roster={roster} /><CouncilInspector run={run} /></section>
      <section className="atlas-answer" aria-live="polite"><span className="eyebrow">ATLAS · GROUNDED ANSWER</span><h2>{run.answer ?? "Atlas is collecting durable evidence."}</h2>{run.uncertainty ? <p><strong>Uncertainty:</strong> {run.uncertainty}</p> : null}</section>
      <GuardrailPanel run={run} />
      <ToolTimeline run={run} />
      <EvidencePanel run={run} />
      <RunMemoryTrace run={run} memories={runMemories} feedback={runFeedback} />
      <AtlasPulse memories={memories} resources={resources} onRefresh={() => void refreshPulse()} />
      {graph ? <CortexV1 graph={graph} /> : null}
    </> : null}
  </article>;
}

function PlanTimeline({ run }: { run: AtlasRunResponse }) { return <section className="atlas-plan"><span className="eyebrow">PLAN · {run.plan.plan_id.slice(-8)}</span><h2>{run.plan.objective}</h2><ol>{(run.plan.steps ?? []).map((step) => <li key={step.step_id} data-state={step.state}><span className="plan-marker" /><div><strong>{step.title}</strong><small>{step.specialist} · {step.tool_name} · attempt {step.attempts}/{step.max_attempts}</small><p>{step.rationale}</p>{step.error ? <em>{step.error}</em> : null}</div></li>)}</ol></section>; }

/** Real roster (`GET /specialists`) crossed with this run's own steps -- a
 * specialist this run never assigned is shown idle, never hidden or
 * animated as if it were working. */
function SpecialistRail({ run, roster }: { run: AtlasRunResponse; roster: AtlasSpecialistIdentity[] }) {
  const entries = buildSpecialistActivity(run, roster);
  return <aside className="atlas-specialists"><span className="eyebrow">SPECIALISTS</span>{entries.map((entry) => <div key={entry.specialist} data-state={entry.state}><span className={`specialist-signal ${entry.state}`} /><strong>{entry.displayName}</strong><small>{entry.state}{entry.steps.length ? ` · ${entry.steps[entry.steps.length - 1]!.title}` : ""}</small></div>)}</aside>;
}

function CouncilInspector({ run }: { run: AtlasRunResponse }) { const council = run.council ?? []; return <aside className="atlas-council"><span className="eyebrow">COUNCIL · EVIDENCE</span>{council.length ? council.map((item) => <article key={`${item.specialist}-${item.conclusion}`}><strong>{item.specialist}</strong><p>{item.conclusion}</p>{(item.objections ?? []).map((objection) => <small key={objection}>Objection: {objection}</small>)}{(item.evidence ?? []).map((evidence) => <code key={evidence.evidence_id}>{evidence.evidence_id}</code>)}</article>) : <p>Conclusions will appear only after a real tool records evidence.</p>}</aside>; }
function AtlasPulse({ memories, resources, onRefresh }: { memories: AtlasMemoryRecord[]; resources: AtlasResourceSnapshot | null; onRefresh: () => void }) { return <section className="atlas-run-grid" aria-label="Atlas memory and resource pulse"><aside className="atlas-council"><span className="eyebrow">MEMORY · INSPECTOR</span>{memories.length ? memories.map((memory) => <article key={memory.memory_id}><strong>{memory.scope} · {memory.confidence}</strong><p>{memory.content}</p><small>{memory.source}</small></article>) : <p>No memories loaded. Atlas memory is durable, scoped, and user-reviewable.</p>}</aside><aside className="atlas-specialists"><span className="eyebrow">ATLAS PULSE</span>{resources ? <><strong>{resources.cpu_count} CPU threads</strong><small>{resources.memory_available_mb ?? "Unknown"} MB RAM available</small><small>{resources.gpu_available ? `${resources.gpu_name ?? "GPU"} · ${resources.vram_total_mb ?? "unknown"} MB VRAM` : resources.gpu_telemetry_detail}</small></> : <p>Refresh to inspect real host capability and active workloads.</p>}<button className="secondary" onClick={onRefresh}>Refresh Atlas Pulse</button></aside><aside className="atlas-council"><span className="eyebrow">RESEARCH · CITATIONS</span><p>Researcher only accepts specific allowlisted HTTPS sources. Web material stays untrusted and is kept distinct from local evidence.</p></aside></section>; }

/** Cortex V2: the same real, durable graph -- extended, never replaced --
 * with a kind filter (derived only from kinds actually present) and a
 * detail panel for whatever node is currently focused. */
function CortexV1({ graph }: { graph: CortexGraphState }) {
  const [focus, setFocus] = useState<string | null>(null); const [zoom, setZoom] = useState(1);
  const nodes = useMemo(() => graph.nodes ?? [], [graph]); const edges = graph.edges ?? [];
  const kinds = useMemo(() => [...new Set(nodes.map((node) => node.kind))].sort(), [nodes]);
  const [hiddenKinds, setHiddenKinds] = useState<Set<string>>(new Set());
  const positions = useMemo(() => Object.fromEntries(nodes.map((node, index) => [node.node_id, positionFor(node, index, nodes.length)])), [nodes]);
  const visible = (node: CortexNode) => !hiddenKinds.has(node.kind) && (!focus || node.node_id === focus || edges.some((edge) => (edge.source_node_id === focus && edge.target_node_id === node.node_id) || (edge.target_node_id === focus && edge.source_node_id === node.node_id)));
  const focusedNode = focus ? nodes.find((node) => node.node_id === focus) ?? null : null;
  function toggleKind(kind: string) { setHiddenKinds((prev) => { const next = new Set(prev); if (next.has(kind)) next.delete(kind); else next.add(kind); return next; }); }
  return <section className="cortex-v1" aria-label="Cortex real-state graph">
    <header><div><span className="eyebrow">CORTEX V1 · DURABLE STATE ONLY</span><h2>Run topology</h2><p>{nodes.length} real nodes · {edges.length} real relations · select a node to focus.</p></div><div className="cortex-controls"><button onClick={() => setZoom((value) => Math.min(1.5, value + 0.1))} aria-label="Zoom in Cortex">+</button><button onClick={() => setZoom((value) => Math.max(0.7, value - 0.1))} aria-label="Zoom out Cortex">−</button><button onClick={() => setFocus(null)} disabled={!focus}>Reset focus</button></div></header>
    <div className="cortex-filters" role="group" aria-label="Filter Cortex by node kind">{kinds.map((kind) => <button key={kind} type="button" className={`migration-chip ${hiddenKinds.has(kind) ? "" : "ready"}`} aria-pressed={!hiddenKinds.has(kind)} onClick={() => toggleKind(kind)}>{kind.replaceAll("_", " ")}</button>)}</div>
    <svg viewBox="0 0 800 420" role="img" aria-label="Cortex graph of this Atlas run" className="cortex-canvas"><g transform={`translate(400 210) scale(${zoom}) translate(-400 -210)`}>{edges.map((edge) => { const a = positions[edge.source_node_id]!, b = positions[edge.target_node_id]!; return <path key={edge.edge_id} className={focus && edge.source_node_id !== focus && edge.target_node_id !== focus ? "is-muted" : ""} d={`M ${a.x} ${a.y} Q ${(a.x + b.x) / 2} ${Math.min(a.y, b.y) - 36} ${b.x} ${b.y}`} />; })}{nodes.map((node) => { const point = positions[node.node_id]!; return <g key={node.node_id} className={`${visible(node) ? "" : "is-muted"} state-${node.state}${node.label.startsWith("Memory:") ? " is-memory" : ""}`} transform={`translate(${point.x} ${point.y})`} tabIndex={0} role="button" aria-label={`Focus ${node.label}`} onClick={() => setFocus(node.node_id)} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") setFocus(node.node_id); }}><circle r={node.kind === "run" ? 24 : 14} /><text y={node.kind === "run" ? 43 : 32}>{node.label.slice(0, 28)}</text></g>; })}</g></svg>
    {focusedNode ? <dl className="cortex-detail" aria-label="Selected Cortex node"><dt>Kind</dt><dd>{focusedNode.kind.replaceAll("_", " ")}</dd><dt>Label</dt><dd>{focusedNode.label}</dd><dt>State</dt><dd>{focusedNode.state}</dd><dt>Source ID</dt><dd className="acc-mono">{focusedNode.source_id}</dd></dl> : null}
    <ul className="cortex-legend"><li>Running / current</li><li>Recorded evidence</li><li>Blocked or cancelled</li></ul>
  </section>;
}
function positionFor(node: CortexNode, index: number, total: number) { if (node.kind === "run") return { x: 400, y: 210 }; const angle = (index / Math.max(1, total - 1)) * Math.PI * 2; const radius = node.kind === "evidence" ? 170 : 110; return { x: 400 + Math.cos(angle) * radius, y: 210 + Math.sin(angle) * radius }; }
