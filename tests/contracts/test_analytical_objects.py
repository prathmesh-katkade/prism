from datetime import datetime, timezone
from typing import List, Optional

import pytest
from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalObjectRegistry,
    AnalyticalProvenance,
    DatasetRef,
    GenericReproducibilitySpec,
    LifecycleState,
    ObjectKind,
    ParentRef,
    Producer,
    sanitize_provenance_parameters,
)


def _record(object_id: str = "analysis_1", parents: Optional[List[ParentRef]] = None) -> AnalyticalObject:
    return AnalyticalObject(
        object_id=object_id,
        kind=ObjectKind.ANALYSIS,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=DatasetRef(dataset_id="ds_test", revision=2, source_fingerprint="a" * 64),
            parent_refs=parents or [],
            reproducibility=GenericReproducibilitySpec(
                producer=Producer(service="test", version="1.0"), operation="test"
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={"result": "original"},
    )


def test_provenance_parameters_are_json_safe_and_redact_secrets_recursively() -> None:
    sanitized = sanitize_provenance_parameters(
        {
            "password": "do-not-store",
            "nested": {"api_key": "also-not-stored", "safe": "kept"},
            "connection": "postgresql://analyst:do-not-store@db.example/prism",
        }
    )

    assert sanitized["password"] == "[redacted]"
    assert sanitized["nested"] == {"api_key": "[redacted]", "safe": "kept"}
    assert sanitized["connection"] == "[redacted]"


def test_registry_rejects_duplicate_and_self_parent_and_preserves_history() -> None:
    registry = AnalyticalObjectRegistry()
    registered = registry.register(_record())
    registered.payload["result"] = "mutated by caller"

    historical = registry.get("analysis_1")
    assert historical is not None
    assert historical.payload["result"] == "original"
    assert registry.exists("analysis_1")
    assert [item.object_id for item in registry.list_for_dataset("ds_test", revision=2)] == ["analysis_1"]

    with pytest.raises(ValueError, match="already registered"):
        registry.register(_record())
    with pytest.raises(ValueError, match="cannot reference itself"):
        registry.register(_record("self_parent", [ParentRef(object_id="self_parent")]))
