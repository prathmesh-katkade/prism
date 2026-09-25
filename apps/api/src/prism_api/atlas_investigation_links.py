"""Durable link capability, disabled at HTTP boundary until external identity exists.

The secret is returned once, accepted in a POST body (never a URL/log path),
and only its SHA-256 hash is persisted. A link never grants run access.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from prism_api_contracts import (
    AtlasInvestigationLink,
    AtlasInvestigationLinkIssued,
    AtlasInvestigationLinkRequest,
    AtlasInvestigationLinkResolve,
)
from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
    update,
)

from .atlas_authorization import Principal, RunAuthorization, current_principal

_metadata = MetaData()
_links = Table("prism_atlas_investigation_links", _metadata,
    Column("link_id", String(120), primary_key=True), Column("secret_hash", String(64), nullable=False),
    Column("issuer", String(255), nullable=False), Column("project_id", String(255), nullable=False),
    Column("run_id", String(120), nullable=False), Column("expires_at", Integer, nullable=False),
    Column("revoked", Integer, nullable=False))
_audit = Table("prism_atlas_investigation_link_audit", _metadata,
    Column("event_id", String(40), primary_key=True), Column("link_id", String(120), nullable=False),
    Column("subject", String(255), nullable=False), Column("action", String(32), nullable=False),
    Column("occurred_at", Integer, nullable=False))


class InvestigationLinks:
    def __init__(self, database_url: str, authorization: RunAuthorization) -> None:
        self.engine = create_engine(database_url, connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)
        self.authorization = authorization

    def _access(self, principal: Principal, project_id: str, run_id: str) -> bool:
        return (principal.authenticated and not principal.local_owner
                and self.authorization.project_for_run(run_id) == project_id
                and self.authorization.can_read(principal, project_id, run_id))

    def issue(self, principal: Principal, request: AtlasInvestigationLinkRequest) -> AtlasInvestigationLinkIssued:
        project = self.authorization.project_for_run(request.run_id)
        if project is None or not self._access(principal, project, request.run_id):
            raise HTTPException(403, "Run access denied.")
        secret = secrets.token_urlsafe(32)
        link_id = "link_" + uuid.uuid4().hex
        expires = datetime.now(timezone.utc) + timedelta(seconds=request.expires_in_seconds)
        with self.engine.begin() as connection:
            connection.execute(insert(_links).values(link_id=link_id, secret_hash=hashlib.sha256(secret.encode()).hexdigest(),
                issuer=principal.subject, project_id=project, run_id=request.run_id, expires_at=int(expires.timestamp()), revoked=0))
            connection.execute(insert(_audit).values(event_id=uuid.uuid4().hex, link_id=link_id, subject=principal.subject, action="issued", occurred_at=int(datetime.now(timezone.utc).timestamp())))
        return AtlasInvestigationLinkIssued(link_id=link_id, expires_at=expires, bearer_secret=secret)

    def resolve(self, principal: Principal, request: AtlasInvestigationLinkResolve) -> str:
        with self.engine.begin() as connection:
            row = connection.execute(select(_links).where(_links.c.link_id == request.link_id)).mappings().first()
            supplied = hashlib.sha256(request.bearer_secret.encode()).hexdigest()
            valid_secret = hmac.compare_digest(supplied, str(row["secret_hash"]) if row else "0" * 64)
            now = int(datetime.now(timezone.utc).timestamp())
            if row is None or not valid_secret or row["revoked"] or int(row["expires_at"]) <= now:
                raise HTTPException(404, "Investigation link unavailable.")
            project, run_id = str(row["project_id"]), str(row["run_id"])
            issuer = Principal(str(row["issuer"]), authenticated=True)
            if not self._access(issuer, project, run_id):
                raise HTTPException(404, "Investigation link unavailable.")
            if not self._access(principal, project, run_id):
                raise HTTPException(403, "Run access denied.")
            connection.execute(insert(_audit).values(event_id=uuid.uuid4().hex, link_id=request.link_id,
                subject=principal.subject, action="resolved", occurred_at=now))
            return run_id

    def revoke(self, principal: Principal, link_id: str) -> AtlasInvestigationLink:
        with self.engine.begin() as connection:
            row = connection.execute(select(_links).where(_links.c.link_id == link_id)).mappings().first()
            if row is None or row["issuer"] != principal.subject or not self._access(principal, str(row["project_id"]), str(row["run_id"])):
                raise HTTPException(404, "Investigation link unavailable.")
            connection.execute(update(_links).where(_links.c.link_id == link_id).values(revoked=1))
            connection.execute(insert(_audit).values(event_id=uuid.uuid4().hex, link_id=link_id,
                subject=principal.subject, action="revoked", occurred_at=int(datetime.now(timezone.utc).timestamp())))
            return AtlasInvestigationLink(link_id=link_id, expires_at=datetime.fromtimestamp(int(row["expires_at"]), timezone.utc), revoked=True)


router = APIRouter(prefix="/api/v1/atlas/investigation-links", tags=["atlas"])


def require_identity_integration(principal: Annotated[Principal, Depends(current_principal)]) -> None:
    raise HTTPException(503, "Remote investigation sharing is disabled: external identity and project/run authorization are not integrated.")


@router.post("", response_model=AtlasInvestigationLinkIssued, dependencies=[Depends(require_identity_integration)])
def issue_link(request: AtlasInvestigationLinkRequest) -> AtlasInvestigationLinkIssued:
    raise HTTPException(503, "Investigation sharing unavailable.")


@router.post("/resolve", response_model=dict[str, str], dependencies=[Depends(require_identity_integration)])
def resolve_link(request: AtlasInvestigationLinkResolve) -> dict[str, str]:
    raise HTTPException(503, "Investigation sharing unavailable.")


@router.post("/{link_id}/revoke", response_model=AtlasInvestigationLink, dependencies=[Depends(require_identity_integration)])
def revoke_link(link_id: str) -> AtlasInvestigationLink:
    raise HTTPException(503, "Investigation sharing unavailable.")
