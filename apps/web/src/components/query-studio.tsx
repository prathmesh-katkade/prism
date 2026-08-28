"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { AtlasSqlAction, AtlasSqlResponse, SqlConnectionSummary, SqlPlanResponse, SqlResultPageResponse, SqlResultPromotionResponse, SqlRunResponse, SqlSchemaResponse, SqlSnippet } from "@prism/api-contracts";
import type { InspectorObjectState } from "../state/shell-model";
import { QueryEditor } from "./query-editor";

const API_BASE = process.env.NEXT_PUBLIC_PRISM_API_URL ?? "http://127.0.0.1:8000";

function apiUrl(path: string): string { return new URL(path, API_BASE).toString(); }

type StudioState = "loading" | "empty" | "ready" | "running" | "degraded" | "error";
type ResultTab = "results" | "plan" | "history";

export function QueryStudio({ onSelectContext, initialSql, onUseAsEvidence }: { onSelectContext(state: InspectorObjectState): void; initialSql?: string; onUseAsEvidence?(runId: string): void }) {
  const [state, setState] = useState<StudioState>("loading");
  const [connections, setConnections] = useState<SqlConnectionSummary[]>([]);
  const [connectionId, setConnectionId] = useState("");
  const [schema, setSchema] = useState<SqlSchemaResponse | null>(null);
  const [sql, setSql] = useState("SELECT *\nFROM data\nLIMIT 100;");
  const [parametersText, setParametersText] = useState("{}");
  const [run, setRun] = useState<SqlRunResponse | null>(null);
  const [results, setResults] = useState<SqlResultPageResponse | null>(null);
  const [plan, setPlan] = useState<SqlPlanResponse | null>(null);
  const [history, setHistory] = useState<SqlRunResponse[]>([]);
  const [snippets, setSnippets] = useState<SqlSnippet[]>([]);
  const [atlas, setAtlas] = useState<AtlasSqlResponse | null>(null);
  const [activeResultTab, setActiveResultTab] = useState<ResultTab>("results");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { if (initialSql) setSql(initialSql); }, [initialSql]);

  const activeConnection = useMemo(() => connections.find((item) => item.connection_id === connectionId) ?? null, [connectionId, connections]);
  const readyConnections = useMemo(() => connections.filter((item) => item.status === "ready"), [connections]);

  const loadConnections = useCallback(async () => {
    setState("loading"); setError(null);
    try {
      const response = await fetch(apiUrl("/api/v1/sql-lab/connections"));
      if (!response.ok) throw new Error("SQL source metadata is unavailable.");
      const next = await response.json() as SqlConnectionSummary[];
      setConnections(next); setSnippets(await loadJson<SqlSnippet[]>("/api/v1/sql-lab/snippets"));
      const first = next.find((item) => item.status === "ready") ?? null;
      if (!first) { setState("empty"); return; }
      setConnectionId(first.connection_id); setState("ready");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "SQL Lab could not reach the PRISM API."); setState("error");
    }
  }, []);

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
    let parameters: Record<string, unknown>;
    try { parameters = JSON.parse(parametersText) as Record<string, unknown>; } catch { setError("Parameters must be valid JSON."); return; }
    setState("running"); setError(null); setAtlas(null);
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

  async function promoteResult() {
    if (!run || run.state !== "succeeded") return;
    try {
      const response = await fetch(apiUrl(`/api/v1/sql-lab/runs/${run.run_id}/promote`), { method: "POST" });
      if (!response.ok) throw new Error("The result could not become a PRISM dataset.");
      const promoted = await response.json() as SqlResultPromotionResponse;
      setRun(promoted.run);
      onSelectContext({ objectId: promoted.dataset.dataset_id, label: promoted.dataset.source_name, type: "dataset", state: "ready", actions: [{ id: "open-overview", label: "Open in Overview" }], metadata: [`${promoted.dataset.row_count} rows`, `Derived from ${run.run_id.slice(0, 12)}…`] });
    } catch (reason) { setError(reason instanceof Error ? reason.message : "The result could not become a PRISM dataset."); }
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
    <section className="query-toolbar" aria-label="Query source and actions"><label>Source<select value={connectionId} onChange={(event) => setConnectionId(event.target.value)}>{readyConnections.map((item) => <option key={item.connection_id} value={item.connection_id}>{item.label} · {item.dialect}</option>)}</select></label><label>Parameters<textarea aria-label="Query parameters JSON" value={parametersText} onChange={(event) => setParametersText(event.target.value)} /></label><button onClick={() => void execute()} disabled={!activeConnection || state === "running"}>Run query <kbd>⌘ ↵</kbd></button>{run && ["queued", "running"].includes(run.state) ? <button className="secondary" onClick={() => void cancelActiveRun()}>Cancel query</button> : null}<button className="secondary" onClick={() => setSql(formatSql(sql))} disabled={!activeConnection}>Format query</button><button className="secondary" onClick={() => void inspectPlan()} disabled={!activeConnection}>Inspect plan</button><button className="secondary" onClick={() => void saveSnippet()} disabled={!activeConnection}>Save snippet</button></section>
    <section className="query-layout"><div><QueryEditor value={sql} dialect={activeConnection?.dialect ?? "sql"} schemaItems={schema?.tables.flatMap((table) => [table.name, ...table.columns.map((column) => column.name)]) ?? []} onChange={setSql} onRun={() => void execute()} /><div className="query-editor-foot"><span>Dialect: <code>{activeConnection?.dialect ?? "unavailable"}</code></span><span>Safe reads run without a repeated prompt. Writes and unproven SQL are blocked.</span></div></div><SchemaPanel schema={schema} onInsert={(identifier) => setSql((current) => `${current}${current.endsWith(" ") || current.endsWith("\n") ? "" : " "}${identifier}`)} /></section>
    {error ? <p className="query-error" role="alert">{error}</p> : null}
    <section className="sql-result-panel"><div className="result-tabs" role="tablist" aria-label="SQL result views">{(["results", "plan", "history"] as ResultTab[]).map((tab) => <button key={tab} role="tab" aria-selected={activeResultTab === tab} onClick={() => setActiveResultTab(tab)}>{tab}</button>)}</div>{activeResultTab === "results" ? <DataGrid result={results} run={run} onSelectContext={onSelectContext} onPage={(offset) => void loadResultPage(offset)} onPromote={() => void promoteResult()} {...(onUseAsEvidence ? { onUseAsEvidence } : {})} /> : null}{activeResultTab === "plan" ? <PlanPanel plan={plan} /> : null}{activeResultTab === "history" ? <HistoryPanel history={history} onUse={(entry) => setSql(entry.sql)} /> : null}</section>
    <section className="sql-atlas"><div><span className="eyebrow">ATLAS · CONTEXTUAL SQL ACTIONS</span><h2>Inspect before execution.</h2><p>Atlas returns schema-grounded, editable drafts. It does not execute SQL, invent schema objects, or claim unsupported connectors.</p></div><div className="atlas-action-row">{(["explain_query", "optimize_query", "debug_error", "inspect_plan", "generate_sql", "compare_queries", "explain_selection", "trace_lineage", "convert_result"] as AtlasSqlAction[]).map((action) => <button key={action} onClick={() => void askAtlas(action)}>{action.replaceAll("_", " ")}</button>)}</div>{atlas ? <aside className="atlas-result" aria-live="polite"><span className="eyebrow">ATLAS RESPONSE · {atlas.action.replaceAll("_", " ")}</span><strong>{atlas.summary}</strong><small>{atlas.uncertainty}</small></aside> : null}</section>
    <SourceCapabilities connections={connections.filter((item) => item.status !== "ready")} />
    {snippets.length ? <section className="snippet-strip"><span className="eyebrow">SAVED SNIPPETS</span>{snippets.map((snippet) => <button key={snippet.snippet_id} onClick={() => setSql(snippet.sql)}>{snippet.name}</button>)}</section> : null}
  </article>;
}

async function loadJson<T>(path: string): Promise<T> { const response = await fetch(apiUrl(path)); if (!response.ok) throw new Error(`PRISM API request failed: ${response.status}`); return await response.json() as T; }
async function waitForTerminalRun(run: SqlRunResponse): Promise<SqlRunResponse> { if (!["queued", "running"].includes(run.state)) return run; for (let attempt = 0; attempt < 200; attempt += 1) { await new Promise((resolve) => window.setTimeout(resolve, 100)); const current = await loadJson<SqlRunResponse>(`/api/v1/sql-lab/runs/${run.run_id}`); if (!["queued", "running"].includes(current.state)) return current; } throw new Error("Query did not reach a terminal state before the client timeout."); }
function formatSql(value: string): string { return value.replace(/\b(select|from|where|group by|order by|limit|join|left join|inner join|on|as)\b/gi, (keyword) => keyword.toUpperCase()).replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|LIMIT|JOIN|LEFT JOIN|INNER JOIN)\b/g, "\n$1"); }

function SchemaPanel({ schema, onInsert }: { schema: SqlSchemaResponse | null; onInsert(identifier: string): void }) { return <aside className="schema-panel" aria-label="SQL schema browser"><span className="eyebrow">SCHEMA · AUTOCOMPLETE CONTEXT</span>{schema ? schema.tables.map((table) => <div key={table.name}><button className="schema-table" onClick={() => onInsert(table.name)}>{table.name}</button>{table.columns.map((column) => <button key={column.name} className="schema-column" onClick={() => onInsert(column.name)}><strong>{column.name}</strong><small>{column.data_type}{column.nullable ? " · nullable" : ""}</small></button>)}</div>) : <p>Schema metadata is loading.</p>}</aside>; }

function DataGrid({ result, run, onSelectContext, onPage, onPromote, onUseAsEvidence }: { result: SqlResultPageResponse | null; run: SqlRunResponse | null; onSelectContext(state: InspectorObjectState): void; onPage(offset: number): void; onPromote(): void; onUseAsEvidence?(runId: string): void }) {
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
  return <div><div className="result-meta"><span>{(run.returned_row_count ?? 0).toLocaleString()} returned / {(run.row_count ?? 0).toLocaleString()} {run.truncated ? "observed" : "total"} rows</span><span>{run.duration_ms ?? 0} ms</span><span>{run.truncated ? "result capped server-side" : "complete result"}</span><label className="result-filter">Filter page<input aria-label="Filter current result page" value={filterText} onChange={(event) => setFilterText(event.target.value)} /></label><button className="result-action" onClick={() => void copyPage()}>Copy page</button><a className="result-action" href={apiUrl(`/api/v1/sql-lab/runs/${run.run_id}/export?format=csv`)}>Export CSV</a><button className="result-action" onClick={onPromote}>Create dataset</button>{onUseAsEvidence ? <button className="result-action" onClick={() => onUseAsEvidence(run.run_id)}>Use as AI evidence</button> : null}<button className="result-action" onClick={() => onSelectContext({ objectId: `result:${run.run_id}`, label: "SQL result set", type: "dataset", state: "ready", actions: [{ id: "explain-result-set", label: "Ask Atlas to explain result" }, { id: "convert-result", label: "Create PRISM dataset" }], metadata: [`${run.returned_row_count ?? 0} rows`, `Fingerprint ${run.provenance.result_fingerprint?.slice(0, 12) ?? "pending"}…`] })}>Inspect result</button></div><div className="sql-grid-virtual" role="grid" aria-label="Query results" aria-rowcount={run.returned_row_count ?? 0}><div className="sql-grid-head" role="row" style={{ gridTemplateColumns }}>{columns.map((column) => <button key={column.name} role="columnheader" aria-sort={sortColumn === column.name ? (sortDescending ? "descending" : "ascending") : "none"} onClick={() => { setSortDescending(sortColumn === column.name ? !sortDescending : false); setSortColumn(column.name); }}>{column.name}<small>{column.data_type}</small></button>)}</div><div className="sql-grid-body" ref={scrollRef} role="rowgroup"><div style={{ height: `${virtualRows.getTotalSize()}px`, position: "relative" }}>{virtualRows.getVirtualItems().map((virtualRow) => { const row = rows[virtualRow.index] ?? {}; const rowIndex = (result?.offset ?? 0) + virtualRow.index; return <div key={virtualRow.key} className="sql-grid-row" role="row" style={{ gridTemplateColumns, transform: `translateY(${virtualRow.start}px)` }}>{columns.map((column) => <button key={column.name} role="gridcell" onClick={() => onSelectContext({ objectId: `result:${run.run_id}:${rowIndex}:${column.name}`, label: `${column.name} result value`, type: "finding", state: "ready", actions: [{ id: "explain-result-cell", label: "Ask Atlas to explain selection" }, { id: "copy-result-cell", label: "Copy value" }], metadata: [String(row[column.name] ?? "—"), `Run ${run.run_id.slice(0, 12)}…`] })}>{row[column.name] === null ? "—" : String(row[column.name])}</button>)}</div>; })}</div></div></div><div className="result-pagination"><button className="secondary" onClick={() => onPage(Math.max(0, (result?.offset ?? 0) - 100))} disabled={!result?.offset}>Previous 100</button><span>Rows {(result?.offset ?? 0) + 1}–{(result?.offset ?? 0) + rows.length}</span><button className="secondary" onClick={() => onPage((result?.offset ?? 0) + 100)} disabled={(result?.offset ?? 0) + rows.length >= (run.returned_row_count ?? 0)}>Next 100</button></div></div>;
}

function PlanPanel({ plan }: { plan: SqlPlanResponse | null }) { return <div className="plan-panel">{plan?.supported ? <pre>{plan.plan?.join("\n") ?? "No plan rows returned."}</pre> : <p>{plan?.warning ?? "Inspect a read-only query plan when the active connector supports EXPLAIN."}</p>}</div>; }
function HistoryPanel({ history, onUse }: { history: SqlRunResponse[]; onUse(entry: SqlRunResponse): void }) { return <div className="history-panel">{history.length ? history.map((entry) => <button key={entry.run_id} onClick={() => onUse(entry)}><span className={`migration-chip ${entry.state === "succeeded" ? "ready" : "unavailable"}`}>{entry.state}</span><code>{entry.sql.replaceAll("\n", " ").slice(0, 120)}</code><small>{entry.duration_ms ?? 0} ms · {entry.provenance.dialect}</small></button>) : <p>No durable query history exists in this local project yet.</p>}</div>; }
function SourceCapabilities({ connections }: { connections: SqlConnectionSummary[] }) { if (!connections.length) return null; return <section className="source-capabilities"><span className="eyebrow">CONNECTOR CAPABILITIES</span>{connections.map((connection) => <article key={connection.connection_id}><strong>{connection.label}</strong><span className={`migration-chip ${connection.status === "ready" ? "ready" : "unavailable"}`}>{connection.status}</span><small>{connection.capabilities.map((capability) => capability.reason).find(Boolean) ?? "Available"}</small></article>)}</section>; }
