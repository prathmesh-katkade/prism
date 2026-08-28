"""Phase 6A native Clean: transformations as versioned, reversible analytical objects.

Every transformation reads the dataset's current revision, computes a new frame, and
appends it as the next revision via ``overview.store`` — it never mutates data in
place. Overview, SQL Lab, and AI Analyst all resolve the dataset by id through the
same store, so a Clean transformation is immediately visible everywhere without those
modules needing to know revisions exist. Undo is a linear undo stack: reverting to an
earlier revision drops any later ones, then a new transformation starts a fresh path.
"""

from __future__ import annotations

import hashlib
import math
import uuid
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    AtlasCleanAction,
    AtlasCleanRequest,
    AtlasCleanResponse,
    AtlasEvidence,
    CleanApplyResponse,
    CleanIssue,
    CleanIssueKind,
    CleanOperation,
    CleanPreviewResponse,
    CleanStateResponse,
    CleanTransformation,
    CleanTransformationRequest,
    CleanUndoRequest,
    OverviewColumn,
    OverviewQuality,
)
from prism_overview_analytics import build_overview

from .overview import StoredDataset
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/clean", tags=["clean"])
PREVIEW_SAMPLE_ROWS = 10
_history: dict[str, list[CleanTransformation]] = {}


def _fingerprint(frame: pd.DataFrame) -> str:
    return hashlib.sha256(pd.util.hash_pandas_object(frame, index=True).values.tobytes()).hexdigest()


def _json_value(value: Any) -> object | None:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else value
    if isinstance(value, (pd.Timestamp, datetime)):
        return str(value.isoformat())
    return None if bool(pd.isna(value)) else str(value)


def _sample(frame: pd.DataFrame, n: int = PREVIEW_SAMPLE_ROWS) -> list[dict[str, Any]]:
    return [{str(k): _json_value(v) for k, v in row.items()} for row in frame.head(n).to_dict(orient="records")]


def _require_column(frame: pd.DataFrame, column: str | None) -> str:
    if not column:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This operation requires a column.")
    if column not in frame.columns:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset. PRISM will not assume a column that does not exist.")
    return column


def detect_issues(frame: pd.DataFrame) -> list[CleanIssue]:
    """Deterministic, evidence-based issue detection reusing Overview's own analytics."""
    profile = build_overview(frame)
    quality = OverviewQuality(**profile["quality"])
    columns = [OverviewColumn(**item) for item in profile["columns"]]
    issues: list[CleanIssue] = []
    for column in columns:
        missing_pct = quality.missing_by_column.get(column.name, 0.0)
        if column.semantic_type == "all_null":
            issues.append(CleanIssue(
                issue_id=f"issue_all_null_{column.name}", kind=CleanIssueKind.ALL_NULL_COLUMN, column=column.name,
                severity="high", affected_rows=quality.n_rows,
                description=f"{column.name!r} has no non-missing values in any row.",
                suggested_operation=CleanOperation.DROP_COLUMN,
            ))
        elif missing_pct > 0:
            severity = "high" if missing_pct >= 50 else "medium" if missing_pct >= 10 else "low"
            issues.append(CleanIssue(
                issue_id=f"issue_missing_{column.name}", kind=CleanIssueKind.MISSING_VALUES, column=column.name,
                severity=severity, affected_rows=int(round(missing_pct / 100 * quality.n_rows)),
                description=f"{missing_pct}% of {column.name!r} is missing.",
                suggested_operation=CleanOperation.FILL_MISSING if column.semantic_type == "numeric" else CleanOperation.DROP_MISSING_ROWS,
            ))
    if quality.duplicate_rows:
        issues.append(CleanIssue(
            issue_id="issue_duplicate_rows", kind=CleanIssueKind.DUPLICATE_ROWS, column=None,
            severity="medium" if quality.duplicate_rows < quality.n_rows * 0.05 else "high",
            affected_rows=quality.duplicate_rows,
            description=f"{quality.duplicate_rows:,} rows are exact duplicates of another row.",
            suggested_operation=CleanOperation.DROP_DUPLICATES,
        ))
    outliers = quality.outliers
    for column_name, finding in outliers.items():
        if finding.pct >= 5:
            issues.append(CleanIssue(
                issue_id=f"issue_outliers_{column_name}", kind=CleanIssueKind.OUTLIER_BURDEN, column=column_name,
                severity="low", affected_rows=finding.count,
                description=f"{finding.pct}% of {column_name!r} falls outside the IQR fence. This is a screening signal, not proof of bad data — inspect before removing.",
                suggested_operation=None,
            ))
    return issues


def _apply_operation(frame: pd.DataFrame, request: CleanTransformationRequest) -> tuple[pd.DataFrame, int, list[str], list[str]]:
    """Returns (new_frame, affected_rows, affected_columns, warnings). Never mutates ``frame``."""
    warnings: list[str] = []
    if request.operation is CleanOperation.DROP_DUPLICATES:
        mask = frame.duplicated()
        affected = int(mask.sum())
        return frame.loc[~mask].reset_index(drop=True), affected, [], warnings
    if request.operation is CleanOperation.DROP_COLUMN:
        column = _require_column(frame, request.column)
        return frame.drop(columns=[column]), len(frame), [column], warnings
    if request.operation is CleanOperation.RENAME_COLUMN:
        column = _require_column(frame, request.column)
        if not request.new_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A new column name is required.")
        if request.new_name in frame.columns and request.new_name != column:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {request.new_name!r} already exists.")
        return frame.rename(columns={column: request.new_name}), len(frame), [column, request.new_name], warnings
    if request.operation is CleanOperation.DROP_MISSING_ROWS:
        column = _require_column(frame, request.column)
        mask = frame[column].isna()
        affected = int(mask.sum())
        return frame.loc[~mask].reset_index(drop=True), affected, [column], warnings
    if request.operation is CleanOperation.FILL_MISSING:
        column = _require_column(frame, request.column)
        series = frame[column]
        mask = series.isna()
        affected = int(mask.sum())
        strategy = request.fill_strategy
        if strategy is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A fill strategy is required.")
        numeric = pd.to_numeric(series, errors="coerce")
        if strategy.value in ("mean", "median") and numeric.notna().sum() == 0:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{column!r} has no numeric values to compute a {strategy.value} from.")
        if strategy.value == "mean":
            fill_value: Any = numeric.mean()
        elif strategy.value == "median":
            fill_value = numeric.median()
        elif strategy.value == "mode":
            modes = series.mode(dropna=True)
            fill_value = modes.iloc[0] if not modes.empty else None
        elif strategy.value == "constant":
            fill_value = request.fill_value
        else:  # forward_fill
            updated = frame.copy()
            updated[column] = series.ffill()
            still_missing = int(updated[column].isna().sum())
            if still_missing:
                warnings.append(f"{still_missing} row(s) at the start of the data had no prior value to forward-fill from and remain missing.")
            return updated, affected - still_missing, [column], warnings
        updated = frame.copy()
        updated[column] = series.fillna(fill_value)
        return updated, affected, [column], warnings
    if request.operation is CleanOperation.CONVERT_TYPE:
        column = _require_column(frame, request.column)
        if request.target_type is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A target type is required.")
        series = frame[column]
        updated = frame.copy()
        if request.target_type == "numeric":
            converted = pd.to_numeric(series, errors="coerce")
        elif request.target_type == "datetime":
            converted = pd.to_datetime(series, errors="coerce", format="mixed")
        elif request.target_type == "boolean":
            converted = series.astype(str).str.strip().str.lower().map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False})
        else:
            converted = series.astype(str)
        newly_invalid = int((converted.isna() & series.notna()).sum())
        if newly_invalid:
            warnings.append(f"{newly_invalid} value(s) could not be converted to {request.target_type} and became missing instead of being silently guessed.")
        updated[column] = converted
        return updated, len(frame), [column], warnings
    if request.operation is CleanOperation.TRIM_WHITESPACE:
        column = _require_column(frame, request.column)
        series = frame[column].astype(str)
        trimmed = series.str.strip()
        mask = trimmed.ne(series) & frame[column].notna()
        updated = frame.copy()
        updated[column] = frame[column].where(frame[column].isna(), trimmed)
        return updated, int(mask.sum()), [column], warnings
    if request.operation is CleanOperation.NORMALIZE_CASE:
        column = _require_column(frame, request.column)
        if request.case is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A case (lower/upper/title) is required.")
        series = frame[column].astype(str)
        normalized = getattr(series.str, request.case)()
        mask = normalized.ne(series) & frame[column].notna()
        updated = frame.copy()
        updated[column] = frame[column].where(frame[column].isna(), normalized)
        return updated, int(mask.sum()), [column], warnings
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported operation.")


def _health(frame: pd.DataFrame):  # type: ignore[no-untyped-def]
    return build_overview(frame)["health"]


def _state(stored: StoredDataset) -> CleanStateResponse:
    issues = detect_issues(stored.frame)
    return CleanStateResponse(dataset=stored.dataset, issues=issues, history=_history.get(stored.dataset.dataset_id, []), health=_health(stored.frame))


@router.get("/datasets/{dataset_id}/state", response_model=CleanStateResponse)
def get_state(dataset_id: str) -> CleanStateResponse:
    return _state(overview_store.get(dataset_id))


@router.post("/datasets/{dataset_id}/preview", response_model=CleanPreviewResponse)
def preview_transformation(dataset_id: str, request: CleanTransformationRequest) -> CleanPreviewResponse:
    stored = overview_store.get(dataset_id)
    before_sample = _sample(stored.frame)
    updated, affected_rows, affected_columns, warnings = _apply_operation(stored.frame, request)
    return CleanPreviewResponse(
        operation=request.operation, affected_rows=affected_rows, affected_columns=affected_columns,
        before_sample=before_sample, after_sample=_sample(updated), warnings=warnings, projected_health=_health(updated),
    )


@router.post("/datasets/{dataset_id}/apply", response_model=CleanApplyResponse, status_code=status.HTTP_201_CREATED)
def apply_transformation(dataset_id: str, request: CleanTransformationRequest) -> CleanApplyResponse:
    stored = overview_store.get(dataset_id)
    source_revision = stored.dataset.revision
    updated, affected_rows, affected_columns, warnings = _apply_operation(stored.frame, request)
    fingerprint = _fingerprint(updated)
    dataset = overview_store.add_revision(dataset_id, updated, fingerprint)
    transformation = CleanTransformation(
        transformation_id=f"clean_{uuid.uuid4().hex}", operation=request.operation, column=request.column,
        parameters=request.model_dump(exclude={"operation", "column"}, exclude_none=True),
        affected_rows=affected_rows, affected_columns=affected_columns,
        source_revision=source_revision, resulting_revision=dataset.revision,
        source_fingerprint=stored.source_fingerprint, resulting_fingerprint=fingerprint,
        reversible=True, created_at=datetime.now(timezone.utc),
    )
    _history.setdefault(dataset_id, []).append(transformation)
    return CleanApplyResponse(dataset=dataset, transformation=transformation, issues=detect_issues(updated), health=_health(updated))


@router.post("/datasets/{dataset_id}/undo", response_model=CleanStateResponse)
def undo(dataset_id: str, request: CleanUndoRequest) -> CleanStateResponse:
    overview_store.revert(dataset_id, request.to_revision)
    history = _history.get(dataset_id, [])
    _history[dataset_id] = [item for item in history if item.resulting_revision <= request.to_revision]
    return _state(overview_store.get(dataset_id))


@router.post("/datasets/{dataset_id}/atlas", response_model=AtlasCleanResponse)
def atlas_action(dataset_id: str, request: AtlasCleanRequest) -> AtlasCleanResponse:
    stored = overview_store.get(dataset_id)
    issues = detect_issues(stored.frame)
    issue = next((item for item in issues if item.issue_id == request.issue_id), None) if request.issue_id else None
    uncertainty = "Issue detection is a deterministic screening pass; it flags candidates for review, not confirmed defects."
    if request.action is AtlasCleanAction.EXPLAIN_ISSUE:
        if issue is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="That issue was not found in the current revision.")
        summary = issue.description
        evidence = [AtlasEvidence(label="Affected rows", value=f"{issue.affected_rows:,}"), AtlasEvidence(label="Severity", value=issue.severity)]
        proposed = CleanTransformationRequest(operation=issue.suggested_operation, column=issue.column) if issue.suggested_operation else None
        return AtlasCleanResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=evidence, proposed_operation=proposed)
    if request.action is AtlasCleanAction.PROPOSE_FIX:
        if issue is None or issue.suggested_operation is None:
            return AtlasCleanResponse(action=request.action, summary="No deterministic safe fix is available for this issue; it needs analyst judgment.", uncertainty=uncertainty, evidence=[], proposed_operation=None)
        proposal = CleanTransformationRequest(operation=issue.suggested_operation, column=issue.column, fill_strategy="median" if issue.suggested_operation is CleanOperation.FILL_MISSING else None)
        return AtlasCleanResponse(
            action=request.action, summary=f"Proposed: {issue.suggested_operation.value.replace('_', ' ')} on {issue.column or 'the dataset'}. Preview it before applying — Atlas does not clean data without visibility.",
            uncertainty=uncertainty, evidence=[AtlasEvidence(label="Affected rows", value=f"{issue.affected_rows:,}")], proposed_operation=proposal,
        )
    history = _history.get(dataset_id, [])
    summary = f"{len(history)} transformation(s) applied so far, from revision 0 to {stored.dataset.revision}." if history else "No transformations have been applied to this dataset yet."
    return AtlasCleanResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=[], proposed_operation=None)
