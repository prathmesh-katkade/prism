from fastapi.testclient import TestClient
from prism_api.analytical_objects import registry
from prism_api.main import create_app


def _dataset(client: TestClient) -> str:
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("phase8.csv", b"x,y,label\n1,2,a\n2,4,a\n3,6,b\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_stats_registers_a_completed_analysis_bound_to_the_active_revision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    response = client.post(
        f"/api/v1/stats/datasets/{dataset_id}/run",
        json={"test": "pearson", "col_a": "x", "col_b": "y"},
    )
    assert response.status_code == 200

    records = registry.list_for_dataset(dataset_id, revision=0)
    stats_record = next(record for record in records if record.kind.value == "analysis")
    assert stats_record.lifecycle.value == "completed"
    assert stats_record.provenance.reproducibility.kind.value == "statistical_test"
    assert stats_record.provenance.reproducibility.columns == ["x", "y"]


def test_clean_registers_a_completed_object_for_the_new_dataset_revision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    response = client.post(
        f"/api/v1/clean/datasets/{dataset_id}/apply",
        json={"operation": "drop_duplicates"},
    )
    assert response.status_code == 201

    records = registry.list_for_dataset(dataset_id, revision=1)
    clean_record = next(record for record in records if record.kind.value == "cleaning_plan")
    assert clean_record.lifecycle.value == "completed"
    assert clean_record.provenance.reproducibility.kind.value == "cleaning"
    assert clean_record.provenance.reproducibility.operation == "drop_duplicates"
