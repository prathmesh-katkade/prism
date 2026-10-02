"""SQL Lab join diagnostics: key cardinality, unmatched keys, and row-multiplication
risk for a query's joins.

Uses sqlglot to parse the query's real structure (table aliases, ON conditions) —
never unsafe string splitting. Scoped deliberately to simple, enumerable equi-joins
(``a.col = b.col``); any join this can't confidently characterize is named in
``unsupported_notes`` instead of guessing at an analysis for it.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import sqlglot
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    JoinDiagnostic,
    JoinDiagnosticsRequest,
    JoinDiagnosticsResponse,
    JoinKeyCardinality,
    SqlDialect,
)
from prism_sql_lab_runtime import (
    classify_query,
    execute_external_query,
    execute_local_query,
    execute_sqlite_query,
)
from sqlglot import expressions as exp

from .sql_lab import ConnectionTarget, _connection, _fingerprint

router = APIRouter(prefix="/api/v1/sql-lab", tags=["sql-lab-join-diagnostics"])

_SQLGLOT_DIALECT = {
    SqlDialect.DUCKDB: "duckdb", SqlDialect.MYSQL: "mysql", SqlDialect.POSTGRESQL: "postgres",
    SqlDialect.SQLSERVER: "tsql", SqlDialect.SQLITE: "sqlite",
}
DIAGNOSTIC_TIMEOUT_MS = 10_000


@dataclass(frozen=True)
class _DetectedJoin:
    join_index: int
    join_kind: str
    left_table: str
    left_column: str
    right_table: str
    right_column: str


def _detect_equi_joins(sql: str, dialect_name: str) -> tuple[list[_DetectedJoin], list[str]]:
    try:
        tree = sqlglot.parse_one(sql, read=dialect_name)
    except Exception as error:
        return [], [f"The query could not be parsed for join analysis: {error}"]

    alias_to_table: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        alias_to_table[table.alias_or_name] = table.name

    joins: list[_DetectedJoin] = []
    notes: list[str] = []
    for index, join in enumerate(tree.find_all(exp.Join)):
        on = join.args.get("on")
        kind = (join.kind or "inner").lower() or "inner"
        if not (isinstance(on, exp.EQ) and isinstance(on.left, exp.Column) and isinstance(on.right, exp.Column)):
            notes.append(f"Join {index + 1}: only a single equality condition (table.column = table.column) is supported for diagnostics; this join's condition isn't in that form.")
            continue
        left_alias, right_alias = on.left.table, on.right.table
        if not left_alias or not right_alias:
            notes.append(f"Join {index + 1}: both sides of the join condition must reference a table alias or name explicitly.")
            continue
        joins.append(_DetectedJoin(
            join_index=index, join_kind=kind,
            left_table=alias_to_table.get(left_alias, left_alias), left_column=on.left.name,
            right_table=alias_to_table.get(right_alias, right_alias), right_column=on.right.name,
        ))
    if not joins and not notes:
        notes.append("No JOIN clause was found in this query.")
    return joins, notes


def _run_diagnostic_sql(target: ConnectionTarget, sql: str) -> tuple[pd.DataFrame | None, str | None]:
    if target.dataset is not None:
        result, error, _duration = execute_local_query(
            target.dataset.frame, sql, {}, DIAGNOSTIC_TIMEOUT_MS,
            additional_frames={"joined": target.secondary_dataset.frame} if target.secondary_dataset is not None else None,
        )
        return result, error
    if target.sqlite_path is not None:
        result, error, _duration = execute_sqlite_query(str(target.sqlite_path), sql, {}, DIAGNOSTIC_TIMEOUT_MS)
        return result, error
    if target.external_source is not None:
        result, error, _duration = execute_external_query(target.external_source, sql, {})
        return result, error
    return None, "The SQL connector is unavailable."


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _cardinality(target: ConnectionTarget, table: str, column: str) -> JoinKeyCardinality:
    sql = (
        f"SELECT COUNT(*) AS total_rows, COUNT(DISTINCT {_quote(column)}) AS distinct_keys, "
        f"SUM(CASE WHEN {_quote(column)} IS NULL THEN 1 ELSE 0 END) AS null_keys FROM {_quote(table)}"
    )
    result, error = _run_diagnostic_sql(target, sql)
    if error is not None or result is None or result.empty:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Could not compute key cardinality for {table}.{column}: {error or 'no result returned'}.")
    row = result.iloc[0]
    total_rows, distinct_keys, null_keys = int(row["total_rows"]), int(row["distinct_keys"]), int(row["null_keys"] or 0)
    return JoinKeyCardinality(
        table=table, column=column, total_rows=total_rows, distinct_keys=distinct_keys, null_keys=null_keys,
        duplicate_key_rows=max(0, total_rows - null_keys - distinct_keys),
    )


def _unmatched_count(target: ConnectionTarget, from_table: str, from_column: str, against_table: str, against_column: str) -> int:
    sql = (
        f"SELECT COUNT(*) AS unmatched FROM {_quote(from_table)} WHERE {_quote(from_column)} IS NOT NULL "
        f"AND {_quote(from_column)} NOT IN (SELECT {_quote(against_column)} FROM {_quote(against_table)} WHERE {_quote(against_column)} IS NOT NULL)"
    )
    result, error = _run_diagnostic_sql(target, sql)
    if error is not None or result is None or result.empty:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Could not compute unmatched keys between {from_table}.{from_column} and {against_table}.{against_column}: {error or 'no result returned'}.")
    return int(result.iloc[0]["unmatched"])


@router.post("/joins/diagnose", response_model=JoinDiagnosticsResponse)
def diagnose_joins(request: JoinDiagnosticsRequest) -> JoinDiagnosticsResponse:
    classification = classify_query(request.sql)
    if not classification.is_read_only:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Join diagnostics require a read-only query. {classification.reason}")
    target = _connection(request.connection_id)
    dialect_name = _SQLGLOT_DIALECT.get(target.connection.dialect, "")
    detected, notes = _detect_equi_joins(request.sql, dialect_name)

    diagnostics: list[JoinDiagnostic] = []
    for join in detected:
        left = _cardinality(target, join.left_table, join.left_column)
        right = _cardinality(target, join.right_table, join.right_column)
        unmatched_left = _unmatched_count(target, join.left_table, join.left_column, join.right_table, join.right_column)
        unmatched_right = _unmatched_count(target, join.right_table, join.right_column, join.left_table, join.left_column)
        diagnostics.append(JoinDiagnostic(
            join_index=join.join_index, join_kind=join.join_kind, left=left, right=right,
            unmatched_left_rows=unmatched_left, unmatched_right_rows=unmatched_right,
            row_multiplication_risk=left.duplicate_key_rows > 0 and right.duplicate_key_rows > 0,
        ))

    return JoinDiagnosticsResponse(
        connection_id=request.connection_id, sql_fingerprint=_fingerprint({"sql": request.sql}),
        joins=diagnostics, unsupported_notes=notes,
    )
