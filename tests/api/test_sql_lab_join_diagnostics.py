from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api.sql_lab_join_diagnostics import _detect_equi_joins, _quote
from prism_api_contracts import SqlDialect

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


def test_quote_uses_backticks_for_mysql_and_double_quotes_for_every_other_dialect() -> None:
    """MySQL rejects double-quoted identifiers unless the non-default ANSI_QUOTES
    sql_mode is enabled -- it parses `"x"` as a string literal and raises a syntax
    error on the SQL around it. Every other connected dialect here (DuckDB,
    PostgreSQL, SQL Server with its default QUOTED_IDENTIFIER setting, SQLite)
    accepts standard double-quote identifier quoting, so only MySQL needs its own
    branch. Regression test for join diagnostics failing outright against every
    real MySQL connection (caught via a live MySQL connector, not local DuckDB)."""
    assert _quote("customer_id", SqlDialect.MYSQL) == "`customer_id`"
    assert _quote("customer_id", SqlDialect.DUCKDB) == '"customer_id"'
    assert _quote("customer_id", SqlDialect.POSTGRESQL) == '"customer_id"'
    assert _quote("customer_id", SqlDialect.SQLSERVER) == '"customer_id"'
    assert _quote("customer_id", SqlDialect.SQLITE) == '"customer_id"'


def test_quote_escapes_an_embedded_quote_character_per_dialect() -> None:
    assert _quote("weird`col", SqlDialect.MYSQL) == "`weird``col`"
    assert _quote('weird"col', SqlDialect.DUCKDB) == '"weird""col"'


def test_detect_equi_joins_reports_the_real_join_kind_not_a_blanket_inner_default() -> None:
    """Regression test: sqlglot splits a join's type across two attributes --
    `side` (LEFT/RIGHT/FULL) and `kind` (INNER/OUTER/CROSS) -- a LEFT JOIN has
    side="LEFT" and kind="" (empty), so reading `kind` alone always fell
    through to the "inner" default, misreporting every outer join as inner.
    That also made the UI's "unmatched rows retained by INNER JOIN" message
    self-contradictory, since an inner join is exactly what drops unmatched
    rows rather than retaining them."""
    cases = {
        "SELECT * FROM a JOIN b ON a.id = b.id": "inner",
        "SELECT * FROM a INNER JOIN b ON a.id = b.id": "inner",
        "SELECT * FROM a LEFT JOIN b ON a.id = b.id": "left",
        "SELECT * FROM a RIGHT JOIN b ON a.id = b.id": "right",
        "SELECT * FROM a FULL JOIN b ON a.id = b.id": "full",
        "SELECT * FROM a FULL OUTER JOIN b ON a.id = b.id": "full",
        "SELECT * FROM a LEFT OUTER JOIN b ON a.id = b.id": "left",
    }
    for sql, expected_kind in cases.items():
        joins, notes = _detect_equi_joins(sql, "mysql")
        assert not notes, f"{sql!r} produced unsupported_notes: {notes}"
        assert len(joins) == 1
        assert joins[0].join_kind == expected_kind, f"{sql!r}: expected {expected_kind!r}, got {joins[0].join_kind!r}"


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
