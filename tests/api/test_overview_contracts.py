from __future__ import annotations

from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api_contracts.models import AtlasOverviewResponse, OverviewProfileResponse


def upload(client: TestClient) -> str:
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("sales.csv", b"id,revenue,segment\n1,10,a\n2,12,b\n2,12,b\n4,400,a\n", "text/csv")},
    )
    assert response.status_code == 201
    return response.json()["dataset_id"]


def test_overview_profile_and_paginated_rows_are_typed_and_provenanced() -> None:
    client = TestClient(create_app())
    dataset_id = upload(client)

    profile_response = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile")
    rows_response = client.get(f"/api/v1/overview/datasets/{dataset_id}/rows?offset=0&limit=2")

    profile = OverviewProfileResponse.model_validate(profile_response.json())
    assert profile_response.status_code == 200
    assert profile.quality.duplicate_rows == 1
    assert profile.provenance.source_fingerprint == profile.dataset.source_fingerprint
    assert profile.provenance.parameters["outlier_method"] == "iqr_tukey_1.5"
    assert rows_response.status_code == 200
    assert len(rows_response.json()["rows"]) == 2
    assert "revenue" in rows_response.json()["rows"][0]


def test_atlas_overview_actions_are_grounded_and_explicit_about_uncertainty() -> None:
    client = TestClient(create_app())
    dataset_id = upload(client)

    response = client.post(f"/api/v1/overview/datasets/{dataset_id}/atlas", json={"action": "diagnose_quality"})
    payload = AtlasOverviewResponse.model_validate(response.json())

    assert response.status_code == 200
    assert "duplicate" in payload.summary.lower()
    assert "not a causal conclusion" in payload.uncertainty
    assert payload.evidence


def test_unknown_dataset_has_a_recoverable_not_found_failure() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/overview/datasets/ds_missing/profile")
    assert response.status_code == 404


def test_local_web_origin_can_reach_the_overview_api_without_opening_cors_globally() -> None:
    client = TestClient(create_app())
    response = client.options(
        "/api/v1/overview/datasets",
        headers={
            "Origin": "http://127.0.0.1:3000",
            "Access-Control-Request-Method": "POST",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
