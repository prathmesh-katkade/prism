from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from prism_api.atlas_authorization import Principal, current_principal
from prism_api.atlas_investigation_links import InvestigationLinks, _audit, _links
from prism_api.main import create_app
from prism_api_contracts import AtlasInvestigationLinkRequest, AtlasInvestigationLinkResolve
from sqlalchemy import select, update


class Access:
    allowed = {"issuer", "reader"}
    def project_for_run(self, run_id):
        return "project" if run_id == "run" else None
    def can_read(self, principal, project_id, run_id):
        return principal.subject in self.allowed and project_id == "project" and run_id == "run"


@pytest.fixture
def links(tmp_path):
    return InvestigationLinks(f"sqlite:///{tmp_path / 'links.db'}", Access())


def issue(links):
    return links.issue(Principal("issuer", authenticated=True), AtlasInvestigationLinkRequest(run_id="run"))


def resolve_request(link):
    return AtlasInvestigationLinkResolve(link_id=link.link_id, bearer_secret=link.bearer_secret)


def test_hash_only_and_durable_audit(links):
    link = issue(links)
    reader = Principal("reader", authenticated=True)
    assert links.resolve(reader, resolve_request(link)) == "run"
    with links.engine.connect() as connection:
        row = connection.execute(select(_links)).mappings().one()
        assert link.bearer_secret not in str(dict(row))
        assert len(row["secret_hash"]) == 64
        assert connection.execute(select(_audit.c.action)).scalars().all() == ["issued", "resolved"]
    reopened = InvestigationLinks(str(links.engine.url), Access())
    assert reopened.resolve(reader, resolve_request(link)) == "run"


@pytest.mark.parametrize("case", ["expired", "revoked", "invalid", "missing", "issuer_lost_access"])
def test_invalid_links_fail_closed_without_run_disclosure(links, case):
    link = issue(links)
    request = resolve_request(link)
    if case == "expired":
        with links.engine.begin() as connection:
            connection.execute(update(_links).values(expires_at=int(datetime.now(timezone.utc).timestamp()) - 1))
    elif case == "revoked":
        links.revoke(Principal("issuer", authenticated=True), link.link_id)
    elif case == "invalid":
        request.bearer_secret = "wrong"
    elif case == "missing":
        request.link_id = "missing"
    else:
        links.authorization.allowed = {"reader"}
    with pytest.raises(HTTPException) as error:
        links.resolve(Principal("reader", authenticated=True), request)
    assert error.value.status_code == 404
    assert error.value.detail == "Investigation link unavailable."


def test_unauthorized_principal_is_403(links):
    link = issue(links)
    with pytest.raises(HTTPException) as error:
        links.resolve(Principal("outsider", authenticated=True), resolve_request(link))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as error:
        links.issue(Principal("local", local_owner=True), AtlasInvestigationLinkRequest(run_id="run"))
    assert error.value.status_code == 403


def test_http_sharing_is_disabled_and_headers_are_not_identity():
    client = TestClient(create_app())
    response = client.post("/api/v1/atlas/investigation-links", json={"run_id": "run"}, headers={"X-Principal": "issuer", "Authorization": "Bearer pretend"})
    assert response.status_code == 503
    for path, body in [("/resolve", {"link_id": "x", "bearer_secret": "x"}), ("/x/revoke", None)]:
        assert client.post("/api/v1/atlas/investigation-links" + path, json=body).status_code == 503


def test_run_routes_deny_unprivileged_principal_before_run_lookup():
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: Principal("outsider", authenticated=True)
    client = TestClient(app)
    for suffix in ["", "/cortex", "/events"]:
        assert client.get("/api/v1/atlas/runs/missing" + suffix).status_code == 403
    assert client.post("/api/v1/atlas/runs/missing/cancel").status_code == 403


def test_non_loopback_cannot_claim_local_owner():
    from starlette.requests import Request
    request = Request({"type": "http", "client": ("203.0.113.1", 1234), "headers": [(b"x-forwarded-for", b"127.0.0.1")]})
    with pytest.raises(HTTPException) as error:
        current_principal(request)
    assert error.value.status_code == 403
