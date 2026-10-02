from __future__ import annotations

import time

from fastapi.testclient import TestClient
from prism_api.main import create_app

CSV_V1 = b"id,status,amount\n1,open,100\n2,open,200\n3,closed,50\n"
CSV_V2 = b"id,status,amount\n1,closed,100\n2,open,250\n4,open,10\n"  # 1 changed (status), 2 changed (amount), 3 removed, 4 added


def _run(client: TestClient, connection_id: str, sql: str) -> str:
    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": connection_id, "sql": sql})
    assert submitted.status_code == 201
    run_id = submitted.json()["run_id"]
    for _ in range(100):
        polled = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if polled["state"] not in {"queued", "running"}:
            assert polled["state"] == "succeeded", polled
            return run_id
        time.sleep(0.01)
    raise AssertionError("run did not reach a terminal state")


def test_compare_results_reports_added_removed_and_changed_rows_by_declared_key() -> None:
    client = TestClient(create_app())
    base_dataset = client.post("/api/v1/overview/datasets", files={"file": ("v1.csv", CSV_V1, "text/csv")}).json()["dataset_id"]
    compare_dataset = client.post("/api/v1/overview/datasets", files={"file": ("v2.csv", CSV_V2, "text/csv")}).json()["dataset_id"]
    base_run = _run(client, f"local:{base_dataset}", "SELECT * FROM data")
    compare_run = _run(client, f"local:{compare_dataset}", "SELECT * FROM data")

    response = client.post("/api/v1/sql-lab/runs/compare", json={"base_run_id": base_run, "compare_run_id": compare_run, "key_columns": ["id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["added_count"] == 1  # id=4
    assert body["removed_count"] == 1  # id=3
    assert body["changed_count"] == 2  # id=1 (status), id=2 (amount)
    assert body["unchanged_count"] == 0

    diffs_by_key = {tuple(sorted(d["key"].items())): d for d in body["sample_diffs"]}
    added = next(d for d in body["sample_diffs"] if d["change"] == "added")
    assert added["key"]["id"] == "4"  # keys travel as strings (joined/compared as text)
    removed = next(d for d in body["sample_diffs"] if d["change"] == "removed")
    assert removed["key"]["id"] == "3"
    changed = [d for d in body["sample_diffs"] if d["change"] == "changed"]
    assert len(changed) == 2
    status_change = next(d for d in changed if "status" in d["changed_columns"])
    assert status_change["base_values"]["status"] == "open"
    assert status_change["compare_values"]["status"] == "closed"
    assert diffs_by_key  # sanity: dict built without error


def test_compare_results_rejects_a_key_column_missing_from_either_result() -> None:
    client = TestClient(create_app())
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("v1.csv", CSV_V1, "text/csv")}).json()["dataset_id"]
    run_id = _run(client, f"local:{dataset_id}", "SELECT * FROM data")
    response = client.post("/api/v1/sql-lab/runs/compare", json={"base_run_id": run_id, "compare_run_id": run_id, "key_columns": ["not_a_real_column"]})
    assert response.status_code == 422


def test_compare_results_discloses_duplicate_keys_instead_of_silently_picking_one() -> None:
    client = TestClient(create_app())
    csv_with_dupes = b"id,amount\n1,10\n1,20\n2,30\n"
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("dupes.csv", csv_with_dupes, "text/csv")}).json()["dataset_id"]
    run_id = _run(client, f"local:{dataset_id}", "SELECT * FROM data")
    response = client.post("/api/v1/sql-lab/runs/compare", json={"base_run_id": run_id, "compare_run_id": run_id, "key_columns": ["id"]})
    assert response.status_code == 200
    body = response.json()
    assert body["duplicate_key_count_base"] == 2  # both id=1 rows
    assert body["duplicate_key_count_compare"] == 2
    assert any("duplicated key" in warning for warning in body["warnings"])
    assert body["unchanged_count"] == 1  # only id=2 is unambiguous


def test_compare_results_requires_both_runs_to_have_succeeded() -> None:
    client = TestClient(create_app())
    dataset_id = client.post("/api/v1/overview/datasets", files={"file": ("v1.csv", CSV_V1, "text/csv")}).json()["dataset_id"]
    failed = client.post("/api/v1/sql-lab/runs", json={"connection_id": f"local:{dataset_id}", "sql": "DROP TABLE data"})
    failed_run_id = failed.json()["run_id"]
    good_run_id = _run(client, f"local:{dataset_id}", "SELECT * FROM data")
    response = client.post("/api/v1/sql-lab/runs/compare", json={"base_run_id": failed_run_id, "compare_run_id": good_run_id, "key_columns": ["id"]})
    assert response.status_code == 422


def test_compare_results_rejects_an_unknown_run_id() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/sql-lab/runs/compare", json={"base_run_id": "run_does_not_exist", "compare_run_id": "run_also_missing", "key_columns": ["id"]})
    assert response.status_code == 404
