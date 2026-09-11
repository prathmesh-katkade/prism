"use client";

/**
 * Shared, real-data-only building blocks for Atlas "activity" views -- tool
 * calls, specialist involvement, the guardrail decision, and a coarse
 * request->result pipeline stage -- derived purely from one already-fetched
 * `AtlasRunResponse` (its `plan.steps` and `events`, both durable) plus the
 * real specialist roster from `GET /api/v1/atlas/specialists`.
 *
 * Nothing here invents an event type, a specialist, or a "thinking" state:
 * every field traces back to a real `AtlasRunEventType` (run_created,
 * plan_created, step_started, step_completed, council_conclusion,
 * run_completed/failed/cancelled) or a real `AtlasStepState`
 * (pending/running/completed/failed/cancelled/blocked). There is no
 * "approved" state in the backend today (`requires_approval` exists on the
 * contract but the runtime never sets it) so it is never surfaced as one --
 * see the ToolTimelineStatus union below.
 *
 * Used by both the per-run `AtlasWorkspace` (live, SSE-driven) and the
 * system-level `AtlasCommandCenter` (a static fetch of recent runs), so the
 * same real transform and the same presentational components back both.
 */

import type { AtlasFeedbackEvent, AtlasMemoryRecord, AtlasRunEvent, AtlasRunResponse, AtlasSpecialistId, AtlasSpecialistIdentity } from "@prism/api-contracts";

// --- Evidence lineage --------------------------------------------------------

export type EvidenceLineageEntry = {
  evidence_id: string;
  kind: string;
  summary: string;
  dataset_id: string | null;
  dataset_revision: number | null;
  source_fingerprint: string | null;
  citedBy: string[];
};

const EVIDENCE_KIND_LABELS: Record<string, string> = {
  dataset_revision: "Dataset revision",
  overview_profile: "Overview profile",
  analytical_object: "Analytical object",
  tool_output: "Tool output",
  web_research: "Web research",
  memory: "Memory",
  project_knowledge: "Project knowledge",
};

/** Every real evidence reference this run recorded (`run.evidence`, the
 * durable deduped set), cross-referenced against council conclusions to
 * show which specialist(s) actually cited it -- real lineage, not an
 * inferred one. `AtlasEvidenceReference` carries no freshness/timestamp/
 * verification-state fields today, so this never fabricates them; only
 * evidence_id, kind, summary, dataset_id/revision, and source_fingerprint
 * are shown. */
export function buildEvidenceLineage(run: AtlasRunResponse): EvidenceLineageEntry[] {
  const byId = new Map<string, EvidenceLineageEntry>();
  const upsert = (item: { evidence_id: string; kind: string; summary: string; dataset_id?: string; dataset_revision?: number; source_fingerprint?: string }, specialist?: string) => {
    const existing = byId.get(item.evidence_id);
    if (existing) {
      if (specialist && !existing.citedBy.includes(specialist)) existing.citedBy.push(specialist);
      return;
    }
    byId.set(item.evidence_id, {
      evidence_id: item.evidence_id,
      kind: item.kind,
      summary: item.summary,
      dataset_id: item.dataset_id ?? null,
      dataset_revision: item.dataset_revision ?? null,
      source_fingerprint: item.source_fingerprint ?? null,
      citedBy: specialist ? [specialist] : [],
    });
  };
  for (const item of run.evidence ?? []) upsert(item);
  for (const conclusion of run.council ?? []) {
    for (const item of conclusion.evidence ?? []) upsert(item, conclusion.specialist);
  }
  return [...byId.values()];
}

export function EvidencePanel({ run }: { run: AtlasRunResponse }) {
  const entries = buildEvidenceLineage(run);
  return (
    <section className="atlas-evidence" aria-label="Atlas evidence">
      <span className="eyebrow">EVIDENCE{entries.length ? ` · ${entries.length} RECORD${entries.length === 1 ? "" : "S"}` : ""}</span>
      {entries.length ? (
        <ul>
          {entries.map((entry) => (
            <li key={entry.evidence_id}>
              <details>
                <summary>
                  <span className="migration-chip ready">{EVIDENCE_KIND_LABELS[entry.kind] ?? entry.kind.replaceAll("_", " ")}</span>
                  <strong className="acc-mono">{entry.evidence_id}</strong>
                </summary>
                <dl>
                  <dt>Summary</dt>
                  <dd>{entry.summary}</dd>
                  {entry.dataset_id ? (
                    <>
                      <dt>Dataset</dt>
                      <dd className="acc-mono">
                        {entry.dataset_id}
                        {entry.dataset_revision !== null ? ` · revision ${entry.dataset_revision}` : ""}
                      </dd>
                    </>
                  ) : null}
                  {entry.source_fingerprint ? (
                    <>
                      <dt>Source fingerprint</dt>
                      <dd className="acc-mono">{entry.source_fingerprint}</dd>
                    </>
                  ) : null}
                  {entry.citedBy.length ? (
                    <>
                      <dt>Cited by</dt>
                      <dd>{entry.citedBy.join(", ")}</dd>
                    </>
                  ) : null}
                </dl>
              </details>
            </li>
          ))}
        </ul>
      ) : (
        <p>No evidence has been recorded for this run yet.</p>
      )}
    </section>
  );
}

// --- Guardrail decision -----------------------------------------------------

export type GuardrailFinding = { category: string; rule: string; subject: string; detail: string; state: string };
export type GuardrailDecision = { policy_version: string; authority: string; state: string; findings: GuardrailFinding[]; decision_id: string };

/** The server's deterministic guardrails (atlas_guardrails.py, policy
 * atlas-guardrails-v1) record their decision in the run's plan_created
 * event payload -- real, already-persisted data with no dedicated contract
 * type yet. Parsed defensively: a missing or malformed payload returns
 * `null` rather than a fabricated "all clear". */
export function guardrailDecisionFor(run: AtlasRunResponse): GuardrailDecision | null {
  const event = (run.events ?? []).find((item) => item.type === "plan_created");
  const raw = event?.payload?.["guardrail_decision"];
  if (!raw || typeof raw !== "object") return null;
  const value = raw as Record<string, unknown>;
  if (typeof value.state !== "string" || typeof value.policy_version !== "string" || typeof value.decision_id !== "string") return null;
  const findings = Array.isArray(value.findings)
    ? (value.findings.filter(
        (item): item is GuardrailFinding =>
          typeof item === "object" && item !== null && typeof (item as Record<string, unknown>).category === "string" && typeof (item as Record<string, unknown>).state === "string"
      ) as GuardrailFinding[])
    : [];
  return { policy_version: value.policy_version, authority: typeof value.authority === "string" ? value.authority : "server", state: value.state, findings, decision_id: value.decision_id };
}

const GUARDRAIL_CATEGORY_LABELS: Record<string, string> = {
  evidence: "Evidence Integrity",
  python: "Python Safety",
  target: "Target Leakage",
  temporal: "Temporal Leakage",
};
const GUARDRAIL_CATEGORY_ORDER = ["evidence", "python", "target", "temporal"];

function toneFor(state: string): string {
  return state === "blocked" ? "unavailable" : state === "verification_required" ? "bridged" : "ready";
}

export function GuardrailPanel({ run }: { run: AtlasRunResponse }) {
  const decision = guardrailDecisionFor(run);
  if (!decision) return null;
  const groups = new Map<string, GuardrailFinding[]>();
  for (const finding of decision.findings) {
    const list = groups.get(finding.category) ?? [];
    list.push(finding);
    groups.set(finding.category, list);
  }
  const orderedCategories = [...GUARDRAIL_CATEGORY_ORDER.filter((category) => groups.has(category)), ...[...groups.keys()].filter((category) => !GUARDRAIL_CATEGORY_ORDER.includes(category))];
  return (
    <section className="atlas-guardrails" aria-label="Atlas server guardrails">
      <header>
        <span className="eyebrow">ATLAS GUARDRAILS · {decision.policy_version}</span>
        <span className={`migration-chip ${toneFor(decision.state)}`}>{decision.state.replaceAll("_", " ")}</span>
      </header>
      {decision.findings.length ? (
        orderedCategories.map((category) => (
          <div key={category} className="guardrail-group">
            <h3>{GUARDRAIL_CATEGORY_LABELS[category] ?? category.replaceAll("_", " ")}</h3>
            <ul>
              {(groups.get(category) ?? []).map((finding, index) => (
                <li key={`${finding.category}-${finding.rule}-${index}`} data-state={finding.state}>
                  <details>
                    <summary>
                      <strong>{finding.rule.replaceAll("_", " ")}</strong>
                      <span className={`migration-chip ${toneFor(finding.state)}`}>{finding.state.replaceAll("_", " ")}</span>
                    </summary>
                    <dl>
                      <dt>Subject</dt>
                      <dd>{finding.subject}</dd>
                      <dt>Reason</dt>
                      <dd>{finding.detail}</dd>
                      <dt>Decision ID</dt>
                      <dd className="acc-mono">{decision.decision_id}</dd>
                    </dl>
                  </details>
                </li>
              ))}
            </ul>
          </div>
        ))
      ) : (
        <p>No findings -- the request cleared evidence, Python-safety, and leakage checks with nothing to flag.</p>
      )}
    </section>
  );
}

// --- Tool execution timeline -------------------------------------------------

export type ToolTimelineStatus = "queued" | "running" | "blocked" | "completed" | "cancelled" | "failed";

export type ToolTimelineEntry = {
  step_id: string;
  tool_name: string;
  specialist: AtlasSpecialistId;
  title: string;
  status: ToolTimelineStatus;
  requestedAt: string | null;
  resolvedAt: string | null;
  durationMs: number | null;
  evidenceIds: string[];
  reason: string | null;
};

function eventFor(events: AtlasRunEvent[], type: string, stepId: string): AtlasRunEvent | undefined {
  return events.find((event) => event.type === type && event.step_id === stepId);
}

/** One entry per real plan step, viewed as a tool call: every field comes
 * from the step's own state plus its matching step_started/step_completed
 * events. A model *requesting* a tool is the step_started event; it is
 * never treated as proof the tool ran -- only step_completed with a
 * completed state, or a blocked state with its real reason, closes it out. */
export function buildToolTimeline(run: AtlasRunResponse): ToolTimelineEntry[] {
  const events = run.events ?? [];
  return (run.plan.steps ?? []).map((step) => {
    const started = eventFor(events, "step_started", step.step_id);
    const completed = eventFor(events, "step_completed", step.step_id);
    const requestedAt = started?.occurred_at ?? null;
    const resolvedAt = completed?.occurred_at ?? null;
    const durationMs = requestedAt && resolvedAt ? Math.max(0, new Date(resolvedAt).getTime() - new Date(requestedAt).getTime()) : null;
    const rawEvidence = completed?.payload?.["evidence_ids"];
    const evidenceIds = Array.isArray(rawEvidence) ? rawEvidence.filter((item): item is string => typeof item === "string") : [];
    const payloadReason = typeof completed?.payload?.["reason"] === "string" ? (completed.payload["reason"] as string) : null;
    const state = step.state ?? "pending";
    const status: ToolTimelineStatus = state === "pending" ? "queued" : (state as ToolTimelineStatus);
    return { step_id: step.step_id, tool_name: step.tool_name, specialist: step.specialist, title: step.title, status, requestedAt, resolvedAt, durationMs, evidenceIds, reason: step.error ?? payloadReason };
  });
}

const TOOL_STATUS_TONE: Record<ToolTimelineStatus, string> = { queued: "", running: "bridged", blocked: "unavailable", completed: "ready", cancelled: "unavailable", failed: "unavailable" };

export function ToolTimeline({ run }: { run: AtlasRunResponse }) {
  const entries = buildToolTimeline(run);
  if (!entries.length) return null;
  return (
    <section className="atlas-tool-timeline" aria-label="Atlas tool execution timeline">
      <span className="eyebrow">TOOL ACTIVITY</span>
      <ol>
        {entries.map((entry) => (
          <li key={entry.step_id} data-status={entry.status}>
            <span className={`migration-chip ${TOOL_STATUS_TONE[entry.status]}`}>{entry.status.toUpperCase()}</span>
            <div>
              <strong className="acc-mono">{entry.tool_name}</strong>
              <small>{entry.specialist} · {entry.title}</small>
              {entry.requestedAt ? (
                <small className="acc-mono">
                  requested {new Date(entry.requestedAt).toLocaleTimeString()}
                  {entry.durationMs !== null ? ` · ${entry.durationMs}ms` : entry.resolvedAt ? "" : " · in flight"}
                </small>
              ) : (
                <small>not yet requested</small>
              )}
              {entry.evidenceIds.length ? <small>evidence: {entry.evidenceIds.join(", ")}</small> : null}
              {entry.reason ? <p>{entry.reason}</p> : null}
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

// --- Specialist activity -----------------------------------------------------

export type SpecialistState = "idle" | "queued" | "running" | "completed" | "blocked" | "cancelled" | "failed";

export type SpecialistActivityEntry = {
  specialist: AtlasSpecialistId;
  displayName: string;
  role: string;
  state: SpecialistState;
  steps: { step_id: string; title: string; tool_name: string; state: string }[];
  startedAt: string | null;
  completedAt: string | null;
};

/** One entry per *real, declared* specialist identity (`GET /specialists`),
 * never an invented roster. A specialist this run never assigned a step to
 * is honestly "idle" -- not hidden, not animated as if working. */
export function buildSpecialistActivity(run: AtlasRunResponse | null, roster: AtlasSpecialistIdentity[]): SpecialistActivityEntry[] {
  const events = run?.events ?? [];
  return roster
    .filter((identity) => identity.visible !== false)
    .map((identity) => {
      const steps = run ? (run.plan.steps ?? []).filter((step) => step.specialist === identity.specialist) : [];
      let state: SpecialistState = "idle";
      if (steps.length) {
        if (steps.some((step) => step.state === "running")) state = "running";
        else if (steps.some((step) => step.state === "blocked")) state = "blocked";
        else if (steps.some((step) => step.state === "failed")) state = "failed";
        else if (steps.some((step) => step.state === "cancelled")) state = "cancelled";
        else if (steps.length && steps.every((step) => step.state === "completed")) state = "completed";
        else state = "queued";
      }
      const stepIds = new Set(steps.map((step) => step.step_id));
      const startedTimes = events.filter((event) => event.type === "step_started" && event.step_id && stepIds.has(event.step_id)).map((event) => event.occurred_at).sort();
      const completedTimes = events.filter((event) => event.type === "step_completed" && event.step_id && stepIds.has(event.step_id)).map((event) => event.occurred_at).sort();
      return {
        specialist: identity.specialist,
        displayName: identity.display_name,
        role: identity.role,
        state,
        steps: steps.map((step) => ({ step_id: step.step_id, title: step.title, tool_name: step.tool_name, state: step.state ?? "pending" })),
        startedAt: startedTimes[0] ?? null,
        completedAt: completedTimes[completedTimes.length - 1] ?? null,
      };
    });
}

const SPECIALIST_STATE_TONE: Record<SpecialistState, string> = { idle: "", queued: "", running: "bridged", completed: "ready", blocked: "unavailable", cancelled: "unavailable", failed: "unavailable" };

export function SpecialistActivity({ run, roster }: { run: AtlasRunResponse | null; roster: AtlasSpecialistIdentity[] }) {
  const entries = buildSpecialistActivity(run, roster);
  if (!entries.length) return null;
  return (
    <section className="atlas-specialist-activity" aria-label="Atlas specialist activity">
      <span className="eyebrow">SPECIALISTS</span>
      <ul>
        {entries.map((entry) => (
          <li key={entry.specialist} data-state={entry.state}>
            <span className={`specialist-signal ${entry.state}`} aria-hidden="true" />
            <div>
              <strong>{entry.displayName}</strong>
              <span className={`migration-chip ${SPECIALIST_STATE_TONE[entry.state]}`}>{entry.state}</span>
              <small>{entry.role}</small>
              {entry.steps.length ? <small>{entry.steps.map((step) => step.title).join(" · ")}</small> : null}
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}

// --- Command Core pipeline stage --------------------------------------------

export type PipelineStage = "request" | "plan" | "guardrails" | "specialists" | "tools" | "evidence" | "result";
const PIPELINE_STAGES: { id: PipelineStage; label: string }[] = [
  { id: "request", label: "Request" },
  { id: "plan", label: "Plan" },
  { id: "guardrails", label: "Guardrails" },
  { id: "specialists", label: "Specialists" },
  { id: "tools", label: "Tools" },
  { id: "evidence", label: "Evidence" },
  { id: "result", label: "Result" },
];

/** How far a real run has actually progressed, read from its own durable
 * state -- never a timer or a canned animation. A run held at the
 * guardrail boundary (see atlas_runtime.execute()) truthfully never
 * reaches "specialists": every step is marked blocked without any step
 * ever entering RUNNING, so `attempts` never advances past 0. */
export function pipelineStageIndex(run: AtlasRunResponse | null): number {
  if (!run) return 0;
  const decision = guardrailDecisionFor(run);
  const guardrailChecked = decision !== null;
  const specialistsStarted = (run.plan.steps ?? []).some((step) => (step.attempts ?? 0) > 0);
  const toolsResolved = (run.events ?? []).some((event) => event.type === "step_completed");
  const evidenceRecorded = (run.evidence ?? []).length > 0 || (run.council ?? []).some((item) => (item.evidence ?? []).length > 0);
  const resultReady = Boolean(run.answer) && ["completed", "failed", "cancelled"].includes(run.plan.state ?? "");
  if (resultReady) return 6;
  if (evidenceRecorded) return 5;
  if (toolsResolved) return 4;
  if (specialistsStarted) return 3;
  if (guardrailChecked) return 2;
  return 1;
}

export function PipelineStepper({ run }: { run: AtlasRunResponse | null }) {
  const reached = pipelineStageIndex(run);
  const blockedAtGuardrail = run ? guardrailDecisionFor(run)?.state !== "checked" && guardrailDecisionFor(run) !== null : false;
  return (
    <ol className="atlas-pipeline" aria-label="Atlas request pipeline">
      {PIPELINE_STAGES.map((stage, index) => {
        const isReached = index <= reached;
        const isCurrent = index === reached && index < PIPELINE_STAGES.length - 1;
        const held = blockedAtGuardrail && index > 2;
        return (
          <li key={stage.id} className={isReached && !held ? "is-reached" : ""} data-current={isCurrent} aria-current={isCurrent ? "step" : undefined}>
            <span className="atlas-pipeline-dot" aria-hidden="true" />
            {stage.label}
            {held ? <small> held</small> : null}
          </li>
        );
      })}
    </ol>
  );
}

// --- Memory & corrections ----------------------------------------------------

export const MEMORY_CLASS_LABELS: Record<string, string> = {
  data_evidence: "Evidence Memory",
  project_knowledge: "Project Knowledge",
  user_memory: "User Memory",
  model_knowledge: "Model Knowledge",
  web_research: "Web Research",
};

const FEEDBACK_KIND_LABELS: Record<string, string> = {
  helpful: "Helpful",
  not_helpful: "Not helpful",
  accepted: "Accepted",
  rejected: "Rejected",
  corrected: "Corrected",
};
const FEEDBACK_KIND_TONE: Record<string, string> = { helpful: "ready", accepted: "ready", not_helpful: "unavailable", rejected: "unavailable", corrected: "bridged" };

/** The backend's own Cortex graph builder (`cortex_graph` in
 * atlas_runtime.py) treats `source_ref === run_id` as the proof a memory
 * record cites this run -- the same real rule applied here client-side,
 * since `GET /memories` has no dedicated run_id filter yet. Never a
 * heuristic on timestamp or text similarity. */
export function filterMemoriesForRun(memories: AtlasMemoryRecord[], runId: string): AtlasMemoryRecord[] {
  return memories.filter((record) => record.source_ref === runId);
}

/** Whether this record's `content` may ever be put in the DOM here.
 * `public`/`internal` (the schema default) can be expanded on request;
 * `private`/`restricted` content is never rendered by this general view --
 * only its existence and safe metadata are shown. */
export function memoryContentDisclosable(record: AtlasMemoryRecord): boolean {
  return record.sensitivity === "public" || record.sensitivity === "internal";
}

export function groupMemoriesByClass(memories: AtlasMemoryRecord[]): { knowledgeClass: string; records: AtlasMemoryRecord[] }[] {
  const groups = new Map<string, AtlasMemoryRecord[]>();
  for (const record of memories) {
    const list = groups.get(record.knowledge_class) ?? [];
    list.push(record);
    groups.set(record.knowledge_class, list);
  }
  return [...groups.entries()].map(([knowledgeClass, records]) => ({ knowledgeClass, records }));
}

export function MemoryRecordItem({ record }: { record: AtlasMemoryRecord }) {
  const disclosable = memoryContentDisclosable(record);
  return (
    <li data-sensitivity={record.sensitivity}>
      <details>
        <summary>
          <span className="migration-chip ready">{MEMORY_CLASS_LABELS[record.knowledge_class] ?? record.knowledge_class.replaceAll("_", " ")}</span>
          <strong>{record.source}</strong>
          <small className="acc-mono">{record.scope}</small>
        </summary>
        <dl>
          <dt>Memory ID</dt>
          <dd className="acc-mono">{record.memory_id}</dd>
          {record.project_id ? (
            <>
              <dt>Project</dt>
              <dd className="acc-mono">{record.project_id}</dd>
            </>
          ) : null}
          <dt>Confidence</dt>
          <dd>{record.confidence}</dd>
          {record.created_at ? (
            <>
              <dt>Created</dt>
              <dd>{new Date(record.created_at).toLocaleString()}</dd>
            </>
          ) : null}
          {record.superseded_by ? (
            <>
              <dt>Superseded by</dt>
              <dd className="acc-mono">{record.superseded_by}</dd>
            </>
          ) : null}
          <dt>Content</dt>
          <dd>{disclosable ? record.content : <span className="memory-redacted">hidden -- sensitivity: {record.sensitivity}</span>}</dd>
        </dl>
      </details>
    </li>
  );
}

export function FeedbackItem({ event }: { event: AtlasFeedbackEvent }) {
  return (
    <li data-kind={event.kind}>
      <details>
        <summary>
          <span className={`migration-chip ${FEEDBACK_KIND_TONE[event.kind] ?? ""}`}>{FEEDBACK_KIND_LABELS[event.kind] ?? event.kind}</span>
          <strong className="acc-mono">{event.run_id}</strong>
          <small>{new Date(event.created_at).toLocaleString()}</small>
        </summary>
        <dl>
          <dt>Answer</dt>
          <dd>{event.answer}</dd>
          {event.correction ? (
            <>
              <dt>Correction</dt>
              <dd>{event.correction}</dd>
            </>
          ) : null}
          {event.note ? (
            <>
              <dt>Note</dt>
              <dd>{event.note}</dd>
            </>
          ) : null}
          {event.project_id ? (
            <>
              <dt>Project</dt>
              <dd className="acc-mono">{event.project_id}</dd>
            </>
          ) : null}
        </dl>
      </details>
    </li>
  );
}

/** Memory/feedback actually tied to one real run: memories via the same
 * source_ref === run_id rule the backend's own Cortex graph uses, and
 * feedback via the dedicated `GET /feedback/runs/{run_id}` route (an exact
 * match, no filtering needed). A run with neither shows an honest empty
 * state rather than nothing at all, so its absence reads as checked, not
 * broken. */
export function RunMemoryTrace({ run, memories, feedback }: { run: AtlasRunResponse; memories: AtlasMemoryRecord[]; feedback: AtlasFeedbackEvent[] }) {
  const linked = filterMemoriesForRun(memories, run.run_id);
  return (
    <section className="atlas-memory-trace" aria-label="Atlas memory used by this run">
      <span className="eyebrow">MEMORY &amp; CORRECTIONS</span>
      {linked.length ? (
        <div className="acc-memory-group">
          <h3>Memory cited by this run</h3>
          <ul>
            {linked.map((record) => (
              <MemoryRecordItem key={record.memory_id} record={record} />
            ))}
          </ul>
        </div>
      ) : null}
      {feedback.length ? (
        <div className="acc-memory-group">
          <h3>Corrections &amp; feedback on this run</h3>
          <ul>
            {feedback.map((event) => (
              <FeedbackItem key={event.feedback_id} event={event} />
            ))}
          </ul>
        </div>
      ) : null}
      {!linked.length && !feedback.length ? <p>No persisted ATLAS memory or feedback is linked to this run yet.</p> : null}
    </section>
  );
}
