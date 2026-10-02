"""SQL Lab result comparison: diff two runs' results against explicitly declared
row-matching key columns.

Two result sets have no inherent row identity — pretending otherwise (e.g. comparing
by row position) would silently misreport unrelated rows as "changed." The caller
must declare which columns identify a row, and duplicate keys on either side are
counted and disclosed rather than arbitrarily resolved by picking one occurrence.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    QueryExecutionState,
    ResultComparisonRequest,
    ResultComparisonResponse,
    ResultRowDiff,
)

from .sql_lab import _json_value, store

router = APIRouter(prefix="/api/v1/sql-lab", tags=["sql-lab-comparison"])


def _row_key(frame: pd.DataFrame, columns: list[str]) -> pd.Series:
    # A separator unlikely to appear in ordinary key values; collisions would only
    # under-count duplicates, never fabricate a match that isn't there.
    return frame[columns].astype(str).agg("\x1f".join, axis=1)


def _key_dict(row: "pd.Series[Any]", columns: list[str]) -> dict[str, Any]:
    return {column: _json_value(row[column]) for column in columns}


@router.post("/runs/compare", response_model=ResultComparisonResponse)
def compare_results(request: ResultComparisonRequest) -> ResultComparisonResponse:
    base = store.get_run(request.base_run_id)
    compare = store.get_run(request.compare_run_id)
    if base.response.state != QueryExecutionState.SUCCEEDED or compare.response.state != QueryExecutionState.SUCCEEDED:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Both runs must have succeeded to compare their results.")
    if not base.materialized or not compare.materialized:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or both runs' result data is no longer held in memory (results are intentionally not persisted durably, and the API may have restarted). Re-run the query to compare it.",
        )
    base_frame, compare_frame = base.frame, compare.frame
    missing_base = [c for c in request.key_columns if c not in base_frame.columns]
    missing_compare = [c for c in request.key_columns if c not in compare_frame.columns]
    if missing_base or missing_compare:
        detail = "Key column(s) are not present in both results."
        if missing_base:
            detail += f" Missing from base: {', '.join(missing_base)}."
        if missing_compare:
            detail += f" Missing from compare: {', '.join(missing_compare)}."
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)

    warnings: list[str] = []
    if base.response.truncated:
        warnings.append("The base result was truncated server-side; comparison only covers the rows actually returned.")
    if compare.response.truncated:
        warnings.append("The compare result was truncated server-side; comparison only covers the rows actually returned.")

    key_columns = list(request.key_columns)
    base_keys = _row_key(base_frame, key_columns)
    compare_keys = _row_key(compare_frame, key_columns)
    base_dup_mask = base_keys.duplicated(keep=False)
    compare_dup_mask = compare_keys.duplicated(keep=False)
    duplicate_key_count_base = int(base_dup_mask.sum())
    duplicate_key_count_compare = int(compare_dup_mask.sum())
    if duplicate_key_count_base:
        warnings.append(f"{duplicate_key_count_base} base row(s) share a duplicated key under {key_columns}; they are excluded from the row-level diff below (key columns don't uniquely identify them).")
    if duplicate_key_count_compare:
        warnings.append(f"{duplicate_key_count_compare} compare row(s) share a duplicated key under {key_columns}; they are excluded from the row-level diff below (key columns don't uniquely identify them).")

    base_unique = base_frame.loc[~base_dup_mask].set_index(base_keys.loc[~base_dup_mask])
    compare_unique = compare_frame.loc[~compare_dup_mask].set_index(compare_keys.loc[~compare_dup_mask])
    added_keys = compare_unique.index.difference(base_unique.index)
    removed_keys = base_unique.index.difference(compare_unique.index)
    common_keys = base_unique.index.intersection(compare_unique.index)
    common_columns = [column for column in base_frame.columns if column in compare_frame.columns]

    sample_diffs: list[ResultRowDiff] = []
    changed_count = 0
    unchanged_count = 0
    for key in common_keys:
        base_row, compare_row = base_unique.loc[key], compare_unique.loc[key]
        changed_columns = [column for column in common_columns if _json_value(base_row[column]) != _json_value(compare_row[column])]
        if not changed_columns:
            unchanged_count += 1
            continue
        changed_count += 1
        if len(sample_diffs) < request.max_sample_diffs:
            sample_diffs.append(ResultRowDiff(
                key=_key_dict(base_row, key_columns), change="changed", changed_columns=changed_columns,
                base_values={column: _json_value(base_row[column]) for column in changed_columns},
                compare_values={column: _json_value(compare_row[column]) for column in changed_columns},
            ))
    for key in added_keys:
        if len(sample_diffs) >= request.max_sample_diffs:
            break
        row = compare_unique.loc[key]
        sample_diffs.append(ResultRowDiff(key=_key_dict(row, key_columns), change="added", compare_values={column: _json_value(row[column]) for column in common_columns}))
    for key in removed_keys:
        if len(sample_diffs) >= request.max_sample_diffs:
            break
        row = base_unique.loc[key]
        sample_diffs.append(ResultRowDiff(key=_key_dict(row, key_columns), change="removed", base_values={column: _json_value(row[column]) for column in common_columns}))

    return ResultComparisonResponse(
        base_run_id=request.base_run_id, compare_run_id=request.compare_run_id, key_columns=key_columns,
        base_row_count=len(base_frame), compare_row_count=len(compare_frame),
        duplicate_key_count_base=duplicate_key_count_base, duplicate_key_count_compare=duplicate_key_count_compare,
        added_count=len(added_keys), removed_count=len(removed_keys), changed_count=changed_count, unchanged_count=unchanged_count,
        sample_diffs=sample_diffs, warnings=warnings,
    )
