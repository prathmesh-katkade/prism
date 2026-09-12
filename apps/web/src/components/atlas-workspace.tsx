"use client";

import { useEffect, useRef, useState } from "react";
import type { AtlasFeedbackEvent, AtlasMemoryRecord, AtlasResourceSnapshot, AtlasRunResponse, AtlasSpecialistIdentity, CortexGraphState } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { buildSpecialistActivity, EvidencePanel, GuardrailPanel, PipelineStepper, RunMemoryTrace, ToolTimeline } from "./atlas-run-activity";
import { AtlasCortex3D } from "./atlas-cortex-3d";

export { connectedStepIdForNode } from "./atlas-cortex-shared";

const terminal = new Set(["completed", "failed", "cancelled"]);

export function AtlasWorkspace({ datasetId, initialRunId }: { datasetId: string | undefined; initialRunId?: string | undefined }) {
  const [objective, setObjective] = useState("Profile this dataset and identify the evidence needed for the next decision.");
  const [run, setRun] = useState<AtlasRunResponse | null>(null);
  const [graph, setGraph] = useState<CortexGraphState | null>(null);
  const [memories, setMemories] = useState<AtlasMemoryRecord[]>([]);
  const [resources, setResources] = useState<AtlasResourceSnapshot | null>(null);
  const [roster, setRoster] = useState<AtlasSpecialistIdentity[]>([]);
  const [runMemories, setRunMemories] = useState<AtlasMemoryRecord[]>([]);
  const [runFeedback, setRunFeedback] = useState<AtlasFeedbackEvent[]>([]);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
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
    if (runResponse.ok) {
      const nextRun = await runResponse.json() as AtlasRunResponse;
      if (nextRun.plan.dataset_id !== datasetId) return;
      setRun(nextRun);
      if (graphResponse.ok) setGraph(await graphResponse.json() as CortexGraphState);
    }
  }
  useEffect(() => {
    if (datasetId && initialRunId) void refresh(initialRunId);
  }, [datasetId, initialRunId]);
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
    if (!datasetId) return; setError(null); setRun(null); setGraph(null); setRunMemories([]); setRunFeedback([]); setSelectedStepId(null);
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
  useEffect(() => {
    if (!run) return;
    const steps = run.plan.steps ?? [];
    if (!steps.length) { setSelectedStepId(null); return; }
    const stillExists = selectedStepId && steps.some((step) => step.step_id === selectedStepId);
    if (stillExists) return;
    const current = steps.find((step) => step.state === "running") ?? [...steps].reverse().find((step) => step.state === "completed") ?? steps[0];
    setSelectedStepId(current?.step_id ?? null);
  }, [run, selectedStepId]);
  if (!datasetId) return <section className="atlas-state empty-state"><span className="eyebrow">ATLAS · LOCAL ORCHESTRATION</span><h1>Load a dataset before opening an investigation.</h1><p>Atlas plans against durable dataset metadata and never ships raw rows to a provider.</p></section>;
  const state = run?.plan.state ?? "ready";
  return <article className="atlas-workspace">
    <header className="atlas-heading"><div><span className="eyebrow">ATLAS · OPERATIONS DESK</span><h1>Make the analytical route inspectable.</h1><p>Plans are advisory until PRISM validates every declared tool. Evidence, objections, and events are durable.</p></div><span className={`migration-chip ${state === "failed" ? "unavailable" : "ready"}`} aria-live="polite">{state.replaceAll("_", " ")}</span></header>
    <section className="atlas-command" aria-label="Atlas investigation"><label htmlFor="atlas-objective">Investigation objective</label><textarea id="atlas-objective" value={objective} onChange={(event) => setObjective(event.target.value)} maxLength={2000} /><div><button onClick={() => void start()} disabled={state === "running"}>Run investigation</button>{run && !terminal.has(run.plan.state ?? "") ? <button className="secondary" onClick={() => void cancel()}>Cancel run</button> : null}</div></section>
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    {run ? <>
      <RunJourney run={run} selectedStepId={selectedStepId} onSelectStep={setSelectedStepId} />
      <PipelineStepper run={run} />
      <section className="atlas-run-grid"><PlanTimeline run={run} selectedStepId={selectedStepId} onSelectStep={setSelectedStepId} /><SpecialistRail run={run} roster={roster} selectedStepId={selectedStepId} onSelectStep={setSelectedStepId} /><CouncilInspector run={run} selectedStepId={selectedStepId} /></section>
      <section className="atlas-answer" aria-live="polite"><span className="eyebrow">ATLAS · GROUNDED ANSWER</span><h2>{run.answer ?? "Atlas is collecting durable evidence."}</h2>{run.uncertainty ? <p><strong>Uncertainty:</strong> {run.uncertainty}</p> : null}</section>
      <GuardrailPanel run={run} />
      <ToolTimeline run={run} />
      <EvidencePanel run={run} />
      <RunMemoryTrace run={run} memories={runMemories} feedback={runFeedback} />
      <AtlasPulse memories={memories} resources={resources} onRefresh={() => void refreshPulse()} />
      {graph ? <AtlasCortex3D graph={graph} run={run} selectedStepId={selectedStepId} onSelectStep={setSelectedStepId} /> : null}
    </> : null}
  </article>;
}

function RunJourney({ run, selectedStepId, onSelectStep }: { run: AtlasRunResponse; selectedStepId: string | null; onSelectStep(stepId: string): void }) {
  const steps = run.plan.steps ?? [];
  if (!steps.length) return null;
  return <section className="atlas-run-journey" aria-label="Atlas active investigation journey">
    <header><div><span className="eyebrow">LIVE INVESTIGATION · DURABLE RUN</span><h2>Follow the declared route.</h2></div><span className="acc-mono">{run.run_id}</span></header>
    <ol>{steps.map((step, index) => <li key={step.step_id} data-state={step.state} className={step.step_id === selectedStepId ? "is-selected" : ""}><button type="button" onClick={() => onSelectStep(step.step_id)} aria-pressed={step.step_id === selectedStepId}><span className="journey-index">{String(index + 1).padStart(2, "0")}</span><strong>{step.title}</strong><small>{step.specialist} · {step.tool_name}</small><span className="migration-chip">{(step.state ?? "pending").replaceAll("_", " ")}</span></button></li>)}</ol>
    <p>Selection links the declared plan step to its specialist, tool, and Cortex records. It does not imply activity beyond the persisted run state.</p>
  </section>;
}

function PlanTimeline({ run, selectedStepId, onSelectStep }: { run: AtlasRunResponse; selectedStepId: string | null; onSelectStep(stepId: string): void }) { return <section className="atlas-plan"><span className="eyebrow">PLAN · {run.plan.plan_id.slice(-8)}</span><h2>{run.plan.objective}</h2><ol>{(run.plan.steps ?? []).map((step) => <li key={step.step_id} data-state={step.state} className={step.step_id === selectedStepId ? "is-selected" : ""}><button type="button" onClick={() => onSelectStep(step.step_id)} aria-pressed={step.step_id === selectedStepId}><span className="plan-marker" /><div><strong>{step.title}</strong><small>{step.specialist} · {step.tool_name} · attempt {step.attempts}/{step.max_attempts}</small><p>{step.rationale}</p>{step.error ? <em>{step.error}</em> : null}</div></button></li>)}</ol></section>; }

/** Real roster (`GET /specialists`) crossed with this run's own steps -- a
 * specialist this run never assigned is shown idle, never hidden or
 * animated as if it were working. */
function SpecialistRail({ run, roster, selectedStepId, onSelectStep }: { run: AtlasRunResponse; roster: AtlasSpecialistIdentity[]; selectedStepId: string | null; onSelectStep(stepId: string): void }) {
  const entries = buildSpecialistActivity(run, roster);
  return <aside className="atlas-specialists"><span className="eyebrow">SPECIALISTS</span>{entries.map((entry) => { const step = entry.steps.find((item) => item.step_id === selectedStepId) ?? entry.steps.find((item) => item.state === "running") ?? entry.steps.at(-1); return <button key={entry.specialist} type="button" data-state={entry.state} className={step?.step_id === selectedStepId ? "is-selected" : ""} onClick={() => step && onSelectStep(step.step_id)} disabled={!step} aria-pressed={step?.step_id === selectedStepId}><span className={`specialist-signal ${entry.state}`} /><strong>{entry.displayName}</strong><small>{entry.state}{step ? ` · ${step.title}` : ""}</small></button>; })}</aside>;
}

function CouncilInspector({ run, selectedStepId }: { run: AtlasRunResponse; selectedStepId: string | null }) { const council = run.council ?? []; const selectedStep = (run.plan.steps ?? []).find((step) => step.step_id === selectedStepId); const selectedCouncil = selectedStep ? council.filter((item) => item.specialist === selectedStep.specialist) : council; return <aside className="atlas-council"><span className="eyebrow">COUNCIL · EVIDENCE</span>{selectedStep ? <p className="atlas-selection-caption">Showing evidence reported by <strong>{selectedStep.specialist}</strong> for the selected plan step.</p> : null}{selectedCouncil.length ? selectedCouncil.map((item) => <article key={`${item.specialist}-${item.conclusion}`}><strong>{item.specialist}</strong><p>{item.conclusion}</p>{(item.objections ?? []).map((objection) => <small key={objection}>Objection: {objection}</small>)}{(item.evidence ?? []).map((evidence) => <code key={evidence.evidence_id}>{evidence.evidence_id}</code>)}</article>) : <p>{selectedStep ? "No conclusion is recorded for this selected step yet." : "Conclusions will appear only after a real tool records evidence."}</p>}</aside>; }
function AtlasPulse({ memories, resources, onRefresh }: { memories: AtlasMemoryRecord[]; resources: AtlasResourceSnapshot | null; onRefresh: () => void }) { return <section className="atlas-run-grid" aria-label="Atlas memory and resource pulse"><aside className="atlas-council"><span className="eyebrow">MEMORY · INSPECTOR</span>{memories.length ? memories.map((memory) => <article key={memory.memory_id}><strong>{memory.scope} · {memory.confidence}</strong><p>{memory.content}</p><small>{memory.source}</small></article>) : <p>No memories loaded. Atlas memory is durable, scoped, and user-reviewable.</p>}</aside><aside className="atlas-specialists"><span className="eyebrow">ATLAS PULSE</span>{resources ? <><strong>{resources.cpu_count} CPU threads</strong><small>{resources.memory_available_mb ?? "Unknown"} MB RAM available</small><small>{resources.gpu_available ? `${resources.gpu_name ?? "GPU"} · ${resources.vram_total_mb ?? "unknown"} MB VRAM` : resources.gpu_telemetry_detail}</small></> : <p>Refresh to inspect real host capability and active workloads.</p>}<button className="secondary" onClick={onRefresh}>Refresh Atlas Pulse</button></aside><aside className="atlas-council"><span className="eyebrow">RESEARCH · CITATIONS</span><p>Researcher only accepts specific allowlisted HTTPS sources. Web material stays untrusted and is kept distinct from local evidence.</p></aside></section>; }

