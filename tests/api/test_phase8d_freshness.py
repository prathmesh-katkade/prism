"""Phase 8D: contextual freshness/staleness assessment - current/stale/superseded/
unknown, computed live against DatasetStore's active identity, never stored on
the (immutable) analytical object itself.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from prism_analytical_schemas import ObjectKind
from prism_api.analytical_objects import registry
from prism_api.main import create_app


def _dataset(client: TestClient, csv: bytes = b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", name: str = "phase8d.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _dsrev(dataset_id: str, revision: int):
    return registry.list_for_dataset(dataset_id, revision=revision, kind=ObjectKind.DATASET_REVISION)[0]


def test_analysis_on_the_active_revision_is_current() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/freshness")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "current"
    assert body["freshness_known"] is True
    assert body["active_revision"] == 0


def test_analysis_on_a_prior_revision_is_stale_after_a_clean_apply() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    apply_response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert apply_response.status_code == 201

    response = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/freshness")
    body = response.json()
    assert body["state"] == "stale"
    assert body["object_revision"] == 0
    assert body["active_revision"] == 1
    assert body["reason_code"] == "upstream_revision_changed"
    assert "revision 1" in body["reason"]


def test_multiple_descendants_go_stale_together() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    client.post(
        f"/api/v1/visualize/datasets/{dataset_id}/render",
        json={"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "y", "aggregation": "sum", "filters": {}, "max_categories": 20},
    )
    revision0_objects = [r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind in (ObjectKind.ANALYSIS, ObjectKind.VISUALIZATION)]
    assert len(revision0_objects) == 2

    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    for record in revision0_objects:
        body = client.get(f"/api/v1/lineage/objects/{record.object_id}/freshness").json()
        assert body["state"] == "stale"


def test_dataset_revision_object_is_superseded_not_stale() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision0 = _dsrev(dataset_id, 0)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    response = client.get(f"/api/v1/lineage/objects/{revision0.object_id}/freshness")
    body = response.json()
    assert body["state"] == "superseded"
    assert body["reason_code"] == "revision_superseded"
    assert "1 recorded object" in body["reason"] or "recorded object" in body["reason"]


def test_current_dataset_revision_object_is_current() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision0 = _dsrev(dataset_id, 0)

    body = client.get(f"/api/v1/lineage/objects/{revision0.object_id}/freshness").json()
    assert body["state"] == "current"


def test_analysis_intentionally_run_on_an_old_revision_is_immediately_stale() -> None:
    """DatasetStore's `get()` always resolves the active revision, so a producer can
    only ever register against the currently-active identity - there is no code path
    for "intentionally analyze an old revision" other than reverting to it first,
    which makes it active again. This test proves that once superseded, the effect
    is immediate: no lag, no separate propagation step required."""
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_on_r1 = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.ANALYSIS)

    # Still active - current.
    assert client.get(f"/api/v1/lineage/objects/{stats_on_r1.object_id}/freshness").json()["state"] == "current"

    # A further revision immediately (not eventually) makes it stale.
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    assert client.get(f"/api/v1/lineage/objects/{stats_on_r1.object_id}/freshness").json()["state"] == "stale"


def test_undo_revert_with_reused_revision_number_is_fingerprint_safe() -> None:
    """The Phase 8B revert/redo disambiguation extends correctly into freshness:
    an object tied to an abandoned branch's fingerprint must never read as current
    just because a different branch now occupies the same revision number."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"x,y\n1,2\n1,2\n,4\n")

    first = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert first.status_code == 201
    branch_a = next(r for r in registry.list_for_dataset(dataset_id, revision=1) if r.kind is ObjectKind.CLEANING_PLAN)

    client.post(f"/api/v1/clean/datasets/{dataset_id}/undo", json={"to_revision": 0})
    second = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    assert second.status_code == 201

    # branch_a's own clean-transformation object still points at revision 1, but a
    # *different* fingerprint is now active at revision 1 - branch_a must read stale,
    # never current, even though the revision number alone matches.
    body = client.get(f"/api/v1/lineage/objects/{branch_a.object_id}/freshness").json()
    assert body["state"] == "stale"
    assert body["object_revision"] == 1
    assert body["active_revision"] == 1


def test_partial_lineage_after_registry_reset_is_unknown_not_current_or_stale() -> None:
    """Models the process-local partial-history case: the registry (and a fresh
    DatasetStore standing in for one that no longer knows this dataset_id) has an
    object whose dataset_id was never re-established after a restart."""
    from datetime import datetime, timezone

    from prism_analytical_schemas import (
        AnalyticalObject,
        AnalyticalProvenance,
        DatasetRef,
        GenericReproducibilitySpec,
        LifecycleState,
        Producer,
    )
    from prism_api import freshness_service
    from prism_api.overview import DatasetStore

    local_registry = registry.__class__()
    local_registry.register(
        AnalyticalObject(
            object_id="orphan_analysis",
            kind=ObjectKind.ANALYSIS,
            lifecycle=LifecycleState.COMPLETED,
            provenance=AnalyticalProvenance(
                dataset=DatasetRef(dataset_id="ds_gone_after_restart", revision=3, source_fingerprint="a" * 64),
                reproducibility=GenericReproducibilitySpec(producer=Producer(service="test", version="1"), operation="test"),
                created_at=datetime.now(timezone.utc),
            ),
            payload={},
        )
    )
    empty_store = DatasetStore()  # never saw ds_gone_after_restart

    result = freshness_service.assess_object(local_registry, empty_store, "orphan_analysis")
    assert result is not None
    assert result.state == "unknown"
    assert result.freshness_known is False
    assert result.active_revision is None


def test_8c_traversal_is_unaffected_by_8d() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision0 = _dsrev(dataset_id, 0)

    assert client.get(f"/api/v1/lineage/objects/{revision0.object_id}/descendants").status_code == 200
    assert client.get(f"/api/v1/lineage/objects/{revision0.object_id}/children").status_code == 200


def test_freshness_endpoint_404s_for_an_unknown_object() -> None:
    client = TestClient(create_app())
    assert client.get("/api/v1/lineage/objects/does-not-exist/freshness").status_code == 404


def test_dataset_freshness_returns_every_registered_object_and_never_404s() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})

    response = client.get(f"/api/v1/lineage/datasets/{dataset_id}/freshness")
    assert response.status_code == 200
    states = {item["state"] for item in response.json()}
    assert "current" in states

    empty = client.get("/api/v1/lineage/datasets/ds_never_touched/freshness")
    assert empty.status_code == 200
    assert empty.json() == []


def test_no_secret_leakage_through_freshness_endpoint() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={
            "connection_id": f"local:{dataset_id}",
            "sql": "SELECT * FROM data WHERE segment = $api_key",
            "parameters": {"api_key": "sk-should-not-leak-c"},
        },
    )
    import time

    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{submitted.json()['run_id']}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    assert run["state"] == "succeeded"
    sql_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]

    freshness_body = client.get(f"/api/v1/lineage/objects/{sql_record.object_id}/freshness").text
    assert "sk-should-not-leak" not in freshness_body


def test_freshness_assessment_stays_fast_at_synthetic_scale() -> None:
    import time
    from datetime import datetime, timezone

    import pandas as pd
    from prism_analytical_schemas import (
        AnalyticalObject,
        AnalyticalProvenance,
        DatasetRef,
        GenericReproducibilitySpec,
        LifecycleState,
        Producer,
    )
    from prism_api import freshness_service
    from prism_api.overview import DatasetStore, OverviewDataset, StoredDataset

    local_registry = registry.__class__()
    dataset_id = "ds_freshness_perf"
    for i in range(1_000):
        local_registry.register(
            AnalyticalObject(
                object_id=f"perf_{i}",
                kind=ObjectKind.ANALYSIS,
                lifecycle=LifecycleState.COMPLETED,
                provenance=AnalyticalProvenance(
                    dataset=DatasetRef(dataset_id=dataset_id, revision=i % 5, source_fingerprint="a" * 64),
                    reproducibility=GenericReproducibilitySpec(producer=Producer(service="perf", version="1"), operation="test"),
                    created_at=datetime.now(timezone.utc),
                ),
                payload={},
            )
        )
    local_store = DatasetStore()
    frame = pd.DataFrame({"x": [1, 2, 3]})
    active = OverviewDataset(dataset_id=dataset_id, revision=4, source_name="perf.csv", source_fingerprint="a" * 64, row_count=3, column_count=1)
    local_store._datasets[dataset_id] = StoredDataset(active, frame, "a" * 64)

    started = time.perf_counter()
    results = freshness_service.assess_dataset(local_registry, local_store, dataset_id)
    elapsed = time.perf_counter() - started
    assert len(results) == 1_000
    assert elapsed < 2.0
