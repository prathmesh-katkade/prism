"""Phase 8A adapters from native workflows to canonical analytical records."""

from __future__ import annotations

import uuid
from typing import Any, List

from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalObjectRegistry,
    AnalyticalProvenance,
    CleaningReproducibilitySpec,
    DatasetRef,
    EvidenceRef,
    LifecycleState,
    ObjectKind,
    Producer,
    StatisticalTestReproducibilitySpec,
)
from prism_api_contracts import CleanTransformation, StatTestResult
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION

from .overview import StoredDataset

registry = AnalyticalObjectRegistry()


def _dataset_ref(stored: StoredDataset) -> DatasetRef:
    return DatasetRef(
        dataset_id=stored.dataset.dataset_id,
        revision=stored.dataset.revision,
        source_fingerprint=stored.source_fingerprint,
    )


def register_statistical_test(
    stored: StoredDataset,
    result: StatTestResult,
    columns: List[str],
) -> AnalyticalObject:
    """Record a completed deterministic Stats computation without changing its API shape."""
    producer = Producer(service="stats", version=result.provenance.service_version)
    parameters: dict[str, Any] = dict(result.provenance.parameters)
    record = AnalyticalObject(
        object_id=f"stats_{uuid.uuid4().hex}",
        kind=ObjectKind.ANALYSIS,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=_dataset_ref(stored),
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
                columns=columns,
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
    """Record a completed Clean action after DatasetStore appends its new revision."""
    producer = Producer(service="clean", version=ANALYTICS_SERVICE_VERSION)
    record = AnalyticalObject(
        object_id=f"clean_{transformation.transformation_id}",
        kind=ObjectKind.CLEANING_PLAN,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=DatasetRef(
                dataset_id=source.dataset.dataset_id,
                revision=transformation.resulting_revision,
                source_fingerprint=transformation.resulting_fingerprint,
            ),
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
                parameters=transformation.parameters,
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
