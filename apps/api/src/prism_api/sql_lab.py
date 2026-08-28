"""Phase 4 SQL Lab routes: typed metadata, guarded execution, results, and contextual Atlas drafts."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import sqlite3
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, cast

import pandas as pd
from fastapi import APIRouter, HTTPException, Query, Response, status
from prism_api_contracts import (
    AtlasEvidence,
    AtlasSqlAction,
    AtlasSqlRequest,
    AtlasSqlResponse,
    QueryExecutionState,
    QueryRisk,
    SqlCapability,
    SqlColumn,
    SqlConnectionSummary,
    SqlDialect,
    SqlPlanResponse,
    SqlProvenance,
    SqlResultColumn,
    SqlResultPageResponse,
    SqlResultPromotionResponse,
    SqlRunRequest,
    SqlRunResponse,
    SqlSchemaResponse,
    SqlSnippet,
    SqlSnippetCreate,
    SqlSourceType,
    SqlTable,
)
from prism_sql_lab_runtime import (
    SQL_LAB_SERVICE_VERSION,
    ExternalConnectorError,
    ExternalSource,
    classify_query,
    execute_external_query,
    execute_local_query,
    execute_sqlite_query,
    external_driver_error,
    external_plan,
    external_schema,
    load_external_sources,
    schema_for_frame,
)

from .overview import StoredDataset
from .overview import store as overview_store
from .sql_jobs import QueryJob, runtime
from .transport import ServerSentEvent, sse_response

router = APIRouter(prefix="/api/v1/sql-lab", tags=["sql-lab"])
RESULT_PAGE_LIMIT = 1_000


@dataclass
class StoredRun:
    response: SqlRunResponse
    frame: pd.DataFrame
    materialized: bool = False


@dataclass(frozen=True)
class ConnectionTarget:
    connection: SqlConnectionSummary
    dataset: StoredDataset | None = None
    sqlite_path: Path | None = None
    external_source: ExternalSource | None = field(default=None, repr=False)


class SqlLabStore:
    """Durable, secret-free execution metadata with in-memory result pages.

    Result data intentionally remains ephemeral: durable metadata lets a user inspect and
    reproduce a run without silently retaining potentially sensitive result values.
    """

    def __init__(self, database_path: Path | None = None) -> None:
        self._runs: dict[str, StoredRun] = {}
        self._snippets: dict[str, SqlSnippet] = {}
        self._lock = RLock()
        configured_path = os.environ.get("PRISM_SQL_METADATA_PATH")
        self._database_path = database_path or Path(configured_path or ".prism/runtime/sql-lab.sqlite")
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._database() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS sql_lab_runs (run_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS sql_lab_snippets (snippet_id TEXT PRIMARY KEY, payload TEXT NOT NULL)")
            connection.execute("CREATE TABLE IF NOT EXISTS sql_lab_idempotency (request_id TEXT PRIMARY KEY, request_fingerprint TEXT NOT NULL, run_id TEXT NOT NULL)")
            rows = connection.execute("SELECT run_id, payload FROM sql_lab_runs").fetchall()
            for run_id, payload in rows:
                recovered = SqlRunResponse.model_validate_json(cast(str, payload))
                if recovered.state in {QueryExecutionState.QUEUED, QueryExecutionState.RUNNING}:
                    interrupted = recovered.model_copy(update={
                        "state": QueryExecutionState.FAILED,
                        "error": "The API process restarted before this query reached a terminal state; rerun it from history.",
                        "warnings": [*recovered.warnings, "Execution interrupted by API restart."],
                    })
                    connection.execute(
                        "UPDATE sql_lab_runs SET payload = ? WHERE run_id = ?",
                        (self._payload(interrupted), cast(str, run_id)),
                    )

    def _database(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database_path)

    @staticmethod
    def _payload(model: SqlRunResponse | SqlSnippet) -> str:
        return model.model_dump_json()

    def _persist_run(self, run: SqlRunResponse) -> None:
        with self._database() as connection:
            connection.execute("INSERT OR REPLACE INTO sql_lab_runs (run_id, payload) VALUES (?, ?)", (run.run_id, self._payload(run)))

    def _persist_snippet(self, snippet: SqlSnippet) -> None:
        with self._database() as connection:
            connection.execute("INSERT OR REPLACE INTO sql_lab_snippets (snippet_id, payload) VALUES (?, ?)", (snippet.snippet_id, self._payload(snippet)))

    def put_run(self, run: StoredRun, request_id: str | None = None, request_fingerprint: str | None = None) -> None:
        with self._lock:
            self._runs[run.response.run_id] = run
            self._persist_run(run.response)
            if request_id is not None and request_fingerprint is not None:
                with self._database() as connection:
                    connection.execute(
                        "INSERT OR REPLACE INTO sql_lab_idempotency (request_id, request_fingerprint, run_id) VALUES (?, ?, ?)",
                        (request_id, request_fingerprint, run.response.run_id),
                    )

    def idempotent_run(self, request_id: str, request_fingerprint: str) -> SqlRunResponse | None:
        with self._database() as connection:
            row = connection.execute(
                "SELECT request_fingerprint, run_id FROM sql_lab_idempotency WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            return None
        if cast(str, row[0]) != request_fingerprint:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="The client request ID was already used for a different SQL execution payload.",
            )
        return self.get_run(cast(str, row[1])).response

    def update_run(self, run_id: str, response: SqlRunResponse, frame: pd.DataFrame | None = None) -> None:
        with self._lock:
            existing = self.get_run(run_id)
            existing.response = response
            if frame is not None:
                existing.frame = frame
                existing.materialized = True
            self._persist_run(response)

    def get_run(self, run_id: str) -> StoredRun:
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                return run
            with self._database() as connection:
                row = connection.execute("SELECT payload FROM sql_lab_runs WHERE run_id = ?", (run_id,)).fetchone()
            if row is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SQL Lab run was not found.")
            recovered = StoredRun(response=SqlRunResponse.model_validate_json(cast(str, row[0])), frame=pd.DataFrame(), materialized=False)
            self._runs[run_id] = recovered
            return recovered

    def history(self) -> list[SqlRunResponse]:
        with self._database() as connection:
            rows = connection.execute("SELECT payload FROM sql_lab_runs ORDER BY rowid DESC LIMIT 100").fetchall()
        return [SqlRunResponse.model_validate_json(cast(str, row[0])) for row in rows]

    def save_snippet(self, name: str, sql: str, dialect: SqlDialect, parameters: dict[str, Any]) -> SqlSnippet:
        snippet = SqlSnippet(
            snippet_id=f"snippet_{uuid.uuid4().hex}", name=name, sql=sql, dialect=dialect,
            parameters=parameters, created_at=datetime.now(timezone.utc),
        )
        with self._lock:
            self._snippets[snippet.snippet_id] = snippet
            self._persist_snippet(snippet)
        return snippet

    def snippets(self) -> list[SqlSnippet]:
        with self._database() as connection:
            rows = connection.execute("SELECT payload FROM sql_lab_snippets ORDER BY rowid DESC").fetchall()
        return [SqlSnippet.model_validate_json(cast(str, row[0])) for row in rows]


store = SqlLabStore()


def _fingerprint(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _safe_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    """Provenance retains reproducibility shape without recording credential-like values."""
    secret_markers = ("password", "secret", "token", "credential", "api_key", "apikey")
    return {
        key: "[redacted]" if any(marker in key.lower() for marker in secret_markers) else value
        for key, value in parameters.items()
    }


def _json_value(value: Any) -> object | None:
    if value is None:
        return None
    if isinstance(value, (str, bool, int)):
        return cast(object, value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else cast(object, value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value.isoformat())
    return None if bool(pd.isna(value)) else str(value)


def _capability(name: str, supported: bool, reason: str | None = None) -> SqlCapability:
    return SqlCapability(name=name, supported=supported, reason=reason)


def _quoted_identifier(name: str, dialect: SqlDialect) -> str:
    if dialect is SqlDialect.MYSQL:
        return f"`{name.replace('`', '``')}`"
    if dialect is SqlDialect.SQLSERVER:
        return f"[{name.replace(']', ']]')}]"
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def _bounded_select(table_name: str, dialect: SqlDialect) -> str:
    table = _quoted_identifier(table_name, dialect)
    if dialect is SqlDialect.SQLSERVER:
        return f"SELECT TOP (100) *\nFROM {table};"
    return f"SELECT *\nFROM {table}\nLIMIT 100;"


def _local_connection(dataset: StoredDataset) -> SqlConnectionSummary:
    return SqlConnectionSummary(
        connection_id=f"local:{dataset.dataset.dataset_id}", label=f"{dataset.dataset.source_name} · local dataset",
        source_type=SqlSourceType.LOCAL_DATASET, dialect=SqlDialect.DUCKDB, status="ready",
        source_fingerprint=dataset.source_fingerprint,
        capabilities=[
            _capability("query_execution", True), _capability("schema_autocomplete", True),
            _capability("query_plan", True), _capability("safe_read", True),
            _capability("cancellation", True),
            _capability("writes", False, "Native SQL Lab only permits proven read queries."),
        ],
    )


def _configured_sqlite_sources() -> list[ConnectionTarget]:
    """Load server-owned SQLite paths; neither paths nor credentials cross the API boundary."""
    raw = os.environ.get("PRISM_SQLITE_SOURCES_JSON", "[]")
    try:
        entries = json.loads(raw)
    except json.JSONDecodeError:
        entries = []
    if not isinstance(entries, list):
        return []
    sources: list[ConnectionTarget] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id, label, raw_path = entry.get("id"), entry.get("label"), entry.get("path")
        if not all(isinstance(value, str) and value.strip() for value in (source_id, label, raw_path)):
            continue
        path = Path(cast(str, raw_path)).expanduser()
        exists = path.is_file()
        fingerprint = _fingerprint({"source_id": source_id, "path": str(path.resolve()) if exists else raw_path, "mtime": path.stat().st_mtime_ns if exists else None})
        connection = SqlConnectionSummary(
            connection_id=f"sqlite:{source_id}", label=cast(str, label), source_type=SqlSourceType.SQLITE,
            dialect=SqlDialect.SQLITE, status="ready" if exists else "degraded", source_fingerprint=fingerprint,
            capabilities=[
                _capability("query_execution", exists, None if exists else "The server-configured SQLite file is unavailable."),
                _capability("schema_autocomplete", exists), _capability("query_plan", exists),
                _capability("safe_read", exists), _capability("cancellation", exists),
                _capability("writes", False, "Native SQL Lab only permits proven read queries."),
            ],
        )
        sources.append(ConnectionTarget(connection=connection, sqlite_path=path))
    return sources


def _configured_external_sources() -> list[ConnectionTarget]:
    sources = load_external_sources(os.environ.get("PRISM_EXTERNAL_SQL_SOURCES_JSON", "[]"), os.environ)
    targets: list[ConnectionTarget] = []
    for source in sources:
        driver_error = external_driver_error(source)
        ready = source.connection_url is not None and driver_error is None
        source_type = SqlSourceType(source.dialect)
        plan_supported = source.dialect != SqlDialect.SQLSERVER.value
        connection = SqlConnectionSummary(
            connection_id=f"{source.dialect}:{source.source_id}", label=source.label,
            source_type=source_type, dialect=SqlDialect(source.dialect),
            status="ready" if ready else "degraded",
            source_fingerprint=_fingerprint({"source_id": source.source_id, "dialect": source.dialect}),
            capabilities=[
                _capability("query_execution", ready, driver_error),
                _capability("schema_autocomplete", ready, driver_error),
                _capability("query_plan", ready and plan_supported, None if plan_supported else "SQL Server SHOWPLAN is not enabled."),
                _capability("safe_read", ready, driver_error),
                _capability("cancellation", ready, driver_error),
                _capability("writes", False, "Native SQL Lab only permits proven read queries."),
            ],
        )
        targets.append(ConnectionTarget(connection=connection, external_source=source))
    return targets


def _unavailable_connections(configured: set[SqlSourceType]) -> list[SqlConnectionSummary]:
    return [
        SqlConnectionSummary(
            connection_id=f"unavailable:{source.value}", label=label, source_type=source, dialect=dialect,
            status="unavailable", capabilities=[_capability("query_execution", False, reason)],
        )
        for source, dialect, label, reason in [
            (SqlSourceType.MYSQL, SqlDialect.MYSQL, "MySQL", "Configure a server-side secret reference to enable the native MySQL connector."),
            (SqlSourceType.POSTGRESQL, SqlDialect.POSTGRESQL, "PostgreSQL", "Configure a server-side secret reference and PostgreSQL driver to enable this connector."),
            (SqlSourceType.SQLSERVER, SqlDialect.SQLSERVER, "SQL Server", "Configure a server-side secret reference and ODBC driver to enable this connector."),
        ]
        if source not in configured
    ]


def _connection(connection_id: str) -> ConnectionTarget:
    dataset = overview_store.latest()
    if dataset is not None and connection_id == f"local:{dataset.dataset.dataset_id}":
        return ConnectionTarget(connection=_local_connection(dataset), dataset=dataset)
    for target in _configured_sqlite_sources():
        if target.connection.connection_id == connection_id:
            if target.connection.status != "ready":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This server-configured SQLite source is currently unavailable.")
            return target
    for target in _configured_external_sources():
        if target.connection.connection_id == connection_id:
            if target.connection.status != "ready":
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This server-configured external source is currently unavailable.")
            return target
    if connection_id.startswith("unavailable:"):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This source is intentionally unavailable; inspect its connector capabilities.")
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SQL Lab source was not found. Load a dataset in native Overview first.")


def _schema(target: ConnectionTarget) -> SqlSchemaResponse:
    connection = target.connection
    if target.external_source is not None:
        try:
            raw_tables = external_schema(target.external_source)
        except ExternalConnectorError as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
        tables = [
            SqlTable(name=cast(str, table["name"]), columns=[SqlColumn(**cast(dict[str, Any], column)) for column in cast(list[dict[str, object]], table["columns"])])
            for table in raw_tables
        ]
        fingerprint = _fingerprint({"source": connection.source_fingerprint, "tables": [table.model_dump() for table in tables]})
        return SqlSchemaResponse(connection=connection, tables=tables, schema_fingerprint=fingerprint)
    if target.sqlite_path is not None:
        try:
            with sqlite3.connect(target.sqlite_path) as database:
                table_names = [cast(str, row[0]) for row in database.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                tables = [
                    SqlTable(name=table_name, columns=[
                        SqlColumn(name=cast(str, column[1]), data_type=cast(str, column[2]) or "unknown", nullable=not bool(column[3]), sample_count=0)
                        for column in database.execute(f'PRAGMA table_info("{table_name.replace(chr(34), chr(34) * 2)}")')
                    ])
                    for table_name in table_names
                ]
        except sqlite3.Error as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="SQLite schema metadata is unavailable.") from error
        fingerprint = _fingerprint({"source": connection.source_fingerprint, "tables": [table.model_dump() for table in tables]})
        return SqlSchemaResponse(connection=connection, tables=tables, schema_fingerprint=fingerprint)
    if target.dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="SQL Lab source was not found.")
    columns = [
        SqlColumn(
            name=str(column["name"]), data_type=str(column["data_type"]), nullable=bool(column["nullable"]),
            sample_count=cast(int, column["sample_count"]),
        )
        for column in schema_for_frame(target.dataset.frame)
    ]
    fingerprint = _fingerprint({"source": target.dataset.source_fingerprint, "columns": [column.model_dump() for column in columns]})
    return SqlSchemaResponse(connection=connection, tables=[SqlTable(name="data", columns=columns)], schema_fingerprint=fingerprint)


def _provenance(connection: SqlConnectionSummary, schema: SqlSchemaResponse, request: SqlRunRequest, result: pd.DataFrame | None = None) -> SqlProvenance:
    return SqlProvenance(
        connection_id=connection.connection_id, source_fingerprint=connection.source_fingerprint or _fingerprint(connection.connection_id),
        schema_fingerprint=schema.schema_fingerprint, sql_fingerprint=_fingerprint(request.sql), dialect=connection.dialect,
        parameters=_safe_parameters(request.parameters), service_version=SQL_LAB_SERVICE_VERSION, executed_at=datetime.now(timezone.utc),
        result_fingerprint=None if result is None else _fingerprint({"columns": list(result.columns), "rows": result.head(RESULT_PAGE_LIMIT).to_dict(orient="records")}),
    )


@router.get("/connections", response_model=list[SqlConnectionSummary])
def list_connections() -> list[SqlConnectionSummary]:
    dataset = overview_store.latest()
    external = _configured_external_sources()
    configured = {target.connection.source_type for target in external}
    return ([] if dataset is None else [_local_connection(dataset)]) + [target.connection for target in _configured_sqlite_sources()] + [target.connection for target in external] + _unavailable_connections(configured)


@router.get("/connections/{connection_id}/schema", response_model=SqlSchemaResponse)
def get_schema(connection_id: str) -> SqlSchemaResponse:
    return _schema(_connection(connection_id))


@router.post("/runs", response_model=SqlRunResponse, status_code=status.HTTP_201_CREATED)
def execute_query(request: SqlRunRequest) -> SqlRunResponse:
    request_fingerprint = _fingerprint(request.model_dump(exclude={"client_request_id"}))
    if request.client_request_id is not None:
        existing = store.idempotent_run(request.client_request_id, request_fingerprint)
        if existing is not None:
            return existing
    target = _connection(request.connection_id)
    connection = target.connection
    schema = _schema(target)
    classification = classify_query(request.sql)
    risk = QueryRisk.SAFE_READ if classification.is_read_only else QueryRisk.GOVERNED_WRITE if classification.kind == "mutating" else QueryRisk.UNKNOWN
    run_id = f"run_{uuid.uuid4().hex}"
    if not classification.is_read_only:
        response = SqlRunResponse(
            run_id=run_id, state=QueryExecutionState.FAILED, risk=risk, sql=request.sql,
            warnings=["Write/DDL and unproven SQL are blocked until the governed-write phase is implemented."],
            error=classification.reason, provenance=_provenance(connection, schema, request),
        )
        store.put_run(
            StoredRun(response=response, frame=pd.DataFrame()),
            request.client_request_id,
            request_fingerprint,
        )
        return response
    response = SqlRunResponse(
        run_id=run_id, state=QueryExecutionState.QUEUED, risk=risk, sql=request.sql,
        provenance=_provenance(connection, schema, request),
    )
    store.put_run(
        StoredRun(response=response, frame=pd.DataFrame()),
        request.client_request_id,
        request_fingerprint,
    )

    def work(job: QueryJob) -> None:
        store.update_run(run_id, response.model_copy(update={"state": QueryExecutionState.RUNNING}))
        if target.dataset is not None:
            result, error, duration_ms = execute_local_query(
                target.dataset.frame, request.sql, request.parameters, request.timeout_ms, job.attach_interrupt,
                max_result_rows=request.result_limit + 1,
            )
        elif target.sqlite_path is not None:
            result, error, duration_ms = execute_sqlite_query(
                str(target.sqlite_path), request.sql, request.parameters, request.timeout_ms, job.attach_interrupt,
                max_result_rows=request.result_limit + 1,
            )
        elif target.external_source is not None:
            result, error, duration_ms = execute_external_query(
                target.external_source, request.sql, request.parameters,
                max_result_rows=request.result_limit + 1, on_connection=job.attach_interrupt,
            )
        else:
            result, error, duration_ms = None, "The SQL connector is unavailable.", 0
        if job.timed_out.is_set():
            completed = response.model_copy(update={"state": QueryExecutionState.TIMED_OUT, "duration_ms": duration_ms, "error": "Query exceeded its configured timeout."})
        elif job.cancelled.is_set():
            completed = response.model_copy(update={"state": QueryExecutionState.CANCELLED, "duration_ms": duration_ms, "error": "Query cancelled by user."})
        elif error is not None or result is None:
            completed = response.model_copy(update={"state": QueryExecutionState.FAILED, "duration_ms": duration_ms, "error": error or "SQL execution did not return a result."})
        else:
            truncated = len(result) > request.result_limit
            kept = result.iloc[:request.result_limit].copy()
            completed = response.model_copy(update={
                "state": QueryExecutionState.SUCCEEDED,
                "result_columns": [SqlResultColumn(name=str(name), data_type=str(dtype)) for name, dtype in kept.dtypes.items()],
                "row_count": len(result), "returned_row_count": len(kept), "truncated": truncated, "duration_ms": duration_ms,
                "warnings": [f"Result capped at {request.result_limit:,} rows."] if truncated else [],
                "provenance": _provenance(connection, schema, request, kept),
            })
            store.update_run(run_id, completed, kept)
            return
        store.update_run(run_id, completed)

    runtime.start(run_id, request.timeout_ms, work)
    return response


@router.get("/runs/{run_id}", response_model=SqlRunResponse)
def get_run(run_id: str) -> SqlRunResponse:
    return store.get_run(run_id).response


@router.post("/runs/{run_id}/cancel", response_model=SqlRunResponse)
def cancel_run(run_id: str) -> SqlRunResponse:
    run = store.get_run(run_id).response
    if run.state in {QueryExecutionState.SUCCEEDED, QueryExecutionState.FAILED, QueryExecutionState.CANCELLED, QueryExecutionState.TIMED_OUT}:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This SQL run already reached a terminal state.")
    if not runtime.cancel(run_id):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This SQL run already reached a terminal state.")
    cancelled = run.model_copy(update={"state": QueryExecutionState.CANCELLED, "error": "Cancellation requested."})
    store.update_run(run_id, cancelled)
    return cancelled


@router.get("/runs/{run_id}/events")
async def run_events(run_id: str):  # type: ignore[no-untyped-def]
    async def events() -> AsyncIterator[str]:
        previous_state: QueryExecutionState | None = None
        for _ in range(1_200):
            run = store.get_run(run_id).response
            if run.state is not previous_state:
                yield ServerSentEvent(event="sql.run", id=run.run_id, data={"run_id": run.run_id, "state": run.state.value}).encode()
                previous_state = run.state
            if run.state in {QueryExecutionState.SUCCEEDED, QueryExecutionState.FAILED, QueryExecutionState.CANCELLED, QueryExecutionState.TIMED_OUT}:
                return
            await asyncio.sleep(0.1)

    return sse_response(events())


@router.get("/runs/{run_id}/results", response_model=SqlResultPageResponse)
def get_results(run_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=RESULT_PAGE_LIMIT)) -> SqlResultPageResponse:
    run = store.get_run(run_id)
    if run.response.state is not QueryExecutionState.SUCCEEDED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Results are available only for successful query runs.")
    if not run.materialized:
        raise HTTPException(status_code=status.HTTP_410_GONE, detail="Result materialization expired; rerun this query from its durable provenance record.")
    page = run.frame.iloc[offset : offset + limit]
    return SqlResultPageResponse(run=run.response, offset=offset, limit=limit, rows=[{str(key): _json_value(value) for key, value in row.items()} for row in page.to_dict(orient="records")])


@router.get("/runs/{run_id}/export")
def export_results(run_id: str, format: str = Query("csv", pattern="^(csv|json)$")) -> Response:
    run = store.get_run(run_id)
    if run.response.state is not QueryExecutionState.SUCCEEDED or not run.materialized:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only materialized successful results can be exported.")
    if format == "json":
        return Response(
            content=run.frame.to_json(orient="records", date_format="iso"),
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{run_id}.json"'},
        )
    return Response(
        content=run.frame.to_csv(index=False),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{run_id}.csv"'},
    )


@router.post("/runs/{run_id}/promote", response_model=SqlResultPromotionResponse, status_code=status.HTTP_201_CREATED)
def promote_result(run_id: str) -> SqlResultPromotionResponse:
    stored = store.get_run(run_id)
    if stored.response.state is not QueryExecutionState.SUCCEEDED or not stored.materialized or stored.frame.empty:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only materialized successful results can become datasets.")
    fingerprint = stored.response.provenance.result_fingerprint or _fingerprint(stored.frame.to_dict(orient="records"))
    dataset = overview_store.put(stored.frame.copy(), f"SQL result {run_id}", fingerprint)
    downstream = [*stored.response.provenance.downstream_objects, f"dataset:{dataset.dataset_id}"]
    provenance = stored.response.provenance.model_copy(update={"downstream_objects": list(dict.fromkeys(downstream))})
    updated = stored.response.model_copy(update={"provenance": provenance})
    store.update_run(run_id, updated)
    return SqlResultPromotionResponse(run=updated, dataset=dataset)


@router.post("/plans", response_model=SqlPlanResponse)
def inspect_plan(request: SqlRunRequest) -> SqlPlanResponse:
    target = _connection(request.connection_id)
    connection = target.connection
    if not classify_query(request.sql).is_read_only:
        return SqlPlanResponse(connection_id=connection.connection_id, supported=False, warning="Plans are limited to proven read queries.")
    if target.dataset is not None:
        plan, error, _duration = execute_local_query(target.dataset.frame, f"EXPLAIN {request.sql}", request.parameters, request.timeout_ms)
    elif target.sqlite_path is not None:
        plan, error, _duration = execute_sqlite_query(str(target.sqlite_path), f"EXPLAIN QUERY PLAN {request.sql}", request.parameters, request.timeout_ms)
    elif target.external_source is not None:
        plan_lines, error = external_plan(target.external_source, request.sql, request.parameters)
        return SqlPlanResponse(
            connection_id=connection.connection_id,
            supported=error is None,
            plan=plan_lines if error is None else [],
            warning=error,
        )
    else:
        plan, error, _duration = None, "The SQL connector is unavailable.", 0
    if error is not None or plan is None:
        return SqlPlanResponse(connection_id=connection.connection_id, supported=False, warning=error or "Plan is unavailable for this query.")
    return SqlPlanResponse(connection_id=connection.connection_id, supported=True, plan=[" | ".join(map(str, row)) for row in plan.itertuples(index=False, name=None)])


@router.get("/history", response_model=list[SqlRunResponse])
def query_history() -> list[SqlRunResponse]:
    return store.history()


@router.get("/snippets", response_model=list[SqlSnippet])
def list_snippets() -> list[SqlSnippet]:
    return store.snippets()


@router.post("/snippets", response_model=SqlSnippet, status_code=status.HTTP_201_CREATED)
def create_snippet(snippet: SqlSnippetCreate) -> SqlSnippet:
    return store.save_snippet(snippet.name, snippet.sql, snippet.dialect, _safe_parameters(snippet.parameters))


@router.post("/atlas", response_model=AtlasSqlResponse)
def atlas_sql_action(request: AtlasSqlRequest) -> AtlasSqlResponse:
    target = _connection(request.connection_id)
    connection = target.connection
    schema = _schema(target)
    table = schema.tables[0]
    evidence = [AtlasEvidence(label="Dialect", value=connection.dialect.value), AtlasEvidence(label="Table", value=f"{table.name} ({len(table.columns)} columns)")]
    uncertainty = "This is a deterministic, schema-grounded draft. Inspect it before execution; no schema object is inferred beyond the metadata shown."
    sql = request.sql or ""
    if request.action is AtlasSqlAction.GENERATE_SQL:
        draft = _bounded_select(table.name, connection.dialect)
        summary = f"Drafted a bounded query against the verified `{table.name}` table."
    elif request.action is AtlasSqlAction.EXPLAIN_QUERY:
        classification = classify_query(sql)
        draft = None
        summary = f"The selected SQL is classified as {classification.kind} for the {connection.dialect.value} dialect. {classification.reason}"
    elif request.action is AtlasSqlAction.INSPECT_PLAN:
        draft, summary = None, "Use Inspect plan to request the connector-supported EXPLAIN output."
    elif request.action is AtlasSqlAction.DEBUG_ERROR:
        draft, summary = sql or None, "The SQL remains editable. Check the selected dialect, table name, and column metadata before retrying."
    elif request.action is AtlasSqlAction.TRACE_LINEAGE:
        draft, summary = None, f"This query is tied to source fingerprint {connection.source_fingerprint[:12] if connection.source_fingerprint else 'unavailable'}… and schema fingerprint {schema.schema_fingerprint[:12]}…."
    elif request.action is AtlasSqlAction.CONVERT_RESULT:
        draft, summary = None, "Use Create dataset on a successful materialized result. PRISM records the new dataset in the run provenance and never creates it automatically."
    elif request.action is AtlasSqlAction.EXPLAIN_SELECTION:
        draft, summary = None, f"Selected region: {(request.selected_text or 'none')[:160]}. It is interpreted only as SQL text, not executed."
    elif request.action is AtlasSqlAction.COMPARE_QUERIES:
        comparison = request.comparison_sql or ""
        draft, summary = None, f"The queries are {'identical' if sql.strip() == comparison.strip() and comparison else 'different'} as text. PRISM has not executed either query as part of this comparison."
    elif request.action is AtlasSqlAction.OPTIMIZE_QUERY:
        draft, summary = sql or None, "Keep a restrictive projection and LIMIT while iterating; inspect the plan before claiming a performance improvement."
    else:
        draft, summary = None, "The query can be inspected by dialect and source metadata; execution remains user-initiated."
    return AtlasSqlResponse(action=request.action, summary=summary, draft_sql=draft, evidence=evidence, uncertainty=uncertainty, executable=False)
