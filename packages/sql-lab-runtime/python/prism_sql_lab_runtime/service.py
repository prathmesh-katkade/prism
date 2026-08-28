"""Pure SQL Lab helpers. No HTTP, credentials, or process state."""

from __future__ import annotations

import re
import sqlite3
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import pandas as pd

try:
    import duckdb as _duckdb
    duckdb: Any = _duckdb
except ImportError:  # pragma: no cover - covered by the degraded API capability state
    duckdb = None


SQL_LAB_SERVICE_VERSION = "sql-lab-runtime/1.0"
_LEADING_COMMENT = re.compile(r"^(?:\s|--[^\n]*(?:\n|$)|/\*.*?\*/)*", re.DOTALL)
_READ_KEYWORD = re.compile(r"^(select|with|values|explain|describe|show)\b", re.IGNORECASE)
_MUTATING_KEYWORD = re.compile(
    r"^(insert|update|delete|merge|drop|alter|create|truncate|replace|grant|revoke|"
    r"lock|unlock|call|load\s+data|rename|set)\b",
    re.IGNORECASE,
)
_MUTATING_ANYWHERE = re.compile(
    r"\b(insert|update|delete|merge|drop|alter|create|truncate|replace|grant|revoke|"
    r"lock|unlock|call|rename)\b|\bload\s+data\b|\bset\s+global\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class QueryClassification:
    kind: str
    is_read_only: bool
    reason: str


def classify_query(sql: str) -> QueryClassification:
    """Classify conservatively: unknown SQL is never treated as a safe read."""
    statement = _LEADING_COMMENT.sub("", sql).strip()
    if not statement:
        return QueryClassification("empty", False, "SQL is empty.")
    masked = _mask_literals_and_comments(statement)
    statements = [item for item in masked.split(";") if item.strip()]
    if len(statements) != 1:
        return QueryClassification("unknown", False, "Multiple SQL statements are not permitted in one native run.")
    if _MUTATING_ANYWHERE.search(masked):
        return QueryClassification("mutating", False, "A mutating or DDL keyword was detected outside a quoted literal.")
    if _READ_KEYWORD.match(masked.strip()):
        return QueryClassification("read", True, "Read-only query form detected.")
    if _MUTATING_KEYWORD.match(masked.strip()):
        return QueryClassification("mutating", False, "Mutating or DDL query form detected.")
    return QueryClassification("unknown", False, "SQL could not be proven read-only.")


def _mask_literals_and_comments(sql: str) -> str:
    """Mask quoted values/comments while retaining statement and keyword boundaries."""
    output: list[str] = []
    index = 0
    state = "plain"
    while index < len(sql):
        char = sql[index]
        following = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "plain":
            if char == "'":
                state = "single"
                output.append(" ")
            elif char == '"':
                state = "double"
                output.append(" ")
            elif char == "`":
                state = "backtick"
                output.append(" ")
            elif char == "-" and following == "-":
                state = "line_comment"
                output.extend((" ", " "))
                index += 1
            elif char == "/" and following == "*":
                state = "block_comment"
                output.extend((" ", " "))
                index += 1
            else:
                output.append(char)
        elif state == "line_comment":
            output.append("\n" if char == "\n" else " ")
            if char == "\n":
                state = "plain"
        elif state == "block_comment":
            output.append(" ")
            if char == "*" and following == "/":
                output.append(" ")
                index += 1
                state = "plain"
        else:
            output.append(" ")
            delimiter = {"single": "'", "double": '"', "backtick": "`"}[state]
            if char == delimiter:
                if following == delimiter:
                    output.append(" ")
                    index += 1
                else:
                    state = "plain"
        index += 1
    return "".join(output)


def execute_local_query(
    frame: pd.DataFrame,
    sql: str,
    parameters: dict[str, object] | None = None,
    timeout_ms: int = 30_000,
    on_connection: Optional[Callable[[Any], object]] = None,
    max_result_rows: Optional[int] = None,
) -> tuple[pd.DataFrame | None, str | None, int]:
    """Execute against a short-lived DuckDB connection, preserving legacy table name `data`."""
    started = time.perf_counter()
    classification = classify_query(sql)
    if not classification.is_read_only:
        return None, classification.reason, int((time.perf_counter() - started) * 1000)
    if duckdb is None:
        return None, "DuckDB is unavailable in this PRISM runtime.", int((time.perf_counter() - started) * 1000)
    connection: Any = None
    try:
        connection = duckdb.connect(database=":memory:", config={"enable_external_access": "false"})
        if on_connection is not None:
            if bool(on_connection(connection.interrupt)):
                return None, "Query cancelled before execution.", int((time.perf_counter() - started) * 1000)
        connection.register("data", frame)
        # DuckDB does not expose a portable statement timeout setting. The API records this
        # limitation and applies its timeout policy at the job boundary instead.
        executable_sql = sql
        if max_result_rows is not None:
            executable_sql = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS prism_result LIMIT {max_result_rows}"
        return connection.execute(executable_sql, parameters or {}).df(), None, int((time.perf_counter() - started) * 1000)
    except Exception as error:
        return None, str(error), int((time.perf_counter() - started) * 1000)
    finally:
        if connection is not None:
            connection.close()


def execute_sqlite_query(
    database_path: str,
    sql: str,
    parameters: dict[str, object] | None = None,
    timeout_ms: int = 30_000,
    on_connection: Optional[Callable[[Any], object]] = None,
    max_result_rows: Optional[int] = None,
) -> tuple[pd.DataFrame | None, str | None, int]:
    """Execute a proven read against a server-configured SQLite source."""
    started = time.perf_counter()
    classification = classify_query(sql)
    if not classification.is_read_only:
        return None, classification.reason, int((time.perf_counter() - started) * 1000)
    connection: Optional[sqlite3.Connection] = None
    try:
        connection = sqlite3.connect(database_path)
        if on_connection is not None:
            if bool(on_connection(connection.interrupt)):
                return None, "Query cancelled before execution.", int((time.perf_counter() - started) * 1000)
        executable_sql = sql
        if max_result_rows is not None:
            executable_sql = f"SELECT * FROM ({sql.rstrip().rstrip(';')}) AS prism_result LIMIT {max_result_rows}"
        return pd.read_sql_query(executable_sql, connection, params=parameters or {}), None, int((time.perf_counter() - started) * 1000)
    except Exception as error:
        return None, str(error), int((time.perf_counter() - started) * 1000)
    finally:
        if connection is not None:
            connection.close()


def schema_for_frame(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Return serialisable local-source metadata without exposing data values."""
    return [
        {
            "name": str(name),
            "data_type": str(dtype),
            "nullable": bool(frame[name].isna().any()),
            "sample_count": int(frame[name].notna().sum()),
        }
        for name, dtype in frame.dtypes.items()
    ]
