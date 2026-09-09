"""Append-only human feedback on Atlas answers.

This is the foundation the mission's future preference-learning work stands
on: binary feedback (``helpful``/``not_helpful``/``accepted``/``rejected``)
is the eventual KTO substrate, and ``corrected`` (a human-supplied
replacement answer) is the eventual DPO substrate. Neither training method
starts here -- this module only records the signal durably, bound to the
exact run/answer/evidence/project it was given about, so a later training
pipeline can trust its provenance instead of a bare rating with no context.

Feedback is never mutated or deleted once recorded: a changed mind is a new
event, matching the append-only discipline used for candidate verification,
promotion history, and every other durable Atlas record.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasEvidenceReference,
    AtlasFeedbackEvent,
    AtlasFeedbackKind,
    AtlasFeedbackWriteRequest,
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

from .durable_atlas_store import redact_atlas_payload
from .durable_registry import history_database_url

# Same credential-shaped-content boundary used by Atlas memory/retrieval
# indexing: a human rating or correction is not a place to durably store a
# pasted API key or password, even by accident.
_CREDENTIAL = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}|password\s*[:=])", re.I
)


def _feedback_id() -> str:
    """Nanosecond-ordered id so rapid feedback on the same run stays orderable."""
    return f"atlasfeedback_{time.time_ns():020d}_{uuid.uuid4().hex}"


def _rejects_secret_shaped(*values: Optional[str]) -> None:
    for value in values:
        if value is None:
            continue
        if _CREDENTIAL.search(value) or redact_atlas_payload(value) != value:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Feedback rejects credentials and secret-shaped content.",
            )


_metadata = MetaData()
_feedback = Table(
    "prism_atlas_feedback_events",
    _metadata,
    Column("feedback_id", String(140), primary_key=True),
    Column("run_id", String(140), nullable=False, index=True),
    Column("project_id", String(200), nullable=True, index=True),
    Column("kind", String(16), nullable=False, index=True),
    Column("answer", Text, nullable=False),
    Column("evidence_payload", Text, nullable=False),
    Column("correction", Text, nullable=True),
    Column("note", Text, nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasFeedbackStore:
    """Append-only feedback history; nothing here ever updates or deletes a row."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    def record(self, request: AtlasFeedbackWriteRequest) -> AtlasFeedbackEvent:
        _rejects_secret_shaped(request.answer, request.correction, request.note)
        event = AtlasFeedbackEvent(
            feedback_id=_feedback_id(),
            run_id=request.run_id,
            project_id=request.project_id,
            kind=request.kind,
            answer=request.answer,
            evidence=request.evidence,
            correction=request.correction,
            note=request.note,
            created_at=datetime.now(timezone.utc),
        )
        with self.engine.begin() as connection:
            connection.execute(
                insert(_feedback).values(
                    feedback_id=event.feedback_id,
                    run_id=event.run_id,
                    project_id=event.project_id,
                    kind=event.kind.value,
                    answer=event.answer,
                    evidence_payload=json.dumps(
                        [item.model_dump(mode="json") for item in event.evidence], sort_keys=True
                    ),
                    correction=event.correction,
                    note=event.note,
                    created_at=event.created_at,
                )
            )
        return event

    @staticmethod
    def _record_row(row: object) -> AtlasFeedbackEvent:
        evidence = [
            AtlasEvidenceReference.model_validate(item)
            for item in json.loads(row["evidence_payload"])  # type: ignore[index]
        ]
        return AtlasFeedbackEvent(
            feedback_id=row["feedback_id"],  # type: ignore[index]
            run_id=row["run_id"],  # type: ignore[index]
            project_id=row["project_id"],  # type: ignore[index]
            kind=AtlasFeedbackKind(row["kind"]),  # type: ignore[index]
            answer=row["answer"],  # type: ignore[index]
            evidence=evidence,
            correction=row["correction"],  # type: ignore[index]
            note=row["note"],  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
        )

    def list_for_run(self, run_id: str, *, limit: int = 100) -> list[AtlasFeedbackEvent]:
        statement = (
            select(_feedback)
            .where(_feedback.c.run_id == run_id)
            .order_by(_feedback.c.created_at.desc(), _feedback.c.feedback_id.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record_row(row) for row in rows]

    def list_for_project(self, project_id: str, *, limit: int = 200) -> list[AtlasFeedbackEvent]:
        statement = (
            select(_feedback)
            .where(_feedback.c.project_id == project_id)
            .order_by(_feedback.c.created_at.desc(), _feedback.c.feedback_id.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record_row(row) for row in rows]

    def list_by_kind(self, kind: AtlasFeedbackKind, *, limit: int = 500) -> list[AtlasFeedbackEvent]:
        """Future DPO/KTO pipelines read their substrate through here.

        ``AtlasFeedbackKind.CORRECTED`` events are the DPO candidate pairs
        (this ``answer`` as the rejected response, ``correction`` as the
        preferred one); every other kind is binary KTO signal. This module
        does not itself decide when enough signal exists to start training --
        it only makes the recorded signal queryable by shape.
        """
        statement = (
            select(_feedback)
            .where(_feedback.c.kind == kind.value)
            .order_by(_feedback.c.created_at.desc(), _feedback.c.feedback_id.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record_row(row) for row in rows]


router = APIRouter(prefix="/api/v1/atlas/feedback", tags=["atlas-feedback"])
_store = DurableAtlasFeedbackStore()


@router.post("", response_model=AtlasFeedbackEvent, status_code=status.HTTP_201_CREATED)
def record_feedback(request: AtlasFeedbackWriteRequest) -> AtlasFeedbackEvent:
    return _store.record(request)


@router.get("/runs/{run_id}", response_model=list[AtlasFeedbackEvent])
def list_feedback_for_run(run_id: str, limit: int = Query(default=100, ge=1, le=500)) -> list[AtlasFeedbackEvent]:
    return _store.list_for_run(run_id, limit=limit)


@router.get("/projects/{project_id}", response_model=list[AtlasFeedbackEvent])
def list_feedback_for_project(project_id: str, limit: int = Query(default=200, ge=1, le=1_000)) -> list[AtlasFeedbackEvent]:
    return _store.list_for_project(project_id, limit=limit)
