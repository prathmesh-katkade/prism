"use client";

import { useCallback, useEffect, useState } from "react";
import type { OverviewProfileResponse, Report, ReportDetail, SavedChart } from "@prism/api-contracts";
import { apiUrl } from "../config/api";
import { ChartCanvas, FacetCharts } from "./visualize-workspace";

async function readJson<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const body = await response.json() as { detail?: string };
    throw new Error(body.detail ?? `Request failed (${response.status}).`);
  }
  return response.json() as Promise<T>;
}

export function ReportsWorkspace({ datasetId, onOpenWorkflow }: { datasetId?: string | undefined; onOpenWorkflow(workflow: string): void }) {
  const [reports, setReports] = useState<Report[]>([]);
  const [charts, setCharts] = useState<SavedChart[]>([]);
  const [detail, setDetail] = useState<ReportDetail | null>(null);
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [selectedChartId, setSelectedChartId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [sourceProfile, setSourceProfile] = useState<OverviewProfileResponse | null>(null);
  const [tableTitle, setTableTitle] = useState("");
  const [tableColumns, setTableColumns] = useState<string[]>([]);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [nextReports, nextCharts] = await Promise.all([
        fetch(apiUrl("/api/v1/reports")).then(readJson<Report[]>),
        fetch(apiUrl("/api/v1/reports/charts")).then(readJson<SavedChart[]>),
      ]);
      setReports(nextReports); setCharts(nextCharts);
      if (nextReports.length) setDetail(await fetch(apiUrl(`/api/v1/reports/${nextReports[0]!.report_id}`)).then(readJson<ReportDetail>));
      else setDetail(null);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not load reports."); }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { if (!datasetId) { setSourceProfile(null); return; } void fetch(apiUrl(`/api/v1/overview/datasets/${datasetId}/profile`)).then(readJson<OverviewProfileResponse>).then(setSourceProfile).catch(() => setSourceProfile(null)); }, [datasetId]);

  async function moveItem(itemId: string, direction: -1 | 1) {
    if (!detail) return;
    const order = [...(detail.report.item_order ?? [])];
    const index = order.indexOf(itemId); const target = index + direction;
    if (index < 0 || target < 0 || target >= order.length) return;
    [order[index], order[target]] = [order[target]!, order[index]!];
    await mutate(`/api/v1/reports/${detail.report.report_id}/order`, "PUT", { item_order: order });
  }

  async function addTable() {
    if (!detail || !datasetId || !sourceProfile || !tableTitle.trim() || !tableColumns.length) return;
    await mutate(`/api/v1/reports/${detail.report.report_id}/tables`, "POST", {
      title: tableTitle.trim(), dataset_id: datasetId, source_revision: sourceProfile.dataset.revision,
      source_fingerprint: sourceProfile.dataset.source_fingerprint, columns: tableColumns, limit: 50,
    });
    setTableTitle("");
  }

  async function openReport(reportId: string) {
    setError(null);
    try { setDetail(await fetch(apiUrl(`/api/v1/reports/${reportId}`)).then(readJson<ReportDetail>)); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not open report."); }
  }

  async function mutate(url: string, method: string, body?: unknown) {
    setBusy(true); setError(null);
    try {
      const next = await fetch(apiUrl(url), { method, ...(body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }) }).then(readJson<ReportDetail>);
      setDetail(next);
      setReports((previous) => previous.map((report) => report.report_id === next.report.report_id ? next.report : report));
      setCharts((previous) => [...(next.charts ?? []).filter((chart) => !previous.some((old) => old.chart_id === chart.chart_id)), ...previous]);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Report change failed."); }
    finally { setBusy(false); }
  }

  async function createReport() {
    if (!name.trim()) return;
    setBusy(true); setError(null);
    try {
      const report = await fetch(apiUrl("/api/v1/reports"), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: name.trim() }) }).then(readJson<Report>);
      setReports((previous) => [report, ...previous]);
      setDetail({ report, charts: [], freshness: [] }); setName("");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not create report."); }
    finally { setBusy(false); }
  }

  async function addNote() {
    if (!detail || !note.trim()) return;
    setBusy(true); setError(null);
    try {
      const report = await fetch(apiUrl(`/api/v1/reports/${detail.report.report_id}/notes`), { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ text: note.trim() }) }).then(readJson<Report>);
      setDetail({ ...detail, report }); setNote("");
      setReports((previous) => previous.map((item) => item.report_id === report.report_id ? report : item));
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not add note."); }
    finally { setBusy(false); }
  }

  async function refresh(chart: SavedChart) {
    if (!detail) return;
    const freshness = detail.freshness?.find((item) => item.chart_id === chart.chart_id);
    if (!freshness?.current_fingerprint || freshness.current_revision === undefined) return;
    await mutate(`/api/v1/reports/${detail.report.report_id}/refresh`, "POST", {
      chart_ids: [chart.chart_id], source_revisions: { [chart.chart_id]: freshness.current_revision },
      source_fingerprints: { [chart.chart_id]: freshness.current_fingerprint },
    });
  }

  return <article className="reports-workspace">
    <nav className="reports-list" aria-label="Saved reports">
      <span className="eyebrow">REPORTS</span><h1>Saved evidence</h1>
      <label>New report name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Monthly review" /></label>
      <button disabled={busy || !name.trim()} onClick={() => void createReport()}>Create report</button>
      <ol>{reports.map((report) => <li key={report.report_id}><button className={detail?.report.report_id === report.report_id ? "is-selected" : ""} onClick={() => void openReport(report.report_id)}>{report.name}<small>{report.chart_refs?.length ?? 0} chart(s) · {report.notes?.length ?? 0} note(s)</small></button></li>)}</ol>
    </nav>
    <section className="reports-canvas" aria-label="Report canvas">
      {loading ? <p aria-live="polite">Loading saved reports…</p> : null}
      {error ? <div role="alert" className="query-error">{error} <button onClick={() => void load()}>Retry</button></div> : null}
      {!loading && !detail ? <div className="overview-state empty-state"><h1>Start a report</h1><p>Save a chart in Visualize, then create a report here to preserve the result and its source revision.</p><button onClick={() => onOpenWorkflow("visualize")}>Open Visualize</button></div> : null}
      {detail ? <>
        <header><span className="eyebrow">REPORT CANVAS · EXPLICIT SOURCE VERSIONS</span><h1>{detail.report.name}</h1><small>Saved {new Date(detail.report.created_at).toLocaleString()}</small></header>
        <div className="report-add"><label>Add saved chart<select value={selectedChartId} onChange={(event) => setSelectedChartId(event.target.value)}><option value="">Choose a chart</option>{charts.filter((chart) => !detail.report.chart_refs?.some((ref) => ref.chart_id === chart.chart_id)).map((chart) => <option key={chart.chart_id} value={chart.chart_id}>{chart.name} · revision {chart.dataset_revision}</option>)}</select></label><button disabled={busy || !selectedChartId} onClick={() => { void mutate(`/api/v1/reports/${detail.report.report_id}/charts`, "POST", { chart_id: selectedChartId }); setSelectedChartId(""); }}>Add chart</button></div>
        {sourceProfile ? <details className="report-add report-table-editor"><summary>Table snapshot controls · current revision {sourceProfile.dataset.revision}</summary><label>Table title<input value={tableTitle} onChange={(event) => setTableTitle(event.target.value)} placeholder="Source rows" /></label><fieldset><legend>Columns</legend>{sourceProfile.columns.map((column) => <label key={column.name}><input type="checkbox" checked={tableColumns.includes(column.name)} onChange={(event) => setTableColumns((previous) => event.target.checked ? [...previous, column.name] : previous.filter((name) => name !== column.name))} />{column.name}</label>)}</fieldset><button disabled={busy || !tableTitle.trim() || !tableColumns.length} onClick={() => void addTable()}>Add table snapshot</button><small>First 50 source rows saved with revision and fingerprint.</small></details> : null}
        <div className="report-items">{(detail.report.item_order ?? []).map((itemId, index) => {
          const chart = detail.charts?.find((item) => item.chart_id === itemId);
          const freshness = detail.freshness?.find((item) => item.chart_id === itemId);
          const table = detail.report.tables?.find((item) => item.table_id === itemId);
          const tableFreshness = detail.table_freshness?.find((item) => item.table_id === itemId);
          const noteItem = detail.report.notes?.find((item) => item.note_id === itemId);
          const controls = <div className="report-order-controls"><button className="secondary" disabled={busy || index === 0} onClick={() => void moveItem(itemId, -1)} aria-label={`Move item ${index + 1} up`}>↑</button><button className="secondary" disabled={busy || index === (detail.report.item_order?.length ?? 0) - 1} onClick={() => void moveItem(itemId, 1)} aria-label={`Move item ${index + 1} down`}>↓</button></div>;
          if (chart) return <section className="report-item" key={itemId}><header><div><span className="eyebrow">CHART · REVISION {chart.dataset_revision}</span><h2>{chart.name}</h2></div>{controls}<button className="secondary" disabled={busy} onClick={() => void mutate(`/api/v1/reports/${detail.report.report_id}/charts/${chart.chart_id}`, "DELETE")}>Remove</button></header>
            {freshness?.dataset_unavailable ? <p className="report-stale" role="status">Source unavailable. This saved result is the last available snapshot; refresh is disabled.</p> : freshness?.needs_refresh ? <p className="report-stale" role="status">Source changed: saved revision {chart.dataset_revision}; current revision {freshness.current_revision}. Review before refreshing.</p> : <p className="quiet-note">Source revision {chart.dataset_revision} · fingerprint {chart.source_fingerprint.slice(0, 12)}…</p>}
            {chart.result ? chart.result.facets?.length ? <FacetCharts result={chart.result} /> : <ChartCanvas mark={chart.spec.mark} data={chart.result.data} referenceLine={chart.spec.reference_line} /> : <p className="report-stale">This older chart has no preserved rendered result.</p>}
            {chart.result?.warnings?.length ? <ul className="clean-warnings">{chart.result.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul> : null}
            {freshness?.needs_refresh && !freshness.dataset_unavailable ? <button disabled={busy} onClick={() => void refresh(chart)}>Refresh from reviewed current source</button> : null}
            {chart.previous_chart_id ? <PreviousChartVersion chartId={chart.previous_chart_id} /> : null}
          </section>;
          if (table) return <section className="report-item" key={itemId}><header><div><span className="eyebrow">TABLE · REVISION {table.dataset_revision}</span><h2>{table.title}</h2></div>{controls}<button className="secondary" disabled={busy} onClick={() => void mutate(`/api/v1/reports/${detail.report.report_id}/tables/${table.table_id}`, "DELETE")}>Remove</button></header>{tableFreshness?.dataset_unavailable ? <p className="report-stale" role="status">Table source unavailable. Showing the preserved snapshot.</p> : tableFreshness?.needs_refresh ? <><p className="report-stale" role="status">Table source changed after this snapshot. Showing saved revision {table.dataset_revision}; current revision {tableFreshness.current_revision}.</p><button disabled={busy} onClick={() => void mutate(`/api/v1/reports/${detail.report.report_id}/tables/${table.table_id}/refresh`, "POST", { source_revision: tableFreshness.current_revision, source_fingerprint: tableFreshness.current_fingerprint })}>Refresh table from reviewed current source</button></> : null}<p className="quiet-note">Saved {table.rows.length} of {table.source_row_count} source rows · fingerprint {table.source_fingerprint.slice(0, 12)}…</p><div className="data-table-wrap" tabIndex={0}><table><thead><tr>{table.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{table.rows.map((row, rowIndex) => <tr key={rowIndex}>{table.columns.map((column) => <td key={column}>{row[column] === null || row[column] === undefined ? "—" : String(row[column])}</td>)}</tr>)}</tbody></table></div>{table.previous_table_id ? <details><summary>Inspect previous table versions</summary>{detail.report.table_history?.filter((version) => version.table_id === table.previous_table_id || version.title === table.title).map((version) => <div key={version.table_id}><p>Version {version.table_id} · revision {version.dataset_revision} · {version.rows.length} saved row(s)</p><div className="data-table-wrap" tabIndex={0}><table><thead><tr>{version.columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{version.rows.map((row, rowIndex) => <tr key={rowIndex}>{version.columns.map((column) => <td key={column}>{row[column] === null || row[column] === undefined ? "—" : String(row[column])}</td>)}</tr>)}</tbody></table></div></div>)}</details> : null}</section>;
          if (noteItem) return <section className="report-item" key={itemId}><header><span className="eyebrow">NOTE</span>{controls}<button className="secondary" disabled={busy} onClick={async () => { setBusy(true); setError(null); try { const report = await fetch(apiUrl(`/api/v1/reports/${detail.report.report_id}/notes/${noteItem.note_id}`), { method: "DELETE" }).then(readJson<Report>); setDetail({ ...detail, report }); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not remove note."); } finally { setBusy(false); } }}>Remove</button></header><p>{noteItem.text}</p></section>;
          return null;
        })}</div>
        <div className="report-add"><label>New note<textarea value={note} onChange={(event) => setNote(event.target.value)} placeholder="Interpretation, caveat, or next question" /></label><button disabled={busy || !note.trim()} onClick={() => void addNote()}>Add note</button></div>
      </> : null}
    </section>
  </article>;
}

function PreviousChartVersion({ chartId }: { chartId: string }) {
  const [chart, setChart] = useState<SavedChart | null>(null);
  const [error, setError] = useState<string | null>(null);
  return <details onToggle={(event) => {
    if (!event.currentTarget.open || chart || error) return;
    void fetch(apiUrl(`/api/v1/reports/charts/${chartId}`)).then(readJson<SavedChart>).then(setChart).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Previous chart version is unavailable."));
  }}><summary>Inspect previous chart version</summary>{error ? <p role="alert">{error}</p> : chart ? <div><p>Saved revision {chart.dataset_revision} · fingerprint {chart.source_fingerprint.slice(0, 12)}…</p>{chart.result ? chart.result.facets?.length ? <FacetCharts result={chart.result} /> : <ChartCanvas mark={chart.spec.mark} data={chart.result.data} referenceLine={chart.spec.reference_line} /> : <p>Stored chart has no rendered snapshot.</p>}{chart.previous_chart_id ? <PreviousChartVersion chartId={chart.previous_chart_id} /> : null}</div> : <p>Loading previous snapshot…</p>}</details>;
}
