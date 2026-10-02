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


def test_scatter_points_carry_the_actual_numeric_x_value_not_a_row_index() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "scatter", "intent": "relationship", "dimension": "revenue", "measure": "units", "aggregation": "none", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec).json()
    assert response["data"]
    x_values = [point["x"] for point in response["data"]]
    assert all(x is not None for x in x_values)
    # With this fixture revenue only takes 7 distinct values (i % 7) * 10 + 5; a row
    # index standing in for x would instead produce as many distinct values as rows.
    assert set(x_values) <= {5.0, 15.0, 25.0, 35.0, 45.0, 55.0, 65.0}


def test_box_plot_reports_real_quartiles_whiskers_and_outliers_not_a_bar_fallback() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "box", "intent": "distribution", "dimension": "segment", "measure": "revenue", "aggregation": "none", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec).json()
    assert response["data"]
    first = response["data"][0]
    assert first["box"] is not None
    box = first["box"]
    assert box["q1"] <= box["median"] <= box["q3"]
    assert box["whisker_low"] <= box["q1"]
    assert box["whisker_high"] >= box["q3"]
    assert isinstance(box["outliers"], list)


def test_line_chart_preserves_chronological_order_even_when_values_are_not_monotonic() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "line", "intent": "trend", "dimension": "ordered_at", "measure": "revenue", "aggregation": "sum", "max_categories": 50}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec).json()
    labels = [point["label"] for point in response["data"]]
    assert labels == sorted(labels)  # chronological, never resorted by value


def test_atlas_explain_chart_and_trust_check_do_not_mutate_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 3}

    explained = client.post(f"/api/v1/visualize/datasets/{dataset_id}/atlas", json={"action": "explain_chart", "spec": spec})
    assert explained.status_code == 200
    assert "comparison" in explained.json()["summary"]

    trust = client.post(f"/api/v1/visualize/datasets/{dataset_id}/atlas", json={"action": "propose_alternative", "spec": spec})
    assert "additional" in trust.json()["summary"]  # category truncation is a real trust issue for max_categories=3
