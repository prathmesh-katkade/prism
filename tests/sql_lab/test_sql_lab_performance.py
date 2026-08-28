from __future__ import annotations

import time

import pandas as pd
from prism_sql_lab_runtime import execute_local_query, schema_for_frame


def test_large_local_query_and_schema_overhead_stay_within_phase_4_baseline() -> None:
    frame = pd.DataFrame(
        {
            "id": range(500_000),
            "segment": ["north", "south"] * 250_000,
            "value": [float(value % 100) for value in range(500_000)],
        }
    )
    schema_started = time.perf_counter()
    schema = schema_for_frame(frame)
    schema_ms = int((time.perf_counter() - schema_started) * 1_000)
    result, error, query_ms = execute_local_query(
        frame,
        "SELECT segment, SUM(value) AS total FROM data GROUP BY segment ORDER BY segment",
        max_result_rows=1_001,
    )

    assert len(schema) == 3
    assert schema_ms < 1_500
    assert error is None
    assert result is not None
    assert len(result) == 2
    assert query_ms < 2_000


def test_large_result_is_capped_before_grid_delivery_with_bounded_overhead() -> None:
    frame = pd.DataFrame({"id": range(500_000)})
    result, error, query_ms = execute_local_query(
        frame,
        "SELECT * FROM data ORDER BY id",
        max_result_rows=1_001,
    )

    assert error is None
    assert result is not None
    assert len(result) == 1_001
    assert query_ms < 2_000
