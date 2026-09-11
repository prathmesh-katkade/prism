"""Phase 9 persistence contract tests: no API process may own history."""

from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

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


def test_dataset_revision_selection_survives_equal_activation_times(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """MySQL DATETIME may give rapid upload/apply operations the same second."""
    configured = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", "")
    database_url = configured if configured.startswith("mysql") else f"sqlite:///{(tmp_path / 'tied-revisions.sqlite').as_posix()}"
    store = DurableDatasetStore(database_url)
    # Exercise the same tie against CI's real MySQL store as well as SQLite.
    activation = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        with patch("prism_api.durable_dataset_store.datetime") as clock:
            clock.now.return_value = activation
            original = store.put(pd.DataFrame({"value": [1, 1, 2]}), "tied.csv", "a" * 32)
            first = store.add_revision(original.dataset_id, pd.DataFrame({"value": [1, 2]}), "b" * 32)
            assert store.get(original.dataset_id).dataset == first
            second = store.add_revision(original.dataset_id, pd.DataFrame({"value": [2]}), "c" * 32)
            assert second.revision == 2
            assert store.get(original.dataset_id).dataset == second
            if not configured.startswith("mysql"):
                assert store.latest().dataset == second
            store.revert(original.dataset_id, 0)
            assert store.get(original.dataset_id).dataset == original
            reapplied = store.add_revision(original.dataset_id, pd.DataFrame({"value": [1, 2]}), "b" * 32)
            assert reapplied == first
            assert store.get(original.dataset_id).dataset == first
            assert [item.dataset.revision for item in store.revisions(original.dataset_id)] == [0, 1]
    finally:
        store.engine.dispose()


def test_concurrent_add_revision_never_allocates_the_same_revision_twice(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Two overlapping apply requests must serialize onto distinct revisions.

    Both transactions read the same "current" head and, without the row lock
    in add_revision, could both compute the same next revision number and
    both insert successfully (different fingerprints keep the composite
    primary key unique), silently producing two rows claiming to be the same
    revision and breaking the linear undo history."""
    configured = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", "")
    database_url = configured if configured.startswith("mysql") else f"sqlite:///{(tmp_path / 'concurrent-revisions.sqlite').as_posix()}"
    store = DurableDatasetStore(database_url)
    try:
        original = store.put(pd.DataFrame({"value": [1]}), "concurrent.csv", "a" * 32)

        results: list[object] = [None, None]
        errors: list[BaseException] = []

        def apply(index: int, fingerprint: str) -> None:
            try:
                results[index] = store.add_revision(original.dataset_id, pd.DataFrame({"value": [index]}), fingerprint)
            except BaseException as exc:  # noqa: BLE001 -- surfaced via `errors` for the assertion below
                errors.append(exc)

        threads = [
            threading.Thread(target=apply, args=(0, "b" * 32)),
            threading.Thread(target=apply, args=(1, "c" * 32)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert not errors, f"add_revision raised under concurrency: {errors}"
        revisions = [item.dataset.revision for item in store.revisions(original.dataset_id)]
        assert revisions == sorted(revisions), "revisions must stay ordered"
        assert len(revisions) == len(set(revisions)), f"no revision number may be allocated twice: {revisions}"
        assert sorted(r.revision for r in results) == [1, 2]  # type: ignore[attr-defined]
    finally:
        store.engine.dispose()
