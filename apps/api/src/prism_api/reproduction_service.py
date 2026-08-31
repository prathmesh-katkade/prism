"""Phase 8F: safe reproduction/rerun of an analytical object's original configuration.

A rerun never overwrites history: it always creates a brand-new ``AnalyticalObject``
by calling the exact same producer logic (the ``execute_*`` helpers extracted from
each route module for this purpose) the original run used, targeting either the
object's own original dataset identity (``same_revision``) or DatasetStore's current
active identity (``current_revision``). The original object is only ever read here,
never mutated, and its own object id, provenance, parameters, evidence, and timestamp
are untouched by a rerun's outcome either way.

The server derives every configuration value (columns, target, test, horizon, ...)
from the original object's own recorded ``provenance.reproducibility`` - a rerun
request supplies only ``object_id`` and ``mode``, never an analytical payload of its
own, so a client cannot smuggle in different parameters under the "rerun" label.
"""

from __future__ import annotations

from typing import List, Optional, cast

from fastapi import HTTPException
from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalObjectRegistry,
    ObjectKind,
    ReproductionMode,
    ReproductionOutcome,
    ReproductionResponse,
)
from prism_api_contracts import (
    ForecastRequest,
    MlBaselineRequest,
    MlFeatureSelectionRequest,
    MlShapRequest,
    StatTestKind,
    StatTestRequest,
    VisualizationSpec,
)

from . import forecasting, mllab, visualize
from .analytical_objects import register_visualization
from .analytical_objects import registry as object_registry
from .overview import DatasetStore, StoredDataset

_SUPPORTED_KINDS = {ObjectKind.ANALYSIS, ObjectKind.FORECAST, ObjectKind.ML_MODEL, ObjectKind.VISUALIZATION}

_UNSUPPORTED_REASONS = {
    ObjectKind.DATASET_REVISION: "A dataset-revision object is a data identity record, not an analytical result - there is nothing to rerun.",
    ObjectKind.CLEANING_PLAN: "Clean transformations already have their own deterministic apply/undo mechanism; use Clean's apply action again rather than a generic rerun.",
    ObjectKind.QUERY_RESULT: "SQL Lab runs execute asynchronously (submit, then poll); the synchronous rerun endpoint does not support that flow in this phase.",
    ObjectKind.PROFILE: "A profile is a read-only snapshot, not a rerunnable analytical action.",
    ObjectKind.EVIDENCE: "AI Analyst evidence involves a provider call outside deterministic rerun scope in this phase.",
}


def _resolve_stored(
    overview_store: DatasetStore, dataset_id: str, mode: ReproductionMode, target_revision: int, target_fingerprint: str
) -> Optional[StoredDataset]:
    if mode is ReproductionMode.CURRENT_REVISION:
        try:
            return overview_store.get(dataset_id)
        except HTTPException:
            return None
    # SAME_REVISION: must match the *exact* (revision, fingerprint) identity originally
    # used - never revision number alone. DatasetStore.revert can truncate history to
    # before that revision, or (after undo + a different redo) leave a same-numbered but
    # different-fingerprint revision as the only one present - both are correctly reported
    # as "unavailable" rather than silently rerun against the wrong data.
    try:
        history = overview_store.revisions(dataset_id)
    except HTTPException:
        return None
    return next((item for item in history if item.dataset.revision == target_revision and item.source_fingerprint == target_fingerprint), None)


def _require_columns_present(stored: StoredDataset, columns: List[str]) -> Optional[str]:
    missing = [column for column in columns if column not in stored.frame.columns]
    if missing:
        return f"Column(s) {', '.join(repr(c) for c in missing)} no longer exist in this dataset revision."
    return None


def _reconstruct_stats_request(record: AnalyticalObject) -> StatTestRequest:
    spec = record.provenance.reproducibility
    params = spec.parameters
    test = StatTestKind(spec.test)
    if "numeric_col" in params and "cat_col" in params:
        return StatTestRequest(test=test, col_a=params["numeric_col"], col_b=params["cat_col"], numeric_col=params["numeric_col"], cat_col=params["cat_col"])
    return StatTestRequest(test=test, col_a=params["col_a"], col_b=params["col_b"])


def reproduce(
    registry: AnalyticalObjectRegistry, overview_store: DatasetStore, object_id: str, mode: ReproductionMode
) -> Optional[ReproductionResponse]:
    """``None`` means ``object_id`` itself is not registered (caller -> 404)."""
    record = registry.get(object_id)
    if record is None:
        return None

    if record.kind not in _SUPPORTED_KINDS:
        reason = _UNSUPPORTED_REASONS.get(record.kind, f"Rerun is not supported for {record.kind.value} objects.")
        return ReproductionResponse(outcome=ReproductionOutcome.UNSUPPORTED, original_object_id=object_id, mode=mode, detail=reason)

    ref = record.provenance.dataset
    stored = _resolve_stored(overview_store, ref.dataset_id, mode, ref.revision, ref.source_fingerprint)
    if stored is None:
        detail = (
            f"The active dataset state for {ref.dataset_id!r} could not be resolved."
            if mode is ReproductionMode.CURRENT_REVISION
            else (
                f"Revision {ref.revision} with the original fingerprint is no longer available in this "
                "process's history (it may have been superseded by an undo/redo branch, or this process restarted)."
            )
        )
        return ReproductionResponse(outcome=ReproductionOutcome.SOURCE_REVISION_UNAVAILABLE, original_object_id=object_id, mode=mode, detail=detail)

    try:
        new_object = _dispatch(record, stored)
    except HTTPException as error:
        return ReproductionResponse(outcome=ReproductionOutcome.VALIDATION_FAILED, original_object_id=object_id, mode=mode, detail=str(error.detail))
    except (KeyError, ValueError) as error:
        return ReproductionResponse(outcome=ReproductionOutcome.VALIDATION_FAILED, original_object_id=object_id, mode=mode, detail=str(error))

    return ReproductionResponse(
        outcome=ReproductionOutcome.CREATED, original_object_id=object_id, mode=mode, new_object=new_object,
        detail=f"Reproduced as a new {new_object.kind.value} object ({new_object.object_id}); the original object is unchanged.",
    )


def _newest_of_kind(stored: StoredDataset, kind: ObjectKind) -> AnalyticalObject:
    """Every branch below registers via the same producer function the original run
    used; the object it just created is the newest one for this exact dataset
    identity and kind (every producer stamps `created_at` at call time)."""
    return object_registry.list_for_dataset(stored.dataset.dataset_id, revision=stored.dataset.revision, kind=kind)[0]


def _dispatch(record: AnalyticalObject, stored: StoredDataset) -> AnalyticalObject:
    spec = record.provenance.reproducibility
    params = spec.parameters

    if record.kind is ObjectKind.ANALYSIS:
        request = _reconstruct_stats_request(record)
        missing = _require_columns_present(stored, [request.col_a, request.col_b])
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        from . import stats as stats_module

        stats_module.run_test(stored, request)
    elif record.kind is ObjectKind.FORECAST:
        forecast_request = ForecastRequest(datetime_col=params["datetime_col"], numeric_col=params["numeric_col"], horizon=params["horizon"])
        missing = _require_columns_present(stored, [forecast_request.datetime_col, forecast_request.numeric_col])
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        forecasting.execute_forecast(stored, forecast_request)
    elif record.kind is ObjectKind.ML_MODEL:
        operation = spec.operation
        feature_cols = cast(List[str], params["feature_cols"])
        target_col = cast(str, params["target_col"])
        task_type = params.get("task_type")
        missing = _require_columns_present(stored, [*feature_cols, target_col])
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        if operation == "baseline":
            mllab.execute_baseline(stored, MlBaselineRequest(feature_cols=feature_cols, target_col=target_col, task_type=task_type, use_smote=params.get("use_smote", False)))
        elif operation == "feature_selection":
            mllab.execute_feature_selection(stored, MlFeatureSelectionRequest(feature_cols=feature_cols, target_col=target_col, task_type=task_type, top_k=params.get("top_k")))
        elif operation == "shap":
            mllab.execute_shap(stored, MlShapRequest(feature_cols=feature_cols, target_col=target_col, task_type=task_type))
        else:
            raise ValueError(f"Unrecognized ML operation {operation!r} in recorded provenance.")
    elif record.kind is ObjectKind.VISUALIZATION:
        spec_obj = VisualizationSpec(
            mark=params["mark"], intent=params["intent"], dimension=params.get("dimension"), measure=params.get("measure"),
            aggregation=params["aggregation"], filters=params.get("filters") or {}, max_categories=params.get("max_categories", 20),
        )
        missing = _require_columns_present(stored, [column for column in (spec_obj.dimension, spec_obj.measure) if column])
        if missing:
            raise HTTPException(status_code=422, detail=missing)
        data, truncated, warnings = visualize._aggregate(stored.frame, spec_obj)  # noqa: SLF001 - reusing the route's own pure computation, not duplicating it
        del data
        register_visualization(stored, spec_obj, truncated, warnings)
    else:  # pragma: no cover - guarded by _SUPPORTED_KINDS above
        raise ValueError(f"Unreachable: {record.kind} is not in _SUPPORTED_KINDS.")

    return _newest_of_kind(stored, record.kind)
