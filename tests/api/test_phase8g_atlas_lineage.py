"""Phase 8G: Atlas lineage awareness - deterministic explanations grounded entirely in
Phase 8A-8F's own recorded provenance/freshness/reproducibility data. Never AI-inferred:
Atlas here is a rule-based explainer over already-computed results, not an LLM call.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from prism_analytical_schemas import ObjectKind
from prism_api.analytical_objects import registry
from prism_api.main import create_app


def _dataset(client: TestClient, csv: bytes = b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", name: str = "phase8g.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _atlas(client: TestClient, object_id: str, action: str, compare_to_object_id: str | None = None):
    payload: dict[str, object] = {"action": action}
    if compare_to_object_id is not None:
        payload["compare_to_object_id"] = compare_to_object_id
    return client.post(f"/api/v1/lineage/objects/{object_id}/atlas", json=payload)


def test_explain_provenance_is_grounded_in_recorded_fields() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = _atlas(client, stats_record.object_id, "explain_provenance")
    assert response.status_code == 200
    body = response.json()
    assert "pearson" in body["summary"]
    assert dataset_id in body["summary"]
    assert any(item["label"] == "Producer" for item in body["evidence"])
    assert body["limitation"] is None


def test_explain_staleness_is_grounded_and_matches_the_freshness_endpoint() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    freshness = client.get(f"/api/v1/lineage/objects/{stats_record.object_id}/freshness").json()
    response = _atlas(client, stats_record.object_id, "explain_staleness")
    body = response.json()
    assert "stale" in body["summary"]
    assert freshness["reason"] in body["summary"]
    assert body["limitation"] is None


def test_explain_lineage_reports_direct_and_transitive_counts() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    revision1 = registry.list_for_dataset(dataset_id, revision=1, kind=ObjectKind.DATASET_REVISION)[0]

    response = _atlas(client, revision1.object_id, "explain_lineage")
    body = response.json()
    by_label = {item["label"]: item["value"] for item in body["evidence"]}
    assert by_label["Direct parents"] == "1"
    assert int(by_label["Direct children"]) >= 1
    assert int(by_label["Total ancestors"]) >= 1


def test_recommend_reruns_lists_only_actually_stale_objects() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    revision0 = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]

    still_fresh = _atlas(client, revision0.object_id, "recommend_reruns").json()
    assert still_fresh["summary"] == "No recorded downstream object is currently stale."
    assert still_fresh["evidence"] == []

    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    now_stale = _atlas(client, revision0.object_id, "recommend_reruns").json()
    stale_ids = {item["value"] for item in now_stale["evidence"]}
    assert stats_record.object_id in stale_ids


def test_compare_versions_reports_changed_parameters() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    first = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "chi2", "col_a": "segment", "col_b": "label"})
    second = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS and r.object_id != first.object_id)

    response = _atlas(client, first.object_id, "compare_versions", compare_to_object_id=second.object_id)
    body = response.json()
    assert first.object_id in body["summary"]
    assert second.object_id in body["summary"]
    changed = next(item["value"] for item in body["evidence"] if item["label"] == "Changed parameters")
    assert changed != "none recorded"


def test_compare_versions_without_a_target_is_a_limitation_not_a_guess() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = _atlas(client, record.object_id, "compare_versions")
    body = response.json()
    assert body["limitation"] is not None
    assert body["evidence"] == []


def test_explain_evidence_reflects_recorded_evidence_refs() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    record = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = _atlas(client, record.object_id, "explain_evidence")
    body = response.json()
    assert body["evidence"]
    assert body["limitation"] is None


def test_explain_evidence_reports_a_limitation_when_none_is_recorded() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]

    response = _atlas(client, dsrev.object_id, "explain_evidence")
    body = response.json()
    assert body["evidence"] == []
    assert body["limitation"] is not None


def test_partial_history_staleness_explanation_is_a_limitation_not_a_guess() -> None:
    """Models the process-local partial-history case directly against the service, the
    same way test_phase8d_freshness.py does for the freshness endpoint itself."""
    from datetime import datetime, timezone

    from prism_analytical_schemas import (
        AnalyticalObject,
        AnalyticalProvenance,
        DatasetRef,
        GenericReproducibilitySpec,
        LifecycleState,
        Producer,
    )
    from prism_api import atlas_lineage
    from prism_api.overview import DatasetStore
    from prism_api_contracts import AtlasLineageAction

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
    empty_store = DatasetStore()

    result = atlas_lineage.explain(local_registry, empty_store, "orphan_analysis", AtlasLineageAction.EXPLAIN_STALENESS)
    assert result is not None
    assert result.limitation is not None
    assert "restart" in result.limitation


def test_atlas_lineage_404s_for_an_unknown_object() -> None:
    client = TestClient(create_app())
    assert _atlas(client, "does-not-exist", "explain_provenance").status_code == 404


def test_no_secret_leakage_through_atlas_lineage_explanations() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": f"local:{dataset_id}", "sql": "SELECT * FROM data WHERE segment = $api_key", "parameters": {"api_key": "sk-should-not-leak-e"}},
    )
    import time

    run_id = submitted.json()["run_id"]
    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    sql_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]

    response = _atlas(client, sql_record.object_id, "explain_provenance")
    assert "sk-should-not-leak" not in response.text
