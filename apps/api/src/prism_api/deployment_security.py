"""Fail-closed deployment boundary for the current local-only PRISM API.

PRISM does not yet have user identity, sessions, tenant isolation, or RBAC.
A bearer token would only prove possession of one shared secret; it would not
authorize a person or scope access to Atlas, SQL Lab, Foundry, or promotion
operations. Local desktop mode is allowed. Staging and production refuse to
start until a real external OIDC/session/RBAC boundary is implemented.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

DeploymentMode = Literal["local", "staging", "production"]
_VALID_MODES: tuple[DeploymentMode, ...] = ("local", "staging", "production")


class DeploymentSecurityError(RuntimeError):
    """Raised when configuration would expose the unauthenticated API remotely."""


@dataclass(frozen=True)
class DeploymentSecurity:
    mode: DeploymentMode

    @property
    def local_only(self) -> bool:
        return self.mode == "local"


def resolve_deployment_security() -> DeploymentSecurity:
    """Resolve the declared mode and reject every non-local deployment.

    The deployment mode is an explicit operational assertion. Local launch
    commands must bind Uvicorn to ``127.0.0.1``. Public manifests declare
    staging/production and are intentionally blocked until the identity and
    authorization boundary described in the operations guide exists.
    """

    raw_mode = os.environ.get("PRISM_DEPLOYMENT_MODE", "local").strip().lower()
    if raw_mode not in _VALID_MODES:
        raise DeploymentSecurityError(
            f"PRISM_DEPLOYMENT_MODE={raw_mode!r} is not one of {_VALID_MODES}. "
            "Refusing to guess whether this process is safe to expose."
        )
    mode: DeploymentMode = raw_mode  # type: ignore[assignment]
    if mode != "local":
        raise DeploymentSecurityError(
            f"PRISM_DEPLOYMENT_MODE={mode!r} is blocked. PRISM currently has "
            "no external user identity, session, tenant, or RBAC boundary, so "
            "its Atlas, SQL Lab, Foundry, and promotion routes are supported "
            "only on a loopback-bound local desktop process. A shared bearer "
            "token is not sufficient authorization. Implement the OIDC/session/"
            "RBAC boundary in docs/operations/deployment-security-boundary.md "
            "before enabling staging or production."
        )
    return DeploymentSecurity(mode=mode)
