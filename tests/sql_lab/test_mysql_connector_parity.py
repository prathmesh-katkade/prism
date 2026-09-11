from __future__ import annotations

import os
import time
from decimal import Decimal
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
from prism_sql_lab_runtime.external import _normalize_decimal_columns

from modules import db_connect
from modules import sql_lab as legacy_sql_lab

MYSQL_URL = os.environ.get("PRISM_PHASE4_MYSQL_URL")


def test_mysql_attach_omits_an_empty_password_option() -> None:
    clause = db_connect.build_attach_clause(
        "mysql",
        {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "root",
            "password": "",
            "database": "prism_phase4",
        },
        alias="live",
    )

    assert "passwd=" not in clause
    assert "user=root db=prism_phase4" in clause


def test_mysql_attach_includes_a_configured_password() -> None:
    clause = db_connect.build_attach_clause(
        "mysql",
        {
            "host": "127.0.0.1",
            "port": 3306,
            "user": "prism",
            "password": "configured-secret",
            "database": "prism_phase4",
        },
        alias="live",
    )

    assert "passwd=configured-secret" in clause


def test_normalize_decimal_columns_converts_decimal_to_float_but_preserves_other_null_columns() -> None:
    """Regression test for the int64/int32 + Decimal/object parity gap this connector used to hit
    against DuckDB's mysql_scanner path — deterministic, no live database required."""
    frame = pd.DataFrame({
        "id": [1, 2, 3],
        "revenue": [Decimal("10.50"), None, Decimal("12.00")],
        "note": [None, None, None],  # an all-null non-numeric column must not be force-cast to float
    })

    normalized = _normalize_decimal_columns(frame)

    assert normalized["revenue"].dtype == "float64"
    assert normalized["revenue"].tolist()[1] != normalized["revenue"].tolist()[1]  # NaN
    assert normalized["revenue"].tolist()[0] == 10.5
    assert normalized["note"].dtype == object


@pytest.mark.skipif(not MYSQL_URL, reason="Phase 4 MySQL parity source is not configured")
def test_mysql_results_schema_nulls_order_plan_and_legacy_parity() -> None:
    assert MYSQL_URL is not None
    parsed = urlparse(MYSQL_URL)
    database = parsed.path.lstrip("/")
    legacy_params = {
        "host": parsed.hostname or "127.0.0.1",
        "port": parsed.port or 3306,
        "database": database,
        "user": parsed.username or "root",
        "password": parsed.password or "",
    }
    source = ExternalSource("phase4", "Phase 4 MySQL", "mysql", MYSQL_URL)
    sql = "SELECT id, region, revenue FROM sales ORDER BY id"

    legacy_outcome = legacy_sql_lab.run_query_multi(
        {},
        "SELECT id, region, revenue FROM live.sales ORDER BY id",
        attach_clause=db_connect.build_attach_clause("mysql", legacy_params, alias="live"),
        attach_extension=db_connect.extension_for_engine("mysql"),
    )
    legacy = legacy_outcome["result_df"]
    legacy_error = legacy_outcome["error"]
    native, native_error, _duration = execute_external_query(source, sql, max_result_rows=101)
    schema = external_schema(source)
    plan, plan_error = external_plan(source, sql)

    assert legacy_error is None
    assert native_error is None
    assert legacy is not None
    assert native is not None
    assert not legacy_outcome["truncated"]
    # check_dtype=False: the native (pymysql/SQLAlchemy) and legacy (DuckDB mysql_scanner) paths
    # are two different engines reading the same MySQL INT column, and each infers a different
    # (individually correct) integer width for it — pandas int64 vs DuckDB's int32. Values,
    # column order, and nullability are still asserted exactly; only the numpy bit-width is
    # exempted, which is an implementation detail neither engine's caller should depend on.
    pd.testing.assert_frame_equal(native, legacy, check_dtype=False)
    for column in ("id",):
        assert pd.api.types.is_integer_dtype(native[column]) and pd.api.types.is_integer_dtype(legacy[column]), (
            f"{column!r} should stay integer-typed on both paths even though check_dtype=False"
        )
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
