"""Append-only, explicitly human interventions against recorded Atlas items."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from prism_api_contracts import (
    AtlasInterventionRecord,
    AtlasInterventionWriteRequest,
    AtlasRunResponse,
)
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .atlas_authorization import require_run_access
from .atlas_runtime import runs
from .durable_atlas_store import redact_atlas_payload
from .durable_registry import history_database_url

_metadata = MetaData()
_interventions = Table(
    "prism_atlas_interventions",
    _metadata,
    Column("intervention_id", String(140), primary_key=True),
    Column("run_id", String(120), nullable=False, index=True),
    Column("target_id", String(200), nullable=False),
    Column("text", Text, nullable=False),
    Column("author", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


def valid_targets(run: AtlasRunResponse) -> set[str]:
    """Only identifiers visible in the persisted run may receive a note."""
    result = {step.step_id for step in run.plan.steps}
    if run.answer:
        result.add("answer")
    result.update(evidence.evidence_id for evidence in run.evidence)
    for index, conclusion in enumerate(run.council):
        result.add(f"council:{index}")
        result.update(f"objection:{index}:{offset}" for offset in range(len(conclusion.objections)))
        result.update(evidence.evidence_id for evidence in conclusion.evidence)
    return result


class DurableAtlasInterventionStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url, future=True, pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    def record(self, run_id: str, request: AtlasInterventionWriteRequest) -> AtlasInterventionRecord:
        run = runs.get(run_id)
        if request.target_id not in valid_targets(run):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Target is not a recorded item in this run.")
        if redact_atlas_payload(request.text) != request.text:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Intervention rejects secret-shaped content.")
        record = AtlasInterventionRecord(
            intervention_id=f"atlasnote_{uuid.uuid4().hex}", run_id=run_id,
            target_id=request.target_id, text=request.text.strip(),
            created_at=datetime.now(timezone.utc),
        )
        with self.engine.begin() as connection:
            connection.execute(insert(_interventions).values(**record.model_dump()))
        return record

    def list_for_run(self, run_id: str) -> list[AtlasInterventionRecord]:
        runs.get(run_id)
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(_interventions).where(_interventions.c.run_id == run_id)
                .order_by(_interventions.c.created_at, _interventions.c.intervention_id)
            ).mappings().all()
        return [AtlasInterventionRecord.model_validate(dict(row)) for row in rows]


router = APIRouter(prefix="/api/v1/atlas/runs", tags=["atlas-interventions"])


@lru_cache(maxsize=1)
def _store() -> DurableAtlasInterventionStore:
    return DurableAtlasInterventionStore()


@router.get("/{run_id}/interventions", response_model=list[AtlasInterventionRecord], dependencies=[Depends(require_run_access)])
def list_interventions(run_id: str) -> list[AtlasInterventionRecord]:
    return _store().list_for_run(run_id)


@router.post("/{run_id}/interventions", response_model=AtlasInterventionRecord, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_run_access)])
def record_intervention(run_id: str, request: AtlasInterventionWriteRequest) -> AtlasInterventionRecord:
    return _store().record(run_id, request)
