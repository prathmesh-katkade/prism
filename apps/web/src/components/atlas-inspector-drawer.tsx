"use client";

/**
 * The unified context inspector: one side drawer instead of a wall of
 * disconnected panels. Every section here already existed (plan, council,
 * specialists, guardrails, tools, evidence, memory, pulse) -- this module
 * only relocates them into one scrollable place and adds a synchronized
 * focus header that names whatever was last really clicked in the Cortex
 * (the core, a node, or a pipeline stage), via `CortexSelection`. Nothing
 * here computes a new fact: it reads the same `AtlasRunResponse` fields and
 * calls the same `atlas-run-activity` builders every panel already used.
 */
import type { AtlasFeedbackEvent, AtlasMemoryRecord, AtlasResourceSnapshot, AtlasRunResponse, AtlasSpecialistIdentity } from "@prism/api-contracts";
import { PIPELINE_STAGES, buildSpecialistActivity, EvidencePanel, GuardrailPanel, RunMemoryTrace, ToolTimeline } from "./atlas-run-activity";
import { isMemoryNode, type CortexSelection } from "./atlas-cortex-shared";

export function AtlasInspectorDrawer({
  run,
  roster,
  selectedStepId,
  onSelectStep,
  runMemories,
  runFeedback,
  memories,
  resources,
  onRefreshPulse,
  selection,
}: {
  run: AtlasRunResponse;
  roster: AtlasSpecialistIdentity[];
  selectedStepId: string | null;
  onSelectStep(stepId: string): void;
  runMemories: AtlasMemoryRecord[];
  runFeedback: AtlasFeedbackEvent[];
  memories: AtlasMemoryRecord[];
  resources: AtlasResourceSnapshot | null;
  onRefreshPulse(): void;
  selection: CortexSelection;
}) {
  return (
    <aside className="atlas-inspector-drawer" aria-label="Atlas context inspector">
      <header className="atlas-inspector-focus">
        <span className="eyebrow">INSPECTOR · CURRENT FOCUS</span>
        <strong>{focusLabel(selection)}</strong>
      </header>
      <PlanTimeline run={run} selectedStepId={selectedStepId} onSelectStep={onSelectStep} />
      <SpecialistRail run={run} roster={roster} selectedStepId={selectedStepId} onSelectStep={onSelectStep} />
      <CouncilInspector run={run} selectedStepId={selectedStepId} />
      <GuardrailPanel run={run} />
      <ToolTimeline run={run} />
      <EvidencePanel run={run} />
      <RunMemoryTrace run={run} memories={runMemories} feedback={runFeedback} />
      <AtlasPulse memories={memories} resources={resources} onRefresh={onRefreshPulse} />
    </aside>
  );
}

function focusLabel(selection: CortexSelection): string {
  if (selection.kind === "core") return "Run overview";
  if (selection.kind === "pipeline") return `Pipeline stage: ${PIPELINE_STAGES.find((stage) => stage.id === selection.stage)?.label ?? selection.stage}`;
  const { node } = selection;
  if (isMemoryNode(node)) return `Memory: ${node.label.replace(/^Memory:\s*/, "")}`;
  const kindLabel = node.kind.replaceAll("_", " ");
  return `${kindLabel[0]!.toUpperCase()}${kindLabel.slice(1)}: ${node.label}`;
}

function PlanTimeline({ run, selectedStepId, onSelectStep }: { run: AtlasRunResponse; selectedStepId: string | null; onSelectStep(stepId: string): void }) {
  return (
    <section className="atlas-plan">
      <span className="eyebrow">PLAN · {run.plan.plan_id.slice(-8)}</span>
      <h2>{run.plan.objective}</h2>
      <ol>
        {(run.plan.steps ?? []).map((step) => (
          <li key={step.step_id} data-state={step.state} className={step.step_id === selectedStepId ? "is-selected" : ""}>
            <button type="button" onClick={() => onSelectStep(step.step_id)} aria-pressed={step.step_id === selectedStepId}>
              <span className="plan-marker" />
              <div>
                <strong>{step.title}</strong>
                <small>{step.specialist} · {step.tool_name} · attempt {step.attempts}/{step.max_attempts}</small>
                <p>{step.rationale}</p>
                {step.error ? <em>{step.error}</em> : null}
              </div>
            </button>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** Real roster (`GET /specialists`) crossed with this run's own steps -- a
 * specialist this run never assigned is shown idle, never hidden or
 * animated as if it were working. */
function SpecialistRail({ run, roster, selectedStepId, onSelectStep }: { run: AtlasRunResponse; roster: AtlasSpecialistIdentity[]; selectedStepId: string | null; onSelectStep(stepId: string): void }) {
  const entries = buildSpecialistActivity(run, roster);
  return (
    <aside className="atlas-specialists">
      <span className="eyebrow">SPECIALISTS</span>
      {entries.map((entry) => {
        const step = entry.steps.find((item) => item.step_id === selectedStepId) ?? entry.steps.find((item) => item.state === "running") ?? entry.steps.at(-1);
        return (
          <button key={entry.specialist} type="button" data-state={entry.state} className={step?.step_id === selectedStepId ? "is-selected" : ""} onClick={() => step && onSelectStep(step.step_id)} disabled={!step} aria-pressed={step?.step_id === selectedStepId}>
            <span className={`specialist-signal ${entry.state}`} />
            <strong>{entry.displayName}</strong>
            <small>{entry.state}{step ? ` · ${step.title}` : ""}</small>
          </button>
        );
      })}
    </aside>
  );
}

function CouncilInspector({ run, selectedStepId }: { run: AtlasRunResponse; selectedStepId: string | null }) {
  const council = run.council ?? [];
  const selectedStep = (run.plan.steps ?? []).find((step) => step.step_id === selectedStepId);
  const selectedCouncil = selectedStep ? council.filter((item) => item.specialist === selectedStep.specialist) : council;
  return (
    <aside className="atlas-council">
      <span className="eyebrow">COUNCIL · EVIDENCE</span>
      {selectedStep ? <p className="atlas-selection-caption">Showing evidence reported by <strong>{selectedStep.specialist}</strong> for the selected plan step.</p> : null}
      {selectedCouncil.length ? selectedCouncil.map((item) => (
        <article key={`${item.specialist}-${item.conclusion}`}>
          <strong>{item.specialist}</strong>
          <p>{item.conclusion}</p>
          {(item.objections ?? []).map((objection) => <small key={objection}>Objection: {objection}</small>)}
          {(item.evidence ?? []).map((evidence) => <code key={evidence.evidence_id}>{evidence.evidence_id}</code>)}
        </article>
      )) : <p>{selectedStep ? "No conclusion is recorded for this selected step yet." : "Conclusions will appear only after a real tool records evidence."}</p>}
    </aside>
  );
}

function AtlasPulse({ memories, resources, onRefresh }: { memories: AtlasMemoryRecord[]; resources: AtlasResourceSnapshot | null; onRefresh: () => void }) {
  return (
    <section className="atlas-run-grid" aria-label="Atlas memory and resource pulse">
      <aside className="atlas-council">
        <span className="eyebrow">MEMORY · INSPECTOR</span>
        {memories.length ? memories.map((memory) => (
          <article key={memory.memory_id}>
            <strong>{memory.scope} · {memory.confidence}</strong>
            <p>{memory.content}</p>
            <small>{memory.source}</small>
          </article>
        )) : <p>No memories loaded. Atlas memory is durable, scoped, and user-reviewable.</p>}
      </aside>
      <aside className="atlas-specialists">
        <span className="eyebrow">ATLAS PULSE</span>
        {resources ? <>
          <strong>{resources.cpu_count} CPU threads</strong>
          <small>{resources.memory_available_mb ?? "Unknown"} MB RAM available</small>
          <small>{resources.gpu_available ? `${resources.gpu_name ?? "GPU"} · ${resources.vram_total_mb ?? "unknown"} MB VRAM` : resources.gpu_telemetry_detail}</small>
        </> : <p>Refresh to inspect real host capability and active workloads.</p>}
        <button className="secondary" onClick={onRefresh}>Refresh Atlas Pulse</button>
      </aside>
      <aside className="atlas-council">
        <span className="eyebrow">RESEARCH · CITATIONS</span>
        <p>Researcher only accepts specific allowlisted HTTPS sources. Web material stays untrusted and is kept distinct from local evidence.</p>
      </aside>
    </section>
  );
}
