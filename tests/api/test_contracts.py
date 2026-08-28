from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api_contracts import HealthResponse, ReleaseChannel


def test_health_contract_reports_phase_5_ai_analyst_as_enabled() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/platform/health")

    assert response.status_code == 200
    payload = HealthResponse.model_validate(response.json())
    assert payload.contract_version == "v1"
    assert {item.workflow for item in payload.migrations} == {"overview", "sql-lab", "ai-analyst"}
    channels = {item.workflow: item.channel for item in payload.migrations}
    assert channels == {
        "overview": ReleaseChannel.ENABLED,
        "sql-lab": ReleaseChannel.ENABLED,
        "ai-analyst": ReleaseChannel.ENABLED,
    }


def test_openapi_is_served_at_the_versioned_contract_location() -> None:
    client = TestClient(create_app())

    schema = client.get("/api/v1/openapi.json").json()

    assert "/api/v1/platform/health" in schema["paths"]
    assert "HealthResponse" in schema["components"]["schemas"]


def test_sse_transport_emits_a_typed_platform_event() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/platform/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: platform.ready" in response.text
    assert '"phase":1' in response.text
