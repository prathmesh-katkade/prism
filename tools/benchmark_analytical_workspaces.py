"""Reproducible, non-sensitive 100k-row analytical-workspace measurement.

Run with an explicit temporary SQLite PRISM_ANALYTICAL_HISTORY_DATABASE_URL.
This script records observed durations; it defines no post-hoc pass threshold.
"""

from __future__ import annotations

import io
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Callable

from fastapi.testclient import TestClient
from prism_api.main import create_app

ROWS = 100_000
OUTPUT = Path("docs/analytical-workspaces-v1/performance-100k.json")


def fixture() -> bytes:
    lines = ["record_id,segment,revenue,ordered_at\n"]
    for index in range(ROWS):
        actual = index - 1 if index % 100 == 99 else index
        segment = ("North", "South", "East", "West")[actual % 4]
        revenue = "" if actual % 50 == 0 else str((actual % 20) * 10 + 5)
        lines.append(f"r{actual},{segment},{revenue},2025-01-{actual % 28 + 1:02d}\n")
    return "".join(lines).encode("utf-8")


def measure(label: str, operation: Callable[[], Any], durations: dict[str, float]) -> Any:
    started = time.perf_counter()
    result = operation()
    durations[label] = round((time.perf_counter() - started) * 1000, 2)
    return result


def main() -> None:
    database = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", "")
    if not database.startswith("sqlite:///") or "Temp" not in database:
        raise SystemExit("Set PRISM_ANALYTICAL_HISTORY_DATABASE_URL to an explicit isolated Temp SQLite file.")
    client = TestClient(create_app())
    durations: dict[str, float] = {}
    payload = measure("fixture_generation_ms", fixture, durations)
    uploaded = measure("upload_ms", lambda: client.post("/api/v1/overview/datasets", files={"file": ("generated-100k.csv", io.BytesIO(payload), "text/csv")}), durations)
    assert uploaded.status_code == 201, uploaded.text
    dataset_id = uploaded.json()["dataset_id"]
    profile = measure("profile_ms", lambda: client.get(f"/api/v1/overview/datasets/{dataset_id}/profile"), durations)
    assert profile.status_code == 200, profile.text
    preview = measure("clean_preview_ms", lambda: client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={
        "operation": "category_mapping", "column": "segment", "category_mapping": {"North": "Northern"},
    }), durations)
    assert preview.status_code == 200, preview.text
    assert preview.json()["affected_rows"] == 25_000
    applied = measure("clean_apply_ms", lambda: client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={
        "operation": "category_mapping", "column": "segment", "category_mapping": {"North": "Northern"},
        "review_token": preview.json()["review_token"],
    }), durations)
    assert applied.status_code == 201, applied.text
    query = measure("sql_submit_ms", lambda: client.post("/api/v1/sql-lab/runs", json={
        "connection_id": f"local:{dataset_id}", "sql": "SELECT segment, COUNT(*) AS rows FROM data GROUP BY segment ORDER BY segment",
    }), durations)
    assert query.status_code == 201, query.text
    run_id = query.json()["run_id"]
    started = time.perf_counter()
    while True:
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}")
        assert run.status_code == 200, run.text
        if run.json()["state"] not in {"queued", "running"}:
            break
        if time.perf_counter() - started > 30:
            raise AssertionError("SQL run exceeded the existing 30 second observation window")
        time.sleep(0.05)
    durations["sql_to_terminal_ms"] = round((time.perf_counter() - started) * 1000, 2)
    assert run.json()["state"] == "succeeded", run.text
    sql_page = client.get(f"/api/v1/sql-lab/runs/{run_id}/results")
    assert sql_page.status_code == 200
    spec = {"mark": "bar", "intent": "comparison", "dimension": "segment", "aggregation": "count", "filters": {"segment": ["Northern", "South"]}}
    rendered = measure("chart_render_ms", lambda: client.post(f"/api/v1/visualize/datasets/{dataset_id}/render", json=spec), durations)
    assert rendered.status_code == 200, rendered.text
    chart = measure("chart_save_ms", lambda: client.post("/api/v1/reports/charts", json={
        "name": "Selected segments", "dataset_id": dataset_id, "spec": spec,
        "source_revision": rendered.json()["provenance"]["dataset_revision"],
        "source_fingerprint": rendered.json()["provenance"]["source_fingerprint"],
    }), durations)
    assert chart.status_code == 201, chart.text
    report = client.post("/api/v1/reports", json={"name": "100k review"})
    assert report.status_code == 201
    added = measure("report_add_chart_ms", lambda: client.post(f"/api/v1/reports/{report.json()['report_id']}/charts", json={"chart_id": chart.json()["chart_id"]}), durations)
    assert added.status_code == 200, added.text
    report_detail = measure("report_reopen_ms", lambda: client.get(f"/api/v1/reports/{report.json()['report_id']}"), durations)
    assert report_detail.status_code == 200, report_detail.text
    expected = {"rows": ROWS, "exact_duplicate_rows": 1_000, "north_rows_renamed": 25_000}
    actual = {"rows": uploaded.json()["row_count"], "north_rows_renamed": preview.json()["affected_rows"],
              "sql_group_rows": {row["segment"]: row["rows"] for row in sql_page.json()["rows"]},
              "chart_points": rendered.json()["data"]}
    assert actual["rows"] == expected["rows"]
    assert actual["sql_group_rows"]["Northern"] == expected["north_rows_renamed"]
    result = {"fixture": "generated deterministic 100,000-row business export; 1,000 exact duplicate rows; 2,000 intended missing revenue cells before duplicate substitution",
              "fixture_bytes": len(payload), "expected": expected, "actual": actual, "durations_ms": durations,
              "environment": {"system": platform.platform(), "processor": platform.processor(), "logical_cpus": os.cpu_count(), "python": platform.python_version(), "database": "isolated SQLite file in Temp"},
              "limits": {"clean_row_inspection_sample": 100, "sql_result_limit": 1000, "scatter_sample_limit": 500, "report_table_snapshot_limit": 100},
              "measurement_scope": "In-process FastAPI TestClient wall clock; includes local persistence and service work, excludes network/browser rendering. Single observed run, no warmup or threshold."}
    OUTPUT.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
