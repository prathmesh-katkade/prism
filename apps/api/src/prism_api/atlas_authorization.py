"""Identity integration seam. Local owner is explicitly NOT authentication."""
from __future__ import annotations

from dataclasses import dataclass
from ipaddress import ip_address
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request

from .deployment_security import resolve_deployment_security


@dataclass(frozen=True)
class Principal:
    subject: str
    authenticated: bool = False
    local_owner: bool = False


class RunAuthorization(Protocol):
    """An identity adapter must resolve ownership server-side, never from headers."""
    def project_for_run(self, run_id: str) -> str | None: ...
    def can_read(self, principal: Principal, project_id: str, run_id: str) -> bool: ...


def current_principal(request: Request) -> Principal:
    resolve_deployment_security()
    # Read the socket peer; forwarded headers never create an owner identity.
    peer = request.client.host if request.client else ""
    try:
        loopback = ip_address(peer).is_loopback
    except ValueError:
        loopback = peer == "testclient"  # Starlette's in-process test transport only.
    if not loopback:
        raise HTTPException(403, "Local workspace access required.")
    return Principal(subject="local-workspace-owner", local_owner=True)


def require_local_owner(principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    if not principal.local_owner:
        raise HTTPException(403, "Local workspace access required.")
    return principal


def require_run_access(run_id: str, principal: Annotated[Principal, Depends(current_principal)]) -> Principal:
    # No external identity provider is wired. Authenticated-looking client headers
    # are ignored; future adapters must implement RunAuthorization before use.
    if not principal.local_owner:
        raise HTTPException(403, "Run access denied.")
    return principal
