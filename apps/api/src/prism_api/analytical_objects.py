"""Phase 8A/8B adapters from native workflows to canonical analytical records."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional, cast

from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalObjectRegistry,
    AnalyticalProvenance,
    CleaningReproducibilitySpec,
    DatasetRef,
    EvidenceRef,
    GenericReproducibilitySpec,
    LifecycleState,
    ObjectKind,
    ParentRef,
    Producer,
    StatisticalTestReproducibilitySpec,
)
from prism_api_contracts import (
    AiAnalystRequest,
    AiAnalystResponse,
    CleanTransformation,
    ForecastRequest,
    ForecastResult,
    SqlRunRequest,
    SqlRunResponse,
    StatTestResult,
    VisualizationSpec,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION

from .durable_registry import create_history_registry
from .overview import StoredDataset

registry: AnalyticalObjectRegistry = cast(AnalyticalObjectRegistry, create_history_registry())


def _dataset_ref(stored: StoredDataset) -> DatasetRef:
    return DatasetRef(
        dataset_id=stored.dataset.dataset_id,
        revision=stored.dataset.revision,
        source_fingerprint=stored.source_fingerprint,
    )


def _dataset_revision_object_id(ref: DatasetRef) -> str:
    """Keyed on the full (dataset_id, revision, source_fingerprint) identity, not just
    (dataset_id, revision).

    ``DatasetStore.revert`` truncates history to an earlier revision and a later
    transformation then reuses that same revision *number* for a genuinely different
    piece of data (see ``DatasetStore.add_revision``/``revert``) - the revision number
    alone is not a stable identity across an undo-then-redo-differently sequence. The
    fingerprint is what actually distinguishes the two branches, so it is part of the
    object id: registering the second branch's revision creates a new object rather than
    silently returning the first branch's (now-abandoned) one.
    """
    return f"dsrev_{ref.dataset_id}_r{ref.revision}_{ref.source_fingerprint[:16]}"


def ensure_dataset_revision(ref: DatasetRef, parent: Optional[AnalyticalObject] = None) -> AnalyticalObject:
    """Idempotently mirror one DatasetStore dataset/revision/fingerprint identity into the
    registry.

    DatasetStore remains the sole revision authority (rule: "exactly one canonical
    analytical object for a given DatasetStore revision identity"); this only registers a
    durable record for it the first time any producer needs to reference it, and returns
    the existing record on every later call for the same identity - callers never need to
    check "does this exist yet" themselves. ``parent`` is only ever meaningful from
    ``register_clean_transformation`` (the one place that actually creates a new
    revision, and so is the only place that actually knows the correct predecessor);
    every other producer calls this with no ``parent`` for a revision it only reads -
    that revision's dataset-revision object, if it is not revision 0, was necessarily
    already registered (with its correct parent) by whichever Clean call produced it,
    since DatasetStore revisions are only ever created that way.

    Registration itself is race-safe: if two requests are the first concurrent producers
    to touch the same identity, both may see it absent and both call ``registry.register``;
    the loser's ``ValueError`` (duplicate id) is caught here and resolved by returning the
    winner's own already-registered record, rather than surfacing as a 500 on top of an
    otherwise-successful computation.
    """
    object_id = _dataset_revision_object_id(ref)
    existing = registry.get(object_id)
    if existing is not None:
        return existing
    parent_refs = [ParentRef(object_id=parent.object_id, relation="revision_of")] if parent is not None else []
    record = AnalyticalObject(
        object_id=object_id,
        kind=ObjectKind.DATASET_REVISION,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=parent_refs,
            reproducibility=GenericReproducibilitySpec(
                producer=Producer(service="dataset-store", version=ANALYTICS_SERVICE_VERSION),
                operation="ingest" if ref.revision == 0 else "revision",
                parameters={"revision": ref.revision},
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={},
    )
    try:
        return registry.register(record)
    except ValueError:
        winner = registry.get(object_id)
        if winner is None:
            raise  # a genuinely different failure (e.g. self-parent) - do not mask it
        return winner


def _derived_from(stored: StoredDataset) -> tuple[DatasetRef, list[ParentRef]]:
    """The current revision's ref plus a direct-parent link to its dataset-revision object.

    Shared by every producer that reads an existing revision without creating a new one
    (Stats, SQL Lab, Visualize, Forecasting, ML Lab, AI Analyst) - they never infer parent
    relationships themselves, only point at the one DatasetStore identity they actually ran
    against.
    """
    ref = _dataset_ref(stored)
    dataset_revision = ensure_dataset_revision(ref)
    return ref, [ParentRef(object_id=dataset_revision.object_id, relation="derived_from")]


def register_statistical_test(
    stored: StoredDataset,
    result: StatTestResult,
) -> AnalyticalObject:
    """Record a completed deterministic Stats computation without changing its API shape."""
    producer = Producer(service="stats", version=result.provenance.service_version)
    parameters: dict[str, Any] = dict(result.provenance.parameters)
    column_keys = (
        ("numeric_col", "cat_col")
        if "numeric_col" in parameters and "cat_col" in parameters
        else ("col_a", "col_b")
    )
    columns = [parameters.get(key) for key in column_keys]
    if not all(isinstance(column, str) and column for column in columns):
        raise ValueError("Statistical result provenance must identify the columns actually tested.")
    ref, parent_refs = _derived_from(stored)
    record = AnalyticalObject(
        object_id=f"stats_{uuid.uuid4().hex}",
        kind=ObjectKind.ANALYSIS,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=parent_refs,
            warnings=list(result.warnings),
            evidence_refs=[
                EvidenceRef(
                    evidence_id=f"stat:{result.test.value}",
                    kind="statistical_test",
                    summary=result.evidence_statement,
                )
            ],
            reproducibility=StatisticalTestReproducibilitySpec(
                producer=producer,
                test=result.test.value,
                columns=[str(column) for column in columns],
                parameters=parameters,
            ),
            created_at=result.provenance.computed_at,
        ),
        payload={
            "test": result.test.value,
            "statistic": result.statistic,
            "p_value": result.p_value,
            "significant": result.significant,
        },
    )
    return registry.register(record)


def register_clean_transformation(
    source: StoredDataset,
    transformation: CleanTransformation,
    warnings: List[str],
) -> AnalyticalObject:
    """Record a completed Clean action after DatasetStore appends its new revision.

    Ensures both the source revision it read and the resulting revision it created have
    their own dataset-revision objects (so the chain is never missing a link regardless of
    which revision a dataset's history first gets touched at), then points this Clean
    object's own direct parent at the source it actually transformed - never the revision
    it produced, since that didn't exist yet when the transformation ran.
    """
    producer = Producer(service="clean", version=ANALYTICS_SERVICE_VERSION)
    source_dataset_revision = ensure_dataset_revision(_dataset_ref(source))
    resulting_ref = DatasetRef(
        dataset_id=source.dataset.dataset_id,
        revision=transformation.resulting_revision,
        source_fingerprint=transformation.resulting_fingerprint,
    )
    ensure_dataset_revision(resulting_ref, parent=source_dataset_revision)
    record = AnalyticalObject(
        object_id=f"clean_{transformation.transformation_id}",
        kind=ObjectKind.CLEANING_PLAN,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=resulting_ref,
            parent_refs=[ParentRef(object_id=source_dataset_revision.object_id, relation="derived_from")],
            warnings=warnings,
            evidence_refs=[
                EvidenceRef(
                    evidence_id=transformation.transformation_id,
                    kind="clean_transformation",
                    summary=f"{transformation.operation.value} from revision {transformation.source_revision}",
                )
            ],
            reproducibility=CleaningReproducibilitySpec(
                producer=producer,
                operation=transformation.operation.value,
                parameters={
                    **transformation.parameters,
                    "column": transformation.column,
                    "affected_columns": transformation.affected_columns,
                },
            ),
            created_at=transformation.created_at,
        ),
        payload={
            "affected_rows": transformation.affected_rows,
            "reversible": transformation.reversible,
            "source_revision": transformation.source_revision,
        },
    )
    return registry.register(record)


def register_query_result(
    stored: StoredDataset,
    request: SqlRunRequest,
    response: SqlRunResponse,
) -> AnalyticalObject:
    """Record a completed native SQL Lab run against the local in-memory dataset connection.

    A run against a configured SQLite/external database source has no DatasetStore revision
    to attach to and is deliberately not registered here - it would need its own, differently
    shaped provenance identity, out of scope for this pass. ``response.sql`` and
    ``response.provenance`` never carry a connection string or credential for the local
    connection this registers (see ``_local_connection``/``_safe_parameters`` in sql_lab.py);
    the reproducibility parameters below still pass through the standard redaction as
    defense in depth.
    """
    producer = Producer(service="sql-lab", version=response.provenance.service_version)
    ref, parent_refs = _derived_from(stored)
    record = AnalyticalObject(
        object_id=f"sql_{response.run_id}",
        kind=ObjectKind.QUERY_RESULT,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=parent_refs,
            warnings=list(response.warnings),
            reproducibility=GenericReproducibilitySpec(
                producer=producer,
                operation="sql_query",
                parameters={
                    "sql": response.sql,
                    "dialect": response.provenance.dialect.value,
                    "connection_id": response.provenance.connection_id,
                    "parameters": response.provenance.parameters,
                },
            ),
            created_at=response.provenance.executed_at,
        ),
        payload={
            "row_count": response.row_count,
            "returned_row_count": response.returned_row_count,
            "truncated": response.truncated,
        },
    )
    return registry.register(record)


def register_visualization(
    stored: StoredDataset,
    spec: VisualizationSpec,
    truncated: bool,
    warnings: List[str],
) -> AnalyticalObject:
    """Record a completed chart render as its deterministic spec, not a rendered payload -
    the spec alone is sufficient to reproduce the exact same chart from the same revision."""
    producer = Producer(service="visualize", version=ANALYTICS_SERVICE_VERSION)
    ref, parent_refs = _derived_from(stored)
    record = AnalyticalObject(
        object_id=f"viz_{uuid.uuid4().hex}",
        kind=ObjectKind.VISUALIZATION,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=parent_refs,
            warnings=list(warnings),
            reproducibility=GenericReproducibilitySpec(
                producer=producer,
                operation="visualize",
                parameters={
                    "mark": spec.mark.value,
                    "intent": spec.intent.value,
                    "dimension": spec.dimension,
                    "measure": spec.measure,
                    "aggregation": spec.aggregation.value,
                    "filters": spec.filters,
                    "max_categories": spec.max_categories,
                },
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={"truncated": truncated},
    )
    return registry.register(record)


def register_forecast(
    stored: StoredDataset,
    request: ForecastRequest,
    result: ForecastResult,
) -> AnalyticalObject:
    """Record a completed forecast run - its deterministic configuration and headline
    metrics only, never the fitted statsmodels object that produced it."""
    producer = Producer(service="forecasting", version=ANALYTICS_SERVICE_VERSION)
    ref, parent_refs = _derived_from(stored)
    record = AnalyticalObject(
        object_id=f"forecast_{uuid.uuid4().hex}",
        kind=ObjectKind.FORECAST,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=parent_refs,
            warnings=list(result.warnings),
            reproducibility=GenericReproducibilitySpec(
                producer=producer,
                operation="forecast",
                parameters={
                    "datetime_col": request.datetime_col,
                    "numeric_col": request.numeric_col,
                    "horizon": request.horizon,
                    "frequency": result.frequency,
                    "model_used": result.model_used,
                },
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={"model_used": result.model_used, "horizon": result.horizon},
    )
    return registry.register(record)


def register_ml_result(
    stored: StoredDataset,
    operation: str,
    parameters: dict[str, Any],
    warnings: Optional[List[str]] = None,
) -> AnalyticalObject:
    """Record one completed ML Lab analysis (baseline / feature_selection / shap).

    Each call site supplies only the reproducibility-relevant configuration for that
    specific operation (target/features/task type/seed/split/method); no fitted estimator,
    transformed feature matrix, or raw SHAP array is ever passed in here - mllab.py's own
    response models are already metrics/rankings/importances only (rule 46), so there is
    nothing unserializable for this adapter to accidentally leak.
    """
    producer = Producer(service="mllab", version=ANALYTICS_SERVICE_VERSION)
    ref, parent_refs = _derived_from(stored)
    record = AnalyticalObject(
        object_id=f"ml_{operation}_{uuid.uuid4().hex}",
        kind=ObjectKind.ML_MODEL,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=parent_refs,
            warnings=list(warnings or []),
            reproducibility=GenericReproducibilitySpec(
                producer=producer,
                operation=operation,
                parameters=parameters,
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={},
    )
    return registry.register(record)


def register_ai_evidence(
    dataset_id: str,
    revision: int,
    source_fingerprint: str,
    request: AiAnalystRequest,
    response: AiAnalystResponse,
) -> AnalyticalObject:
    """Record one completed, evidence-grounded AI Analyst answer.

    Only called for ``AiAnalystOutcome.ANSWERED`` (see the call site in ai_analyst.py) -
    a causal-limit refusal and an unexecuted SQL draft neither carry a completed evidence
    packet worth preserving, so nothing is registered for those outcomes. No chain-of-thought
    or hidden reasoning exists in this response shape to begin with (the deterministic and
    Ollama-routing paths never produce or expose one); ``request.question`` is free user text
    and still passes through the standard secret redaction as defense in depth.
    """
    ref = DatasetRef(dataset_id=dataset_id, revision=revision, source_fingerprint=source_fingerprint)
    dataset_revision = ensure_dataset_revision(ref)
    producer = Producer(service="ai-analyst", version=response.context.config_version)
    record = AnalyticalObject(
        object_id=f"aievidence_{response.request_id}",
        kind=ObjectKind.EVIDENCE,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=ref,
            parent_refs=[ParentRef(object_id=dataset_revision.object_id, relation="derived_from")],
            warnings=list(response.limiting_factors),
            evidence_refs=[
                EvidenceRef(evidence_id=item.provenance_ref, kind=item.kind, summary=item.value[:500])
                for item in response.evidence
            ],
            reproducibility=GenericReproducibilitySpec(
                producer=producer,
                operation="ai_analyst_answer",
                parameters={
                    "question": request.question,
                    "provider": response.provider.value,
                    "outcome": response.outcome.value,
                    "prompt_version": response.context.prompt_version,
                },
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={
            "answer": response.answer,
            "uncertainty": response.uncertainty,
            "recommended_next_step": response.recommended_next_step,
        },
    )
    return registry.register(record)
