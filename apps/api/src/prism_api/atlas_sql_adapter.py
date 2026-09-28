"""Typed Atlas aggregate adapter into the existing SQL Lab execution boundary."""

from __future__ import annotations

import time
from typing import Any, Callable

import pandas as pd
from fastapi import HTTPException
from prism_api_contracts import AtlasSqlAnalysis, QueryExecutionState, SqlRunRequest

from . import sql_lab
from .overview import store as dataset_store

POLICY_VERSION = "atlas-local-aggregate-v1"
TERMINAL = {
    QueryExecutionState.SUCCEEDED,
    QueryExecutionState.FAILED,
    QueryExecutionState.CANCELLED,
    QueryExecutionState.TIMED_OUT,
}


def compile_query(dataset_id: str, analysis: AtlasSqlAnalysis) -> SqlRunRequest:
    """Resolve every identifier against the server-held revision and bind values."""
    dataset = dataset_store.get(dataset_id)
    columns = {str(name): name for name in dataset.frame.columns}

    def identifier(name: str) -> str:
        if name not in columns or name != str(columns[name]):
            raise ValueError(f"Column {name!r} is not in the active dataset schema.")
        return '"' + name.replace('"', '""') + '"'

    if analysis.aggregate != "count" and analysis.measure is None:
        raise ValueError("Choose a measure column for this aggregate.")
    if analysis.aggregate == "count" and analysis.measure is not None:
        raise ValueError("Count rows does not take a measure column.")
    if (analysis.filter_column is None) != (analysis.filter_value is None):
        raise ValueError("Provide both a filter column and a filter value.")
    if isinstance(analysis.filter_value, str) and len(analysis.filter_value) > 256:
        raise ValueError("Filter values are limited to 256 characters.")
    if analysis.measure is not None:
        measure = identifier(analysis.measure)
        if not pd.api.types.is_numeric_dtype(dataset.frame[analysis.measure]):
            raise ValueError("This aggregate requires a numeric measure column.")
        expression = f"{analysis.aggregate.upper()}({measure})"
    else:
        expression = "COUNT(*)"
    group = identifier(analysis.group_by) if analysis.group_by is not None else None
    if analysis.group_by is not None and dataset.frame[analysis.group_by].astype(str).str.len().max() > 256:
        raise ValueError("Group values are limited to 256 characters.")
    selected = f"{group} AS group_value, " if group else ""
    sql = f'SELECT {selected}{expression} AS result_value FROM "data"'
    parameters: dict[str, Any] = {}
    if analysis.filter_column is not None:
        sql += f" WHERE {identifier(analysis.filter_column)} = $filter_value"
        parameters["filter_value"] = analysis.filter_value
    if group:
        sql += f" GROUP BY {group} ORDER BY {group}"
    sql += " LIMIT 100"
    return SqlRunRequest(
        connection_id=f"local:{dataset_id}", sql=sql, parameters=parameters,
        timeout_ms=10_000, result_limit=100,
    )


def execute_aggregate(run_id: str, step_id: str, dataset_id: str, analysis: AtlasSqlAnalysis,
                      cancelled: Callable[[], bool]) -> dict[str, object]:
    """Submit once, propagate cancellation, and return bounded durable evidence data."""
    before = dataset_store.get(dataset_id).dataset
    query = compile_query(dataset_id, analysis).model_copy(update={
        "client_request_id": f"atlas:{run_id}:{step_id}",
    })
    submitted = sql_lab.execute_query(query)
    deadline = time.monotonic() + 12
    while submitted.state not in TERMINAL:
        if cancelled():
            try:
                sql_lab.cancel_run(submitted.run_id)
            except HTTPException as error:
                if error.status_code != 409:
                    raise
        if time.monotonic() >= deadline:
            try:
                sql_lab.cancel_run(submitted.run_id)
            except HTTPException:
                pass
            submitted = sql_lab.get_run(submitted.run_id)
            break
        time.sleep(0.025)
        submitted = sql_lab.get_run(submitted.run_id)
    after = dataset_store.get(dataset_id).dataset
    if before.revision != after.revision or before.source_fingerprint != after.source_fingerprint:
        raise ValueError("Dataset revision changed during SQL execution; result is stale.")
    if submitted.provenance.source_fingerprint != before.source_fingerprint:
        raise ValueError("SQL source fingerprint changed during execution; result is stale.")
    result = sql_lab.get_results(submitted.run_id, offset=0, limit=100) if submitted.state is QueryExecutionState.SUCCEEDED else None
    return {
        "sql_run_id": submitted.run_id,
        "policy_version": POLICY_VERSION,
        "dataset_id": dataset_id,
        "dataset_revision": before.revision,
        "source_fingerprint": before.source_fingerprint,
        "connection_id": query.connection_id,
        "sql": query.sql,
        "parameters": query.parameters,
        "execution_state": submitted.state.value if submitted.state in TERMINAL else "timed_out",
        "error": submitted.error if submitted.state in TERMINAL else "Atlas SQL polling exceeded its 12 second bound.",
        "duration_ms": submitted.duration_ms,
        "result_fingerprint": submitted.provenance.result_fingerprint,
        "rows": result.rows if result is not None else [],
        "truncated": submitted.truncated,
    }
