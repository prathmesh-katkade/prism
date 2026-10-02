from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app

CSV = b"customer_id,revenue\nc1,10\nc1,20\nc2,30\n"

CTE_SQL = (
    "WITH recent AS (SELECT * FROM data WHERE revenue > 10), "
    "totals AS (SELECT customer_id, SUM(revenue) AS total FROM recent GROUP BY customer_id) "
    "SELECT * FROM totals WHERE total > 5"
)


def _connection(client: TestClient) -> str:
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("sales.csv", CSV, "text/csv")}).json()["dataset_id"]
    return f"local:{dataset_id}"


def test_list_ctes_returns_the_named_ctes_in_order() -> None:
    client = TestClient(create_app())
    connection_id = _connection(client)
    response = client.post("/api/v1/sql-lab/ctes/list", json={"connection_id": connection_id, "sql": CTE_SQL})
    assert response.status_code == 200
    assert response.json()["ctes"] == ["recent", "totals"]


def test_list_ctes_on_a_query_without_a_with_clause_returns_an_empty_list() -> None:
    client = TestClient(create_app())
    connection_id = _connection(client)
    response = client.post("/api/v1/sql-lab/ctes/list", json={"connection_id": connection_id, "sql": "SELECT * FROM data"})
    assert response.status_code == 200
    assert response.json()["ctes"] == []


def test_materialize_an_early_cte_drops_the_later_ones_and_executes_standalone() -> None:
    client = TestClient(create_app())
    connection_id = _connection(client)
    response = client.post("/api/v1/sql-lab/ctes/materialize", json={"connection_id": connection_id, "sql": CTE_SQL, "cte_name": "recent"})
    assert response.status_code == 200
    body = response.json()
    assert body["cte_name"] == "recent"
    materialized = body["materialized_sql"]
    assert "totals" not in materialized  # the later CTE this one doesn't depend on is dropped

    run = client.post("/api/v1/sql-lab/runs", json={"connection_id": connection_id, "sql": materialized})
    assert run.status_code == 201
    run_id = run.json()["run_id"]
    import time
    for _ in range(100):
        polled = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if polled["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    assert polled["state"] == "succeeded"
    page = client.get(f"/api/v1/sql-lab/runs/{run_id}/results").json()
    # "recent" keeps rows with revenue > 10: c1's 20 and c2's 30 both qualify; c1's 10 does not.
    assert {row["customer_id"] for row in page["rows"]} == {"c1", "c2"}
    assert len(page["rows"]) == 2


def test_materialize_a_later_cte_keeps_the_ctes_it_depends_on() -> None:
    client = TestClient(create_app())
    connection_id = _connection(client)
    response = client.post("/api/v1/sql-lab/ctes/materialize", json={"connection_id": connection_id, "sql": CTE_SQL, "cte_name": "totals"})
    assert response.status_code == 200
    materialized = response.json()["materialized_sql"]
    assert "recent" in materialized  # "totals" depends on "recent", so it must stay
    assert "FROM totals" in materialized or "from totals" in materialized.lower()


def test_materialize_rejects_an_unknown_cte_name() -> None:
    client = TestClient(create_app())
    connection_id = _connection(client)
    response = client.post("/api/v1/sql-lab/ctes/materialize", json={"connection_id": connection_id, "sql": CTE_SQL, "cte_name": "not_a_real_cte"})
    assert response.status_code == 422


def test_materialize_rejects_a_query_with_no_with_clause() -> None:
    client = TestClient(create_app())
    connection_id = _connection(client)
    response = client.post("/api/v1/sql-lab/ctes/materialize", json={"connection_id": connection_id, "sql": "SELECT * FROM data", "cte_name": "x"})
    assert response.status_code == 422
