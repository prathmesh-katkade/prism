from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app

CSV = (
    b"customer_id,revenue,start_date,end_date\n"
    b"c1,100,2026-01-01,2026-01-10\n"
    b"c1,50,2026-01-02,2026-01-11\n"  # duplicate customer_id
    b"c2,-20,2026-01-03,2026-01-12\n"  # negative revenue
    b"c3,30,2026-01-20,2026-01-15\n"  # end_date before start_date
    b"c4,40,2026-01-05,2026-01-06\n"  # clean row
)


def _dataset(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("sales.csv", CSV, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_create_list_and_delete_a_validation_rule() -> None:
    client = TestClient(create_app())
    created = client.post("/api/v1/clean/validation-rules", json={"name": "Unique customers", "kind": "uniqueness", "column": "customer_id"})
    assert created.status_code == 201
    rule_id = created.json()["rule_id"]

    listed = client.get("/api/v1/clean/validation-rules").json()
    assert any(item["rule_id"] == rule_id for item in listed)

    deleted = client.delete(f"/api/v1/clean/validation-rules/{rule_id}")
    assert deleted.status_code == 204
    listed_after = client.get("/api/v1/clean/validation-rules").json()
    assert not any(item["rule_id"] == rule_id for item in listed_after)


def test_create_rejects_missing_required_columns_for_each_kind() -> None:
    client = TestClient(create_app())
    assert client.post("/api/v1/clean/validation-rules", json={"name": "x", "kind": "uniqueness"}).status_code == 422
    assert client.post("/api/v1/clean/validation-rules", json={"name": "x", "kind": "nonnegative"}).status_code == 422
    assert client.post("/api/v1/clean/validation-rules", json={"name": "x", "kind": "date_order", "before_column": "start_date"}).status_code == 422


def test_uniqueness_rule_finds_the_duplicate_customer_id() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    rule_id = client.post("/api/v1/clean/validation-rules", json={"name": "Unique customers", "kind": "uniqueness", "column": "customer_id"}).json()["rule_id"]

    result = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule_id}/run")
    assert result.status_code == 200
    body = result.json()
    assert body["passed"] is False
    assert body["violation_count"] == 2  # both c1 rows
    assert body["total_checked"] == 5
    assert {row["customer_id"] for row in body["sample_violations"]} == {"c1"}


def test_nonnegative_rule_finds_the_negative_revenue_row() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    rule_id = client.post("/api/v1/clean/validation-rules", json={"name": "Revenue >= 0", "kind": "nonnegative", "column": "revenue"}).json()["rule_id"]

    result = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule_id}/run").json()
    assert result["passed"] is False
    assert result["violation_count"] == 1
    assert result["sample_violations"][0]["customer_id"] == "c2"


def test_date_order_rule_finds_the_row_where_end_precedes_start() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    rule_id = client.post("/api/v1/clean/validation-rules", json={"name": "start before end", "kind": "date_order", "before_column": "start_date", "after_column": "end_date"}).json()["rule_id"]

    result = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule_id}/run").json()
    assert result["passed"] is False
    assert result["violation_count"] == 1
    assert result["sample_violations"][0]["customer_id"] == "c3"


def test_a_passing_rule_reports_zero_violations() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    rule_id = client.post("/api/v1/clean/validation-rules", json={"name": "Revenue >= 0 on a clean column", "kind": "uniqueness", "column": "end_date"}).json()["rule_id"]

    result = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule_id}/run").json()
    assert result["passed"] is True
    assert result["violation_count"] == 0
    assert result["sample_violations"] == []


def test_run_rejects_an_unknown_rule_or_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    assert client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/rule_does_not_exist/run").status_code == 404

    rule_id = client.post("/api/v1/clean/validation-rules", json={"name": "x", "kind": "uniqueness", "column": "customer_id"}).json()["rule_id"]
    assert client.post(f"/api/v1/clean/datasets/dataset_does_not_exist/validation-rules/{rule_id}/run").status_code == 404


def test_run_rejects_a_rule_whose_column_is_not_in_the_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    rule_id = client.post("/api/v1/clean/validation-rules", json={"name": "x", "kind": "nonnegative", "column": "not_a_real_column"}).json()["rule_id"]
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/validation-rules/{rule_id}/run")
    assert response.status_code == 422


def test_validation_rules_persist_across_a_fresh_store_connection() -> None:
    from prism_api.durable_registry import history_database_url
    from prism_api.durable_validation_rule_store import DurableValidationRuleStore

    client = TestClient(create_app())
    created = client.post("/api/v1/clean/validation-rules", json={"name": "Durable rule", "kind": "uniqueness", "column": "customer_id"})
    rule_id = created.json()["rule_id"]

    fresh_store = DurableValidationRuleStore(history_database_url())
    recovered = fresh_store.get(rule_id)
    assert recovered.rule_id == rule_id
    assert recovered.name == "Durable rule"
