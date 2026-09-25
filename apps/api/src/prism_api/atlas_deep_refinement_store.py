"""Durable, fail-closed state for optional deep-plan proposals."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Optional, Sequence

from prism_api_contracts import AtlasDeepRefinement, AtlasDeepRefinementState, AtlasPlanStep
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from .durable_registry import history_database_url

_metadata = MetaData()
_refinements = Table(
    "prism_atlas_deep_refinements", _metadata,
    Column("run_id", String(120), primary_key=True),
    Column("state", String(24), nullable=False, index=True),
    Column("reason", String(500), nullable=False),
    Column("candidate_id", String(120), nullable=True),
    Column("runtime_model", String(300), nullable=True),
    Column("runtime_model_digest", String(200), nullable=True),
    Column("dataset_revision", Integer, nullable=True),
    Column("source_fingerprint", String(255), nullable=True),
    Column("proposed_steps", Text, nullable=False),
    Column("accepted_run_id", String(120), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


class DurableAtlasDeepRefinementStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url, future=True, pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    @staticmethod
    def _record(row: object) -> AtlasDeepRefinement:
        return AtlasDeepRefinement(
            run_id=row["run_id"],  # type: ignore[index]
            state=row["state"],  # type: ignore[index]
            reason=row["reason"],  # type: ignore[index]
            candidate_id=row["candidate_id"],  # type: ignore[index]
            runtime_model=row["runtime_model"],  # type: ignore[index]
            runtime_model_digest=row["runtime_model_digest"],  # type: ignore[index]
            dataset_revision=row["dataset_revision"],  # type: ignore[index]
            source_fingerprint=row["source_fingerprint"],  # type: ignore[index]
            proposed_steps=[AtlasPlanStep.model_validate(item) for item in json.loads(row["proposed_steps"])],  # type: ignore[index]
            accepted_run_id=row["accepted_run_id"],  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
            updated_at=row["updated_at"],  # type: ignore[index]
        )

    def get(self, run_id: str) -> Optional[AtlasDeepRefinement]:
        with self.engine.connect() as connection:
            row = connection.execute(select(_refinements).where(_refinements.c.run_id == run_id)).mappings().first()
        return None if row is None else self._record(row)

    def create(
        self, run_id: str, *, state: AtlasDeepRefinementState, reason: str,
        candidate_id: Optional[str] = None, runtime_model: Optional[str] = None,
        runtime_model_digest: Optional[str] = None, dataset_revision: Optional[int] = None,
        source_fingerprint: Optional[str] = None,
    ) -> tuple[AtlasDeepRefinement, bool]:
        now = datetime.now(timezone.utc)
        created = True
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(_refinements).values(
                    run_id=run_id, state=state.value, reason=reason[:500],
                    candidate_id=candidate_id, runtime_model=runtime_model,
                    runtime_model_digest=runtime_model_digest,
                    dataset_revision=dataset_revision, source_fingerprint=source_fingerprint,
                    proposed_steps="[]", accepted_run_id=None, created_at=now, updated_at=now,
                ))
        except IntegrityError:
            created = False
        record = self.get(run_id)
        assert record is not None
        return record, created

    def transition(
        self, run_id: str, *, expected: Sequence[AtlasDeepRefinementState],
        state: AtlasDeepRefinementState, reason: str,
        proposed_steps: Optional[list[AtlasPlanStep]] = None,
        accepted_run_id: Optional[str] = None,
    ) -> bool:
        values: dict[str, object] = {
            "state": state.value, "reason": reason[:500], "updated_at": datetime.now(timezone.utc),
        }
        if proposed_steps is not None:
            values["proposed_steps"] = json.dumps([step.model_dump(mode="json") for step in proposed_steps])
        if accepted_run_id is not None:
            values["accepted_run_id"] = accepted_run_id
        with self.engine.begin() as connection:
            result = connection.execute(
                update(_refinements)
                .where(_refinements.c.run_id == run_id, _refinements.c.state.in_([item.value for item in expected]))
                .values(**values)
            )
        return result.rowcount == 1

    def unfinished_run_ids(self) -> list[str]:
        with self.engine.connect() as connection:
            return [str(item) for item in connection.execute(
                select(_refinements.c.run_id).where(_refinements.c.state.in_([
                    AtlasDeepRefinementState.QUEUED.value, AtlasDeepRefinementState.RUNNING.value,
                    AtlasDeepRefinementState.ACCEPTING.value,
                ]))
            ).scalars().all()]
