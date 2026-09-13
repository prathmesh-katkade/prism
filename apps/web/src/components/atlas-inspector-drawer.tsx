"use client";

/**
 * The unified context inspector. A compact "Summary" view (dataset stats,
 * this run's own recorded step outcomes, and its real evidence -- the
 * reference layout) is the default; every existing detailed panel (plan,
 * council, guardrails, tools, evidence detail, memory, pulse) moves under
 * "Records" rather than being removed, so nothing already built is lost.
 * Nothing here computes a new fact: it reads the same `AtlasRunResponse`/
 * `OverviewProfileResponse` fields and calls the same `atlas-run-activity`
 * builders every panel already used.
 *
 * At narrow widths this same content becomes a modal drawer (role="dialog",
 * focus containment, Escape-to-close, focus restored to the trigger) rather
 * than an always-on column, per the responsive/accessibility requirement;
 * above that breakpoint it renders as the plain in-flow aside it always was.
 */
import { useEffect, useRef, useState } from "react";
import type { AtlasFeedbackEvent, AtlasMemoryRecord, AtlasResourceSnapshot, AtlasRunResponse, AtlasSpecialistIdentity, OverviewProfileResponse } from "@prism/api-contracts";
import { PIPELINE_STAGES, buildEvidenceLineage, buildSpecialistActivity, EvidencePanel, GuardrailPanel, RunMemoryTrace, ToolTimeline } from "./atlas-run-activity";
import { isMemoryNode, type CortexSelection } from "./atlas-cortex-shared";

const NARROW_QUERY = "(max-width: 780px)";

function useNarrowViewport(): boolean {
  const [narrow, setNarrow] = useState(false);
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia(NARROW_QUERY);
    setNarrow(query.matches);
    const onChange = () => setNarrow(query.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);
  return narrow;
}

const FOCUSABLE = 'a[href],button:not([disabled]),textarea,input,select,[tabindex]:not([tabindex="-1"])';

/** Minimal, self-contained focus trap for the narrow-viewport modal drawer:
 * moves focus in on open, restores it to whatever triggered the drawer on
 * close, cycles Tab/Shift+Tab within the dialog, and closes on Escape. */
function useDrawerFocusTrap(active: boolean, containerRef: React.RefObject<HTMLElement | null>, onClose: () => void) {
  useEffect(() => {
    if (!active) return;
    const container = containerRef.current;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const focusables = () => Array.from(container?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? []);
    (focusables()[0] ?? container)?.focus();
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") { event.preventDefault(); onClose(); return; }
      if (event.key !== "Tab") return;
      const items = focusables();
      if (!items.length) return;
      const first = items[0]!;
      const last = items[items.length - 1]!;
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [active, containerRef, onClose]);
}

export function AtlasInspectorDrawer({
  run,
  datasetProfile,
  roster,
  selectedStepId,
  onSelectStep,
  runMemories,
  runFeedback,
  memories,
  resources,
  onRefreshPulse,
  selection,
  openNarrow = false,
  onCloseNarrow,
}: {
  run: AtlasRunResponse;
  datasetProfile: OverviewProfileResponse | null;
  roster: AtlasSpecialistIdentity[];
  selectedStepId: string | null;
  onSelectStep(stepId: string): void;
  runMemories: AtlasMemoryRecord[];
  runFeedback: AtlasFeedbackEvent[];
  memories: AtlasMemoryRecord[];
  resources: AtlasResourceSnapshot | null;
  onRefreshPulse(): void;
  selection: CortexSelection;
  openNarrow?: boolean;
  onCloseNarrow?(): void;
}) {
  // Records (the pre-existing detailed panels) stays the default so every
  // established panel is reachable the instant the inspector opens, exactly
  // as before; Summary is the new, additive compact view one click away.
  const [view, setView] = useState<"summary" | "records">("records");
  const narrow = useNarrowViewport();
  const containerRef = useRef<HTMLElement | null>(null);
  const closeNarrow = onCloseNarrow ?? (() => undefined);
  useDrawerFocusTrap(narrow && openNarrow, containerRef, closeNarrow);

  // Above the narrow breakpoint the inspector is always in-flow; below it,
  // it only exists in the DOM while explicitly opened, so it can never trap
  // focus or announce itself while invisible.
  if (narrow && !openNarrow) return null;

  const content = (
    <>
      <header className="atlas-inspector-focus">
        <div>
          <span className="eyebrow">INSPECTOR · CURRENT FOCUS</span>
          <strong>{focusLabel(selection)}</strong>
        </div>
        {narrow ? <button type="button" className="atlas-inspector-close" onClick={closeNarrow} aria-label="Close inspector">×</button> : null}
      </header>
      <div className="atlas-inspector-tabs" role="tablist" aria-label="Inspector view">
        <button type="button" role="tab" aria-selected={view === "summary"} className={view === "summary" ? "is-selected" : ""} onClick={() => setView("summary")}>Summary</button>
        <button type="button" role="tab" aria-selected={view === "records"} className={view === "records" ? "is-selected" : ""} onClick={() => setView("records")}>Records</button>
      </div>
      {view === "summary" ? (
        <InspectorSummary run={run} datasetProfile={datasetProfile} />
      ) : (
        <div className="atlas-inspector-records">
          <PlanTimeline run={run} selectedStepId={selectedStepId} onSelectStep={onSelectStep} />
          <SpecialistRail run={run} roster={roster} selectedStepId={selectedStepId} onSelectStep={onSelectStep} />
          <CouncilInspector run={run} selectedStepId={selectedStepId} />
          <GuardrailPanel run={run} />
          <ToolTimeline run={run} />
          <EvidencePanel run={run} />
          <RunMemoryTrace run={run} memories={runMemories} feedback={runFeedback} />
          <AtlasPulse memories={memories} resources={resources} onRefresh={onRefreshPulse} />
        </div>
      )}
    </>
  );

  if (narrow) {
    // The scrim is a sibling of the dialog, not its wrapper: `aria-hidden`
    // on a container also hides every descendant, which would take the
    // dialog itself out of the accessibility tree along with it. As a
    // sibling, it can be a purely decorative, pointer-only backdrop
    // (Escape and the explicit close button already cover the keyboard/
    // screen-reader path) without touching the dialog's own accessibility.
    return (
      <>
        <div className="atlas-inspector-scrim" aria-hidden="true" onClick={closeNarrow} />
        <aside ref={containerRef as React.RefObject<HTMLElement>} className="atlas-inspector-drawer is-modal" role="dialog" aria-modal="true" aria-label="Atlas context inspector">
          {content}
        </aside>
      </>
    );
  }
  return (
    <aside className="atlas-inspector-drawer" aria-label="Atlas context inspector">
      {content}
    </aside>
  );
}

function focusLabel(selection: CortexSelection): string {
  if (selection.kind === "core") return "Run overview";
  if (selection.kind === "pipeline") return `Pipeline stage: ${PIPELINE_STAGES.find((stage) => stage.id === selection.stage)?.label ?? selection.stage}`;
  if (selection.kind === "group") return `${selection.group.label}: ${selection.group.status}`;
  const { node } = selection;
  if (isMemoryNode(node)) return `Memory: ${node.label.replace(/^Memory:\s*/, "")}`;
  const kindLabel = node.kind.replaceAll("_", " ");
  return `${kindLabel[0]!.toUpperCase()}${kindLabel.slice(1)}: ${node.label}`;
}

const STEP_ICON: Record<string, string> = { completed: "done", running: "active", blocked: "warn", failed: "warn", cancelled: "warn", pending: "pending" };

/** The compact reference-matching default view: real dataset stats, this
 * run's own step outcomes as a plain honest checklist (a mint check for
 * completed, an amber notice with the step's own recorded reason for
 * blocked/failed/cancelled -- never smoothed into "all good"), and its
 * real deduped evidence. */
function InspectorSummary({ run, datasetProfile }: { run: AtlasRunResponse; datasetProfile: OverviewProfileResponse | null }) {
  const steps = run.plan.steps ?? [];
  const evidence = buildEvidenceLineage(run);
  const blockedSteps = steps.filter((step) => step.state === "blocked" || step.state === "failed" || step.state === "cancelled");
  return (
    <div className="atlas-inspector-summary">
      <section className="atlas-summary-dataset">
        <span className="eyebrow">DATASET</span>
        {datasetProfile ? (
          <>
            <p className="atlas-summary-filename acc-mono">{datasetProfile.dataset.source_name}</p>
            <dl className="atlas-summary-stats">
              <div><dd>{datasetProfile.quality.n_rows.toLocaleString()}</dd><dt>Rows</dt></div>
              <div><dd>{datasetProfile.quality.n_cols}</dd><dt>Columns</dt></div>
              <div><dd>{datasetProfile.health.total}<small>/100</small></dd><dt>Health</dt></div>
              <div><dd>{formatPercent(datasetProfile.quality.total_missing_pct)}</dd><dt>Missing</dt></div>
            </dl>
          </>
        ) : (
          <p className="atlas-summary-empty">Dataset profile is unavailable -- inspect Overview to confirm the source is reachable.</p>
        )}
      </section>
      <section className="atlas-summary-work">
        <span className="eyebrow">RECORDED WORK</span>
        {steps.length ? (
          <ul>
            {steps.map((step) => (
              <li key={step.step_id} data-icon={STEP_ICON[step.state ?? "pending"] ?? "pending"}>
                <span className="atlas-summary-work-icon" aria-hidden="true" />
                <div>
                  <strong>{step.title}</strong>
                  {step.state === "blocked" || step.state === "failed" || step.state === "cancelled" ? <small>{step.error ?? `${step.state.replaceAll("_", " ")} -- additional context required.`}</small> : null}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="atlas-summary-empty">No plan steps recorded yet.</p>
        )}
      </section>
      <section className="atlas-summary-evidence">
        <span className="eyebrow">EVIDENCE</span>
        {evidence.length ? (
          <ul>
            {evidence.map((entry) => (
              <li key={entry.evidence_id}>
                <span>{EVIDENCE_KIND_SHORT[entry.kind] ?? entry.kind.replaceAll("_", " ")}</span>
                <small className="acc-mono">{entry.evidence_id}</small>
              </li>
            ))}
          </ul>
        ) : (
          <p className="atlas-summary-empty">No evidence recorded for this run yet.</p>
        )}
      </section>
      {blockedSteps.length ? (
        <p className="atlas-summary-limitation" role="note">
          {blockedSteps.length} step{blockedSteps.length === 1 ? "" : "s"} could not complete. Results below reflect only what was actually recorded.
        </p>
      ) : null}
      {run.uncertainty ? <p className="atlas-summary-limitation" role="note">{run.uncertainty}</p> : null}
    </div>
  );
}

const EVIDENCE_KIND_SHORT: Record<string, string> = {
  dataset_revision: "Dataset revision",
  overview_profile: "Overview profile",
  analytical_object: "Analytical object",
  tool_output: "Tool output",
  web_research: "Web research",
  memory: "Memory",
  project_knowledge: "Project knowledge",
};

function formatPercent(value: number): string {
  return `${value.toFixed(value % 1 === 0 ? 0 : 2)}%`;
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
