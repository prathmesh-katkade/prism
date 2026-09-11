"""Phase 8F: reproducibility + safe rerun. A rerun never overwrites an existing
analytical object - it always creates a new one, leaving the original untouched.
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from prism_analytical_schemas import ObjectKind
from prism_api.analytical_objects import registry
from prism_api.main import create_app


def _dataset(client: TestClient, csv: bytes = b"x,y,segment,label\n1,10,a,yes\n2,20,a,no\n3,30,b,yes\n4,40,b,no\n5,50,a,yes\n6,60,b,no\n", name: str = "phase8f.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _forecast_csv(values: list[float]) -> bytes:
    import io

    import pandas as pd

    dates = pd.date_range("2026-01-01", periods=len(values), freq="D")
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), "revenue": values})
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


FORECAST_CSV = _forecast_csv([10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0])


def _classification_csv() -> bytes:
    import io

    import pandas as pd

    rows = []
    for i in range(40):
        x1 = float(i % 10)
        x2 = float((i * 3) % 7)
        segment = "a" if i % 3 == 0 else "b" if i % 3 == 1 else "c"
        label = "yes" if (x1 + x2) > 8 else "no"
        rows.append({"x1": x1, "x2": x2, "segment": segment, "label": label})
    buffer = io.StringIO()
    pd.DataFrame(rows).to_csv(buffer, index=False)
    return buffer.getvalue().encode()


CLASSIFICATION_CSV = _classification_csv()


def _rerun(client: TestClient, object_id: str, mode: str = "current_revision"):
    return client.post(f"/api/v1/lineage/objects/{object_id}/rerun", json={"mode": mode})


# --- Stats -------------------------------------------------------------------------------


def test_stats_current_revision_rerun_creates_a_new_object_and_leaves_the_original_untouched() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    response = _rerun(client, original.object_id, "current_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "created"
    assert body["new_object"]["object_id"] != original.object_id
    assert body["new_object"]["kind"] == "analysis"

    refetched_original = registry.get(original.object_id)
    assert refetched_original is not None
    assert refetched_original.provenance.created_at == original.provenance.created_at
    assert refetched_original.object_id == original.object_id


def test_stats_same_revision_rerun_targets_the_exact_original_dataset_identity() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    response = _rerun(client, original.object_id, "same_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "created"
    assert body["new_object"]["provenance"]["dataset"]["revision"] == 0


def test_stats_missing_column_fails_cleanly_without_silent_adaptation() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_column", "column": "y"})

    response = _rerun(client, original.object_id, "current_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "validation_failed"
    assert "y" in body["detail"]


# --- Forecast ------------------------------------------------------------------------------


def test_forecast_rerun_creates_a_new_forecast_object() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=FORECAST_CSV, name="forecast8f.csv")
    client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 5})
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.FORECAST)

    response = _rerun(client, original.object_id, "current_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "created"
    assert body["new_object"]["object_id"] != original.object_id
    assert body["new_object"]["kind"] == "forecast"


# --- ML ------------------------------------------------------------------------------------


def test_ml_baseline_rerun_creates_a_new_object() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=CLASSIFICATION_CSV, name="ml8f.csv")
    client.post(f"/api/v1/ml/datasets/{dataset_id}/baseline", json={"feature_cols": ["x1", "x2", "segment"], "target_col": "label"})
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ML_MODEL)

    response = _rerun(client, original.object_id, "current_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "created"
    assert body["new_object"]["object_id"] != original.object_id


# --- Visualize -----------------------------------------------------------------------------


def test_visualize_rerun_creates_a_new_object() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(
        f"/api/v1/visualize/datasets/{dataset_id}/render",
        json={"mark": "bar", "intent": "comparison", "dimension": "segment", "measure": "y", "aggregation": "sum", "filters": {}, "max_categories": 20},
    )
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.VISUALIZATION)

    response = _rerun(client, original.object_id, "current_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "created"
    assert body["new_object"]["object_id"] != original.object_id


# --- Unsupported kinds -----------------------------------------------------------------------


def test_sql_rerun_is_cleanly_unsupported() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    submitted = client.post("/api/v1/sql-lab/runs", json={"connection_id": f"local:{dataset_id}", "sql": "SELECT * FROM data"})
    import time

    run_id = submitted.json()["run_id"]
    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    sql_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]

    response = _rerun(client, sql_record.object_id, "current_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "unsupported"
    assert body["new_object"] is None


def test_dataset_revision_rerun_is_cleanly_unsupported() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    dsrev = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.DATASET_REVISION)[0]

    response = _rerun(client, dsrev.object_id, "current_revision")
    body = response.json()
    assert body["outcome"] == "unsupported"


# --- Missing revision --------------------------------------------------------------------------


def test_same_revision_rerun_reports_unavailable_after_the_branch_is_abandoned() -> None:
    """DatasetStore.revert truncates history forward of the target revision - an object
    tied to an abandoned undo/redo branch's exact (revision, fingerprint) identity
    becomes genuinely unresolvable for a same_revision rerun, and that must be reported
    honestly rather than silently rerun against the wrong (still-current) data."""
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv=b"x,y\n1,2\n1,2\n,4\n5,6\n7,8\n")
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    branch_a = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "x", "fill_strategy": "median"})
    assert branch_a.status_code == 201
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    stats_on_branch_a = next(r for r in registry.list_for_dataset(dataset_id, revision=2) if r.kind is ObjectKind.ANALYSIS)

    client.post(f"/api/v1/clean/datasets/{dataset_id}/undo", json={"to_revision": 1})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "fill_missing", "column": "y", "fill_strategy": "median"})
    # branch_a's revision 2 is now gone from DatasetStore's history entirely.

    response = _rerun(client, stats_on_branch_a.object_id, "same_revision")
    assert response.status_code == 200
    body = response.json()
    assert body["outcome"] == "source_revision_unavailable"
    assert body["new_object"] is None


# --- Idempotency / no overwrite --------------------------------------------------------------


def test_multiple_reruns_each_create_a_distinct_object_never_overwriting_each_other() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/stats/datasets/{dataset_id}/run", json={"test": "pearson", "col_a": "x", "col_b": "y"})
    original = next(r for r in registry.list_for_dataset(dataset_id, revision=0) if r.kind is ObjectKind.ANALYSIS)

    first = _rerun(client, original.object_id, "current_revision").json()
    second = _rerun(client, original.object_id, "current_revision").json()
    ids = {original.object_id, first["new_object"]["object_id"], second["new_object"]["object_id"]}
    assert len(ids) == 3


# --- Not found ------------------------------------------------------------------------------


def test_rerun_404s_for_an_unknown_object() -> None:
    client = TestClient(create_app())
    assert _rerun(client, "does-not-exist").status_code == 404


# --- Security ------------------------------------------------------------------------------


def test_no_secret_leakage_through_the_rerun_response() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    submitted = client.post(
        "/api/v1/sql-lab/runs",
        json={"connection_id": f"local:{dataset_id}", "sql": "SELECT * FROM data WHERE segment = $api_key", "parameters": {"api_key": "sk-should-not-leak-d"}},
    )
    import time

    run_id = submitted.json()["run_id"]
    for _ in range(200):
        run = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if run["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    sql_record = registry.list_for_dataset(dataset_id, revision=0, kind=ObjectKind.QUERY_RESULT)[0]

    response = _rerun(client, sql_record.object_id, "current_revision")
    assert "sk-should-not-leak" not in response.text
