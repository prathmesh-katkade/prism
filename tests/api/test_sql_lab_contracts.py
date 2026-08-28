from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api_contracts import AtlasSqlResponse, SqlRunResponse, SqlSchemaResponse


def upload(client: TestClient) -> str:
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("sales.csv", b"id,revenue,segment\n1,10,a\n2,12,b\n3,,a\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


def terminal_run(client: TestClient, run_id: str) -> SqlRunResponse:
    for _ in range(100):
        response = client.get(f"/api/v1/sql-lab/runs/{run_id}")
        run = SqlRunResponse.model_validate(response.json())
        if run.state.value not in {"queued", "running"}:
            return run
        time.sleep(0.01)
    raise AssertionError("SQL run did not reach a terminal state")


def test_sql_lab_metadata_execution_results_plan_and_atlas_are_typed() -> None:
    client = TestClient(create_app())
    dataset_id = upload(client)
    connection_id = f"local:{dataset_id}"

    connections = client.get("/api/v1/sql-lab/connections")
    schema_response = client.get(f"/api/v1/sql-lab/connections/{connection_id}/schema")
    schema = SqlSchemaResponse.model_validate(schema_response.json())
    run_response = client.post(
        "/api/v1/sql-lab/runs",
        json={
            "connection_id": connection_id,
            "sql": "SELECT segment, COUNT(*) AS rows FROM data GROUP BY segment ORDER BY segment",
            "result_limit": 100,
        },
    )
    run = SqlRunResponse.model_validate(run_response.json())
    assert run.state.value == "queued"
    run = terminal_run(client, run.run_id)
    result_response = client.get(f"/api/v1/sql-lab/runs/{run.run_id}/results?limit=20")
    event_response = client.get(f"/api/v1/sql-lab/runs/{run.run_id}/events")
    plan_response = client.post("/api/v1/sql-lab/plans", json={"connection_id": connection_id, "sql": "SELECT * FROM data"})
    atlas_response = client.post("/api/v1/sql-lab/atlas", json={"action": "generate_sql", "connection_id": connection_id, "intent": "show rows"})
    atlas = AtlasSqlResponse.model_validate(atlas_response.json())

    assert connections.status_code == 200
    assert schema_response.status_code == 200
    assert schema.connection.dialect.value == "duckdb"
    assert schema.tables[0].name == "data"
    assert run_response.status_code == 201
    assert run.state.value == "succeeded"
    assert run.provenance.source_fingerprint
    assert result_response.status_code == 200
    assert len(result_response.json()["rows"]) == 2
    assert event_response.status_code == 200
    assert "event: sql.run" in event_response.text
    assert '"state":"succeeded"' in event_response.text
    assert plan_response.status_code == 200
    assert plan_response.json()["supported"]
    assert atlas_response.status_code == 200
    assert atlas.draft_sql == 'SELECT *\nFROM "data"\nLIMIT 100;'
    assert not atlas.executable


def test_run_idempotency_export_promotion_and_request_tracing() -> None:
    client = TestClient(create_app())
    dataset_id = upload(client)
    payload = {
        "connection_id": f"local:{dataset_id}",
        "sql": "SELECT * FROM data ORDER BY id",
        "client_request_id": f"request-{dataset_id}",
    }
    first = client.post("/api/v1/sql-lab/runs", json=payload, headers={"X-Request-ID": "trace-phase4-0001"})
    second = client.post("/api/v1/sql-lab/runs", json=payload)
    run = terminal_run(client, first.json()["run_id"])
    exported = client.get(f"/api/v1/sql-lab/runs/{run.run_id}/export?format=csv")
    promoted = client.post(f"/api/v1/sql-lab/runs/{run.run_id}/promote")
    conflict = client.post("/api/v1/sql-lab/runs", json={**payload, "sql": "SELECT id FROM data"})

    assert first.headers["X-Request-ID"] == "trace-phase4-0001"
    assert second.json()["run_id"] == first.json()["run_id"]
    assert exported.status_code == 200
    assert exported.headers["content-type"].startswith("text/csv")
    assert promoted.status_code == 201
    assert promoted.json()["dataset"]["row_count"] == 3
    assert promoted.json()["run"]["provenance"]["downstream_objects"]
    assert conflict.status_code == 409


def test_local_connection_remains_bound_to_its_dataset_after_another_upload() -> None:
    client = TestClient(create_app())
    first_dataset_id = upload(client)
    upload(client)

    schema = client.get(f"/api/v1/sql-lab/connections/local:{first_dataset_id}/schema")
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": f"local:{first_dataset_id}", "sql": "SELECT COUNT(*) AS row_count FROM data"},
    )
    run = terminal_run(client, submitted.json()["run_id"])

    assert schema.status_code == 200
    assert run.state.value == "succeeded"


def test_result_provenance_hashes_all_materialized_rows() -> None:
    client = TestClient(create_app())
    rows = "\n".join(f"{index}" for index in range(1_001))
    dataset_id = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("many.csv", f"id\n{rows}\n".encode(), "text/csv")},
    ).json()["dataset_id"]
    first = terminal_run(client, client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": f"local:{dataset_id}", "sql": "SELECT id FROM data ORDER BY id", "result_limit": 2_000},
    ).json()["run_id"])
    second = terminal_run(client, client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": f"local:{dataset_id}", "sql": "SELECT CASE WHEN id = 1000 THEN -1 ELSE id END AS id FROM data ORDER BY id", "result_limit": 2_000},
    ).json()["run_id"])

    assert first.provenance.result_fingerprint != second.provenance.result_fingerprint


def test_sql_lab_blocks_writes_and_never_reflects_credentials() -> None:
    client = TestClient(create_app())
    dataset_id = upload(client)
    password = "never-return-this-secret"
    response = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": f"local:{dataset_id}", "sql": "DROP TABLE data", "parameters": {"password": password}},
    )

    payload = response.json()
    assert response.status_code == 201
    assert payload["state"] == "failed"
    assert payload["risk"] == "governed_write"
    assert password not in response.text
    assert payload["provenance"]["parameters"]["password"] == "[redacted]"


def test_unsupported_connectors_and_completed_run_cancellation_are_recoverable() -> None:
    client = TestClient(create_app())
    dataset_id = upload(client)
    connection_id = f"local:{dataset_id}"

    unavailable = client.get("/api/v1/sql-lab/connections/unavailable:mysql/schema")
    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": connection_id, "sql": "SELECT * FROM data"}).json()
    run = terminal_run(client, submitted["run_id"])
    cancellation = client.post(f"/api/v1/sql-lab/runs/{run.run_id}/cancel")

    assert unavailable.status_code == 409
    assert cancellation.status_code == 409


def test_server_configured_sqlite_source_keeps_its_path_out_of_the_contract(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    database_path = tmp_path / "sales.sqlite"
    with sqlite3.connect(database_path) as database:
        database.execute("CREATE TABLE sales (id INTEGER PRIMARY KEY, region TEXT)")
        database.execute("INSERT INTO sales (region) VALUES ('North'), ('South')")
    monkeypatch.setenv("PRISM_SQLITE_SOURCES_JSON", json.dumps([{"id": "sales", "label": "Sales archive", "path": str(database_path)}]))
    client = TestClient(create_app())

    connections = client.get("/api/v1/sql-lab/connections")
    schema = client.get("/api/v1/sql-lab/connections/sqlite:sales/schema")
    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": "sqlite:sales", "sql": "SELECT * FROM sales ORDER BY id"}).json()
    run = terminal_run(client, submitted["run_id"])
    results = client.get(f"/api/v1/sql-lab/runs/{run.run_id}/results")

    assert connections.status_code == 200
    assert "sales.sqlite" not in connections.text
    assert schema.status_code == 200
    assert schema.json()["tables"][0]["name"] == "sales"
    assert run.state.value == "succeeded"
    assert results.json()["rows"] == [{"id": 1, "region": "North"}, {"id": 2, "region": "South"}]


def test_external_registry_never_returns_secret_reference_or_connection_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    secret_url = "mysql+pymysql://analyst:do-not-return@127.0.0.1:3307/prism_phase4"
    monkeypatch.setenv("PRISM_PHASE4_DATABASE_URL", secret_url)
    monkeypatch.setenv(
        "PRISM_EXTERNAL_SQL_SOURCES_JSON",
        json.dumps([{"id": "warehouse", "label": "Warehouse", "source_type": "mysql", "url_env": "PRISM_PHASE4_DATABASE_URL"}]),
    )
    response = TestClient(create_app()).get("/api/v1/sql-lab/connections")

    assert response.status_code == 200
    assert any(item["connection_id"] == "mysql:warehouse" for item in response.json())
    assert "do-not-return" not in response.text
    assert "PRISM_PHASE4_DATABASE_URL" not in response.text
