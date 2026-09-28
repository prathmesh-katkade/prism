"""Server-owned Atlas dispatch policy. Checked before every new tool dispatch."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionPolicy:
    version: str
    profile_only: bool
    disabled_tools: frozenset[str]

    def permits(self, tool: str) -> bool:
        return tool not in self.disabled_tools and (
            not self.profile_only or tool in {"overview.profile", "atlas.evidence_audit"}
        )


def current_policy() -> ExecutionPolicy:
    return ExecutionPolicy(
        version=os.environ.get("PRISM_ATLAS_EXECUTION_POLICY_VERSION", "atlas-execution-v1"),
        profile_only=os.environ.get("PRISM_ATLAS_PROFILE_ONLY", "false").lower() == "true",
        disabled_tools=frozenset(item.strip() for item in os.environ.get("PRISM_ATLAS_DISABLED_TOOLS", "").split(",") if item.strip()),
    )
