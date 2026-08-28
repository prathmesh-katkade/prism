from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ObjectKind(str, Enum):
    PROFILE = "profile"
    QUERY_RESULT = "query_result"
    CLEANING_PLAN = "cleaning_plan"
    VISUALIZATION = "visualization"
    ANALYSIS = "analysis"


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetRef(SchemaModel):
    dataset_id: str = Field(min_length=1)
    revision: int = Field(ge=0)


class AnalyticalObject(SchemaModel):
    object_id: str = Field(min_length=1)
    kind: ObjectKind
    dataset: DatasetRef
    schema_version: str = "v1"
    payload: dict[str, object]
