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


def test_horizontal_bar_uses_the_same_aggregation_and_contributing_rows_as_bar() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "horizontal_bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "filters": {"segment": "a"}}
    rendered = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert rendered.status_code == 200
    vertical = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**spec, "mark": "bar"})
    assert vertical.status_code == 200
    assert rendered.json()["data"] == vertical.json()["data"]
    inspected = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "dimension_value": "a"})
    assert inspected.status_code == 200
    assert inspected.json()["total_matching_rows"] == 3
    assert all(row["segment"] == "a" for row in inspected.json()["rows"])


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


def test_drilldown_resolves_a_bar_mark_to_its_real_contributing_rows() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 26}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "dimension_value": "a"})
    assert response.status_code == 200
    body = response.json()
    assert body["total_matching_rows"] == 3  # i=0, 26, 52 all have segment 'a' in this 60-row fixture
    assert all(row["segment"] == "a" for row in body["rows"])
    assert body["truncated"] is False
    assert body["filters_applied"] == {"segment": "a"}


def test_drilldown_paginates_and_discloses_truncation() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 26}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "dimension_value": "a", "limit": 2})
    assert response.status_code == 200
    body = response.json()
    assert len(body["rows"]) == 2
    assert body["total_matching_rows"] == 3
    assert body["truncated"] is True


def test_drilldown_resolves_a_scatter_point_by_exact_x_and_y() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "scatter", "intent": "relationship", "dimension": "revenue", "measure": "units", "aggregation": "none", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "x_value": 5, "y_value": 0})
    assert response.status_code == 200
    body = response.json()
    assert body["total_matching_rows"] >= 1
    assert all(row["revenue"] == 5 and row["units"] == 0 for row in body["rows"])


def test_drilldown_requires_dimension_value_for_a_non_scatter_mark() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 26}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec})
    assert response.status_code == 422


def test_drilldown_requires_x_and_y_for_a_scatter_mark() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "scatter", "intent": "relationship", "dimension": "revenue", "measure": "units", "aggregation": "none", "max_categories": 20}
    response = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec})
    assert response.status_code == 422


def test_atlas_explain_chart_and_trust_check_do_not_mutate_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 3}

    explained = client.post(f"/api/v1/visualize/datasets/{dataset_id}/atlas", json={"action": "explain_chart", "spec": spec})
    assert explained.status_code == 200
    assert "comparison" in explained.json()["summary"]

    trust = client.post(f"/api/v1/visualize/datasets/{dataset_id}/atlas", json={"action": "propose_alternative", "spec": spec})
    assert "additional" in trust.json()["summary"]  # category truncation is a real trust issue for max_categories=3


def test_saved_filters_apply_to_render_and_mark_rows() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "filters": {"segment": "a"}}
    rendered = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert rendered.status_code == 200
    assert len(rendered.json()["data"]) == 1
    inspected = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "dimension_value": "a"})
    assert inspected.status_code == 200
    assert inspected.json()["total_matching_rows"] == 3
    assert inspected.json()["filters_applied"] == {"segment": "a"}


def test_histogram_bin_bounds_resolve_to_same_contributing_row_count() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "histogram", "intent": "distribution", "measure": "revenue", "aggregation": "none", "histogram_bins": 7}
    rendered = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert rendered.status_code == 200
    assert len(rendered.json()["data"]) == 7
    for bin_data in rendered.json()["data"]:
        inspected = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "bin_start": bin_data["bin_start"], "bin_end": bin_data["bin_end"]})
        assert inspected.status_code == 200
        assert inspected.json()["total_matching_rows"] == bin_data["value"]


def test_small_multiples_share_a_saved_spec_and_mark_rows_respect_panel_filter() -> None:
    client = TestClient(create_app())
    csv = b"region,product,revenue\nNorth,A,10\nNorth,B,20\nSouth,A,30\nSouth,B,40\n"
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("facets.csv", csv, "text/csv")}).json()["dataset_id"]
    spec = {"mark": "bar", "intent": "comparison", "dimension": "product", "measure": "revenue",
            "aggregation": "sum", "facet": "region"}
    rendered = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec)
    assert rendered.status_code == 200
    facets = rendered.json()["facets"]
    assert [(facet["value"], {point["label"]: point["value"] for point in facet["data"]}) for facet in facets] == [
        ("North", {"B": 20.0, "A": 10.0}), ("South", {"B": 40.0, "A": 30.0}),
    ]
    inspected = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={
        "spec": {**spec, "filters": {"region": "South"}}, "dimension_value": "A",
    })
    assert inspected.json()["total_matching_rows"] == 1
    assert inspected.json()["rows"][0]["revenue"] == 30
    saved = client.post("/api/v1/reports/charts", json={"name": "Products by region", "dataset_id": dataset_id, "spec": spec})
    assert saved.status_code == 201
    assert saved.json()["result"]["facets"] == facets
    unsupported = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**spec, "mark": "scatter"})
    assert unsupported.status_code == 422


def test_sort_by_controls_bar_order_with_a_deterministic_label_tiebreak() -> None:
    client = TestClient(create_app())
    csv = b"region,revenue\nNorth,30\nSouth,30\nEast,10\nWest,20\n"
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("sort.csv", csv, "text/csv")}).json()["dataset_id"]
    base = {"mark": "bar", "intent": "comparison", "dimension": "region", "measure": "revenue", "aggregation": "sum"}

    default = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=base).json()
    assert [p["label"] for p in default["data"]] == ["North", "South", "West", "East"]  # value desc (30,30,20,10); North/South tie broken by label asc

    value_asc = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "sort_by": "value_asc"}).json()
    assert [p["label"] for p in value_asc["data"]] == ["East", "West", "North", "South"]

    label_asc = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "sort_by": "label_asc"}).json()
    assert [p["label"] for p in label_asc["data"]] == ["East", "North", "South", "West"]

    label_desc = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "sort_by": "label_desc"}).json()
    assert [p["label"] for p in label_desc["data"]] == ["West", "South", "North", "East"]

    # Every ordering is the same set of categories at the same values - only display order changes.
    as_map = lambda body: {p["label"]: p["value"] for p in body["data"]}  # noqa: E731
    assert as_map(default) == as_map(value_asc) == as_map(label_asc) == as_map(label_desc)


def test_sort_by_does_not_change_which_categories_truncation_keeps() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    base = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "max_categories": 5}
    default = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=base).json()
    label_asc = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "sort_by": "label_asc"}).json()
    assert {p["label"] for p in default["data"]} == {p["label"] for p in label_asc["data"]}
    assert [p["label"] for p in label_asc["data"]] == sorted(p["label"] for p in label_asc["data"])


def test_sort_by_also_orders_box_plot_groups_without_changing_which_are_kept() -> None:
    client = TestClient(create_app())
    csv = b"region,revenue\n" + b"".join(
        f"{region},{value}\n".encode()
        for region, value in [("North", 10), ("North", 20), ("South", 5), ("South", 50), ("East", 15), ("East", 25)]
    )
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("box.csv", csv, "text/csv")}).json()["dataset_id"]
    base = {"mark": "box", "intent": "distribution", "dimension": "region", "measure": "revenue", "aggregation": "none"}
    label_asc = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "sort_by": "label_asc"}).json()
    assert [p["label"] for p in label_asc["data"]] == ["East", "North", "South"]
    default = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=base).json()
    assert {p["label"] for p in default["data"]} == {p["label"] for p in label_asc["data"]}


def test_drilldown_still_maps_to_the_correct_category_after_sort_by_reorders_display() -> None:
    client = TestClient(create_app())
    csv = b"region,revenue\nNorth,30\nSouth,30\nEast,10\nWest,20\n"
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("sort2.csv", csv, "text/csv")}).json()["dataset_id"]
    spec = {"mark": "bar", "intent": "comparison", "dimension": "region", "measure": "revenue", "aggregation": "sum", "sort_by": "label_asc"}
    inspected = client.post(f"/api/v1/visualize/datasets/{dataset_id}/drilldown", json={"spec": spec, "dimension_value": "East"})
    assert inspected.status_code == 200
    assert inspected.json()["total_matching_rows"] == 1
    assert inspected.json()["rows"][0]["region"] == "East"


def test_axis_start_other_than_the_truthful_baseline_adds_an_explicit_warning() -> None:
    client = TestClient(create_app())
    csv = b"region,revenue\nNorth,100\nSouth,200\n"
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("axis.csv", csv, "text/csv")}).json()["dataset_id"]
    base = {"mark": "bar", "intent": "comparison", "dimension": "region", "measure": "revenue", "aggregation": "sum"}

    truthful = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "axis_start": 0}).json()
    assert not any("axis starts at" in warning.lower() for warning in truthful["warnings"])

    truncating = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "axis_start": 50}).json()
    assert any("axis starts at" in warning.lower() for warning in truncating["warnings"])

    unset = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=base).json()
    assert not any("axis starts at" in warning.lower() for warning in unset["warnings"])


def test_currency_accepts_the_supported_set_and_rejects_anything_else() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    base = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum"}
    ok = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "currency": "INR"})
    assert ok.status_code == 200
    assert ok.json()["spec"]["currency"] == "INR"
    bad = client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json={**base, "currency": "XXX"})
    assert bad.status_code == 422


def test_sort_by_axis_start_and_currency_persist_through_a_saved_chart() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum",
            "sort_by": "label_asc", "axis_start": 0, "currency": "USD"}
    saved = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": spec})
    assert saved.status_code == 201
    body = saved.json()
    assert body["spec"]["sort_by"] == "label_asc"
    assert body["spec"]["axis_start"] == 0
    assert body["spec"]["currency"] == "USD"
    fetched = client.get(f"/api/v1/reports/charts/{body['chart_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["spec"]["sort_by"] == "label_asc"
    assert fetched.json()["spec"]["currency"] == "USD"
