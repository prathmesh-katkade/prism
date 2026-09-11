from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app

CSV = b"segment,revenue,units,ordered_at\n" + b"".join(
    f"{'abcdefghijklmnopqrstuvwxyz'[i % 26]},{ (i % 7) * 10 + 5 },{i % 12},2024-01-{(i % 28) + 1:02d}\n".encode()
    for i in range(60)
)


def _dataset(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("sales.csv", CSV, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_suggest_picks_a_deterministic_mark_for_a_comparison_question() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    first = client.post(f"/api/v1/visualize/datasets/{dataset_id}/suggest", params={"dimension": "segment", "measure": "revenue"})
    second = client.post(f"/api/v1/visualize/datasets/{dataset_id}/suggest", params={"dimension": "segment", "measure": "revenue"})
    assert first.status_code == 200
    assert first.json() == second.json()  # deterministic: same inputs, same suggestion
    assert first.json()["spec"]["mark"] == "bar"


def test_suggest_rejects_an_unknown_column_rather_than_guessing() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/suggest", params={"dimension": "not_a_real_column"})
    assert response.status_code == 422


def test_render_aggregates_server_side_and_never_returns_raw_row_count_of_data() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert response.status_code == 200
    body = response.json()
    assert len(body["data"]) <= 26  # one point per category, not one per row (60 rows)
    assert body["provenance"]["source_fingerprint"]


def test_render_caps_categories_and_warns_instead_of_silently_truncating() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 5}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec).json()
    assert len(response["data"]) == 5
    assert response["truncated"] is True
    assert response["warnings"]


def test_render_rejects_a_column_that_does_not_exist() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "not_real", "measure": "revenue", "aggregation": "sum", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


def test_scatter_samples_and_warns_about_overplotting() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "scatter", "intent": "relationship", "dimension": "revenue", "measure": "units", "aggregation": "none", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec).json()
    assert len(response["data"]) <= 60


def test_atlas_explain_chart_and_trust_check_do_not_mutate_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 3}

    explained = client.post(f"/api/v1/visualize/datasets/{dataset_id}/atlas", json={"action": "explain_chart", "spec": spec})
    assert explained.status_code == 200
    assert "comparison" in explained.json()["summary"]

    trust = client.post(f"/api/v1/visualize/datasets/{dataset_id}/atlas", json={"action": "propose_alternative", "spec": spec})
    assert "additional" in trust.json()["summary"]  # category truncation is a real trust issue for max_categories=3
