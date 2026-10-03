"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { AtlasSqlAction, AtlasSqlResponse, CteListResponse, CteMaterializeResponse, JoinDiagnosticsResponse, ResultComparisonResponse, SqlConnectionSummary, SqlPlanResponse, SqlResultPageResponse, SqlResultPromotionResponse, SqlRunResponse, SqlSchemaResponse, SqlSnippet } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import type { InspectorObjectState } from "../state/shell-model";
import { QueryEditor } from "./query-editor";
import { WorkspaceProposalPanel } from "./workspace-proposal-panel";

type StudioState = "loading" | "empty" | "ready" | "running" | "degraded" | "error";
type ResultTab = "results" | "plan" | "history" | "joins";

export function QueryStudio({ onSelectContext, initialSql, initialParameters, initialConnectionId, onUseAsEvidence, onDatasetReady, onOpenWorkflow }: { onSelectContext(state: InspectorObjectState): void; initialSql?: string; initialParameters?: Record<string, unknown>; initialConnectionId?: string; onUseAsEvidence?(runId: string): void; onDatasetReady?(datasetId: string): void; onOpenWorkflow?(workflow: string): void }) {
  const [state, setState] = useState<StudioState>("loading");
  const [connections, setConnections] = useState<SqlConnectionSummary[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [schema, setSchema] = useState<SqlSchemaResponse | null>(null);
  const [sql, setSql] = useState("SELECT *\nFROM data\nLIMIT 100;");
  const [parametersText, setParametersText] = useState("{}");
  const [newParameterName, setNewParameterName] = useState("");
  const [run, setRun] = useState<SqlRunResponse | null>(null);
  const [results, setResults] = useState<SqlResultPageResponse | null>(null);
  const [plan, setPlan] = useState<SqlPlanResponse | null>(null);
  const [history, setHistory] = useState<SqlRunResponse[]>([]);
  const [snippets, setSnippets] = useState<SqlSnippet[]>([]);
  const [atlas, setAtlas] = useState<AtlasSqlResponse | null>(null);
  const [activeResultTab, setActiveResultTab] = useState<ResultTab>("results");
  const [error, setError] = useState<string | null>(null);
  const [joinDiagnostics, setJoinDiagnostics] = useState<JoinDiagnosticsResponse | null>(null);
  const [joinDiagnosticsLoading, setJoinDiagnosticsLoading] = useState(false);
  const [joinDiagnosticsError, setJoinDiagnosticsError] = useState<string | null>(null);
  const [ctes, setCtes] = useState<string[]>([]);
  const [cteError, setCteError] = useState<string | null>(null);
  const [compareBaseRunId, setCompareBaseRunId] = useState<string | null>(null);
  const [compareRunId, setCompareRunId] = useState<string | null>(null);
  const [comparisonKeyColumnsText, setComparisonKeyColumnsText] = useState("");
  const [comparison, setComparison] = useState<ResultComparisonResponse | null>(null);
  const [comparisonLoading, setComparisonLoading] = useState(false);
  const [comparisonError, setComparisonError] = useState<string | null>(null);
  const [promotedDatasetId, setPromotedDatasetId] = useState<string | null>(null);

  useEffect(() => { if (initialSql) setSql(initialSql); }, [initialSql]);
  useEffect(() => { if (initialParameters) setParametersText(JSON.stringify(initialParameters)); }, [initialParameters]);

  const activeConnection = useMemo(() => connections.find((item) => item.connection_id === connectionId) ?? null, [connectionId, connections]);
  const readyConnections = useMemo(() => connections.filter((item) => item.status === "ready"), [connections]);
  const parsedParameters = useMemo(() => {
    try {
      const value: unknown = JSON.parse(parametersText);
      return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
    } catch { return null; }
  }, [parametersText]);
  const namedParameters = useMemo(() => [...sql.matchAll(/(?<!:):([a-zA-Z_][a-zA-Z_0-9]*)/g)].map((match) => match[1]!).filter((name, index, names) => names.indexOf(name) === index), [sql]);
  function setParameter(name: string, value: unknown) {
    if (!parsedParameters) return;
    setParametersText(JSON.stringify({ ...parsedParameters, [name]: value }, null, 2));
  }
  function removeParameter(name: string) {
    if (!parsedParameters) return;
    const next = { ...parsedParameters }; delete next[name]; setParametersText(JSON.stringify(next, null, 2));
  }

  const loadConnections = useCallback(async () => {
    setState("loading"); setError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/connections"));
      if (!response.ok) throw new Error("SQL source metadata is unavailable.");
      const next = await response.json() as SqlConnectionSummary[];
      if (initialConnectionId?.startsWith("localjoin:") && !next.some((item) => item.connection_id === initialConnectionId)) {
        const joined = await loadJson<SqlSchemaResponse>(`/api/v1/sql-lab/connections/${encodeURIComponent(initialConnectionId)}/schema`);
        next.unshift(joined.connection);
      }
      setConnections(next); setSnippets(await loadJson<SqlSnippet[]>("/api/v1/sql-lab/snippets"));
      const first = next.find((item) => item.status === "ready" && item.connection_id === initialConnectionId) ?? next.find((item) => item.status === "ready") ?? null;
      if (!first) { setState("empty"); return; }
      setConnectionId(first.connection_id); setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "SQL Lab could not reach the PRISM API."); setState("error");
    }
  }, [initialConnectionId]);

  useEffect(() => { void loadConnections(); }, [loadConnections]);
  useEffect(() => {
    if (!connectionId) return;
    void (async () => {
      try {
        const next = await loadJson<SqlSchemaResponse>(`/api/v1/sql-lab/connections/${encodeURIComponent(connectionId)}/schema`);
        setSchema(next);
        onSelectContext({ objectId: connectionId, label: next.connection.label, type: "dataset", state: "ready", actions: [{ id: "trace-source", label: "Trace SQL source" }, { id: "inspect-schema", label: "Inspect schema" }], metadata: [`${next.connection.dialect} dialect`, `${next.tables[0]?.columns.length ?? 0} columns`, `Schema ${next.schema_fingerprint.slice(0, 12)}…`] });
      } catch (reason) { setError(reason instanceof Error ? reason.message : "Schema metadata is unavailable."); setState("degraded"); }
    })();
  }, [connectionId, onSelectContext]);

  async function execute() {
    if (!activeConnection) return;
    if (!parsedParameters) { setError("Parameters must be a JSON object."); return; }
    const parameters: Record<string, unknown> = parsedParameters;
    const missing = namedParameters.filter((name) => !(name in parameters));
    if (missing.length) { setError(`Set query parameter${missing.length > 1 ? "s" : ""}: ${missing.join(", ")}.`); return; }
    setState("running"); setError(null); setAtlas(null); setJoinDiagnostics(null); setPromotedDatasetId(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/runs"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ connection_id: activeConnection.connection_id, sql, parameters, result_limit: 1_000, timeout_ms: 30_000, client_request_id: crypto.randomUUID() }) });
      if (!response.ok) throw new Error("Query submission failed.");
      const submitted = await response.json() as SqlRunResponse;
      setRun(submitted);
      const next = await waitForTerminalRun(submitted);
      setRun(next); setHistory(await loadJson<SqlRunResponse[]>("/api/v1/sql-lab/history"));
      if (next.state === "succeeded") setResults(await loadJson<SqlResultPageResponse>(`/api/v1/sql-lab/runs/${next.run_id}/results?offset=0&limit=100`));
      else setResults(null);
      setState(next.state === "succeeded" ? "ready" : "degraded"); setActiveResultTab("results");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Query execution failed."); setState("error"); }
  }

  async function inspectPlan() {
    if (!activeConnection) return;
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/plans"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ connection_id: activeConnection.connection_id, sql }) });
      if (!response.ok) throw new Error("The connector did not return a plan.");
      setPlan(await response.json() as SqlPlanResponse); setActiveResultTab("plan");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Plan inspection failed."); }
  }

  async function inspectJoins() {
    if (!activeConnection) return;
    setJoinDiagnosticsLoading(true); setJoinDiagnosticsError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/joins/diagnose"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ connection_id: activeConnection.connection_id, sql }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Join diagnostics failed.");
      setJoinDiagnostics(await response.json() as JoinDiagnosticsResponse);
    } catch (reason) { setJoinDiagnosticsError(reason instanceof Error ? reason.message : "Join diagnostics failed."); }
    finally { setJoinDiagnosticsLoading(false); }
  }

  async function findCtes() {
    if (!activeConnection) return;
    setCteError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/ctes/list"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ connection_id: activeConnection.connection_id, sql }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Could not list this query's CTEs.");
      const body = await response.json() as CteListResponse;
      setCtes(body.ctes ?? []);
      if (!(body.ctes ?? []).length) setCteError("This query has no named CTEs (no WITH clause).");
    } catch (reason) { setCteError(reason instanceof Error ? reason.message : "Could not list this query's CTEs."); setCtes([]); }
  }

  async function materializeCte(cteName: string) {
    if (!activeConnection) return;
    setCteError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/ctes/materialize"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ connection_id: activeConnection.connection_id, sql, cte_name: cteName }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Could not materialize this CTE.");
      const body = await response.json() as CteMaterializeResponse;
      setSql(body.materialized_sql);
      setCtes([]);
    } catch (reason) { setCteError(reason instanceof Error ? reason.message : "Could not materialize this CTE."); }
  }

  async function runComparison() {
    if (!compareBaseRunId || !compareRunId) { setComparisonError("Pick a base run and a compare run from history first."); return; }
    const keyColumns = comparisonKeyColumnsText.split(",").map((item) => item.trim()).filter(Boolean);
    if (!keyColumns.length) { setComparisonError("Declare at least one row-matching key column (e.g. id)."); return; }
    setComparisonLoading(true); setComparisonError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/runs/compare"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ base_run_id: compareBaseRunId, compare_run_id: compareRunId, key_columns: keyColumns }) });
      if (!response.ok) throw new Error((await response.json() as { detail?: string }).detail ?? "Comparison failed.");
      setComparison(await response.json() as ResultComparisonResponse);
    } catch (reason) { setComparisonError(reason instanceof Error ? reason.message : "Comparison failed."); }
    finally { setComparisonLoading(false); }
  }

  async function cancelActiveRun() {
    if (!run || !["queued", "running"].includes(run.state)) return;
    try {
      const response = await fetch(apiUrl(`/api/v1/sql-lab/runs/${run.run_id}/cancel`), { method: "POST" });
      if (!response.ok) throw new Error("The running query could not be cancelled.");
      setRun(await response.json() as SqlRunResponse); setState("ready");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The running query could not be cancelled."); }
  }

  async function loadResultPage(offset: number) {
    if (!run || run.state !== "succeeded") return;
    try {
      setResults(await loadJson<SqlResultPageResponse>(`/api/v1/sql-lab/runs/${run.run_id}/results?offset=${offset}&limit=100`));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The result page could not be loaded."); }
  }

  async function promoteResult(): Promise<string | null> {
    if (!run || run.state !== "succeeded") return null;
    if (promotedDatasetId) return promotedDatasetId;
    try {
      const response = await fetch(apiUrl(`/api/v1/sql-lab/runs/${run.run_id}/promote`), { method: "POST" });
      if (!response.ok) throw new Error("The result could not become a PRISM dataset.");
      const promoted = await response.json() as SqlResultPromotionResponse;
      setRun(promoted.run);
      setPromotedDatasetId(promoted.dataset.dataset_id);
      onSelectContext({ objectId: promoted.dataset.dataset_id, label: promoted.dataset.source_name, type: "dataset", state: "ready", actions: [{ id: "open-overview", label: "Open in Overview" }], metadata: [`${promoted.dataset.row_count} rows`, `Derived from ${run.run_id.slice(0, 12)}…`] });
      return promoted.dataset.dataset_id;
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The result could not become a PRISM dataset."); return null; }
  }

  async function useResultIn(workflow: "clean" | "visualize") {
    const datasetId = await promoteResult();
    if (datasetId) { onDatasetReady?.(datasetId); onOpenWorkflow?.(workflow); }
  }

  async function askAtlas(action: AtlasSqlAction) {
    if (!activeConnection) return;
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/atlas"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ action, connection_id: activeConnection.connection_id, sql }) });
      if (!response.ok) throw new Error("Atlas could not ground that SQL action.");
      const next = await response.json() as AtlasSqlResponse; setAtlas(next);
      if (next.draft_sql) setSql(next.draft_sql);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Atlas is unavailable."); }
  }

  async function saveSnippet() {
    if (!activeConnection) return;
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/snippets"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: `Query ${new Date().toLocaleTimeString()}`, sql, dialect: activeConnection.dialect, parameters: JSON.parse(parametersText) }) });
      if (!response.ok) throw new Error("Snippet could not be saved.");
      setSnippets(await loadJson<SqlSnippet[]>("/api/v1/sql-lab/snippets"));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Snippet could not be saved."); }
  }

  if (state === "loading") return <section className="sql-state loading-state" aria-live="polite"><span className="loading-bar" /><h2>Preparing Query Studio</h2><p>Loading source capabilities and schema metadata.</p></section>;
  if (state === "empty") return <section className="sql-state empty-state"><span className="overview-prism" /><span className="eyebrow">SQL LAB · NATIVE QUERY STUDIO</span><h1>Open a dataset in Overview, then query it here.</h1><p>SQL Lab shares the server-held local source and never copies the full dataset into the browser. External connector availability is surfaced explicitly.</p><button onClick={() => void loadConnections()}>Refresh sources</button><SourceCapabilities connections={connections} /></section>;
  if (state === "error") return <section className="sql-state error-state" role="alert"><h2>Query Studio could not establish its source.</h2><p>{error}</p><button onClick={() => void loadConnections()}>Retry source discovery</button></section>;

  return <article className="query-studio">
    <header className="query-heading"><div><span className="eyebrow">SQL LAB · QUERY STUDIO</span><h1>Write against evidence, not assumptions.</h1><p>{activeConnection ? <><strong>{activeConnection.label}</strong> · <code>{activeConnection.dialect}</code> · schema-aware local source</> : "Select a source"}</p></div><div className="query-status"><span className={`migration-chip ${state === "degraded" ? "unavailable" : "ready"}`}>{run?.state ?? "ready"}</span><small>Ctrl/Cmd + Enter to run</small></div></header>
    <section className="query-toolbar" aria-label="Query source and actions"><label>Source<select value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>{readyConnections.map((item) => <option key={item.connection_id} value={item.connection_id}>{item.label} · {item.dialect}</option>)}</select></label><label>Parameters<textarea aria-label="Query parameters JSON" value={parametersText} onChange={(event) => setParametersText(event.target.value)} /></label><button onClick={() => void execute()} disabled={!activeConnection || state === "running"}>Run query <kbd>⌘ ↵</kbd></button>{run && ["queued", "running"].includes(run.state) ? <button className="secondary" onClick={() => void cancelActiveRun()}>Cancel query</button> : null}<button className="secondary" onClick={() => setSql(formatSql(sql))} disabled={!activeConnection}>Format query</button><button className="secondary" onClick={() => void inspectPlan()} disabled={!activeConnection}>Inspect plan</button><button className="secondary" onClick={() => { setActiveResultTab("joins"); void inspectJoins(); }} disabled={!activeConnection}>Inspect joins</button><button className="secondary" onClick={() => void findCtes()} disabled={!activeConnection}>Find CTEs</button><button className="secondary" onClick={() => void saveSnippet()} disabled={!activeConnection}>Save snippet</button></section>
    <section className="sql-parameter-panel" aria-label="Typed query parameters"><div><span className="eyebrow">TYPED PARAMETERS</span><span>{namedParameters.length ? `Required by SQL: ${namedParameters.join(", ")}` : "Use :name in SQL to bind a value."}</span></div>{parsedParameters ? Object.entries(parsedParameters).map(([name, value]) => <div className="sql-parameter-row" key={name}><label>{name}<input aria-label={`${name} value`} type={typeof value === "number" ? "number" : "text"} value={value === null ? "" : String(value)} onChange={(event) => setParameter(name, typeof value === "number" ? (event.target.value === "" ? null : Number(event.target.value)) : typeof value === "boolean" ? event.target.value === "true" : event.target.value)} /></label><label>Type<select aria-label={`${name} type`} value={value === null ? "null" : typeof value} onChange={(event) => setParameter(name, event.target.value === "number" ? 0 : event.target.value === "boolean" ? false : event.target.value === "null" ? null : "")}><option value="string">Text</option><option value="number">Number</option><option value="boolean">Boolean</option><option value="null">Null</option></select></label><button className="secondary" onClick={() => removeParameter(name)} aria-label={`Remove ${name}`}>Remove</button></div>) : <p className="query-error" role="alert">Parameters must be a JSON object.</p>}<div className="sql-parameter-row"><label>New parameter<input aria-label="New parameter name" value={newParameterName} onChange={(event) => setNewParameterName(event.target.value)} placeholder="e.g. minimum_revenue" /></label><button className="secondary" disabled={!parsedParameters || !/^[a-zA-Z_][a-zA-Z_0-9]*$/.test(newParameterName) || newParameterName in (parsedParameters ?? {})} onClick={() => { setParameter(newParameterName, ""); setNewParameterName(""); }}>Add parameter</button></div></section>
    <WorkspaceProposalPanel kind="sql" datasetId={activeConnection?.connection_id.startsWith("local:") ? activeConnection.connection_id.slice(6) : undefined} onReview={(proposal) => { if (proposal.sql_draft) setSql(proposal.sql_draft); }} />
    {ctes.length ? <section className="snippet-strip" aria-label="Materialize an intermediate CTE"><span className="eyebrow">INTERMEDIATE CTEs</span>{ctes.map((name) => <button key={name} onClick={() => void materializeCte(name)}>Inspect {name}</button>)}</section> : null}
    {cteError ? <p className="query-error" role="alert">{cteError}</p> : null}
    <section className="query-layout"><div><QueryEditor value={sql} dialect={activeConnection?.dialect ?? "sql"} schemaItems={schema?.tables.flatMap((table) => [table.name, ...table.columns.map((column) => column.name)]) ?? []} onChange={setSql} onRun={() => void execute()} /><div className="query-editor-foot"><span>Dialect: <code>{activeConnection?.dialect ?? "unavailable"}</code></span><span>Safe reads run without a repeated prompt. Writes and unproven SQL are blocked.</span></div></div><SchemaPanel schema={schema} onInsert={(identifier) => setSql((current) => `${current}${current.endsWith(" ") || current.endsWith("\n") ? "" : " "}${identifier}`)} /></section>
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    <section className="sql-result-panel"><div className="result-tabs" role="tablist" aria-label="SQL result views">{(["results", "plan", "history", "joins"] as ResultTab[]).map((tab) => <button key={tab} role="tab" aria-selected={activeResultTab === tab} onClick={() => { setActiveResultTab(tab); if (tab === "joins" && !joinDiagnostics && !joinDiagnosticsLoading) void inspectJoins(); }}>{tab}</button>)}</div>{activeResultTab === "results" ? <DataGrid result={results} run={run} onSelectContext={onSelectContext} onPage={(offset) => void loadResultPage(offset)} onPromote={() => void promoteResult()} {...(onUseAsEvidence ? { onUseAsEvidence } : {})} {...((onDatasetReady && onOpenWorkflow) ? { onUseResultIn: useResultIn } : {})} /> : null}{activeResultTab === "plan" ? <PlanPanel plan={plan} /> : null}{activeResultTab === "history" ? <HistoryPanel
      history={history} onUse={(entry) => setSql(entry.sql)}
      compareBaseRunId={compareBaseRunId} compareRunId={compareRunId}
      onSetBase={setCompareBaseRunId} onSetCompare={setCompareRunId}
      comparisonKeyColumnsText={comparisonKeyColumnsText} onKeyColumnsChange={setComparisonKeyColumnsText}
      onCompare={() => void runComparison()} comparison={comparison} comparisonLoading={comparisonLoading} comparisonError={comparisonError}
    /> : null}{activeResultTab === "joins" ? <JoinDiagnosticsPanel diagnostics={joinDiagnostics} loading={joinDiagnosticsLoading} error={joinDiagnosticsError} /> : null}</section>
    <section className="sql-atlas"><div><span className="eyebrow">ATLAS · CONTEXTUAL SQL ACTIONS</span><h2>Inspect before execution.</h2><p>Atlas returns schema-grounded, editable drafts. It does not execute SQL, invent schema objects, or claim unsupported connectors.</p></div><div className="atlas-action-row">{(["explain_query", "optimize_query", "debug_error", "inspect_plan", "generate_sql", "compare_queries", "explain_selection", "trace_lineage", "convert_result"] as AtlasSqlAction[]).map((action) => <button key={action} onClick={() => void askAtlas(action)}>{action.replaceAll("_", " ")}</button>)}</div>{atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS RESPONSE · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}</section>
    <SourceCapabilities connections={connections.filter((item) => item.status !== "ready")} />
    {snippets.length ? <section className="snippet-strip"><span className="eyebrow">SAVED SNIPPETS</span>{snippets.map((snippet) => <button key={snippet.snippet_id} onClick={() => { setSql(snippet.sql); setParametersText(JSON.stringify(snippet.parameters ?? {}, null, 2)); }}>{snippet.name}</button>)}</section> : null}
  </article>;
}

async function loadJson<T>(path: string): Promise<T> { const response = await fetch(apiUrl(path)); if (!response.ok) throw new Error(`PRISM API request failed: ${response.status}`); return await response.json() as T; }
async function waitForTerminalRun(run: SqlRunResponse): Promise<SqlRunResponse> { if (!["queued", "running"].includes(run.state)) return run; for (let attempt = 0; attempt < 200; attempt += 1) { await new Promise((resolve) => window.setTimeout(resolve, 100)); const current = await loadJson<SqlRunResponse>(`/api/v1/sql-lab/runs/${run.run_id}`); if (!["queued", "running"].includes(current.state)) return current; } throw new Error("Query did not reach a terminal state before the client timeout."); }
function formatSql(value: string): string { return value.replace(/\b(select|from|where|group by|order by|limit|join|left join|inner join|on|as)\b/gi, (keyword) => keyword.toUpperCase()).replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|LIMIT|JOIN|LEFT JOIN|INNER JOIN)\b/g, "\n$1"); }

function SchemaPanel({ schema, onInsert }: { schema: SqlSchemaResponse | null; onInsert(identifier: string): void }) { return <aside className="schema-panel" aria-label="SQL schema browser"><span className="eyebrow">SCHEMA · AUTOCOMPLETE CONTEXT</span>{schema ? schema.tables.map((table) => <div key={table.name}><button className="schema-table" onClick={() => onInsert(table.name)}>{table.name}</button>{table.columns.map((column) => <button key={column.name} className="schema-column" onClick={() => onInsert(column.name)}><strong>{column.name}</strong><small>{column.data_type}{column.nullable ? " · nullable" : ""}</small></button>)}</div>) : <p>Schema metadata is loading.</p>}</aside>; }

function DataGrid({ result, run, onSelectContext, onPage, onPromote, onUseAsEvidence, onUseResultIn }: { result: SqlResultPageResponse | null; run: SqlRunResponse | null; onSelectContext(state: InspectorObjectState): void; onPage(offset: number): void; onPromote(): void; onUseAsEvidence?(runId: string): void; onUseResultIn?(workflow: "clean" | "visualize"): void }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [sortColumn, setSortColumn] = useState<string | null>(null);
  const [sortDescending, setSortDescending] = useState(false);
  const [filterText, setFilterText] = useState("");
  const columns = result?.run.result_columns ?? [];
  const rows = useMemo(() => {
    const filtered = (result?.rows ?? []).filter((row) => !filterText || Object.values(row).some((value) => String(value ?? "").toLowerCase().includes(filterText.toLowerCase())));
    if (!sortColumn) return filtered;
    return [...filtered].sort((left, right) => String(left[sortColumn] ?? "").localeCompare(String(right[sortColumn] ?? ""), undefined, { numeric: true }) * (sortDescending ? -1 : 1));
  }, [filterText, result?.rows, sortColumn, sortDescending]);
  const virtualRows = useVirtualizer({ count: rows.length, getScrollElement: () => scrollRef.current, estimateSize: () => 36, overscan: 12 });
  if (!run) return <div className="result-empty"><h2>No query run yet.</h2><p>Use a read-only query, then inspect the paginated result here.</p></div>;
  if (run.state !== "succeeded") return <div className="result-empty"><h2>{["queued", "running"].includes(run.state) ? "Query is running." : "Query did not return a result."}</h2><p>{run.error ?? run.warnings?.[0] ?? "Cancellation and timeout controls remain available while the query is active."}</p></div>;
  const gridTemplateColumns = `repeat(${Math.max(columns.length, 1)}, minmax(150px, 1fr))`;
  const copyPage = async () => { const header = columns.map((column) => column.name).join("\t"); const body = rows.map((row) => columns.map((column) => String(row[column.name] ?? "")).join("\t")).join("\n"); await navigator.clipboard.writeText(`${header}\n${body}`); };
  return <div><div className="result-meta"><span>{(run.returned_row_count ?? 0).toLocaleString()} returned / {(run.row_count ?? 0).toLocaleString()} {run.truncated ? "observed" : "total"} rows</span><span>{run.duration_ms ?? 0} ms</span><span>{run.truncated ? "result capped server-side" : "complete result"}</span><label className="result-filter">Filter page<input aria-label="Filter current result page" value={filterText} onChange={(event) => setFilterText(event.target.value)} /></label><button className="result-action" onClick={() => void copyPage()}>Copy page</button><a className="result-action" href={apiUrl(`/api/v1/sql-lab/runs/${run.run_id}/export?format=csv`)}>Export CSV</a><button className="result-action" onClick={onPromote}>Create dataset</button>{onUseResultIn ? <button className="result-action" onClick={() => onUseResultIn("clean")}>Use in Clean</button> : null}{onUseResultIn ? <button className="result-action" onClick={() => onUseResultIn("visualize")}>Use in Visualize</button> : null}{onUseAsEvidence ? <button className="result-action" onClick={() => onUseAsEvidence(run.run_id)}>Use as AI evidence</button> : null}<button className="result-action" onClick={() => onSelectContext({ objectId: `result:${run.run_id}`, analyticalObjectId: `sql_${run.run_id}`, label: "SQL result set", type: "dataset", state: "ready", actions: [{ id: "explain-result-set", label: "Ask Atlas to explain result" }, { id: "convert-result", label: "Create PRISM dataset" }], metadata: [`${run.returned_row_count ?? 0} rows`, `Fingerprint ${run.provenance.result_fingerprint?.slice(0, 12) ?? "pending"}…`] })}>Inspect result</button></div><div className="sql-grid-virtual" role="grid" aria-label="Query results" aria-rowcount={run.returned_row_count ?? 0}><div className="sql-grid-head" role="row" style={{ gridTemplateColumns }}>{columns.map((column) => <button key={column.name} role="columnheader" aria-sort={sortColumn === column.name ? (sortDescending ? "descending" : "ascending") : "none"} onClick={() => { setSortDescending(sortColumn === column.name ? !sortDescending : false); setSortColumn(column.name); }}>{column.name}<small>{column.data_type}</small></button>)}</div><div className="sql-grid-body" ref={scrollRef} role="rowgroup"><div style={{ height: `${virtualRows.getTotalSize()}px`, position: "relative" }}>{virtualRows.getVirtualItems().map((virtualRow) => { const row = rows[virtualRow.index] ?? {}; const rowIndex = (result?.offset ?? 0) + virtualRow.index; return <div key={virtualRow.key} className="sql-grid-row" role="row" style={{ gridTemplateColumns, transform: `translateY(${virtualRow.start}px)` }}>{columns.map((column) => <button key={column.name} role="gridcell" onClick={() => onSelectContext({ objectId: `result:${run.run_id}:${rowIndex}:${column.name}`, label: `${column.name} result value`, type: "finding", state: "ready", actions: [{ id: "explain-result-cell", label: "Ask Atlas to explain selection" }, { id: "copy-result-cell", label: "Copy value" }], metadata: [String(row[column.name] ?? "—"), `Run ${run.run_id.slice(0, 12)}…`] })}>{row[column.name] === null ? "—" : String(row[column.name])}</button>)}</div>; })}</div></div></div><div className="result-pagination"><button className="secondary" onClick={() => onPage(Math.max(0, (result?.offset ?? 0) - 100))} disabled={!result?.offset}>Previous 100</button><span>Rows {(result?.offset ?? 0) + 1}–{(result?.offset ?? 0) + rows.length}</span><button className="secondary" onClick={() => onPage((result?.offset ?? 0) + 100)} disabled={(result?.offset ?? 0) + rows.length >= (run.returned_row_count ?? 0)}>Next 100</button></div></div>;
}

function PlanPanel({ plan }: { plan: SqlPlanResponse | null }) { return <div className="plan-panel">{plan?.supported ? <pre>{plan.plan?.join("\n") ?? "No plan rows returned."}</pre> : <p>{plan?.warning ?? "Inspect a read-only query plan when the active connector supports EXPLAIN."}</p>}</div>; }
function JoinDiagnosticsPanel({ diagnostics, loading, error }: { diagnostics: JoinDiagnosticsResponse | null; loading: boolean; error: string | null }) {
  if (loading) return <div className="plan-panel"><p>Computing key cardinality and unmatched-key counts…</p></div>;
  if (error) return <div className="plan-panel"><p className="query-error" role="alert">{error}</p></div>;
  if (!diagnostics) return <div className="plan-panel"><p>Select "Inspect joins" to check key cardinality, unmatched keys, and row-multiplication risk for this query's joins.</p></div>;
  return <div className="join-diagnostics">
    {(diagnostics.joins ?? []).length ? (diagnostics.joins ?? []).map((join) => <article key={join.join_index} className={join.row_multiplication_risk ? "join-diagnostic-card is-risky" : "join-diagnostic-card"}>
      <header><strong>{join.join_kind} join</strong>{join.row_multiplication_risk ? <span className="migration-chip unavailable">row-multiplication risk</span> : null}</header>
      <div className="join-diagnostic-sides">
        <div><span className="eyebrow">{join.left.table}.{join.left.column}</span><dl><div><dt>Rows</dt><dd>{join.left.total_rows.toLocaleString()}</dd></div><div><dt>Distinct keys</dt><dd>{join.left.distinct_keys.toLocaleString()}</dd></div><div><dt>Duplicate-key rows</dt><dd>{join.left.duplicate_key_rows.toLocaleString()}</dd></div><div><dt>Null keys</dt><dd>{join.left.null_keys.toLocaleString()}</dd></div></dl></div>
        <div><span className="eyebrow">{join.right.table}.{join.right.column}</span><dl><div><dt>Rows</dt><dd>{join.right.total_rows.toLocaleString()}</dd></div><div><dt>Distinct keys</dt><dd>{join.right.distinct_keys.toLocaleString()}</dd></div><div><dt>Duplicate-key rows</dt><dd>{join.right.duplicate_key_rows.toLocaleString()}</dd></div><div><dt>Null keys</dt><dd>{join.right.null_keys.toLocaleString()}</dd></div></dl></div>
      </div>
      <p className="quiet-note">{join.unmatched_left_rows.toLocaleString()} {join.left.table} row(s) have no match in {join.right.table}; {join.unmatched_right_rows.toLocaleString()} {join.right.table} row(s) have no match in {join.left.table}.</p>
    </article>) : null}
    {(diagnostics.unsupported_notes ?? []).length ? <ul className="clean-warnings">{(diagnostics.unsupported_notes ?? []).map((note) => <li key={note}>{note}</li>)}</ul> : null}
  </div>;
}
function HistoryPanel({ history, onUse, compareBaseRunId, compareRunId, onSetBase, onSetCompare, comparisonKeyColumnsText, onKeyColumnsChange, onCompare, comparison, comparisonLoading, comparisonError }: {
  history: SqlRunResponse[]; onUse(entry: SqlRunResponse): void;
  compareBaseRunId: string | null; compareRunId: string | null; onSetBase(runId: string): void; onSetCompare(runId: string): void;
  comparisonKeyColumnsText: string; onKeyColumnsChange(value: string): void; onCompare(): void;
  comparison: ResultComparisonResponse | null; comparisonLoading: boolean; comparisonError: string | null;
}) {
  if (!history.length) return <div className="history-panel"><p>No durable query history exists in this local project yet.</p></div>;
  return <div className="history-panel">
    {history.map((entry) => <div key={entry.run_id} className="history-row">
      <button onClick={() => onUse(entry)}><span className={`migration-chip ${entry.state === "succeeded" ? "ready" : "unavailable"}`}>{entry.state}</span><code>{entry.sql.replaceAll("\n", " ").slice(0, 120)}</code><small>{entry.duration_ms ?? 0} ms · {entry.provenance.dialect}</small></button>
      <div className="history-compare-picks">
        <button className={compareBaseRunId === entry.run_id ? "secondary is-selected" : "secondary"} disabled={entry.state !== "succeeded"} onClick={() => onSetBase(entry.run_id)}>Base</button>
        <button className={compareRunId === entry.run_id ? "secondary is-selected" : "secondary"} disabled={entry.state !== "succeeded"} onClick={() => onSetCompare(entry.run_id)}>Compare</button>
      </div>
    </div>)}
    <div className="clean-manual-form">
      <label>Row-matching key column(s)<input aria-label="Comparison key columns" value={comparisonKeyColumnsText} onChange={(event) => onKeyColumnsChange(event.target.value)} placeholder="e.g. id or customer_id, order_id" /></label>
      <button type="button" disabled={!compareBaseRunId || !compareRunId || comparisonLoading} onClick={onCompare}>{comparisonLoading ? "Comparing…" : "Compare selected runs"}</button>
      {comparisonError ? <p className="quiet-note">{comparisonError}</p> : null}
    </div>
    {comparison ? <div className="comparison-result">
      <p className="clean-preview-summary"><strong>{comparison.added_count}</strong> added, <strong>{comparison.removed_count}</strong> removed, <strong>{comparison.changed_count}</strong> changed, <strong>{comparison.unchanged_count}</strong> unchanged (matched by {comparison.key_columns.join(", ")}).</p>
      {(comparison.warnings ?? []).length ? <ul className="clean-warnings">{(comparison.warnings ?? []).map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
      {(comparison.sample_diffs ?? []).length ? <ul className="clean-recipe-list">{(comparison.sample_diffs ?? []).map((diff, index) => <li key={index}>
        <div><strong>{diff.change}</strong><small>{Object.entries(diff.key).map(([k, v]) => `${k}=${v}`).join(", ")}{diff.changed_columns?.length ? ` · ${diff.changed_columns.join(", ")}` : ""}</small></div>
      </li>)}</ul> : null}
    </div> : null}
  </div>;
}
function SourceCapabilities({ connections }: { connections: SqlConnectionSummary[] }) { if (!connections.length) return null; return <section className="source-capabilities"><span className="eyebrow">CONNECTOR CAPABILITIES</span>{connections.map((connection) => <article key={connection.connection_id}><strong>{connection.label}</strong><span className={`migration-chip ${connection.status === "ready" ? "ready" : "unavailable"}`}>{connection.status}</span><small>{connection.capabilities.map((capability) => capability.reason).find(Boolean) ?? "Available"}</small></article>)}</section>; }
