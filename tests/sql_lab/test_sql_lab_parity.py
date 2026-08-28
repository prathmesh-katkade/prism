from __future__ import annotations

import pandas as pd
from prism_sql_lab_runtime import classify_query, execute_local_query

from modules import sql_lab as legacy_sql_lab


def representative_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "order_id": [1, 2, 3, 4],
            "segment": ["North", "South", None, "North"],
            "revenue": [10.5, None, 12.0, 9.5],
        }
    )


def test_local_read_results_schema_nulls_and_order_match_legacy_duckdb() -> None:
    frame = representative_frame()
    sql = "SELECT segment, revenue FROM data WHERE revenue IS NOT NULL ORDER BY revenue DESC"

    legacy_result, legacy_error, _legacy_elapsed = legacy_sql_lab.run_query(frame, sql)
    result, error, _elapsed = execute_local_query(frame, sql)

    assert legacy_error is None
    assert error is None
    assert result is not None
    assert legacy_result is not None
    pd.testing.assert_frame_equal(result, legacy_result, check_dtype=True)


def test_parameterized_local_read_has_explicit_safe_read_classification() -> None:
    result, error, _elapsed = execute_local_query(
        representative_frame(), "SELECT * FROM data WHERE revenue > $minimum ORDER BY order_id", {"minimum": 10}
    )

    assert error is None
    assert result is not None
    assert result["order_id"].tolist() == [1, 3]
    assert classify_query("-- audit\nSELECT * FROM data").is_read_only
    assert not classify_query("DROP TABLE data").is_read_only


def test_server_side_result_cap_limits_materialization_before_result_delivery() -> None:
    frame = pd.DataFrame({"id": range(10_000)})
    result, error, _elapsed = execute_local_query(frame, "SELECT * FROM data ORDER BY id", max_result_rows=101)

    assert error is None
    assert result is not None
    assert len(result) == 101
    assert result["id"].iloc[-1] == 100


def test_classifier_blocks_stacked_statements_and_mutating_ctes_without_false_literal_hits() -> None:
    assert not classify_query("SELECT * FROM data; DROP TABLE data").is_read_only
    assert not classify_query("WITH changed AS (DELETE FROM data RETURNING *) SELECT * FROM changed").is_read_only
    assert classify_query("SELECT 'drop table data' AS harmless FROM data").is_read_only
    assert classify_query('SELECT "update" FROM data').is_read_only


def test_local_query_disables_duckdb_external_file_access() -> None:
    result, error, _elapsed = execute_local_query(representative_frame(), "SELECT read_text('nonexistent-secret.txt')")

    assert result is None
    assert error is not None
