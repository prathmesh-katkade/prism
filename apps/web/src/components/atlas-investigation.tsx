"use client";

import { useEffect, useMemo, useState } from "react";
import type { AtlasRunEvent, AtlasRunResponse, OverviewDataset, OverviewProfileResponse } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";

type View = "investigation" | "collaboration" | "evidence" | "activity";
type Note = { intervention_id: string; target_id: string; text: string; created_at: string; author: "human" };
type SampleMessage = { id: string; role: string; kind: string; text: string; reply?: string; target?: string };

const sampleMessages: SampleMessage[] = [
  { id: "sample-m1", role: "Query", kind: "Recorded output · sample", text: "Control: 1,200 / 5,000 activated (24%). Treatment: 1,350 / 5,000 (27%). Observed difference: +3 percentage points.", target: "sample-e1" },
  { id: "sample-m2", role: "Auditor", kind: "Objection · sample", text: "The difference is descriptive. Assignment provenance is missing, so causal attribution remains unresolved.", reply: "sample-m1", target: "sample-issue" },
  { id: "sample-m3", role: "Atlas", kind: "Proposal · sample", text: "Keep the observed difference; request assignment records and check cohort exclusions before revisiting the causal claim.", reply: "sample-m2", target: "sample-issue" },
];

const sampleSteps = [
  { id: "sample-compare", title: "Compare observed activation", role: "Query", method: "Illustrative aggregate", state: "completed", output: "Control 24% · Treatment 27% · observed difference +3 pp", dependencies: [] as string[] },
  { id: "sample-causal", title: "Assess causal attribution", role: "Auditor", method: "Assignment review", state: "blocked", output: "Assignment provenance is missing. Causal attribution remains unresolved.", dependencies: ["sample-compare"] },
  { id: "sample-next", title: "Specify the next check", role: "Atlas", method: "Evidence request", state: "pending", output: "Waiting for assignment records; no check has executed.", dependencies: ["sample-causal"] },
];
const largeSampleSteps = Array.from({ length: 200 }, (_, index) => ({
  id: `large-sample-${index + 1}`, title: `Illustrative task ${index + 1}`,
  role: ["Query", "Auditor", "Atlas"][index % 3]!, method: "Sample method",
  state: index < 180 ? "completed" : "pending", output: index < 180 ? "Illustrative output; no tool executed." : "No output recorded.",
  dependencies: index ? [`large-sample-${index}`] : [],
}));

const sampleEvents = [
  { id: "sample-e1", label: "Illustrative cohort counts recorded" },
  { id: "sample-e2", label: "Illustrative objection opened" },
  { id: "sample-e3", label: "Illustrative next check proposed" },
];

function stringValue(value: unknown): string | null { return typeof value === "string" && value.trim() ? value : null; }
function eventLabel(event: AtlasRunEvent): string {
  const reason = stringValue(event.payload?.reason);
  return `${event.type.replaceAll("_", " ")}${event.step_id ? ` · ${event.step_id}` : ""}${reason ? ` · ${reason}` : ""}`;
}

export function AtlasInvestigation({ datasetId, initialRunId, onSelectContext, onSqlDraft, onRunSelected }: {
  datasetId: string | undefined;
  initialRunId?: string | undefined;
  onSelectContext(state: InspectorObjectState): void;
  onSqlDraft?(sql: string, parameters: Record<string, unknown>, connectionId: string): void;
  onRunSelected?(runId: string): void;
}) {
  const [run, setRun] = useState<AtlasRunResponse | null>(null);
  const [sample, setSample] = useState(false);
  const [largeSample, setLargeSample] = useState(false);
  const [objective, setObjective] = useState("");
  const [view, setView] = useState<View>("investigation");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);
  const [eventIndex, setEventIndex] = useState(0);
  const [noteText, setNoteText] = useState("");
  const [notes, setNotes] = useState<Note[]>([]);
  const [noteState, setNoteState] = useState<"idle" | "saving" | "saved" | "failed">("idle");
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [columns, setColumns] = useState<string[]>([]);
  const [aggregate, setAggregate] = useState<"none" | "count" | "sum" | "avg" | "min" | "max">("none");
  const [measure, setMeasure] = useState("");
  const [groupBy, setGroupBy] = useState("");
  const [groupSource, setGroupSource] = useState<"data" | "joined">("data");
  const [registeredSources, setRegisteredSources] = useState<OverviewDataset[]>([]);
  const [joinDatasetId, setJoinDatasetId] = useState("");
  const [joinColumns, setJoinColumns] = useState<string[]>([]);
  const [joinLeftKey, setJoinLeftKey] = useState("");
  const [joinRightKey, setJoinRightKey] = useState("");
  const [joinCardinality, setJoinCardinality] = useState<"" | "many_to_one" | "one_to_one">("");
  const [statMethod, setStatMethod] = useState<"" | "ttest" | "anova" | "chi2" | "pearson">("");
  const [statColumnA, setStatColumnA] = useState("");
  const [statColumnB, setStatColumnB] = useState("");
  const [statDesign, setStatDesign] = useState<"" | "independent_groups" | "one_way_groups" | "linear_association" | "categorical_association">("");
  const [answering, setAnswering] = useState(false);

  useEffect(() => {
    if (!datasetId) { setColumns([]); return; }
    let active = true;
    fetch(apiUrl(`/api/v1/overview/datasets/${encodeURIComponent(datasetId)}/profile`))
      .then((response) => response.ok ? response.json() as Promise<OverviewProfileResponse> : null)
      .then((profile) => { if (active) setColumns(profile?.columns.map((column) => column.name) ?? []); })
      .catch(() => { if (active) setColumns([]); });
    return () => { active = false; };
  }, [datasetId]);

  useEffect(() => {
    if (!datasetId) { setRegisteredSources([]); return; }
    let active = true;
    fetch(apiUrl("/api/v1/overview/datasets"))
      .then((response) => response.ok ? response.json() as Promise<OverviewDataset[]> : [])
      .then((sources) => { if (active) setRegisteredSources(sources.filter((source) => source.dataset_id !== datasetId)); })
      .catch(() => { if (active) setRegisteredSources([]); });
    return () => { active = false; };
  }, [datasetId]);

  useEffect(() => {
    if (!joinDatasetId) { setJoinColumns([]); return; }
    let active = true;
    fetch(apiUrl(`/api/v1/overview/datasets/${encodeURIComponent(joinDatasetId)}/profile`))
      .then((response) => response.ok ? response.json() as Promise<OverviewProfileResponse> : null)
      .then((profile) => { if (active) setJoinColumns(profile?.columns.map((column) => column.name) ?? []); })
      .catch(() => { if (active) setJoinColumns([]); });
    return () => { active = false; };
  }, [joinDatasetId]);

  useEffect(() => {
    if (!initialRunId) return;
    let active = true;
    fetch(apiUrl(`/api/v1/atlas/runs/${encodeURIComponent(initialRunId)}`))
      .then(async (response) => { if (!response.ok) throw new Error("Recorded investigation could not be loaded."); return response.json() as Promise<AtlasRunResponse>; })
      .then((record) => { if (active && (!datasetId || record.plan.dataset_id === datasetId)) setRun(record); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Investigation unavailable."); });
    return () => { active = false; };
  }, [datasetId, initialRunId]);

  useEffect(() => {
    if (!run || ["completed", "failed", "cancelled", "waiting"].includes(run.plan.state ?? "")) return;
    const runId = run.run_id;
    const timer = window.setInterval(() => {
      fetch(apiUrl(`/api/v1/atlas/runs/${encodeURIComponent(runId)}`))
        .then((response) => response.ok ? response.json() as Promise<AtlasRunResponse> : null)
        .then((record) => { if (record) setRun(record); })
        .catch(() => setError("Could not refresh the recorded run."));
    }, 1500);
    return () => window.clearInterval(timer);
  }, [run?.run_id, run?.plan.state]);

  useEffect(() => {
    if (!run) return;
    let active = true;
    fetch(apiUrl(`/api/v1/atlas/runs/${encodeURIComponent(run.run_id)}/interventions`))
      .then((response) => response.ok ? response.json() as Promise<Note[]> : [])
      .then((records) => { if (active) setNotes(records); })
      .catch(() => undefined);
    return () => { active = false; };
  }, [run?.run_id]);

  const steps = useMemo(() => sample ? (largeSample ? largeSampleSteps : sampleSteps) : (run?.plan.steps ?? []).map((step) => ({
    id: step.step_id, title: step.title, role: step.specialist, method: step.tool_name,
    state: step.state, output: step.error ?? ((step.evidence ?? []).map((e) => e.summary).join(" · ") || "No output recorded."),
    dependencies: step.dependencies ?? [],
  })), [sample, largeSample, run]);
  const events = sample ? (largeSample ? [] : sampleEvents) : (run?.events ?? []).slice().sort((a, b) => a.sequence - b.sequence).map((event) => ({ id: event.event_id, label: eventLabel(event) }));
  const issueCount = sample ? (largeSample ? 0 : 1) : (run?.council ?? []).reduce((count, item) => count + (item.objections ?? []).length, 0);
  const sqlOutput = (run?.events ?? []).map((event) => event.payload?.output).find((value): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && typeof (value as Record<string, unknown>).sql === "string") ?? null;
  const selectedSqlEvidence = selectedId?.startsWith("sql:") && sqlOutput?.sql_run_id === selectedId.slice(4);
  const statOutput = (run?.events ?? []).map((event) => event.payload?.output).find((value): value is Record<string, unknown> =>
    typeof value === "object" && value !== null && typeof (value as Record<string, unknown>).method === "string") ?? null;
  const openQuestion = run?.clarifications?.find((question) => question.state === "open") ?? null;

  async function start() {
    if (!datasetId || !objective.trim() || starting) return;
    setStarting(true); setError(null); setSample(false); setRun(null); setNotes([]);
    try {
      const sql_analysis = aggregate === "none" ? undefined : { aggregate, ...(aggregate === "count" ? {} : { measure }),
        ...(groupBy ? { group_by: groupBy, group_source: groupSource } : {}),
        ...(joinDatasetId ? { join_dataset_id: joinDatasetId, join_left_key: joinLeftKey,
          join_right_key: joinRightKey, join_cardinality: joinCardinality } : {}),
      };
      const response = await fetch(apiUrl("/api/v1/atlas/runs"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ dataset_id: datasetId, objective: objective.trim(), idempotency_key: crypto.randomUUID(), sql_analysis }) });
      if (!response.ok) throw new Error("Atlas did not accept the investigation.");
      const accepted = await response.json() as AtlasRunResponse;
      setRun(accepted); onRunSelected?.(accepted.run_id); setView("investigation");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Investigation failed to start."); }
    finally { setStarting(false); }
  }

  function select(id: string, label: string, detail: string, kind = "recorded item") {
    setSelectedId(id);
    onSelectContext({ objectId: id, label, type: "finding", state: "native", actions: [], metadata: [kind, detail, sample ? "Illustrative sample; no model or tool execution" : `Recorded in run ${run?.run_id ?? "unknown"}`] });
  }

  async function saveNote() {
    if (!run || !selectedId || !noteText.trim() || noteState === "saving") return;
    setNoteState("saving");
    try {
      const response = await fetch(apiUrl(`/api/v1/atlas/runs/${encodeURIComponent(run.run_id)}/interventions`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ target_id: selectedId, text: noteText.trim() }) });
      if (!response.ok) throw new Error("The intervention was not saved.");
      const record = await response.json() as Note;
      setNotes((previous) => [...previous, record]); setNoteText(""); setNoteState("saved");
    } catch { setNoteState("failed"); }
  }

  async function answerQuestion() {
    if (!run || !openQuestion || !statMethod || !statColumnA || !statColumnB || !statDesign || answering) return;
    setAnswering(true); setError(null);
    try {
      const response = await fetch(apiUrl(`/api/v1/atlas/runs/${encodeURIComponent(run.run_id)}/clarifications/${encodeURIComponent(openQuestion.question_id)}`), {
        method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ test: statMethod, col_a: statColumnA, col_b: statColumnB, design: statDesign }),
      });
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error(body.detail ?? "Atlas could not resume this analysis.");
      }
      setRun(await response.json() as AtlasRunResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save the clarification."); }
    finally { setAnswering(false); }
  }

  async function cancelRun() {
    if (!run) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/atlas/runs/${encodeURIComponent(run.run_id)}/cancel`), { method: "POST" });
      if (!response.ok) throw new Error("Atlas could not cancel this run.");
      setRun(await response.json() as AtlasRunResponse);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Cancellation failed."); }
  }

  return <section className="atlas-investigation" aria-label="Atlas investigation workspace">
    <header className="atlas-investigation-header">
      <div><span className="atlas-kicker">ATLAS / {sample ? "ILLUSTRATIVE SAMPLE" : run ? "RECORDED INVESTIGATION" : "INVESTIGATION"}</span>
        <h1>{sample ? (largeSample ? "Large illustrative investigation · 200 tasks" : "Should we roll out the shorter onboarding flow?") : run?.plan.objective ?? "What decision are you trying to make?"}</h1>
        <p>{sample ? (largeSample ? "Synthetic scale check. No model or tool executed." : "The observed lift is recorded in this sample; the causal question remains unresolved.") : run ? `Dataset ${run.plan.dataset_id} · execution ${run.plan.state} · ${run.plan.steps.length} steps` : `Active dataset: ${datasetId ?? "none selected"}`}</p>
      </div>
      {run || sample ? <span className="atlas-run-state" data-state={sample ? "sample" : run?.plan.state}>{sample ? "Sample · no execution" : run?.plan.state}</span> : null}
    </header>
    {!run && !sample ? <div className="atlas-empty-actions"><p>Start with a question about the active dataset, or inspect the labelled sample investigation.</p><button type="button" onClick={() => { setLargeSample(false); setSample(true); setView("investigation"); }}>Open sample investigation</button><button type="button" onClick={() => { setLargeSample(true); setSample(true); setView("collaboration"); }}>Open 200-task sample</button></div> : null}
    {run && ["draft", "running", "waiting"].includes(run.plan.state ?? "") ? <div className="atlas-run-controls"><span role="status">{run.plan.state === "waiting" ? "Waiting for your statistical inputs; completed evidence is saved." : "Investigation in progress."}</span><button type="button" onClick={() => void cancelRun()}>Cancel investigation</button></div> : null}
    {run && openQuestion ? <form className="atlas-clarification" onSubmit={(event) => { event.preventDefault(); void answerQuestion(); }}>
      <h2>Stat needs a clarification</h2><p>{openQuestion.prompt}</p>
      <label htmlFor="atlas-stat-method">Statistical method</label><select id="atlas-stat-method" value={statMethod} onChange={(event) => setStatMethod(event.target.value as typeof statMethod)}><option value="">Choose a method</option><option value="ttest">Welch two-group t-test</option><option value="anova">One-way ANOVA</option><option value="chi2">Chi-square association</option><option value="pearson">Pearson correlation</option></select>
      <label htmlFor="atlas-stat-a">Outcome or first comparison column</label><select id="atlas-stat-a" value={statColumnA} onChange={(event) => setStatColumnA(event.target.value)}><option value="">Choose a column</option>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select>
      <label htmlFor="atlas-stat-b">Group or second comparison column</label><select id="atlas-stat-b" value={statColumnB} onChange={(event) => setStatColumnB(event.target.value)}><option value="">Choose a column</option>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select>
      <label htmlFor="atlas-stat-design">Study design</label><select id="atlas-stat-design" value={statDesign} onChange={(event) => setStatDesign(event.target.value as typeof statDesign)}><option value="">Choose a design</option><option value="independent_groups">Independent groups</option><option value="one_way_groups">One-way groups</option><option value="linear_association">Linear association</option><option value="categorical_association">Categorical association</option></select>
      <p>Only the declared, tested Stats Lab procedure runs. The result describes association or group differences; it does not establish causality.</p>
      <button type="submit" disabled={answering || !statMethod || !statColumnA || !statColumnB || !statDesign}>{answering ? "Resuming…" : "Save answer and resume"}</button>
    </form> : null}
    {(run || sample) ? <nav className="atlas-view-tabs" aria-label="Investigation views">{(["investigation", "collaboration", "evidence", "activity"] as const).map((item) => <button key={item} type="button" aria-current={view === item ? "page" : undefined} onClick={() => setView(item)}>{item === "collaboration" ? `Collaboration${issueCount ? ` · ${issueCount} open` : ""}` : item[0]!.toUpperCase() + item.slice(1)}</button>)}</nav> : null}
    {view === "investigation" && (run || sample) ? <div className="atlas-section"><div className="atlas-section-heading"><div><h2>Plan execution sequence</h2><p>Execution can finish while the question stays unresolved.</p></div><button type="button" onClick={() => setCollapsed((value) => !value)} aria-expanded={!collapsed}>{collapsed ? "Expand details" : "Collapse details"}</button></div><ol className="atlas-plan-list">{steps.map((step, index) => <li key={step.id} data-state={step.state}><div className="atlas-step-head"><span className="atlas-step-index">{String(index + 1).padStart(2, "0")}</span><div><strong>{step.title}</strong><small>{step.role} · {step.method}</small></div><span className="atlas-state-label">{step.state}</span></div>{!collapsed ? <p className="atlas-step-dependency">{step.dependencies.length ? `Depends on ${step.dependencies.join(", ")}` : "No dependency recorded"}</p> : null}<button type="button" className="atlas-step-output" onClick={() => select(step.id, step.title, step.output, step.state === "blocked" ? "execution refusal" : "recorded output")} aria-pressed={selectedId === step.id}><span>{step.state === "blocked" ? "Execution refusal" : step.state === "pending" ? (sample ? "Waiting dependency · sample" : "Pending") : "Recorded output"}</span><strong>{step.output}</strong></button></li>)}</ol>{run?.answer ? <div className="atlas-result"><strong>Atlas interpretation</strong><button type="button" onClick={() => select("answer", "Atlas interpretation", run.answer ?? "", "interpretation")}>{run.answer}</button>{run.uncertainty ? <p><strong>Limit:</strong> {run.uncertainty}</p> : null}{sqlOutput && typeof sqlOutput.sql_run_id === "string" ? <button type="button" onClick={() => { setView("evidence"); select(`sql:${sqlOutput.sql_run_id}`, "Recorded SQL result", String(sqlOutput.sql)); }}>Inspect supporting SQL evidence</button> : statOutput && run ? <button type="button" onClick={() => { setView("evidence"); const item = (run.evidence ?? []).find((evidence) => evidence.evidence_id.startsWith("stat:")); if (item) select(item.evidence_id, item.summary, JSON.stringify(statOutput)); }}>Inspect supporting statistical evidence</button> : <small>Supporting evidence not linked.</small>}</div> : null}</div> : null}
    {view === "collaboration" && (run || sample) ? <div className="atlas-collaboration"><section className="atlas-section"><div className="atlas-section-heading"><div><h2>Work map</h2><p>Participating roles and recorded dependencies</p></div></div><ol className="atlas-work-map">{steps.map((step, index) => <li key={step.id} data-state={step.state}><span className="atlas-step-index">{String(index + 1).padStart(2, "0")}</span><div><strong>{step.role}</strong><span>{step.title}</span><small>{step.dependencies.length ? `After ${step.dependencies.join(", ")}` : "No dependency recorded"}</small></div><span className="atlas-state-label">{step.state}</span></li>)}</ol></section><section className="atlas-section"><div className="atlas-section-heading"><div><h2>Recorded exchange</h2><p>{sample ? "Illustrative messages · one shared model represented by roles" : "Persisted specialist contributions and human notes"}</p></div></div><ol className="atlas-exchange">{sample && !largeSample ? sampleMessages.map((message) => <li key={message.id}><div className="atlas-message-meta"><strong>{message.role}</strong><span>{message.kind}</span><small>{message.reply ? `Reply to ${message.reply}` : "Starts exchange"}</small></div><button type="button" onClick={() => select(message.target ?? message.id, message.kind, message.text)}>{message.text}</button></li>) : (run?.messages?.length ? [...run.messages].sort((a, b) => a.sequence - b.sequence).map((message) => <li key={message.message_id}><div className="atlas-message-meta"><strong>{message.specialist}</strong><span>{message.kind.replaceAll("_", " ")} | {message.origin.replaceAll("_", " ")}</span><small>#{message.sequence} | Task {message.task_id}{message.reply_to ? ` | Reply to ${message.reply_to}` : ""}</small></div><button type="button" onClick={() => select(message.message_id, `${message.specialist} ${message.kind}`, message.content)}>{message.content}</button><small>Inputs: {(message.input_refs ?? []).length ? (message.input_refs ?? []).join(", ") : "none recorded"} | Model: {message.model_binding ?? "none"}</small></li>) : (run?.council ?? []).map((message, index) => <li key={`${message.specialist}-${index}`}><div className="atlas-message-meta"><strong>{message.specialist}</strong><span>Legacy council conclusion</span><small>Record {index + 1} | reply links unavailable</small></div><button type="button" onClick={() => select(`council:${index}`, `${message.specialist} conclusion`, message.conclusion)}>{message.conclusion}</button>{(message.objections ?? []).map((objection, objectionIndex) => <button key={objectionIndex} type="button" className="atlas-objection" onClick={() => select(`objection:${index}:${objectionIndex}`, "Recorded objection", objection)}><span>Objection</span>{objection}</button>)}</li>))}{notes.map((note) => <li key={note.intervention_id}><div className="atlas-message-meta"><strong>You</strong><span>Human intervention</span><small>Targets {note.target_id} · {note.created_at}</small></div><p>{note.text}</p></li>)}</ol>{sample ? <p className="atlas-support-note">Sample messages are illustrative; no model exchange was persisted.</p> : null}</section><section className="atlas-section"><h2>Open issues</h2>{sample && !largeSample ? <button type="button" className="atlas-issue" onClick={() => select("sample-issue", "Causal attribution unresolved", "Assignment provenance is missing. The +3 percentage point observed difference remains descriptive.")}><strong>Causal attribution unresolved</strong><span>Assignment provenance missing · observed difference preserved · assignment records needed</span></button> : issueCount ? (run?.council ?? []).flatMap((item, index) => (item.objections ?? []).map((objection, offset) => <button key={`${index}-${offset}`} type="button" className="atlas-issue" onClick={() => select(`objection:${index}:${offset}`, "Recorded objection", objection)}><strong>{objection}</strong><span>Consequence and resolution not separately recorded.</span></button>)) : <p>No recorded objection.</p>}{!sample && run ? <div className="atlas-intervention"><label htmlFor="atlas-note">Challenge a selected record or request a check</label><textarea id="atlas-note" value={noteText} onChange={(event) => { setNoteText(event.target.value); setNoteState("idle"); }} placeholder={selectedId ? `Note about ${selectedId}` : "Select a record first"} disabled={!selectedId} maxLength={2000} /><button type="button" onClick={() => void saveNote()} disabled={!selectedId || !noteText.trim() || noteState === "saving"}>{noteState === "saving" ? "Saving…" : "Save intervention"}</button><small role="status">{noteState === "saved" ? "Saved as a human note. No check was executed." : noteState === "failed" ? "Save failed. The note was not recorded." : selectedId ? `Target: ${selectedId}` : "Select a contribution, output, or objection."}</small></div> : null}</section></div> : null}
    {view === "evidence" && (run || sample) ? <section className="atlas-section"><h2>Evidence records</h2>{sample && !largeSample ? <button type="button" className="atlas-evidence-row" onClick={() => select("sample-e1", "Illustrative cohort counts", "Control 1,200 / 5,000 (24%); treatment 1,350 / 5,000 (27%). No assignment provenance.")}><strong>Illustrative cohort counts</strong><span>Observed difference +3 percentage points · sample only</span></button> : (run?.evidence ?? []).length ? (run?.evidence ?? []).map((evidence) => <button key={evidence.evidence_id} type="button" className="atlas-evidence-row" onClick={() => select(evidence.evidence_id, evidence.summary, `${evidence.kind} · ${evidence.evidence_id}`)}><strong>{evidence.summary}</strong><span>{evidence.kind} · {evidence.evidence_id}</span></button>) : <p>No evidence record attached to this run.</p>}<p className="atlas-support-note">Supporting evidence is highlighted only where a stored relationship establishes it.</p><button type="button" disabled={!selectedSqlEvidence || !onSqlDraft} onClick={() => { if (sqlOutput && onSqlDraft && typeof sqlOutput.sql === "string" && typeof sqlOutput.connection_id === "string") onSqlDraft(sqlOutput.sql, (sqlOutput.parameters ?? {}) as Record<string, unknown>, sqlOutput.connection_id); }}>Open exact query in SQL Lab</button>{selectedSqlEvidence && sqlOutput ? <div className="atlas-recorded-query"><p>Recorded original; edits in SQL Lab create a draft.</p><pre>{String(sqlOutput.sql)}</pre><pre>{JSON.stringify(sqlOutput.parameters ?? {})}</pre><p>Result rows: {JSON.stringify(sqlOutput.rows ?? [])}</p></div> : <p className="atlas-support-note">Select a recorded SQL result to inspect its exact query.</p>}</section> : null}
    {view === "evidence" && selectedId?.startsWith("stat:") && statOutput ? <section className="atlas-section atlas-stat-record"><h2>Recorded statistical computation</h2><p>Method: {String(statOutput.method)}; design: {String(statOutput.design)}; analyzed: {String(statOutput.analyzed_rows)}; excluded: {String(statOutput.excluded_rows)}.</p><pre>{JSON.stringify(statOutput.result, null, 2)}</pre><p>{Array.isArray(statOutput.limitations) ? statOutput.limitations.join(" ") : "Limitations unavailable."}</p></section> : null}
    {view === "activity" && (run || sample) ? <section className="atlas-section"><h2>Recorded event log</h2><p>Stepping selects an event. Historical state reconstruction is unavailable.</p>{events.length ? <><div className="atlas-replay"><button type="button" disabled={eventIndex === 0} onClick={() => setEventIndex((value) => value - 1)}>Previous event</button><span>Event {eventIndex + 1} of {events.length}</span><button type="button" disabled={eventIndex >= events.length - 1} onClick={() => setEventIndex((value) => value + 1)}>Next event</button></div><ol className="atlas-event-list">{events.map((event, index) => <li key={event.id}><button type="button" aria-current={eventIndex === index ? "step" : undefined} onClick={() => setEventIndex(index)}><span>{String(index + 1).padStart(2, "0")}</span>{event.label}</button></li>)}</ol></> : <p>No event journal entries were recorded.</p>}</section> : null}
    <form className="atlas-new-run" onSubmit={(event) => { event.preventDefault(); void start(); }}>
      <label htmlFor="atlas-objective">Investigation objective</label>
      <div><input id="atlas-objective" value={objective} onChange={(event) => setObjective(event.target.value)} placeholder={datasetId ? "Ask about the active dataset" : "Select a dataset to begin"} disabled={!datasetId || starting} /><button type="submit" disabled={!datasetId || !objective.trim() || starting || (aggregate !== "none" && aggregate !== "count" && !measure) || Boolean(joinDatasetId && (!joinLeftKey || !joinRightKey || !joinCardinality))}>{starting ? "Starting…" : "Run investigation"}</button></div>
      <label htmlFor="atlas-aggregate">Optional SQL aggregate</label>
      <select id="atlas-aggregate" value={aggregate} onChange={(event) => setAggregate(event.target.value as typeof aggregate)} disabled={!datasetId || starting}>
        <option value="none">No SQL calculation</option><option value="count">Count rows</option><option value="sum">Sum</option><option value="avg">Average</option><option value="min">Minimum</option><option value="max">Maximum</option>
      </select>
      {aggregate !== "none" && aggregate !== "count" ? <><label htmlFor="atlas-measure">Measure column</label><select id="atlas-measure" value={measure} onChange={(event) => setMeasure(event.target.value)}><option value="">Choose a column</option>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select></> : null}
      {aggregate !== "none" ? <>
        <label htmlFor="atlas-join-source">Optional registered join source</label>
        <select id="atlas-join-source" value={joinDatasetId} onChange={(event) => { setJoinDatasetId(event.target.value); setJoinRightKey(""); setGroupBy(""); setGroupSource("data"); }}><option value="">Single uploaded dataset</option>{registeredSources.map((source) => <option key={source.dataset_id} value={source.dataset_id}>{source.source_name} · revision {source.revision}</option>)}</select>
        {joinDatasetId ? <><label htmlFor="atlas-join-left">Active dataset key</label><select id="atlas-join-left" value={joinLeftKey} onChange={(event) => setJoinLeftKey(event.target.value)}><option value="">Choose a key</option>{columns.map((column) => <option key={column} value={column}>{column}</option>)}</select>
          <label htmlFor="atlas-join-right">Joined dataset key</label><select id="atlas-join-right" value={joinRightKey} onChange={(event) => setJoinRightKey(event.target.value)}><option value="">Choose a key</option>{joinColumns.map((column) => <option key={column} value={column}>{column}</option>)}</select>
          <label htmlFor="atlas-join-cardinality">Declared join cardinality</label><select id="atlas-join-cardinality" value={joinCardinality} onChange={(event) => setJoinCardinality(event.target.value as typeof joinCardinality)}><option value="">Choose cardinality</option><option value="many_to_one">Many left rows to one right row</option><option value="one_to_one">One to one</option></select>
          <p>The server verifies that the joined key is unique before summing active-dataset measures. Only inner joins are available.</p></> : null}
        <label htmlFor="atlas-group-source">Group source</label><select id="atlas-group-source" value={groupSource} onChange={(event) => { setGroupSource(event.target.value as typeof groupSource); setGroupBy(""); }}><option value="data">Active dataset</option>{joinDatasetId ? <option value="joined">Joined dataset</option> : null}</select>
        <label htmlFor="atlas-group">Group by column</label><select id="atlas-group" value={groupBy} onChange={(event) => setGroupBy(event.target.value)}><option value="">All rows</option>{(groupSource === "data" ? columns : joinColumns).map((column) => <option key={column} value={column}>{column}</option>)}</select><p>Atlas will execute this bounded aggregate through SQL Lab and record the exact query.</p></> : null}
      {error ? <p role="alert">{error}</p> : null}
    </form>
  </section>;
}
