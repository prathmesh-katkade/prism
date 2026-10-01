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
    join_parts = (analysis.join_dataset_id, analysis.join_left_key, analysis.join_right_key, analysis.join_cardinality)
    if any(part is not None for part in join_parts) and not all(part is not None for part in join_parts):
        raise ValueError("Join source, both keys, and cardinality must be declared together.")
    if analysis.group_source == "joined" and analysis.join_dataset_id is None:
        raise ValueError("Grouping from the joined source requires a declared join.")
    right = None
    right_columns: dict[str, object] = {}
    if analysis.join_dataset_id is not None:
        if analysis.join_dataset_id == dataset_id:
            raise ValueError("Choose a distinct registered source for the join.")
        right = dataset_store.get(analysis.join_dataset_id)
        right_columns = {str(name): name for name in right.frame.columns}
        assert analysis.join_left_key is not None and analysis.join_right_key is not None
        if analysis.join_left_key not in columns or analysis.join_right_key not in right_columns:
            raise ValueError("Both join keys must exist in their registered source schemas.")
        if dataset.frame[analysis.join_left_key].dtype != right.frame[analysis.join_right_key].dtype:
            raise ValueError("Join keys must have the same registered data type.")
        if right.frame[analysis.join_right_key].dropna().duplicated().any():
            raise ValueError("The joined key is not unique; a join would multiply left-side measures.")
        if analysis.join_cardinality == "one_to_one" and dataset.frame[analysis.join_left_key].dropna().duplicated().any():
            raise ValueError("One-to-one was declared but the left key repeats.")

    def identifier(name: str, *, source: str = "data") -> str:
        source_columns = columns if source == "data" else right_columns
        if name not in source_columns or name != str(source_columns[name]):
            raise ValueError(f"Column {name!r} is not in the active dataset schema.")
        quoted = '"' + name.replace('"', '""') + '"'
        return f'"{source}".{quoted}' if right is not None else quoted

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
    group = identifier(analysis.group_by, source=analysis.group_source) if analysis.group_by is not None else None
    group_frame = dataset.frame if analysis.group_source == "data" else right.frame if right is not None else dataset.frame
    if analysis.group_by is not None and group_frame[analysis.group_by].astype(str).str.len().max() > 256:
        raise ValueError("Group values are limited to 256 characters.")
    selected = f"{group} AS group_value, " if group else ""
    sql = f'SELECT {selected}{expression} AS result_value FROM "data"'
    if right is not None:
        assert analysis.join_left_key is not None and analysis.join_right_key is not None
        sql += f' INNER JOIN "joined" ON {identifier(analysis.join_left_key)} = {identifier(analysis.join_right_key, source="joined")}'
    parameters: dict[str, Any] = {}
    if analysis.filter_column is not None:
        sql += f" WHERE {identifier(analysis.filter_column)} = $filter_value"
        parameters["filter_value"] = analysis.filter_value
    if group:
        sql += f" GROUP BY {group} ORDER BY {group}"
    sql += " LIMIT 100"
    return SqlRunRequest(
        connection_id=f"localjoin:{dataset_id}:{analysis.join_dataset_id}" if right is not None else f"local:{dataset_id}",
        sql=sql, parameters=parameters,
        timeout_ms=10_000, result_limit=100,
    )


def execute_aggregate(run_id: str, step_id: str, dataset_id: str, analysis: AtlasSqlAnalysis,
                      cancelled: Callable[[], bool]) -> dict[str, object]:
    """Submit once, propagate cancellation, and return bounded durable evidence data."""
    left_stored = dataset_store.get(dataset_id)
    before = left_stored.dataset
    right_stored = dataset_store.get(analysis.join_dataset_id) if analysis.join_dataset_id is not None else None
    joined_before = right_stored.dataset if right_stored is not None else None
    query = compile_query(dataset_id, analysis).model_copy(update={
        "client_request_id": f"atlas:{run_id}:{step_id}",
    })
    join_input_rows = len(left_stored.frame) if right_stored is not None else None
    join_matched_rows = None
    if right_stored is not None:
        assert analysis.join_left_key is not None and analysis.join_right_key is not None
        left_key = left_stored.frame[analysis.join_left_key]
        right_key = right_stored.frame[analysis.join_right_key]
        join_matched_rows = int((left_key.notna() & left_key.isin(right_key.dropna())).sum())
    registered_fingerprint = sql_lab._connection(query.connection_id).connection.source_fingerprint
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
    joined_after = dataset_store.get(analysis.join_dataset_id).dataset if analysis.join_dataset_id is not None else None
    if joined_before is not None and joined_after is not None and (
        joined_before.revision != joined_after.revision or joined_before.source_fingerprint != joined_after.source_fingerprint
    ):
        raise ValueError("Joined dataset revision changed during SQL execution; result is stale.")
    if submitted.provenance.source_fingerprint != registered_fingerprint or (
        analysis.join_dataset_id is not None
        and sql_lab._connection(query.connection_id).connection.source_fingerprint != registered_fingerprint
    ):
        raise ValueError("SQL source fingerprint changed during execution; result is stale.")
    result = sql_lab.get_results(submitted.run_id, offset=0, limit=100) if submitted.state is QueryExecutionState.SUCCEEDED else None
    return {
        "sql_run_id": submitted.run_id,
        "policy_version": POLICY_VERSION,
        "dataset_id": dataset_id,
        "dataset_revision": before.revision,
        "source_fingerprint": before.source_fingerprint,
        "joined_dataset_id": joined_before.dataset_id if joined_before is not None else None,
        "joined_dataset_revision": joined_before.revision if joined_before is not None else None,
        "joined_source_fingerprint": joined_before.source_fingerprint if joined_before is not None else None,
        "join_cardinality": analysis.join_cardinality,
        "join_input_rows": join_input_rows,
        "join_matched_rows": join_matched_rows,
        "join_excluded_rows": join_input_rows - join_matched_rows if join_input_rows is not None and join_matched_rows is not None else None,
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
