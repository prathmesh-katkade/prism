from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class AtlasCommandType(str, Enum):
    NAVIGATE = "navigate"
    ANALYZE = "analyze"
    QUERY = "query"


class AtlasCommandStatus(str, Enum):
    DRAFT = "draft"
    REQUIRES_CONFIRMATION = "requires_confirmation"
    EXECUTED = "executed"


class AtlasCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command_id: str = Field(min_length=1)
    type: AtlasCommandType
    status: AtlasCommandStatus = AtlasCommandStatus.DRAFT
    arguments: dict[str, object] = Field(default_factory=dict)
    requires_confirmation: bool = True
