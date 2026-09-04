from __future__ import annotations

import time

from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api_contracts import AtlasPlanState, AtlasRunResponse, CortexGraphState


def _dataset(client: TestClient) -> str:
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("unknown.csv", b"segment,revenue\na,10\nb,12\na,8\n", "text/csv")},
    )
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _terminal_run(client: TestClient, run_id: str) -> AtlasRunResponse:
    for _ in range(100):
        response = client.get(f"/api/v1/atlas/runs/{run_id}")
        assert response.status_code == 200
        run = AtlasRunResponse.model_validate(response.json())
        if run.plan.state in {AtlasPlanState.COMPLETED, AtlasPlanState.FAILED, AtlasPlanState.CANCELLED}:
            return run
        time.sleep(0.01)
    raise AssertionError("Atlas first-wave run did not reach a terminal state")


def test_atlas_profiles_an_uploaded_dataset_with_visible_council_and_evidence() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    started = client.post("/api/v1/atlas/runs", json={"dataset_id": dataset_id, "objective": "Understand this unknown dataset safely."})

    assert started.status_code == 202
    run = _terminal_run(client, started.json()["run_id"])
    assert run.plan.state is AtlasPlanState.COMPLETED
    assert [step.state.value for step in run.plan.steps] == ["completed", "completed", "completed"]
    assert {conclusion.specialist.value for conclusion in run.council} == {"scout", "stat", "auditor"}
    assert run.answer is not None and "deterministic first-pass assessment" in run.answer
    assert run.uncertainty is not None and "not a causal conclusion" in run.uncertainty
    assert all(item.source_fingerprint for item in run.evidence)
    assert any("Do not infer causality" in objection for conclusion in run.council for objection in conclusion.objections)


def test_atlas_sse_and_cortex_are_projections_of_stored_run_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    run_id = client.post("/api/v1/atlas/runs", json={"dataset_id": dataset_id, "objective": "Profile and audit the data."}).json()["run_id"]
    _terminal_run(client, run_id)

    events = client.get(f"/api/v1/atlas/runs/{run_id}/events")
    cortex = client.get(f"/api/v1/atlas/runs/{run_id}/cortex")

    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert '"type":"plan_created"' in events.text
    assert '"type":"run_completed"' in events.text
    graph = CortexGraphState.model_validate(cortex.json())
    assert graph.run_id == run_id
    assert all(node.source_id for node in graph.nodes)
    assert any(edge.relation == "supports" or edge.relation == "produced" for edge in graph.edges)
    assert not any("thought" in node.label.lower() for node in graph.nodes)


def test_atlas_exposes_a_deterministic_provider_and_atlas_as_sole_voice() -> None:
    client = TestClient(create_app())

    providers = client.get("/api/v1/atlas/providers").json()
    specialists = client.get("/api/v1/atlas/specialists").json()

    assert any(item["provider"] == "deterministic" and item["available"] for item in providers)
    assert [item["specialist"] for item in specialists] == ["atlas", "scout", "stat", "auditor"]
    assert [item["display_name"] for item in specialists if item["speaks_to_user"]] == ["Atlas"]
