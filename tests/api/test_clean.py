from __future__ import annotations

import unittest.mock

from fastapi.testclient import TestClient
from prism_api.main import create_app

CSV = (
    b"segment,revenue,label\n"
    b"a,10,X\n"
    b"a,10,X\n"  # exact duplicate of row 1
    b"b,,y \n"  # missing revenue, needs trim/case normalization
    b"c,30,Z\n"
    b",40,W\n"  # missing segment
)


def _dataset(client: TestClient) -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": ("sales.csv", CSV, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_state_detects_duplicate_rows_and_missing_values_deterministically() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    first = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    second = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()

    kinds = {issue["kind"] for issue in first["issues"]}
    assert "duplicate_rows" in kinds
    assert "missing_values" in kinds
    assert first == second  # deterministic: same input, same issues, no side effects from reading state


def test_preview_never_mutates_the_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    before = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()

    preview = client.post(f"/api/v1/clean/datasets/{dataset_id}/preview", json={"operation": "drop_duplicates"})
    assert preview.status_code == 200
    assert preview.json()["affected_rows"] == 1

    after = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert after == before
    assert after["dataset"]["revision"] == 0


def test_apply_creates_a_new_revision_and_is_visible_to_overview_and_sql_lab() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    applied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert applied.status_code == 201
    body = applied.json()
    assert body["dataset"]["revision"] == 1
    assert body["dataset"]["row_count"] == 4  # one duplicate row removed
    assert body["transformation"]["source_revision"] == 0
    assert body["transformation"]["resulting_revision"] == 1
    assert body["transformation"]["affected_rows"] == 1

    # Overview now reflects the cleaned revision under the same dataset_id.
    profile = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()
    assert profile["dataset"]["revision"] == 1
    assert profile["quality"]["n_rows"] == 4

    # SQL Lab queries the same connection against the cleaned data, not the original.
    schema = client.get(f"/api/v1/sql-lab/connections/local:{dataset_id}/schema")
    assert schema.status_code == 200
    run = client.post("/api/v1/sql-lab/runs", json={"connection_id": f"local:{dataset_id}", "sql": "SELECT COUNT(*) AS n FROM data"})
    assert run.status_code == 201
    import time

    run_id = run.json()["run_id"]
    for _ in range(100):
        polled = client.get(f"/api/v1/sql-lab/runs/{run_id}").json()
        if polled["state"] not in {"queued", "running"}:
            break
        time.sleep(0.01)
    page = client.get(f"/api/v1/sql-lab/runs/{run_id}/results").json()
    assert page["rows"][0]["n"] == 4


def test_apply_rejects_an_unknown_column_rather_than_guessing() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_column", "column": "does_not_exist"})
    assert response.status_code == 422
    assert "does not exist" in response.json()["detail"]


def test_fill_missing_reports_affected_rows_and_preserves_row_count() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    response = client.post(
        f"/api/v1/clean/datasets/{dataset_id}/apply",
        json={"operation": "fill_missing", "column": "revenue", "fill_strategy": "median"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["transformation"]["affected_rows"] == 1
    assert body["dataset"]["row_count"] == 5


def test_undo_restores_the_prior_revision_and_drops_the_history_entry() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})

    state = client.post(f"/api/v1/clean/datasets/{dataset_id}/undo", json={"to_revision": 0}).json()
    assert state["dataset"]["revision"] == 0
    assert state["dataset"]["row_count"] == 5
    assert state["history"] == []

    # A fresh transformation after undo starts a clean new revision 1, not a collision.
    reapplied = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert reapplied.json()["dataset"]["revision"] == 1
    assert len(reapplied.json()["transformation"]["transformation_id"]) > 0


def test_transformation_history_accumulates_with_provenance() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "trim_whitespace", "column": "label"})

    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert [item["resulting_revision"] for item in state["history"]] == [1, 2]
    assert all(item["source_fingerprint"] != item["resulting_fingerprint"] for item in state["history"])


def test_transformation_history_is_reconstructed_from_durable_storage_not_a_process_cache() -> None:
    """Clean's history used to live only in a process-local dict, lost on
    every API restart even though the underlying revisions were already
    durable. Prove the fix by reading history through brand-new store/
    registry connections to the same database file -- exactly what a real
    restart leaves behind -- rather than through the running app's
    warmed-up singletons."""
    import prism_api.clean as clean_module
    from prism_api.durable_dataset_store import DurableDatasetStore
    from prism_api.durable_registry import DurableAnalyticalObjectRegistry, history_database_url

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "trim_whitespace", "column": "label"})
    before_restart = clean_module._durable_history(dataset_id)  # noqa: SLF001
    assert [item.resulting_revision for item in before_restart] == [1, 2]

    url = history_database_url()
    fresh_overview_store = DurableDatasetStore(url)
    fresh_registry = DurableAnalyticalObjectRegistry(url)
    with (
        unittest.mock.patch.object(clean_module, "overview_store", fresh_overview_store),
        unittest.mock.patch.object(clean_module, "registry", fresh_registry),
    ):
        after_restart = clean_module._durable_history(dataset_id)  # noqa: SLF001

    assert [item.resulting_revision for item in after_restart] == [1, 2]
    assert [item.transformation_id for item in after_restart] == [item.transformation_id for item in before_restart]
    assert [item.operation for item in after_restart] == [item.operation for item in before_restart]
    assert [item.source_fingerprint for item in after_restart] == [item.source_fingerprint for item in before_restart]
    assert [item.resulting_fingerprint for item in after_restart] == [item.resulting_fingerprint for item in before_restart]


def test_apply_reverts_the_revision_it_just_created_if_provenance_registration_fails() -> None:
    """A failure between committing the new revision and registering its
    provenance must not leave the mutation live behind a failed response --
    a client retry would otherwise apply on top of already-mutated data."""
    import prism_api.clean as clean_module

    client = TestClient(create_app())
    dataset_id = _dataset(client)

    with unittest.mock.patch.object(clean_module, "register_clean_transformation", side_effect=RuntimeError("history database unavailable")):
        response = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert response.status_code == 500

    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert state["dataset"]["revision"] == 0
    assert state["dataset"]["row_count"] == 5
    assert state["history"] == []

    # The dataset is usable again on the next attempt, not stuck mid-failure.
    retried = client.post(f"/api/v1/clean/datasets/{dataset_id}/apply", json={"operation": "drop_duplicates"})
    assert retried.status_code == 201
    assert retried.json()["dataset"]["revision"] == 1


def test_atlas_explains_an_issue_and_proposes_a_previewable_fix_without_applying_it() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    issues = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()["issues"]
    duplicate_issue = next(item for item in issues if item["kind"] == "duplicate_rows")

    explained = client.post(f"/api/v1/clean/datasets/{dataset_id}/atlas", json={"action": "explain_issue", "issue_id": duplicate_issue["issue_id"]})
    assert explained.status_code == 200
    assert explained.json()["proposed_operation"]["operation"] == "drop_duplicates"

    # Atlas never applied anything - the dataset is still at revision 0.
    state = client.get(f"/api/v1/clean/datasets/{dataset_id}/state").json()
    assert state["dataset"]["revision"] == 0
