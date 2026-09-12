"use client";

import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";
import type { AtlasFeedbackEvent, AtlasMemoryRecord, AtlasResourceSnapshot, AtlasRunResponse, AtlasSpecialistIdentity, CortexGraphState } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { PipelineStepper } from "./atlas-run-activity";
import { AtlasCortex3D } from "./atlas-cortex-3d";
import { AtlasInspectorDrawer } from "./atlas-inspector-drawer";
import { AtlasCommandCenter } from "./atlas-command-center";
import { AtlasStatusBadge } from "./atlas-status-badge";
import { Icon } from "./icons";
import type { CortexSelection } from "./atlas-cortex-shared";

export { connectedStepIdForNode } from "./atlas-cortex-shared";

const terminal = new Set(["completed", "failed", "cancelled"]);

/**
 * ATLAS's immersive shell: a dedicated environment (top identity/status,
 * a dominant 3D Cortex, a bottom command bar, a side context inspector)
 * rather than another flat stack of panels in the ordinary PRISM tab body.
 * `onEnterImmersive`/`onExitImmersive` are optional so this still renders
 * correctly wherever a caller (a test, a future embed) doesn't wire them --
 * they only ever ask the *shell* to recede/restore its own nav chrome, never
 * fabricate or gate any Atlas data.
 */
export function AtlasWorkspace({
  datasetId,
  initialRunId,
  onEnterImmersive,
  onExitImmersive,
  onBackToProject,
}: {
  datasetId: string | undefined;
  initialRunId?: string | undefined;
  onEnterImmersive?: () => void;
  onExitImmersive?: () => void;
  onBackToProject?: () => void;
}) {
  const [objective, setObjective] = useState("Profile this dataset and identify the evidence needed for the next decision.");
  const [run, setRun] = useState<AtlasRunResponse | null>(null);
  const [graph, setGraph] = useState<CortexGraphState | null>(null);
  const [memories, setMemories] = useState<AtlasMemoryRecord[]>([]);
  const [resources, setResources] = useState<AtlasResourceSnapshot | null>(null);
  const [roster, setRoster] = useState<AtlasSpecialistIdentity[]>([]);
  const [runMemories, setRunMemories] = useState<AtlasMemoryRecord[]>([]);
  const [runFeedback, setRunFeedback] = useState<AtlasFeedbackEvent[]>([]);
  const [selectedStepId, setSelectedStepId] = useState<string | null>(null);
  const [selection, setSelection] = useState<CortexSelection>({ kind: "core" });
  const [systemOpen, setSystemOpen] = useState(false);
  const [resultExpanded, setResultExpanded] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const cancelStream = useRef<AbortController | null>(null);
  useEffect(() => () => cancelStream.current?.abort(), []);

  // Entering the Atlas tab collapses PRISM's own nav/inspector chrome so the
  // Cortex gets a dedicated environment; leaving (unmount, or "Back to
  // PRISM") restores it. Both are no-ops when the caller doesn't wire them.
  useEffect(() => {
    onEnterImmersive?.();
    return () => onExitImmersive?.();
    // Intentionally mount/unmount-only: the caller's callbacks are expected
    // to be stable enough to collapse/restore nav chrome once per Atlas tab
    // lifetime, not on every parent re-render (which would otherwise fight
    // the user's own manual rail/inspector toggles).
  }, []);

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
    if (!datasetId) return; setError(null); setRun(null); setGraph(null); setRunMemories([]); setRunFeedback([]); setSelectedStepId(null); setSelection({ kind: "core" }); setResultExpanded(false);
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

  const state = run?.plan.state ?? "ready";
  const running = state === "running";

  return (
    <div className="atlas-immersive">
      <header className="atlas-immersive-top">
        <div className="atlas-immersive-identity">
          <span className="eyebrow">ATLAS</span>
          <strong>Immersive Cortex</strong>
        </div>
        <AtlasStatusBadge />
        <button type="button" className="atlas-immersive-system-toggle" aria-expanded={systemOpen} onClick={() => setSystemOpen((value) => !value)}>
          {systemOpen ? "Hide system status" : "System status"}
        </button>
        {onBackToProject ? <button type="button" className="atlas-immersive-exit" onClick={onBackToProject}>Back to PRISM</button> : null}
      </header>
      {systemOpen ? <div className="atlas-immersive-system"><AtlasCommandCenter /></div> : null}
      {!datasetId ? (
        <section className="atlas-state empty-state">
          <span className="eyebrow">ATLAS · LOCAL ORCHESTRATION</span>
          <h1>Load a dataset before opening an investigation.</h1>
          <p>Atlas plans against durable dataset metadata and never ships raw rows to a provider.</p>
        </section>
      ) : (
        <div className="atlas-immersive-body">
          {run ? <PipelineStepper run={run} onSelectStage={(stage) => setSelection({ kind: "pipeline", stage })} /> : null}
          {run ? <RunJourney run={run} selectedStepId={selectedStepId} onSelectStep={setSelectedStepId} /> : null}
          {error ? <p className="query-error" role="alert">{error}</p> : null}
          <div className="atlas-immersive-main">
            <div className="atlas-immersive-stage-wrap">
              <AtlasCortex3D graph={graph} run={run} selectedStepId={selectedStepId} onSelectStep={setSelectedStepId} onSelectNode={setSelection} />
              {run ? <AtlasResultPanel run={run} expanded={resultExpanded} onToggle={() => setResultExpanded((value) => !value)} /> : null}
            </div>
            {run ? (
              <AtlasInspectorDrawer
                run={run}
                roster={roster}
                selectedStepId={selectedStepId}
                onSelectStep={setSelectedStepId}
                runMemories={runMemories}
                runFeedback={runFeedback}
                memories={memories}
                resources={resources}
                onRefreshPulse={() => void refreshPulse()}
                selection={selection}
              />
            ) : null}
          </div>
          <AtlasCommandBar
            objective={objective}
            onObjectiveChange={setObjective}
            onRun={() => void start()}
            onCancel={() => void cancel()}
            running={running}
            canCancel={Boolean(run) && !terminal.has(run?.plan.state ?? "")}
          />
        </div>
      )}
    </div>
  );
}

/** The primary ATLAS input as a bottom command surface: objective entry,
 * Enter-to-submit (Shift+Enter for a newline), Run/Cancel, and a truthfully
 * disabled microphone -- voice input has no backend in this phase, so the
 * control is never wired to fake recording. */
function AtlasCommandBar({ objective, onObjectiveChange, onRun, onCancel, running, canCancel }: { objective: string; onObjectiveChange(value: string): void; onRun(): void; onCancel(): void; running: boolean; canCancel: boolean }) {
  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (!running) onRun();
    }
  }
  return (
    <section className="atlas-command atlas-command-bar" aria-label="Atlas investigation">
      <label htmlFor="atlas-objective">Investigation objective</label>
      <div className="atlas-command-row">
        <button type="button" className="atlas-mic-button" disabled aria-disabled="true" title="Voice input is not available in this phase.">
          <Icon name="mic-off" />
          <span className="acc-visually-hidden">Microphone input is unavailable in this phase</span>
        </button>
        <textarea id="atlas-objective" value={objective} onChange={(event) => onObjectiveChange(event.target.value)} onKeyDown={onKeyDown} maxLength={2000} rows={1} placeholder="What should Atlas investigate? (Enter to run, Shift+Enter for a new line)" />
        <div className="atlas-command-actions">
          <button onClick={onRun} disabled={running}>Run investigation</button>
          {canCancel ? <button className="secondary" onClick={onCancel}>Cancel run</button> : null}
        </div>
      </div>
    </section>
  );
}

/** The grounded answer, collapsed to a one-line preview by default so the
 * Cortex stays the visual focus -- expand on demand for the full answer,
 * uncertainty, and a real evidence/feedback count. Never a generic chat
 * bubble: this is a single durable run's result, not a conversation. */
function AtlasResultPanel({ run, expanded, onToggle }: { run: AtlasRunResponse; expanded: boolean; onToggle(): void }) {
  const evidenceCount = new Set([...(run.evidence ?? []).map((item) => item.evidence_id), ...(run.council ?? []).flatMap((item) => (item.evidence ?? []).map((evidence) => evidence.evidence_id))]).size;
  const hasAnswer = Boolean(run.answer);
  return (
    <section className={`atlas-result-panel${expanded ? " is-expanded" : ""}`} aria-label="Atlas result">
      <button type="button" className="atlas-result-toggle" aria-expanded={expanded} onClick={onToggle}>
        <Icon name="expand" />
        <span>{hasAnswer ? "Grounded answer ready" : "Atlas is collecting durable evidence"}</span>
        <small>{evidenceCount} evidence · {expanded ? "collapse" : "expand"}</small>
      </button>
      <div className="atlas-answer" aria-live="polite">
        <span className="eyebrow">ATLAS · GROUNDED ANSWER</span>
        <h2>{run.answer ?? "Atlas is collecting durable evidence."}</h2>
        {run.uncertainty ? <p><strong>Uncertainty:</strong> {run.uncertainty}</p> : null}
      </div>
    </section>
  );
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
