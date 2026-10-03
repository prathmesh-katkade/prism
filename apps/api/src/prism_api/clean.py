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
import re
import uuid
from datetime import datetime, timezone
from typing import Any, cast

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_analytical_schemas import CleaningReproducibilitySpec, DatasetRef, ObjectKind
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
    CleanRecipe,
    CleanRecipeApplyRequest,
    CleanRecipeApplyResponse,
    CleanRecipeCreateRequest,
    CleanRecipeDraftPreviewRequest,
    CleanRecipeDraftPreviewResponse,
    CleanRecipePreviewResponse,
    CleanRecipeStep,
    CleanRecipeStepsUpdateRequest,
    CleanRowInspection,
    CleanStateResponse,
    CleanTransformation,
    CleanTransformationRequest,
    CleanUndoRequest,
    ColumnValueCount,
    ColumnValueCountsResponse,
    OverviewColumn,
    OverviewDataset,
    OverviewQuality,
)
from prism_overview_analytics import build_overview
from sqlalchemy import and_, desc, func, insert, select, update

from .analytical_objects import (
    clean_transformation_record,
    dataset_revision_record,
    register_clean_transformation,
    registry,
)
from .durable_clean_review_store import DurableCleanReviewStore
from .durable_dataset_store import DurableDatasetStore, _revisions
from .durable_recipe_store import DurableRecipeStore
from .durable_registry import DurableAnalyticalObjectRegistry
from .overview import StoredDataset
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/clean", tags=["clean"])
PREVIEW_SAMPLE_ROWS = 10
INSPECTION_LIMIT = 100


def _durable_history(dataset_id: str) -> list[CleanTransformation]:
    """Reconstruct Clean's applied-transformation history from the durable
    analytical-object registry (populated by register_clean_transformation
    on every apply) instead of a process-local cache, so it survives an API
    restart. The registry is append-only and keeps every branch a revert
    ever walked away from, so records are filtered against DatasetStore's
    own current active-revision list -- the real source of truth for which
    branch is live -- rather than trusted on their own.
    """
    active_fingerprint_by_revision = {item.dataset.revision: item.source_fingerprint for item in overview_store.revisions(dataset_id)}
    transformations: list[CleanTransformation] = []
    for record in registry.list_for_dataset(dataset_id, kind=ObjectKind.CLEANING_PLAN):
        reproducibility = record.provenance.reproducibility
        if not isinstance(reproducibility, CleaningReproducibilitySpec):
            continue
        resulting_revision = record.provenance.dataset.revision
        resulting_fingerprint = record.provenance.dataset.source_fingerprint
        if active_fingerprint_by_revision.get(resulting_revision) != resulting_fingerprint:
            continue  # an abandoned branch a revert walked away from
        source_revision = cast(int, record.payload.get("source_revision", resulting_revision - 1))
        parameters = dict(reproducibility.parameters)
        column = parameters.pop("column", None)
        affected_columns_raw = parameters.pop("affected_columns", [])
        evidence_refs = record.provenance.evidence_refs
        transformation_id = evidence_refs[0].evidence_id if evidence_refs else record.object_id.removeprefix("clean_")
        transformations.append(CleanTransformation(
            transformation_id=transformation_id,
            operation=CleanOperation(reproducibility.operation),
            column=cast("str | None", column),
            parameters=parameters,
            affected_rows=cast(int, record.payload.get("affected_rows", 0)),
            affected_columns=cast("list[str]", affected_columns_raw) if isinstance(affected_columns_raw, list) else [],
            source_revision=source_revision,
            resulting_revision=resulting_revision,
            source_fingerprint=active_fingerprint_by_revision.get(source_revision, resulting_fingerprint),
            resulting_fingerprint=resulting_fingerprint,
            reversible=cast(bool, record.payload.get("reversible", True)),
            created_at=record.provenance.created_at,
        ))
    transformations.sort(key=lambda item: item.resulting_revision)
    return transformations


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


def _row_inspection(before: pd.DataFrame, after: pd.DataFrame, request: CleanTransformationRequest,
                    unresolved_values: list[str]) -> tuple[list[CleanRowInspection], int, list[CleanRowInspection], int]:
    """Resolve source-row identity and truthful counts without shipping full datasets."""
    after_indices = set(after.index)
    common = before.index.intersection(after.index)
    if request.operation in {CleanOperation.CONVERT_TYPE, CleanOperation.RENAME_COLUMN, CleanOperation.DROP_COLUMN} or list(before.columns) != list(after.columns):
        changed_indices = set(common)
    else:
        changed_mask = before.loc[common].astype(str).ne(after.loc[common].astype(str)).any(axis=1)
        changed_indices = set(common[changed_mask])
    removed_indices = set(before.index) - after_indices
    affected_indices = changed_indices | removed_indices
    changed_total = len(affected_indices)
    unresolved_set = set(unresolved_values)
    exception_indices: set[Any] = set()
    if request.column and request.column in before.columns:
        if unresolved_set:
            exception_indices.update(before.index[before[request.column].astype(str).isin(unresolved_set)])
        if request.column in after.columns:
            newly_missing = before.loc[common, request.column].notna() & after.loc[common, request.column].isna()
            exception_indices.update(common[newly_missing])

    def item(index: Any, kind: str) -> CleanRowInspection:
        before_row = {str(key): _json_value(value) for key, value in before.loc[index].to_dict().items()}
        after_row = ({str(key): _json_value(value) for key, value in after.loc[index].to_dict().items()}
                     if index in after_indices else None)
        return CleanRowInspection(source_row=str(index), status=kind, before=before_row, after=after_row)

    changed = [item(index, "removed" if index in removed_indices else "changed")
               for index in before.index if index in affected_indices][:INSPECTION_LIMIT]
    exceptions = [item(index, "newly_missing" if index in after_indices and request.column and
                       request.column in after.columns and pd.isna(after.at[index, request.column]) else "unresolved")
                  for index in before.index if index in exception_indices][:INSPECTION_LIMIT]
    return changed, changed_total, exceptions, len(exception_indices)


def _require_column(frame: pd.DataFrame, column: str | None) -> str:
    if not column:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This operation requires a column.")
    if column not in frame.columns:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset. PRISM will not assume a column that does not exist.")
    return column


_AMBIGUOUS_DATE_PATTERN = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}\s*$")


def _detect_ambiguous_dates(series: pd.Series) -> list[str]:
    """Distinct values like "03/04/2026" where both components are <=12, so day-first
    and month-first readings are both plausible and silently guessing one would be
    exactly the kind of invented interpretation Clean must not produce without a
    declared date_format."""
    ambiguous: set[str] = set()
    for value in series.dropna().unique():
        match = _AMBIGUOUS_DATE_PATTERN.match(str(value))
        if match and int(match.group(1)) <= 12 and int(match.group(2)) <= 12:
            ambiguous.add(str(value))
    return sorted(ambiguous)


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


def _apply_operation(frame: pd.DataFrame, request: CleanTransformationRequest) -> tuple[pd.DataFrame, int, list[str], list[str], list[str]]:
    """Returns (new_frame, affected_rows, affected_columns, warnings, unresolved_values). Never mutates ``frame``."""
    warnings: list[str] = []
    if request.operation is CleanOperation.DROP_DUPLICATES:
        mask = frame.duplicated()
        affected = int(mask.sum())
        return frame.loc[~mask].copy(), affected, [], warnings, []
    if request.operation is CleanOperation.DROP_COLUMN:
        column = _require_column(frame, request.column)
        return frame.drop(columns=[column]), len(frame), [column], warnings, []
    if request.operation is CleanOperation.RENAME_COLUMN:
        column = _require_column(frame, request.column)
        if not request.new_name:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A new column name is required.")
        if request.new_name in frame.columns and request.new_name != column:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {request.new_name!r} already exists.")
        return frame.rename(columns={column: request.new_name}), len(frame), [column, request.new_name], warnings, []
    if request.operation is CleanOperation.DROP_MISSING_ROWS:
        column = _require_column(frame, request.column)
        mask = frame[column].isna()
        affected = int(mask.sum())
        return frame.loc[~mask].copy(), affected, [column], warnings, []
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
            return updated, affected - still_missing, [column], warnings, []
        updated = frame.copy()
        updated[column] = series.fillna(fill_value)
        return updated, affected, [column], warnings, []
    if request.operation is CleanOperation.CONVERT_TYPE:
        column = _require_column(frame, request.column)
        if request.target_type is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A target type is required.")
        series = frame[column]
        updated = frame.copy()
        unresolved: list[str] = []
        if request.target_type == "numeric":
            raw = series.astype(str)
            if request.number_locale == "european":
                cleaned = raw.str.replace(".", "", regex=False).str.replace(",", ".", regex=False)
            else:
                cleaned = raw.str.replace(",", "", regex=False)
            converted = pd.to_numeric(cleaned.where(series.notna()), errors="coerce")
        elif request.target_type == "datetime":
            if request.date_format:
                converted = pd.to_datetime(series, format=request.date_format, errors="coerce")
            else:
                converted = pd.to_datetime(series, errors="coerce", format="mixed")
                unresolved = _detect_ambiguous_dates(series)
                if unresolved:
                    warnings.append(
                        f"{len(unresolved)} distinct value(s) in {column!r} match more than one plausible date "
                        "reading (day vs month order is ambiguous); declare an explicit date_format to resolve "
                        "them confidently instead of guessing."
                    )
        elif request.target_type == "boolean":
            converted = series.astype(str).str.strip().str.lower().map({"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False})
        else:
            converted = series.astype(str)
        newly_invalid = int((converted.isna() & series.notna()).sum())
        if newly_invalid:
            warnings.append(f"{newly_invalid} value(s) could not be converted to {request.target_type} and became missing instead of being silently guessed.")
        updated[column] = converted
        return updated, len(frame), [column], warnings, unresolved
    if request.operation is CleanOperation.TRIM_WHITESPACE:
        column = _require_column(frame, request.column)
        series = frame[column].astype(str)
        trimmed = series.str.strip()
        mask = trimmed.ne(series) & frame[column].notna()
        updated = frame.copy()
        updated[column] = frame[column].where(frame[column].isna(), trimmed)
        return updated, int(mask.sum()), [column], warnings, []
    if request.operation is CleanOperation.NORMALIZE_CASE:
        column = _require_column(frame, request.column)
        if request.case is None:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A case (lower/upper/title) is required.")
        series = frame[column].astype(str)
        normalized = getattr(series.str, request.case)()
        mask = normalized.ne(series) & frame[column].notna()
        updated = frame.copy()
        updated[column] = frame[column].where(frame[column].isna(), normalized)
        return updated, int(mask.sum()), [column], warnings, []
    if request.operation is CleanOperation.CATEGORY_MAPPING:
        column = _require_column(frame, request.column)
        mapping = request.category_mapping
        if not mapping:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A value mapping is required.")
        case_sensitive = request.case_sensitive if request.case_sensitive is not None else True
        preserve_unmatched = request.preserve_unmatched if request.preserve_unmatched is not None else True
        lookup = {(key if case_sensitive else key.lower()): target for key, target in mapping.items()}
        series = frame[column]
        counts = series.value_counts(dropna=True)
        replacement: dict[Any, Any] = {}
        affected = 0
        unresolved_values: list[str] = []
        for raw_value, n in counts.items():
            text = str(raw_value)
            lookup_key = text if case_sensitive else text.lower()
            if lookup_key in lookup:
                target = lookup[lookup_key]
                if target != text:
                    replacement[raw_value] = target
                    affected += int(n)
            else:
                unresolved_values.append(text)
                if not preserve_unmatched:
                    replacement[raw_value] = None
                    affected += int(n)
        updated = frame.copy()
        updated[column] = series.replace(replacement) if replacement else series
        if unresolved_values:
            warnings.append(
                f"{len(unresolved_values)} distinct value(s) in {column!r} were not covered by the mapping and were "
                + ("left unchanged." if preserve_unmatched else "set to missing.")
            )
        return updated, affected, [column], warnings, unresolved_values
    if request.operation is CleanOperation.DEDUPLICATE_SURVIVORSHIP:
        columns = request.group_by_columns
        if not columns:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="At least one grouping column is required.")
        for group_column in columns:
            _require_column(frame, group_column)
        rule = request.survivorship_rule or "first"
        tiebreak_column: str | None = None
        if rule == "max_by_column":
            tiebreak_column = request.survivorship_tiebreak_column
            if not tiebreak_column:
                raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A tiebreak column is required for the max_by_column survivorship rule.")
            _require_column(frame, tiebreak_column)
        duplicate_group_count = 0
        tied_group_count = 0
        keep_indices: list[Any] = []
        for _key, group in frame.groupby(list(columns), dropna=False, sort=False):
            if len(group) == 1:
                keep_indices.append(group.index[0])
                continue
            duplicate_group_count += 1
            if rule == "last":
                keep_indices.append(group.index[-1])
            elif rule == "most_complete":
                completeness = group.notna().sum(axis=1)
                if int((completeness == completeness.max()).sum()) > 1:
                    tied_group_count += 1
                keep_indices.append(completeness.idxmax())
            elif rule == "max_by_column":
                numeric = pd.to_numeric(group[tiebreak_column], errors="coerce")
                if not numeric.notna().any() or int((numeric == numeric.max()).sum()) > 1:
                    tied_group_count += 1
                keep_indices.append(numeric.idxmax() if numeric.notna().any() else group.index[0])
            else:  # first
                keep_indices.append(group.index[0])
        updated = frame.loc[sorted(keep_indices)].copy()
        affected = len(frame) - len(updated)
        if duplicate_group_count:
            warnings.append(f"{duplicate_group_count} duplicate group(s) found across {', '.join(columns)}; kept 1 row per group using the {rule!r} rule.")
        if tied_group_count:
            warnings.append(f"{tied_group_count} group(s) tied under the {rule!r} rule; the earliest source row was kept deterministically.")
        return updated, affected, list(columns), warnings, []
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported operation.")


def _health(frame: pd.DataFrame):  # type: ignore[no-untyped-def]
    return build_overview(frame)["health"]


def _state(stored: StoredDataset) -> CleanStateResponse:
    issues = detect_issues(stored.frame)
    return CleanStateResponse(dataset=stored.dataset, issues=issues, history=_durable_history(stored.dataset.dataset_id), health=_health(stored.frame))


@router.get("/datasets/{dataset_id}/state", response_model=CleanStateResponse)
def get_state(dataset_id: str) -> CleanStateResponse:
    return _state(overview_store.get(dataset_id))


COLUMN_VALUES_LIMIT = 500


@router.get("/datasets/{dataset_id}/columns/{column}/values", response_model=ColumnValueCountsResponse)
def get_column_values(dataset_id: str, column: str) -> ColumnValueCountsResponse:
    """Every distinct value in a column with its row count, for building a category
    mapping without guessing at values the UI never actually saw. Capped (and the cap
    disclosed) rather than silently truncated for a near-unique column."""
    stored = overview_store.get(dataset_id)
    _require_column(stored.frame, column)
    counts = stored.frame[column].value_counts(dropna=True)
    total_distinct = len(counts)
    truncated = total_distinct > COLUMN_VALUES_LIMIT
    top = counts.iloc[:COLUMN_VALUES_LIMIT]
    return ColumnValueCountsResponse(
        column=column, total_distinct=total_distinct, truncated=truncated,
        values=[ColumnValueCount(value=str(value), count=int(count)) for value, count in top.items()],
    )


@router.post("/datasets/{dataset_id}/preview", response_model=CleanPreviewResponse)
def preview_transformation(dataset_id: str, request: CleanTransformationRequest) -> CleanPreviewResponse:
    stored = overview_store.get(dataset_id)
    before_sample = _sample(stored.frame)
    updated, affected_rows, affected_columns, warnings, unresolved_values = _apply_operation(stored.frame, request)
    changed_rows, changed_total, exception_rows, exception_total = _row_inspection(
        stored.frame, updated, request, unresolved_values)
    token = reviews.issue(dataset_id, stored.dataset.revision, stored.source_fingerprint,
                          request.model_dump(exclude={"review_token"}, exclude_none=True))
    return CleanPreviewResponse(
        operation=request.operation, affected_rows=affected_rows, affected_columns=affected_columns,
        before_sample=before_sample, after_sample=_sample(updated), warnings=warnings, projected_health=_health(updated),
        unresolved_values=unresolved_values,
        review_token=token, source_revision=stored.dataset.revision,
        source_fingerprint=stored.source_fingerprint,
        changed_rows=changed_rows, changed_rows_total=changed_total,
        exception_rows=exception_rows, exception_rows_total=exception_total,
    )


def _commit_operation(dataset_id: str, request: CleanTransformationRequest, extra_parameters: dict[str, Any] | None = None,
                      reviewed_source: StoredDataset | None = None) -> CleanTransformation:
    """Run and durably record one operation against a dataset's *current* revision.

    This path handles one operation. Recipes use a separate atomic publication
    transaction for the entire enabled chain.
    """
    stored = overview_store.get(dataset_id)
    source_revision = stored.dataset.revision
    if reviewed_source is not None and (source_revision != reviewed_source.dataset.revision or
                                        stored.source_fingerprint != reviewed_source.source_fingerprint):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="Dataset changed since preview; review the current revision again.")
    updated, affected_rows, affected_columns, warnings, _unresolved_values = _apply_operation(stored.frame, request)
    fingerprint = _fingerprint(updated)
    dataset = cast(DurableDatasetStore, overview_store).add_revision(
        dataset_id, updated, fingerprint, expected_revision=source_revision,
        expected_fingerprint=stored.source_fingerprint,
    )
    parameters = request.model_dump(exclude={"operation", "column", "review_token"}, exclude_none=True)
    if extra_parameters:
        parameters.update(extra_parameters)
    transformation = CleanTransformation(
        transformation_id=f"clean_{uuid.uuid4().hex}", operation=request.operation, column=request.column,
        parameters=parameters,
        affected_rows=affected_rows, affected_columns=affected_columns,
        source_revision=source_revision, resulting_revision=dataset.revision,
        source_fingerprint=stored.source_fingerprint, resulting_fingerprint=fingerprint,
        reversible=True, created_at=datetime.now(timezone.utc),
    )
    try:
        register_clean_transformation(stored, transformation, warnings)
    except Exception as error:
        # The revision above is already durable; a failure here would leave
        # it live with no matching provenance record, and a client retry
        # would then apply on top of data that was mutated despite the
        # failed response. Compensate by reverting before surfacing the
        # failure, so the client sees a clean error against unchanged data
        # rather than an unhandled exception.
        overview_store.revert(dataset_id, source_revision)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Applying the transformation failed while recording its provenance; no change was made.") from error
    return transformation


@router.post("/datasets/{dataset_id}/apply", response_model=CleanApplyResponse, status_code=status.HTTP_201_CREATED)
def apply_transformation(dataset_id: str, request: CleanTransformationRequest) -> CleanApplyResponse:
    current = overview_store.get(dataset_id)
    reviews.consume(request.review_token, dataset_id, current.dataset.revision,
                    current.source_fingerprint,
                    request.model_dump(exclude={"review_token"}, exclude_none=True))
    transformation = _commit_operation(dataset_id, request, reviewed_source=current)
    updated = overview_store.get(dataset_id)
    return CleanApplyResponse(dataset=updated.dataset, transformation=transformation, issues=detect_issues(updated.frame), health=_health(updated.frame))


recipes = DurableRecipeStore()
reviews = DurableCleanReviewStore()


@router.post("/recipes", response_model=CleanRecipe, status_code=status.HTTP_201_CREATED)
def create_recipe(request: CleanRecipeCreateRequest) -> CleanRecipe:
    steps = [CleanRecipeStep(step_id=f"step_{uuid.uuid4().hex}", request=item.request, enabled=item.enabled) for item in request.steps]
    return recipes.create(request.name, steps)


@router.get("/recipes", response_model=list[CleanRecipe])
def list_recipes() -> list[CleanRecipe]:
    return recipes.list_latest()


@router.get("/recipes/{recipe_id}", response_model=CleanRecipe)
def get_recipe(recipe_id: str) -> CleanRecipe:
    return recipes.latest(recipe_id)


@router.get("/recipes/{recipe_id}/versions", response_model=list[CleanRecipe])
def get_recipe_versions(recipe_id: str) -> list[CleanRecipe]:
    return recipes.versions(recipe_id)


@router.put("/recipes/{recipe_id}/steps", response_model=CleanRecipe)
def update_recipe_steps(recipe_id: str, request: CleanRecipeStepsUpdateRequest) -> CleanRecipe:
    """Reordering, disabling, or editing steps creates a new version; prior versions —
    and any analytical records produced by applying them — are never rewritten."""
    steps = [CleanRecipeStep(step_id=item.step_id, request=item.request, enabled=item.enabled) for item in request.steps]
    return recipes.new_version(recipe_id, steps)


def _dry_run_recipe(frame: pd.DataFrame, steps: list[CleanRecipeStep]) -> None:
    """Validate the whole enabled chain against the dataset's *current* schema before
    committing anything. Raises on the first step that would fail, naming which step
    and why, instead of applying a partial prefix or guessing a column mapping for a
    schema the recipe no longer matches."""
    working = frame
    for index, step in enumerate(steps):
        if not step.enabled:
            continue
        try:
            working, _, _, _, _ = _apply_operation(working, step.request)
        except HTTPException as error:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Recipe step {index + 1} ({step.request.operation.value} on {step.request.column or 'the dataset'}) no longer matches this dataset's schema: {error.detail}",
            ) from error


@router.post("/datasets/{dataset_id}/recipes/{recipe_id}/preview", response_model=CleanRecipePreviewResponse)
def preview_recipe(dataset_id: str, recipe_id: str) -> CleanRecipePreviewResponse:
    recipe = recipes.latest(recipe_id)
    if not any(step.enabled for step in recipe.steps):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="This recipe has no enabled steps to preview.")
    stored = overview_store.get(dataset_id)
    working, impacts = _preview_recipe_steps(stored.frame, recipe.steps)
    token = reviews.issue(dataset_id, stored.dataset.revision, stored.source_fingerprint,
                          {"recipe_id": recipe_id, "recipe_version": recipe.version,
                           "steps": [step.model_dump(mode="json") for step in recipe.steps]})
    return CleanRecipePreviewResponse(
        recipe_id=recipe_id, recipe_version=recipe.version,
        source_revision=stored.dataset.revision, source_fingerprint=stored.source_fingerprint,
        review_token=token, before_sample=_sample(stored.frame), after_sample=_sample(working),
        step_impacts=impacts, projected_health=_health(working),
    )


def _preview_recipe_steps(frame: pd.DataFrame, steps: list[CleanRecipeStep]) -> tuple[pd.DataFrame, list[int]]:
    working = frame
    impacts: list[int] = []
    for index, step in enumerate(steps):
        if not step.enabled:
            impacts.append(0)
            continue
        try:
            working, affected, _, _, _ = _apply_operation(working, step.request)
        except HTTPException as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Recipe step {index + 1} ({step.request.operation.value} on {step.request.column or 'the dataset'}) no longer matches this dataset's schema: {error.detail}") from error
        impacts.append(affected)
    return working, impacts


@router.post("/datasets/{dataset_id}/recipe-draft/preview", response_model=CleanRecipeDraftPreviewResponse)
def preview_recipe_draft(dataset_id: str, request: CleanRecipeDraftPreviewRequest) -> CleanRecipeDraftPreviewResponse:
    stored = overview_store.get(dataset_id)
    steps = [CleanRecipeStep(step_id=f"draft_{index}", request=item.request, enabled=item.enabled)
             for index, item in enumerate(request.steps)]
    working, impacts = _preview_recipe_steps(stored.frame, steps)
    return CleanRecipeDraftPreviewResponse(
        source_revision=stored.dataset.revision, source_fingerprint=stored.source_fingerprint,
        before_sample=_sample(stored.frame), after_sample=_sample(working),
        step_impacts=impacts, projected_health=_health(working),
    )


@router.post("/datasets/{dataset_id}/recipes/{recipe_id}/apply", response_model=CleanRecipeApplyResponse)
def apply_recipe(dataset_id: str, recipe_id: str, request: CleanRecipeApplyRequest) -> CleanRecipeApplyResponse:
    recipe = recipes.latest(recipe_id)
    if not any(step.enabled for step in recipe.steps):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="This recipe has no enabled steps to apply.")
    stored = overview_store.get(dataset_id)
    # Compute every enabled step before opening a publication transaction. A
    # failing later step names its place in the recipe without changing data.
    prepared: list[tuple[StoredDataset, StoredDataset, CleanTransformation, list[str]]] = []
    source = stored
    for index, step in enumerate(recipe.steps):
        if not step.enabled:
            continue
        try:
            frame, affected_rows, affected_columns, warnings, _ = _apply_operation(source.frame, step.request)
        except HTTPException as error:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail=f"Recipe step {index + 1} ({step.request.operation.value} on {step.request.column or 'the dataset'}) no longer matches this dataset's schema: {error.detail}") from error
        fingerprint = _fingerprint(frame)
        next_dataset = OverviewDataset(
            dataset_id=dataset_id, revision=source.dataset.revision + 1,
            source_name=source.dataset.source_name, source_fingerprint=fingerprint,
            row_count=len(frame), column_count=len(frame.columns),
        )
        next_source = StoredDataset(next_dataset, frame, fingerprint)
        parameters = step.request.model_dump(exclude={"operation", "column", "review_token"}, exclude_none=True)
        parameters.update({"recipe_id": recipe_id, "recipe_version": recipe.version, "recipe_step_index": index})
        transformation = CleanTransformation(
            transformation_id=f"clean_{uuid.uuid4().hex}", operation=step.request.operation,
            column=step.request.column, parameters=parameters,
            affected_rows=affected_rows, affected_columns=affected_columns,
            source_revision=source.dataset.revision, resulting_revision=next_dataset.revision,
            source_fingerprint=source.source_fingerprint, resulting_fingerprint=fingerprint,
            reversible=True, created_at=datetime.now(timezone.utc),
        )
        prepared.append((source, next_source, transformation, warnings))
        source = next_source

    reviews.consume(request.review_token, dataset_id, stored.dataset.revision,
                    stored.source_fingerprint, {"recipe_id": recipe_id, "recipe_version": recipe.version,
                                                "steps": [step.model_dump(mode="json") for step in recipe.steps]})

    dataset_store = cast(DurableDatasetStore, overview_store)
    durable_registry = cast(DurableAnalyticalObjectRegistry, registry)
    if durable_registry.engine is None or dataset_store.engine.url != durable_registry.engine.url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="Atomic recipe publication requires the dataset and provenance stores to share one durable database.")
    try:
        with dataset_store.engine.begin() as connection:
            head = connection.execute(
                select(_revisions).where(and_(_revisions.c.dataset_id == dataset_id, _revisions.c.is_active.is_(True)))
                .order_by(desc(_revisions.c.revision)).limit(1).with_for_update()
            ).mappings().first()
            if head is None or head["revision"] != stored.dataset.revision or head["source_fingerprint"] != stored.source_fingerprint:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="Dataset changed while this recipe was being prepared; preview the current revision again.")
            parent_ref = DatasetRef(dataset_id=dataset_id, revision=stored.dataset.revision,
                                    source_fingerprint=stored.source_fingerprint)
            parent_record = dataset_revision_record(parent_ref)
            durable_registry.register_with_connection(connection, parent_record, allow_existing=True)
            for before, after, transformation, warnings in prepared:
                existing = connection.execute(select(_revisions.c.dataset_id).where(and_(
                    _revisions.c.dataset_id == dataset_id, _revisions.c.revision == after.dataset.revision,
                    _revisions.c.source_fingerprint == after.source_fingerprint,
                ))).scalar_one_or_none()
                if existing is None:
                    connection.execute(insert(_revisions).values(
                        dataset_id=dataset_id, revision=after.dataset.revision,
                        source_fingerprint=after.source_fingerprint, source_name=after.dataset.source_name,
                        row_count=after.dataset.row_count, column_count=after.dataset.column_count,
                        frame_json=dataset_store._frame_json(after.frame), is_active=True,
                        activated_at=datetime.now(timezone.utc),
                    ))
                else:
                    connection.execute(update(_revisions).where(and_(
                        _revisions.c.dataset_id == dataset_id, _revisions.c.revision == after.dataset.revision,
                        _revisions.c.source_fingerprint == after.source_fingerprint,
                    )).values(is_active=True, activated_at=datetime.now(timezone.utc)))
                active = connection.execute(select(func.count()).select_from(_revisions).where(and_(
                    _revisions.c.dataset_id == dataset_id, _revisions.c.revision == after.dataset.revision,
                    _revisions.c.is_active.is_(True),
                ))).scalar_one()
                if active != 1:
                    raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                        detail="Another apply created this dataset revision; reload before retrying.")
                next_ref = DatasetRef(dataset_id=dataset_id, revision=after.dataset.revision,
                                      source_fingerprint=after.source_fingerprint)
                next_record = dataset_revision_record(next_ref, parent_record)
                durable_registry.register_with_connection(connection, next_record, allow_existing=True)
                clean_record = clean_transformation_record(before, transformation, warnings, parent_record)
                durable_registry.register_with_connection(connection, clean_record)
                parent_record = next_record
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                            detail="Recipe publication failed; no steps were applied. Retry after the storage error is resolved.") from error
    updated = overview_store.get(dataset_id)
    return CleanRecipeApplyResponse(dataset=updated.dataset, recipe_id=recipe_id, recipe_version=recipe.version,
                                    applied_steps=[item[2] for item in prepared],
                                    issues=detect_issues(updated.frame), health=_health(updated.frame))


@router.post("/datasets/{dataset_id}/undo", response_model=CleanStateResponse)
def undo(dataset_id: str, request: CleanUndoRequest) -> CleanStateResponse:
    overview_store.revert(dataset_id, request.to_revision)
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
        proposed = _issue_proposal(stored.frame, issue)
        return AtlasCleanResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=evidence, proposed_operation=proposed)
    if request.action is AtlasCleanAction.PROPOSE_FIX:
        if issue is None or issue.suggested_operation is None:
            return AtlasCleanResponse(action=request.action, summary="No deterministic safe fix is available for this issue; it needs analyst judgment.", uncertainty=uncertainty, evidence=[], proposed_operation=None)
        proposal = _issue_proposal(stored.frame, issue)
        if proposal is None:
            return AtlasCleanResponse(action=request.action, summary="No deterministic safe fix is available for this issue; it needs analyst judgment.", uncertainty=uncertainty, evidence=[], proposed_operation=None)
        return AtlasCleanResponse(
            action=request.action, summary=f"Proposed: {issue.suggested_operation.value.replace('_', ' ')} on {issue.column or 'the dataset'}. Preview it before applying — Atlas does not clean data without visibility.",
            uncertainty=uncertainty, evidence=[AtlasEvidence(label="Affected rows", value=f"{issue.affected_rows:,}")], proposed_operation=proposal,
        )
    history = _durable_history(dataset_id)
    summary = f"{len(history)} transformation(s) applied so far, from revision 0 to {stored.dataset.revision}." if history else "No transformations have been applied to this dataset yet."
    return AtlasCleanResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=[], proposed_operation=None)


def _issue_proposal(frame: pd.DataFrame, issue: CleanIssue) -> CleanTransformationRequest | None:
    if issue.suggested_operation is None:
        return None
    if issue.suggested_operation is CleanOperation.FILL_MISSING:
        if issue.column is None or frame[issue.column].dropna().empty:
            return None
        strategy = "median" if pd.api.types.is_numeric_dtype(frame[issue.column]) else "mode"
        return CleanTransformationRequest(operation=issue.suggested_operation, column=issue.column, fill_strategy=strategy)
    return CleanTransformationRequest(operation=issue.suggested_operation, column=issue.column)
