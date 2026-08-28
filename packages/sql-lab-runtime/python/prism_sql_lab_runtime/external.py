"""Server-side external SQL connector boundary.

Credentials enter only through environment-backed secret references. Public API models receive
labels, capabilities, and fingerprints—not connection URLs or secret-reference names.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Callable, Mapping, Optional

import pandas as pd
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import Connection, Engine

_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SAFE_ENV = re.compile(r"^[A-Z][A-Z0-9_]{2,127}$")
_SUPPORTED_DIALECTS = {"mysql", "postgresql", "sqlserver"}


@dataclass(frozen=True)
class ExternalSource:
    source_id: str
    label: str
    dialect: str
    connection_url: Optional[str]
    availability_reason: Optional[str] = None


class ExternalConnectorError(RuntimeError):
    """Sanitized connector failure safe to surface through an API error contract."""


def load_external_sources(raw_json: str, environment: Mapping[str, str]) -> list[ExternalSource]:
    """Resolve a public registry through server-only environment secret references."""
    try:
        entries = json.loads(raw_json or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(entries, list):
        return []
    sources: list[ExternalSource] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        source_id, label = entry.get("id"), entry.get("label")
        dialect, url_env = entry.get("source_type"), entry.get("url_env")
        if not isinstance(source_id, str) or not _SAFE_ID.fullmatch(source_id):
            continue
        if not isinstance(label, str) or not label.strip():
            continue
        if dialect not in _SUPPORTED_DIALECTS:
            continue
        if not isinstance(url_env, str) or not _SAFE_ENV.fullmatch(url_env):
            sources.append(ExternalSource(source_id, label.strip(), dialect, None, "The server secret reference is invalid."))
            continue
        connection_url = environment.get(url_env)
        reason = None if connection_url else "The server credential secret is not configured."
        sources.append(ExternalSource(source_id, label.strip(), dialect, connection_url, reason))
    return sources


def _engine(connection_url: str) -> Engine:
    try:
        return create_engine(connection_url, pool_pre_ping=True, pool_recycle=280)
    except Exception as error:
        raise ExternalConnectorError(scrub_connector_error(str(error))) from error


def scrub_connector_error(message: str) -> str:
    message = re.sub(r"(password[=:]\s*)\S+", r"\1********", message, flags=re.IGNORECASE)
    message = re.sub(r"(://[^:]+:)[^@]+(@)", r"\1********\2", message)
    return message[:1_000]


def external_schema(source: ExternalSource) -> list[dict[str, object]]:
    if source.connection_url is None:
        raise ExternalConnectorError(source.availability_reason or "The connector is unavailable.")
    engine = _engine(source.connection_url)
    try:
        inspector = inspect(engine)
        if inspector is None:
            raise ExternalConnectorError("SQLAlchemy inspection is unavailable.")
        tables: list[dict[str, object]] = []
        for table_name in sorted(inspector.get_table_names())[:250]:
            columns = inspector.get_columns(table_name)
            tables.append({
                "name": str(table_name),
                "columns": [
                    {
                        "name": str(column.get("name", "")),
                        "data_type": str(column.get("type", "unknown")),
                        "nullable": bool(column.get("nullable", True)),
                        "sample_count": 0,
                    }
                    for column in columns
                ],
            })
        return tables
    except ExternalConnectorError:
        raise
    except Exception as error:
        raise ExternalConnectorError(scrub_connector_error(str(error))) from error
    finally:
        engine.dispose()


def external_driver_error(source: ExternalSource) -> Optional[str]:
    """Validate URL shape and driver availability without opening a network connection."""
    if source.connection_url is None:
        return source.availability_reason or "The connector is unavailable."
    try:
        engine = _engine(source.connection_url)
        engine.dispose()
        return None
    except ExternalConnectorError as error:
        return str(error)


def _normalize_decimal_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """DB-API drivers (pymysql included) return SQL DECIMAL/NUMERIC as ``decimal.Decimal``,
    which pandas leaves as an opaque ``object`` column instead of a numeric dtype. Every other
    numeric path in PRISM (Overview's quality/health scoring, Visualize's aggregation) expects a
    real numeric dtype, and DuckDB's own DECIMAL -> pandas conversion already produces ``float64``
    — so normalize here rather than let each caller re-discover this per column.
    """
    for column in frame.columns:
        series = frame[column]
        if series.dtype != object:
            continue
        non_null = series[series.notna()]
        if not non_null.empty and non_null.map(lambda value: isinstance(value, Decimal)).all():
            frame[column] = series.astype(float)
    return frame


def _bounded_sql(sql: str, dialect: str, maximum_rows: int) -> str:
    statement = sql.rstrip().rstrip(";")
    if dialect == "sqlserver":
        return f"SELECT TOP ({maximum_rows}) * FROM ({statement}) AS prism_result"
    return f"SELECT * FROM ({statement}) AS prism_result LIMIT {maximum_rows}"


def execute_external_query(
    source: ExternalSource,
    sql: str,
    parameters: Optional[dict[str, object]] = None,
    max_result_rows: int = 1_001,
    on_connection: Optional[Callable[[Callable[[], None]], bool]] = None,
) -> tuple[Optional[pd.DataFrame], Optional[str], int]:
    started = time.perf_counter()
    if source.connection_url is None:
        return None, source.availability_reason or "The connector is unavailable.", 0
    engine = _engine(source.connection_url)
    connection: Optional[Connection] = None
    try:
        connection = engine.connect()
        if on_connection is not None:
            interrupt = _external_interrupt(source, connection)
            if on_connection(interrupt):
                return None, "Query cancelled before execution.", int((time.perf_counter() - started) * 1_000)
        result = connection.execute(text(_bounded_sql(sql, source.dialect, max_result_rows)), parameters or {})
        rows = result.fetchmany(max_result_rows) if result.returns_rows else []
        frame = pd.DataFrame(rows, columns=list(result.keys()) if result.returns_rows else [])
        frame = _normalize_decimal_columns(frame)
        return frame, None, int((time.perf_counter() - started) * 1_000)
    except Exception as error:
        return None, scrub_connector_error(str(error)), int((time.perf_counter() - started) * 1_000)
    finally:
        if connection is not None:
            connection.close()
        engine.dispose()


def _external_interrupt(source: ExternalSource, connection: Connection) -> Callable[[], None]:
    if source.dialect == "mysql":
        connection_id = int(connection.exec_driver_sql("SELECT CONNECTION_ID()").scalar_one())

        def cancel_mysql() -> None:
            assert source.connection_url is not None
            interrupter = _engine(source.connection_url)
            try:
                with interrupter.connect() as control:
                    control.exec_driver_sql(f"KILL QUERY {connection_id}")
            finally:
                interrupter.dispose()

        return cancel_mysql
    if source.dialect == "postgresql":
        process_id = int(connection.exec_driver_sql("SELECT pg_backend_pid()").scalar_one())

        def cancel_postgresql() -> None:
            assert source.connection_url is not None
            interrupter = _engine(source.connection_url)
            try:
                with interrupter.connect() as control:
                    control.execute(text("SELECT pg_cancel_backend(:process_id)"), {"process_id": process_id})
            finally:
                interrupter.dispose()

        return cancel_postgresql
    return connection.invalidate


def external_plan(source: ExternalSource, sql: str, parameters: Optional[dict[str, object]] = None) -> tuple[list[str], Optional[str]]:
    if source.dialect == "sqlserver":
        return [], "SQL Server plan inspection requires a connector-specific SHOWPLAN permission and is unavailable in this slice."
    if source.connection_url is None:
        return [], source.availability_reason or "The connector is unavailable."
    engine = _engine(source.connection_url)
    try:
        with engine.connect() as connection:
            result = connection.execute(text(f"EXPLAIN {sql.rstrip().rstrip(';')}"), parameters or {})
            return [" | ".join(str(value) for value in row) for row in result], None
    except Exception as error:
        return [], scrub_connector_error(str(error))
    finally:
        engine.dispose()
