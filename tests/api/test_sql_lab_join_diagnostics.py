from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app

ORDERS_CSV = b"order_id,customer_id,amount\n1,c1,10\n2,c1,20\n3,c2,30\n4,c3,40\n"
CUSTOMERS_CSV = b"customer_id,name\nc1,Alpha\nc1,Alpha Duplicate\nc2,Beta\nc4,Delta\n"


def _join_connection(client: TestClient) -> str:
    left = client.post("/api/v1/overview/datasets", files={"file": ("orders.csv", ORDERS_CSV, "text/csv")}).json()["dataset_id"]
    right = client.post("/api/v1/overview/datasets", files={"file": ("customers.csv", CUSTOMERS_CSV, "text/csv")}).json()["dataset_id"]
    return f"localjoin:{left}:{right}"


def test_diagnose_joins_reports_cardinality_unmatched_keys_and_multiplication_risk() -> None:
    client = TestClient(create_app())
    connection_id = _join_connection(client)
    sql = "SELECT * FROM data AS o JOIN joined AS c ON o.customer_id = c.customer_id"

    response = client.post("/api/v1/sql-lab/joins/diagnose", json={"connection_id": connection_id, "sql": sql})
    assert response.status_code == 200
    body = response.json()
    assert len(body["joins"]) == 1
    join = body["joins"][0]
    assert join["join_kind"] == "inner"

    left = join["left"]
    assert left["table"] == "data" and left["column"] == "customer_id"
    assert left["total_rows"] == 4
    assert left["distinct_keys"] == 3  # c1, c2, c3
    assert left["duplicate_key_rows"] == 1  # the second c1 row

    right = join["right"]
    assert right["table"] == "joined" and right["column"] == "customer_id"
    assert right["total_rows"] == 4
    assert right["distinct_keys"] == 3  # c1, c2, c4
    assert right["duplicate_key_rows"] == 1  # the second c1 row

    assert join["unmatched_left_rows"] == 1  # c3 has no match on the right
    assert join["unmatched_right_rows"] == 1  # c4 has no match on the left
    assert join["row_multiplication_risk"] is True  # both sides have duplicate keys: many-to-many


def test_diagnose_joins_on_a_query_with_no_join_explains_rather_than_inventing_one() -> None:
    client = TestClient(create_app())
    connection_id = _join_connection(client)
    response = client.post("/api/v1/sql-lab/joins/diagnose", json={"connection_id": connection_id, "sql": "SELECT * FROM data"})
    assert response.status_code == 200
    body = response.json()
    assert body["joins"] == []
    assert any("no join" in note.lower() for note in body["unsupported_notes"])


def test_diagnose_joins_explains_an_unsupported_non_equality_condition() -> None:
    client = TestClient(create_app())
    connection_id = _join_connection(client)
    sql = "SELECT * FROM data AS o JOIN joined AS c ON o.customer_id <> c.customer_id"
    response = client.post("/api/v1/sql-lab/joins/diagnose", json={"connection_id": connection_id, "sql": sql})
    assert response.status_code == 200
    body = response.json()
    assert body["joins"] == []
    assert any("equality condition" in note for note in body["unsupported_notes"])


def test_diagnose_joins_rejects_a_mutating_query() -> None:
    client = TestClient(create_app())
    connection_id = _join_connection(client)
    response = client.post("/api/v1/sql-lab/joins/diagnose", json={"connection_id": connection_id, "sql": "DELETE FROM data"})
    assert response.status_code == 422


def test_diagnose_joins_rejects_an_unknown_connection() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/sql-lab/joins/diagnose", json={"connection_id": "local:does_not_exist", "sql": "SELECT 1"})
    assert response.status_code == 404


def test_diagnose_joins_on_a_single_table_query_with_a_self_join() -> None:
    """Confirms the diagnostics don't assume two distinct source tables -- a self
    join against the same registered table is a legitimate, supported form."""
    client = TestClient(create_app())
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("orders.csv", ORDERS_CSV, "text/csv")}).json()["dataset_id"]
    connection_id = f"local:{dataset_id}"
    sql = "SELECT * FROM data AS a JOIN data AS b ON a.customer_id = b.customer_id"
    response = client.post("/api/v1/sql-lab/joins/diagnose", json={"connection_id": connection_id, "sql": sql})
    assert response.status_code == 200
    body = response.json()
    assert len(body["joins"]) == 1
    assert body["joins"][0]["left"]["table"] == "data"
    assert body["joins"][0]["right"]["table"] == "data"
