from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from prism_api.deployment_security import DeploymentSecurityError, resolve_deployment_security
from prism_api.main import create_app
from prism_api_contracts import ReadinessResponse


def _clear(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.delenv("PRISM_DEPLOYMENT_MODE", raising=False)
    monkeypatch.delenv("PRISM_EXTERNAL_AUTH_TOKEN", raising=False)


def test_default_local_mode_is_the_only_supported_runtime(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _clear(monkeypatch)
    security = resolve_deployment_security()
    assert security.mode == "local"
    assert security.local_only is True


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_non_local_modes_fail_closed_even_when_a_shared_token_is_present(
    monkeypatch, mode: str
) -> None:  # type: ignore[no-untyped-def]
    _clear(monkeypatch)
    monkeypatch.setenv("PRISM_DEPLOYMENT_MODE", mode)
    monkeypatch.setenv("PRISM_EXTERNAL_AUTH_TOKEN", "shared-secret-is-not-identity")
    with pytest.raises(DeploymentSecurityError, match="shared bearer token is not sufficient"):
        resolve_deployment_security()


def test_unrecognized_mode_fails_closed_rather_than_defaulting(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _clear(monkeypatch)
    monkeypatch.setenv("PRISM_DEPLOYMENT_MODE", "public")
    with pytest.raises(DeploymentSecurityError, match="not one of"):
        resolve_deployment_security()


@pytest.mark.parametrize("mode", ["staging", "production"])
def test_create_app_cannot_start_a_public_api(monkeypatch, mode: str) -> None:  # type: ignore[no-untyped-def]
    _clear(monkeypatch)
    monkeypatch.setenv("PRISM_DEPLOYMENT_MODE", mode)
    with pytest.raises(DeploymentSecurityError):
        create_app()


def test_local_readiness_reports_the_enforced_support_boundary(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _clear(monkeypatch)
    response = TestClient(create_app()).get("/api/v1/platform/ready")
    assert response.status_code == 200
    payload = ReadinessResponse.model_validate(response.json())
    boundary = next(item for item in payload.providers if item.name == "external_auth_boundary")
    assert boundary.status == "not_configured"
    assert "127.0.0.1" in boundary.detail
