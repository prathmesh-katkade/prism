"""Phase 9 persistence contract tests: no API process may own history."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pandas as pd
from prism_analytical_schemas import (
    AnalyticalObject,
    AnalyticalProvenance,
    DatasetRef,
    GenericReproducibilitySpec,
    LifecycleState,
    ObjectKind,
    ParentRef,
    Producer,
)
from prism_api.durable_dataset_store import DurableDatasetStore
from prism_api.durable_registry import DurableAnalyticalObjectRegistry


def _object(object_id: str, parents: list[ParentRef] | None = None) -> AnalyticalObject:
    return AnalyticalObject(
        object_id=object_id,
        kind=ObjectKind.ANALYSIS,
        lifecycle=LifecycleState.COMPLETED,
        provenance=AnalyticalProvenance(
            dataset=DatasetRef(dataset_id="dataset_1", revision=0, source_fingerprint="a" * 32),
            parent_refs=parents or [],
            reproducibility=GenericReproducibilitySpec(
                producer=Producer(service="test", version="1"), operation="test", parameters={"token": "must-redact"}
            ),
            created_at=datetime.now(timezone.utc),
        ),
        payload={"database_url": "mysql+pymysql://user:password@example.test/history"},
    )


def test_history_and_lineage_survive_registry_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}"
    writer = DurableAnalyticalObjectRegistry(database_url)
    writer.register(_object("root"))
    writer.register(_object("child", [ParentRef(object_id="root", relation="derived_from")]))

    recovered = DurableAnalyticalObjectRegistry(database_url)
    child = recovered.get("child")
    assert child is not None
    assert child.payload["database_url"] == "[redacted]"
    assert [item.object_id for item in recovered.get_parents("child") or []] == ["root"]
    traversal = recovered.ancestors("child")
    assert traversal is not None
    assert [item.object_id for item, _depth in traversal.nodes] == ["root"]


def test_registration_is_idempotent_at_the_database_primary_key(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = DurableAnalyticalObjectRegistry(f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}")
    record = _object("once")
    assert registry.ensure(record).object_id == "once"
    assert registry.ensure(record).object_id == "once"
    assert [item.object_id for item in registry.list_for_dataset("dataset_1")] == ["once"]


def test_creation_audit_survives_restart_without_storing_secrets(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}"
    DurableAnalyticalObjectRegistry(database_url).register(_object("audited"))

    events = DurableAnalyticalObjectRegistry(database_url).list_audit_events("audited")
    assert len(events) == 1
    assert events[0]["event_type"] == "created"
    assert events[0]["actor"] == "system"
    assert events[0]["producer_service"] == "test"
    assert "password" not in str(events[0]).lower()


def test_configured_mysql_history_survives_registry_restart() -> None:
    """Phase 4 CI sets the managed-store URL; normal unit runs remain self-contained."""
    database_url = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL")
    if not database_url or not database_url.startswith("mysql"):
        return
    object_id = f"mysql_restart_{uuid.uuid4().hex}"
    DurableAnalyticalObjectRegistry(database_url).register(_object(object_id))
    assert DurableAnalyticalObjectRegistry(database_url).get(object_id) is not None


def test_dataset_revisions_survive_restart_and_revert_keeps_branch_safety(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}"
    writer = DurableDatasetStore(database_url)
    created = writer.put(pd.DataFrame({"value": [1, 2]}), "sample.csv", "a" * 32)
    writer.add_revision(created.dataset_id, pd.DataFrame({"value": [3]}), "b" * 32)

    recovered = DurableDatasetStore(database_url)
    assert recovered.get(created.dataset_id).frame["value"].tolist() == [3]
    recovered.revert(created.dataset_id, 0)
    assert recovered.get(created.dataset_id).source_fingerprint == "a" * 32
    assert [item.dataset.revision for item in recovered.revisions(created.dataset_id)] == [0]
