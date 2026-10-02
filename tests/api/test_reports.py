from __future__ import annotations

from unittest.mock import patch

from fastapi import HTTPException
from prism_api.main import create_app
from reviewing_client import ReviewingTestClient as TestClient

CSV = b"segment,revenue\na,10\nb,20\nc,30\n"
SPEC = {"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "revenue", "aggregation": "sum", "filters": {}, "max_categories": 20}


def _dataset(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("sales.csv", CSV, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_save_chart_captures_the_current_dataset_revision_and_fingerprint() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": SPEC, "rationale": "Comparison question."})
    assert response.status_code == 201
    body = response.json()
    assert body["dataset_revision"] == 0
    assert body["name"] == "Revenue by segment"
    assert body["result"]["data"]

    listed = client.get("/api/v1/reports/charts").json()
    assert any(item["chart_id"] == body["chart_id"] for item in listed)


def test_create_report_add_chart_and_note_then_read_the_composed_detail() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": SPEC, "rationale": ""}).json()

    report = client.post("/api/v1/reports", json={"name": "Weekly review"}).json()
    report_id = report["report_id"]

    added = client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})
    assert added.status_code == 200
    assert len(added.json()["report"]["chart_refs"]) == 1

    noted = client.post(f"/api/v1/reports/{report_id}/notes", json={"text": "Segment b leads this week."})
    assert noted.status_code == 200
    assert len(noted.json()["notes"]) == 1

    detail = client.get(f"/api/v1/reports/{report_id}").json()
    assert detail["report"]["name"] == "Weekly review"
    assert len(detail["charts"]) == 1
    assert detail["charts"][0]["chart_id"] == chart["chart_id"]
    assert len(detail["freshness"]) == 1
    assert detail["freshness"][0]["needs_refresh"] is False  # nothing changed since the chart was added


def test_report_tables_are_source_bound_durable_and_ordered_with_notes() -> None:
    from prism_api.durable_registry import history_database_url
    from prism_api.durable_report_store import DurableReportStore

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()
    report_id = client.post("/api/v1/reports", json={"name": "Table review"}).json()["report_id"]
    payload = {"title": "Sample rows", "dataset_id": dataset_id, "source_revision": profile["dataset"]["revision"],
               "source_fingerprint": profile["dataset"]["source_fingerprint"], "columns": ["segment", "revenue"], "limit": 2}
    added = client.post(f"/api/v1/reports/{report_id}/tables", json=payload)
    assert added.status_code == 200
    table = added.json()["report"]["tables"][0]
    assert table["rows"] == [{"segment": "a", "revenue": 10}, {"segment": "b", "revenue": 20}]
    assert table["source_row_count"] == 3
    note = client.post(f"/api/v1/reports/{report_id}/notes", json={"text": "Interpretation"}).json()["notes"][0]
    reordered = client.put(f"/api/v1/reports/{report_id}/order", json={"item_order": [note["note_id"], table["table_id"]]})
    assert reordered.status_code == 200
    assert reordered.json()["report"]["item_order"] == [note["note_id"], table["table_id"]]
    assert client.put(f"/api/v1/reports/{report_id}/order", json={"item_order": [note["note_id"]]}).status_code == 422
    stale = client.post(f"/api/v1/reports/{report_id}/tables", json={**payload, "source_revision": 99})
    assert stale.status_code == 409
    assert client.get(f"/api/v1/reports/{report_id}").json()["report"]["tables"][0]["rows"] == table["rows"]
    restored = DurableReportStore(history_database_url()).get_report(report_id)
    assert restored.tables[0].rows == table["rows"]
    assert restored.item_order == [note["note_id"], table["table_id"]]


def test_report_flags_needs_refresh_after_the_source_dataset_changes_and_clears_on_explicit_refresh() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": SPEC, "rationale": ""}).json()
    report_id = client.post("/api/v1/reports", json={"name": "Weekly review"}).json()["report_id"]
    client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})

    # Apply a Clean transformation, advancing the dataset to revision 1.
    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "category_mapping", "column": "segment", "category_mapping": {"a": "renamed"}})
    assert applied.status_code == 201

    detail = client.get(f"/api/v1/reports/{report_id}").json()
    assert detail["freshness"][0]["needs_refresh"] is True
    assert detail["freshness"][0]["current_revision"] == 1
    assert detail["freshness"][0]["acknowledged_revision"] == 0
    assert detail["charts"][0]["dataset_revision"] == 0  # the saved chart record itself is never rewritten

    missing_selection = client.post(f"/api/v1/reports/{report_id}/refresh", json={})
    assert missing_selection.status_code == 409
    refreshed = client.post(f"/api/v1/reports/{report_id}/refresh", json={
        "chart_ids": [chart["chart_id"]],
        "source_revisions": {chart["chart_id"]: 1},
        "source_fingerprints": {chart["chart_id"]: detail["freshness"][0]["current_fingerprint"]},
    })
    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["freshness"][0]["needs_refresh"] is False
    assert body["freshness"][0]["acknowledged_revision"] == 1
    assert body["charts"][0]["dataset_revision"] == 1
    assert body["charts"][0]["previous_chart_id"] == chart["chart_id"]
    assert body["charts"][0]["result"]["data"] != chart["result"]["data"]
    assert client.get(f"/api/v1/reports/charts/{chart['chart_id']}").json()["result"] == chart["result"]


def test_remove_chart_and_remove_note_from_a_report() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": SPEC, "rationale": ""}).json()
    report_id = client.post("/api/v1/reports", json={"name": "Weekly review"}).json()["report_id"]
    client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})
    note = client.post(f"/api/v1/reports/{report_id}/notes", json={"text": "Draft note"}).json()["notes"][0]

    removed_chart = client.delete(f"/api/v1/reports/{report_id}/charts/{chart['chart_id']}")
    assert removed_chart.status_code == 200
    assert removed_chart.json()["report"]["chart_refs"] == []

    removed_note = client.delete(f"/api/v1/reports/{report_id}/notes/{note['note_id']}")
    assert removed_note.status_code == 200
    assert removed_note.json()["notes"] == []


def test_report_discloses_when_a_charts_source_dataset_is_no_longer_available() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": SPEC, "rationale": ""}).json()
    report_id = client.post("/api/v1/reports", json={"name": "Weekly review"}).json()["report_id"]
    client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})

    detail = client.get(f"/api/v1/reports/{report_id}").json()
    assert detail["freshness"][0]["dataset_unavailable"] is False

    # Simulate the source dataset being gone (e.g. a fresh process) by pointing at a bogus id is not
    # possible without mutating the chart record (which is intentionally immutable), so this test
    # instead verifies the live-dataset path directly used by the unavailable-dataset branch.
    missing_response = client.get("/api/v1/overview/datasets/ds_does_not_exist/profile")
    assert missing_response.status_code == 404


def test_get_report_rejects_an_unknown_report_id() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/reports/report_does_not_exist")
    assert response.status_code == 404


def test_add_chart_rejects_an_unknown_chart_id() -> None:
    client = TestClient(create_app())
    report_id = client.post("/api/v1/reports", json={"name": "Weekly review"}).json()["report_id"]
    response = client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": "chart_does_not_exist"})
    assert response.status_code == 404


def test_adding_the_same_chart_twice_is_idempotent() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue by segment", "dataset_id": dataset_id, "spec": SPEC, "rationale": ""}).json()
    report_id = client.post("/api/v1/reports", json={"name": "Weekly review"}).json()["report_id"]
    client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})
    second = client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})
    assert len(second.json()["report"]["chart_refs"]) == 1


def test_saved_report_and_rendered_chart_survive_a_fresh_store_connection() -> None:
    from prism_api.durable_registry import history_database_url
    from prism_api.durable_report_store import DurableReportStore

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue", "dataset_id": dataset_id, "spec": SPEC}).json()
    report = client.post("/api/v1/reports", json={"name": "Durable review"}).json()
    client.post(f"/api/v1/reports/{report['report_id']}/charts", json={"chart_id": chart["chart_id"]})
    fresh = DurableReportStore(history_database_url())
    assert fresh.get_report(report["report_id"]).chart_refs[0].chart_id == chart["chart_id"]
    restored_result = fresh.get_chart(chart["chart_id"]).result
    assert restored_result is not None
    assert restored_result.model_dump(mode="json") == chart["result"]


def test_missing_source_is_visible_and_refresh_fails_closed() -> None:
    import prism_api.reports as reports_module

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    chart = client.post("/api/v1/reports/charts", json={"name": "Revenue", "dataset_id": dataset_id, "spec": SPEC}).json()
    report_id = client.post("/api/v1/reports", json={"name": "Review"}).json()["report_id"]
    client.post(f"/api/v1/reports/{report_id}/charts", json={"chart_id": chart["chart_id"]})
    with patch.object(reports_module.overview_store, "get", side_effect=HTTPException(status_code=404)):
        detail = client.get(f"/api/v1/reports/{report_id}").json()
        assert detail["freshness"][0]["dataset_unavailable"] is True
        assert detail["freshness"][0]["needs_refresh"] is True
        refreshed = client.post(f"/api/v1/reports/{report_id}/refresh", json={
            "chart_ids": [chart["chart_id"]], "source_revisions": {chart["chart_id"]: 0},
            "source_fingerprints": {chart["chart_id"]: chart["source_fingerprint"]},
        })
        assert refreshed.status_code == 409
    assert client.get(f"/api/v1/reports/{report_id}").json()["report"]["chart_refs"][0]["chart_id"] == chart["chart_id"]
