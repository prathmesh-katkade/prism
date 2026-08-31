"""Phase 8H: end-to-end integration audit across the full Phase 8 stack (8A-8G) —
upload → provenance → lineage → freshness → inspector-facing reads → rerun → Atlas
explanation, all through real HTTP calls, no mocking. Complements the per-phase test
files (which cover each seam in isolation) by proving the seams actually connect.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient
from prism_analytical_schemas import ObjectKind
from prism_api.analytical_objects import registry
from prism_api.main import create_app


def _dataset(client: TestClient, csv: bytes, name: str) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def test_flow_a_upload_stats_lineage_freshness_rerun_atlas() -> None:
    """upload -> dataset revision object -> Stats -> provenance -> lineage -> freshness
    -> inspector-facing reads -> rerun -> new object -> Atlas explanation."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", "flow_a.csv")

    stats_response = client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    assert stats_response.status_code == 200

    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    stats_object = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    # provenance / lineage
    assert client.get(f"/api/v1/lineage/objects/{stats_object.object_id}").status_code == 200
    assert [p["object_id"] for p in client.get(f"/api/v1/lineage/objects/{stats_object.object_id}/parents").json()] == [dsrev.object_id]
    ancestors = client.get(f"/api/v1/lineage/objects/{stats_object.object_id}/ancestors").json()
    assert dsrev.object_id in {node["object"]["object_id"] for node in ancestors["nodes"]}

    # freshness - current before any change
    assert client.get(f"/api/v1/lineage/objects/{stats_object.object_id}/freshness").json()["state"] == "current"

    # inspector-facing reads (graph + dataset objects)
    assert client.get(f"/api/v1/lineage/objects/{stats_object.object_id}/graph").status_code == 200
    assert client.get(f"/api/v1/lineage/datasets/{dataset_id}/objects").status_code == 200

    # rerun (current_revision - still active, so behaves like a fresh reproduction)
    rerun = client.post(f"/api/v1/lineage/objects/{stats_object.object_id}/rerun", json={"mode": "current_revision"})
    assert rerun.status_code == 200
    rerun_body = rerun.json()
    assert rerun_body["outcome"] == "created"
    assert rerun_body["new_object"]["object_id"] != stats_object.object_id

    # Atlas explanation, grounded in the same recorded data
    atlas = client.post(f"/api/v1/lineage/objects/{stats_object.object_id}/atlas", json={"action": "explain_provenance"})
    assert atlas.status_code == 200
    assert dataset_id in atlas.json()["summary"]


def test_flow_b_clean_creates_staleness_inspector_shows_it_atlas_explains_it_rerun_refreshes_it() -> None:
    """upload -> Clean -> new revision -> previous analyses become stale -> freshness
    endpoint (what the inspector reads) shows stale -> Atlas explains why -> rerun on
    current revision -> new current result."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", "flow_b.csv")

    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_object = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    apply_response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert apply_response.status_code == 201

    # stale now - what the Evidence Inspector's freshness badge reads
    freshness = client.get(f"/api/v1/lineage/objects/{stats_object.object_id}/freshness").json()
    assert freshness["state"] == "stale"

    # Atlas explains why, grounded in the same freshness data
    atlas = client.post(f"/api/v1/lineage/objects/{stats_object.object_id}/atlas", json={"action": "explain_staleness"})
    assert atlas.status_code == 200
    assert freshness["reason"] in atlas.json()["summary"]

    # Atlas also recommends this exact object as a rerun candidate
    revision0 = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]
    recommendation = client.post(f"/api/v1/lineage/objects/{revision0.object_id}/atlas", json={"action": "recommend_reruns"}).json()
    assert stats_object.object_id in {item["value"] for item in recommendation["evidence"]}

    # rerun on current revision refreshes it
    rerun = client.post(f"/api/v1/lineage/objects/{stats_object.object_id}/rerun", json={"mode": "current_revision"})
    body = rerun.json()
    assert body["outcome"] == "created"
    new_object_id = body["new_object"]["object_id"]

    # the new result is current; the old one remains stale, unchanged
    assert client.get(f"/api/v1/lineage/objects/{new_object_id}/freshness").json()["state"] == "current"
    assert client.get(f"/api/v1/lineage/objects/{stats_object.object_id}/freshness").json()["state"] == "stale"
    unchanged_original = registry.get(stats_object.object_id)
    assert unchanged_original is not None
    assert unchanged_original.provenance.created_at == stats_object.provenance.created_at


def test_flow_c_sql_visualize_lineage_and_historical_inspection() -> None:
    """SQL -> query analytical object -> visualization -> lineage graph -> historical
    inspection (the SQL result object remains fully readable after later Clean activity,
    unchanged)."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n", "flow_c.csv")

    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": f"local:{dataset_id}", "sql": "SELECT * FROM data"})
    run_id = submitted.json()["run_id"]
    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    assert run["state"] == "succeeded"
    sql_object = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]

    client.post(
        f"/api/v1/visualize/datasets/{dataset_id}/render",
        json={"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "y", "aggregation": "sum", "filters": {}, "max_categories": 20},
    )
    viz_object = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.VISUALIZATION)

    graph = client.get(f"/api/v1/lineage/objects/{sql_object.object_id}/graph", params={"direction": "both"})
    assert graph.status_code == 200

    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    # Historical inspection: both objects remain fully, unchangedly readable after the
    # dataset moved on - and the freshness endpoint (not a 404, not a crash) reports stale.
    for object_id in (sql_object.object_id, viz_object.object_id):
        historical = client.get(f"/api/v1/lineage/objects/{object_id}")
        assert historical.status_code == 200
        assert client.get(f"/api/v1/lineage/objects/{object_id}/freshness").json()["state"] == "stale"


def test_flow_d_forecast_stale_after_clean_then_rerun_is_current() -> None:
    """Forecast -> inspect method/params -> Clean creates a new revision -> forecast
    stale -> rerun -> new forecast current."""
    import io

    import pandas as pd

    dates = pd.date_range("2026-01-01", periods=10, freq="D")
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "revenue": [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]})
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)

    client = TestClient(create_app())
    dataset_id = _dataset(client, buffer.getvalue().encode(), "flow_d.csv")

    client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 5})
    forecast_object = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.FORECAST)

    provenance = client.get(f"/api/v1/lineage/objects/{forecast_object.object_id}").json()
    assert provenance["provenance"]["reproducibility"]["parameters"]["datetime_col"] == "date"

    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert client.get(f"/api/v1/lineage/objects/{forecast_object.object_id}/freshness").json()["state"] == "stale"

    rerun = client.post(f"/api/v1/lineage/objects/{forecast_object.object_id}/rerun", json={"mode": "current_revision"})
    body = rerun.json()
    assert body["outcome"] == "created"
    assert client.get(f"/api/v1/lineage/objects/{body['new_object']['object_id']}/freshness").json()["state"] == "current"


def test_flow_e_ml_baseline_feature_selection_shap_lineage_and_freshness() -> None:
    """ML baseline -> inspect provenance -> feature-selection/SHAP objects -> freshness
    -> lineage navigation, all sharing the same dataset-revision parent."""
    import io

    import pandas as pd

    rows = []
    for i in range(40):
        x1 = float(i % 10)
        x2 = float((i * 3) % 7)
        segment = "a" if i % 3 == 0 else "b" if i % 3 == 1 else "c"
        label = "yes" if (x1 + x2) > 8 else "no"
        rows.append({"x1": x1, "x2": x2, "segment": segment, "label": label})
    buffer = io.StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)

    client = TestClient(create_app())
    dataset_id = _dataset(client, buffer.getvalue().encode(), "flow_e.csv")

    client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    client.post(f"/api/v1/ml/datasets/{dataset_id}/feature-selection", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    client.post(f"/api/v1/ml/datasets/{dataset_id}/shap", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})

    ml_objects = [r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ML_MODEL]
    assert len(ml_objects) == 3
    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]

    for ml_object in ml_objects:
        assert [p["object_id"] for p in client.get(f"/api/v1/lineage/objects/{ml_object.object_id}/parents").json()] == [dsrev.object_id]
        assert client.get(f"/api/v1/lineage/objects/{ml_object.object_id}/freshness").json()["state"] == "current"

    children = client.get(f"/api/v1/lineage/objects/{dsrev.object_id}/children").json()
    assert {o.object_id for o in ml_objects}.issubset({c["object_id"] for c in children})
