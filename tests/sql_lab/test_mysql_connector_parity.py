from __future__ import annotations

import os
import time
from urllib.parse import urlparse

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_sql_lab_runtime import (
    ExternalSource,
    execute_external_query,
    external_plan,
    external_schema,
)

from modules import sql_lab as legacy_sql_lab

MYSQL_URL = os.environ.get("PRISM_PHASE4_MYSQL_URL")


@pytest.mark.skipif(not MYSQL_URL, reason="Phase 4 MySQL parity source is not configured")
def test_mysql_results_schema_nulls_order_plan_and_legacy_parity() -> None:
    assert MYSQL_URL is not None
    parsed = urlparse(MYSQL_URL)
    database = parsed.path.lstrip("/")
    info = legacy_sql_lab.MySQLConnectionInfo(
        host=parsed.hostname or "127.0.0.1",
        port=parsed.port or 3306,
        database=database,
        user=parsed.username or "root",
        password=parsed.password or "",
        label="Phase 4 parity",
    )
    engine, engine_error = legacy_sql_lab.build_mysql_engine(info)
    assert engine_error is None
    assert engine is not None
    source = ExternalSource("phase4", "Phase 4 MySQL", "mysql", MYSQL_URL)
    sql = "SELECT id, region, revenue FROM sales ORDER BY id"

    try:
        legacy, legacy_error, _elapsed, legacy_truncated = legacy_sql_lab.run_mysql_query(engine, sql)
        native, native_error, _duration = execute_external_query(source, sql, max_result_rows=101)
        schema = external_schema(source)
        plan, plan_error = external_plan(source, sql)
    finally:
        legacy_sql_lab.close_mysql_engine(engine)

    assert legacy_error is None
    assert native_error is None
    assert legacy is not None
    assert native is not None
    assert not legacy_truncated
    pd.testing.assert_frame_equal(native, legacy, check_dtype=True)
    assert schema[0]["name"] == "sales"
    assert [column["name"] for column in schema[0]["columns"]] == ["id", "region", "revenue"]
    assert plan_error is None
    assert plan


@pytest.mark.skipif(not MYSQL_URL, reason="Phase 4 MySQL parity source is not configured")
def test_mysql_connector_contract_runs_end_to_end_without_exposing_its_url(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert MYSQL_URL is not None
    monkeypatch.setenv("PRISM_PHASE4_MYSQL_URL", MYSQL_URL)
    monkeypatch.setenv(
        "PRISM_EXTERNAL_SQL_SOURCES_JSON",
        '[{"id":"phase4","label":"Phase 4 MySQL","source_type":"mysql","url_env":"PRISM_PHASE4_MYSQL_URL"}]',
    )
    client = TestClient(create_app())

    connections = client.get("/api/v1/sql-lab/connections")
    schema = client.get("/api/v1/sql-lab/connections/mysql:phase4/schema")
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": "mysql:phase4", "sql": "SELECT * FROM sales ORDER BY id"},
    )
    run_id = submitted.json()["run_id"]
    run = submitted.json()
    for _ in range(100):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    results = client.get(f"/api/v1/sql-lab/runs/{run_id}/results")
    plan = client.post(
        "/api/v1/sql-lab/plans",
        json={"connection_id": "mysql:phase4", "sql": "SELECT * FROM sales"},
    )

    assert connections.status_code == 200
    assert MYSQL_URL not in connections.text
    assert schema.status_code == 200
    assert submitted.status_code == 201
    assert run["state"] == "succeeded"
    assert results.status_code == 200
    assert len(results.json()["rows"]) == 3
    assert plan.json()["supported"]


@pytest.mark.skipif(not MYSQL_URL, reason="Phase 4 MySQL parity source is not configured")
def test_mysql_connector_cancels_a_live_query(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert MYSQL_URL is not None
    monkeypatch.setenv("PRISM_PHASE4_MYSQL_URL", MYSQL_URL)
    monkeypatch.setenv(
        "PRISM_EXTERNAL_SQL_SOURCES_JSON",
        '[{"id":"phase4","label":"Phase 4 MySQL","source_type":"mysql","url_env":"PRISM_PHASE4_MYSQL_URL"}]',
    )
    client = TestClient(create_app())
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": "mysql:phase4", "sql": "SELECT SLEEP(5) AS waited", "timeout_ms": 10_000},
    )
    run_id = submitted.json()["run_id"]
    cancellation = client.post(f"/api/v1/sql-lab/runs/{run_id}/cancel")

    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)

    assert cancellation.status_code == 200
    assert run["state"] == "cancelled"


@pytest.mark.skipif(not MYSQL_URL, reason="Phase 4 MySQL parity source is not configured")
def test_mysql_connector_enforces_runtime_timeout(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    assert MYSQL_URL is not None
    monkeypatch.setenv("PRISM_PHASE4_MYSQL_URL", MYSQL_URL)
    monkeypatch.setenv(
        "PRISM_EXTERNAL_SQL_SOURCES_JSON",
        '[{"id":"phase4","label":"Phase 4 MySQL","source_type":"mysql","url_env":"PRISM_PHASE4_MYSQL_URL"}]',
    )
    client = TestClient(create_app())
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": "mysql:phase4", "sql": "SELECT SLEEP(5) AS waited", "timeout_ms": 100},
    )
    run_id = submitted.json()["run_id"]

    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)

    assert run["state"] == "timed_out"
