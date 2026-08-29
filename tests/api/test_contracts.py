import logging

from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api_contracts import HealthResponse, ReadinessResponse, ReleaseChannel


def test_readiness_never_depends_on_an_optional_ai_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("PRISM_AI_PROVIDER", raising=False)
    client = TestClient(create_app())

    response = client.get("/api/v1/platform/ready")

    assert response.status_code == 200
    payload = ReadinessResponse.model_validate(response.json())
    assert payload.status == "ready"
    ollama = next(item for item in payload.providers if item.name == "ollama")
    assert ollama.status == "not_configured"


def test_readiness_reports_ollama_configured_without_a_live_network_probe(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    client = TestClient(create_app())

    response = client.get("/api/v1/platform/ready")

    assert response.status_code == 200
    payload = ReadinessResponse.model_validate(response.json())
    assert payload.status == "ready"  # still ready: an optional provider never blocks readiness
    ollama = next(item for item in payload.providers if item.name == "ollama")
    assert ollama.status == "configured"


def test_requests_are_logged_with_request_id_status_and_duration_but_never_secrets(caplog) -> None:  # type: ignore[no-untyped-def]
    client = TestClient(create_app())

    with caplog.at_level(logging.INFO, logger="prism_api"):
        response = client.get("/api/v1/platform/health", headers={"X-Request-ID": "req_test_12345678"})

    assert response.status_code == 200
    record = next(r for r in caplog.records if r.getMessage().startswith("request_completed"))
    assert record.request_id == "req_test_12345678"
    assert record.method == "GET"
    assert record.path == "/api/v1/platform/health"
    assert record.status == 200
    assert isinstance(record.duration_ms, float)
    logged_text = caplog.text.lower()
    for secret_marker in ("password", "api_key", "secret", "token"):
        assert secret_marker not in logged_text


def test_health_contract_reports_phase_6_clean_and_visualize_as_enabled() -> None:
    client = TestClient(create_app())

    response = client.get("/api/v1/platform/health")

    assert response.status_code == 200
    payload = HealthResponse.model_validate(response.json())
    assert payload.contract_version == "v1"
    assert {item.workflow for item in payload.migrations} == {"overview", "sql-lab", "ai-analyst", "clean", "visualize", "stats"}
    channels = {item.workflow: item.channel for item in payload.migrations}
    assert channels == {
        "overview": ReleaseChannel.ENABLED,
        "sql-lab": ReleaseChannel.ENABLED,
        "ai-analyst": ReleaseChannel.ENABLED,
        "clean": ReleaseChannel.ENABLED,
        "visualize": ReleaseChannel.ENABLED,
        "stats": ReleaseChannel.SHADOW,
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
