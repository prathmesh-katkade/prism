"""Canonical, framework-independent analytical object and provenance contracts."""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

_REDACTED = "[redacted]"
_SECRET_KEY_PATTERN = re.compile(
    r"(?:api[_-]?key|apikey|access[_-]?key|authorization|credential|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE_PATTERN = re.compile(
    r"(?:\b(?:bearer|basic)\s+\S+|\b(?:api[_-]?key|apikey|password|secret|token)\s*[=:]\s*\S+|"
    r"(?:mysql|postgres(?:ql)?|mssql)\+?\w*://[^\s/@:]+:[^\s/@]+@)",
    re.IGNORECASE,
)


class ObjectKind(str, Enum):
    PROFILE = "profile"
    QUERY_RESULT = "query_result"
    CLEANING_PLAN = "cleaning_plan"
    VISUALIZATION = "visualization"
    ANALYSIS = "analysis"
    FORECAST = "forecast"
    ML_MODEL = "ml_model"


class LifecycleState(str, Enum):
    DRAFT = "draft"
    COMPLETED = "completed"
    FAILED = "failed"
    STALE = "stale"
    ARCHIVED = "archived"


class ReproducibilityKind(str, Enum):
    CLEANING = "cleaning"
    STATISTICAL_TEST = "statistical_test"
    GENERIC = "generic"


class SchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DatasetRef(SchemaModel):
    """An immutable DatasetStore identity; revisions remain owned by DatasetStore."""

    dataset_id: str = Field(min_length=1)
    revision: int = Field(ge=0)
    source_fingerprint: str = Field(min_length=16)


class ParentRef(SchemaModel):
    object_id: str = Field(min_length=1)
    relation: str = Field(default="derived_from", min_length=1)


class EvidenceRef(SchemaModel):
    evidence_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    summary: Optional[str] = Field(default=None, max_length=500)


class Producer(SchemaModel):
    service: str = Field(min_length=1)
    version: str = Field(min_length=1)


def _sanitize_value(value: object) -> object:
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and _SECRET_VALUE_PATTERN.search(value):
            return _REDACTED
        return value
    if isinstance(value, float):
        return value
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {
            str(key): _REDACTED if _SECRET_KEY_PATTERN.search(str(key)) else _sanitize_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_value(item) for item in value]
    return str(value)


def sanitize_provenance_parameters(parameters: Dict[str, object]) -> Dict[str, object]:
    """Return a JSON-safe reproducibility shape with credential-like data redacted.

    Provenance exists to reproduce a computation, never to carry an authentication
    mechanism. Both credential-like keys and common inline secret/connection forms
    are replaced before records can enter the registry.
    """
    return {
        key: _REDACTED if _SECRET_KEY_PATTERN.search(key) else _sanitize_value(value)
        for key, value in parameters.items()
    }


class ReproducibilityBase(SchemaModel):
    producer: Producer


class CleaningReproducibilitySpec(ReproducibilityBase):
    kind: Literal[ReproducibilityKind.CLEANING] = ReproducibilityKind.CLEANING
    operation: str = Field(min_length=1)
    parameters: Dict[str, object] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def sanitize_parameters(cls, value: object) -> Dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("reproducibility parameters must be a mapping")
        return sanitize_provenance_parameters(value)


class StatisticalTestReproducibilitySpec(ReproducibilityBase):
    kind: Literal[ReproducibilityKind.STATISTICAL_TEST] = ReproducibilityKind.STATISTICAL_TEST
    test: str = Field(min_length=1)
    columns: List[str] = Field(min_length=1)
    parameters: Dict[str, object] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def sanitize_parameters(cls, value: object) -> Dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("reproducibility parameters must be a mapping")
        return sanitize_provenance_parameters(value)


class GenericReproducibilitySpec(ReproducibilityBase):
    kind: Literal[ReproducibilityKind.GENERIC] = ReproducibilityKind.GENERIC
    operation: str = Field(min_length=1)
    parameters: Dict[str, object] = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def sanitize_parameters(cls, value: object) -> Dict[str, object]:
        if not isinstance(value, dict):
            raise ValueError("reproducibility parameters must be a mapping")
        return sanitize_provenance_parameters(value)


ReproducibilitySpec = Union[
    CleaningReproducibilitySpec,
    StatisticalTestReproducibilitySpec,
    GenericReproducibilitySpec,
]


class AnalyticalProvenance(SchemaModel):
    dataset: DatasetRef
    parent_refs: List[ParentRef] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    evidence_refs: List[EvidenceRef] = Field(default_factory=list)
    reproducibility: ReproducibilitySpec
    created_at: datetime


class AnalyticalObject(SchemaModel):
    """A durable-in-process record of one completed or pending analytical action."""

    object_id: str = Field(min_length=1)
    kind: ObjectKind
    lifecycle: LifecycleState
    provenance: AnalyticalProvenance
    schema_version: str = "v1"
    payload: Dict[str, object] = Field(default_factory=dict)
