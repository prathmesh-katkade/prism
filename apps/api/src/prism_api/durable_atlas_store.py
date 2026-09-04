"""Durable, append-only Atlas run storage.

Atlas is intentionally stored beside (but never inside) Phase 8/9 analytical
object history.  The tables share the established SQLAlchemy/database policy,
while run snapshots and event journal remain a distinct operational record.
"""

from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Optional, cast

from fastapi import HTTPException, status
from prism_api_contracts import (
    AtlasModelProviderName,
    AtlasRunEvent,
    AtlasRunEventType,
    AtlasRunRequest,
    AtlasRunResponse,
    AtlasSpecialistId,
    AtlasStructuredPlan,
)
from sqlalchemy import (
    Boolean,
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
from sqlalchemy.exc import IntegrityError, OperationalError

from .atlas_schema_utils import ensure_index
from .durable_registry import history_database_url

_metadata = MetaData()
_runs = Table(
    "prism_atlas_runs",
    _metadata,
    Column("run_id", String(120), primary_key=True),
    Column("plan_id", String(120), nullable=False, unique=True, index=True),
    Column("idempotency_key", String(120), nullable=True, unique=True),
    Column("dataset_id", String(255), nullable=False, index=True),
    Column("state", String(32), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("updated_at", DateTime(timezone=True), nullable=False, index=True),
    Column("cancellation_requested", Boolean, nullable=False, default=False, index=True),
    Column("event_sequence", Integer, nullable=False, default=0),
    Column("snapshot", Text, nullable=False),
)
_events = Table(
    "prism_atlas_run_events",
    _metadata,
    Column("event_id", String(120), primary_key=True),
    Column("run_id", String(120), nullable=False, index=True),
    Column("sequence", Integer, nullable=False),
    Column("event_type", String(64), nullable=False, index=True),
    Column("step_id", String(120), nullable=True, index=True),
    Column("specialist", String(64), nullable=True, index=True),
    Column("occurred_at", DateTime(timezone=True), nullable=False, index=True),
    Column("payload", Text, nullable=False),
)
_schema = Table(
    "prism_atlas_schema_version", _metadata, Column("version", Integer, primary_key=True)
)

# ``CREATE INDEX IF NOT EXISTS`` is SQLite/Postgres syntax; MySQL 8.0 rejects
# it with a 1064 syntax error. Every backend gets a plain ``CREATE INDEX``
# guarded by an Inspector existence check instead, so table backfill stays
# idempotent -- and restart-safe -- everywhere Atlas runs.
_INDEX_DDL: tuple[tuple[str, str, str], ...] = (
    (
        "prism_atlas_run_events",
        "ux_prism_atlas_event_sequence",
        "CREATE UNIQUE INDEX ux_prism_atlas_event_sequence "
        "ON prism_atlas_run_events (run_id, sequence)",
    ),
    (
        "prism_atlas_runs",
        "ix_prism_atlas_runs_dataset_state_created",
        "CREATE INDEX ix_prism_atlas_runs_dataset_state_created "
        "ON prism_atlas_runs (dataset_id, state, created_at)",
    ),
    (
        "prism_atlas_run_events",
        "ix_prism_atlas_events_run_sequence",
        "CREATE INDEX ix_prism_atlas_events_run_sequence "
        "ON prism_atlas_run_events (run_id, sequence)",
    ),
)


_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|secret|token|private[_-]?key)", re.IGNORECASE
)
_SECRET_VALUE = re.compile(
    r"(?:sk-[A-Za-z0-9_-]{12,}|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,})", re.IGNORECASE
)


def redact_atlas_payload(value: object, *, key: str = "") -> object:
    """Redact secret-shaped values before the durable boundary.

    This is deliberately defensive: Atlas has no reason to keep request headers,
    credentials, environment values, or raw dataset rows in its run journal.
    """
    if _SECRET_KEY.search(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(item_key): redact_atlas_payload(item_value, key=str(item_key))
            for item_key, item_value in value.items()
        }
    if isinstance(value, list):
        return [redact_atlas_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_atlas_payload(item) for item in value]
    if isinstance(value, str) and _SECRET_VALUE.search(value):
        return "[REDACTED]"
    return value


class DurableAtlasRunStore:
    """SQL-backed run state with a separately append-only event journal.

    ``event_sequence`` is assigned in the same transaction as each event insert.
    The unique ``(run_id, sequence)`` constraint makes an interrupted/concurrent
    writer retry rather than silently reorder events.  MySQL receives row locks;
    SQLite receives transactional compare-and-swap plus bounded retries.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)
        # Index names are intentionally explicit: SQLite's automatic PK indexes
        # differ from managed MySQL, but these query paths must remain indexed.
        with self.engine.begin() as connection:
            if connection.execute(select(_schema.c.version).limit(1)).scalar_one_or_none() is None:
                connection.execute(insert(_schema).values(version=1))
            for table_name, index_name, ddl in _INDEX_DDL:
                ensure_index(connection, table_name, index_name, ddl)

    @staticmethod
    def _snapshot(run: AtlasRunResponse) -> str:
        durable = run.model_copy(update={"events": []})
        return json.dumps(
            redact_atlas_payload(durable.model_dump(mode="json")),
            separators=(",", ":"),
            sort_keys=True,
        )

    @staticmethod
    def _restore(
        snapshot: str, events: list[AtlasRunEvent], cancellation_requested: bool
    ) -> AtlasRunResponse:
        value = json.loads(snapshot)
        value["events"] = [event.model_dump(mode="json") for event in events]
        value["cancellation_requested"] = cancellation_requested
        return AtlasRunResponse.model_validate(value)

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return True

    def list_run_ids(self, *, state: Optional[str] = None, limit: int = 1000) -> list[str]:
        """List run ids, oldest first, optionally filtered to one plan state.

        Used by consumers (the Foundry training-dataset builder, so far) that
        need to walk durable run history rather than fetch one run by id.
        """
        statement = select(_runs.c.run_id).order_by(_runs.c.created_at).limit(limit)
        if state is not None:
            statement = statement.where(_runs.c.state == state)
        with self.engine.connect() as connection:
            return [str(row) for row in connection.execute(statement).scalars().all()]

    def create(
        self, request: AtlasRunRequest, provider: AtlasModelProviderName, plan: AtlasStructuredPlan
    ) -> AtlasRunResponse:
        if request.idempotency_key:
            with self.engine.connect() as connection:
                existing = connection.execute(
                    select(_runs.c.run_id).where(_runs.c.idempotency_key == request.idempotency_key)
                ).scalar_one_or_none()
            if existing is not None:
                return self.get(str(existing))
        now = datetime.now(timezone.utc)
        run = AtlasRunResponse(
            run_id=f"atlas_{uuid.uuid4().hex}", plan=plan, created_at=now, updated_at=now
        )
        values = {
            "run_id": run.run_id,
            "plan_id": plan.plan_id,
            "idempotency_key": request.idempotency_key,
            "dataset_id": request.dataset_id,
            "state": plan.state.value,
            "created_at": now,
            "updated_at": now,
            "cancellation_requested": False,
            "event_sequence": 0,
            "snapshot": self._snapshot(run),
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(_runs).values(**values))
        except IntegrityError:
            if request.idempotency_key:
                with self.engine.connect() as connection:
                    existing = connection.execute(
                        select(_runs.c.run_id).where(
                            _runs.c.idempotency_key == request.idempotency_key
                        )
                    ).scalar_one_or_none()
                if existing is not None:
                    return self.get(str(existing))
            raise
        return run

    def get(self, run_id: str) -> AtlasRunResponse:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(_runs.c.snapshot, _runs.c.cancellation_requested).where(
                        _runs.c.run_id == run_id
                    )
                )
                .mappings()
                .first()
            )
            event_rows = (
                connection.execute(
                    select(_events).where(_events.c.run_id == run_id).order_by(_events.c.sequence)
                )
                .mappings()
                .all()
            )
        if row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found."
            )
        events = [
            AtlasRunEvent(
                event_id=str(item["event_id"]),
                run_id=str(item["run_id"]),
                sequence=int(item["sequence"]),
                type=AtlasRunEventType(str(item["event_type"])),
                occurred_at=item["occurred_at"],
                specialist=item["specialist"],
                step_id=item["step_id"],
                payload=json.loads(str(item["payload"])),
            )
            for item in event_rows
        ]
        return self._restore(str(row["snapshot"]), events, bool(row["cancellation_requested"]))

    def save(self, response: AtlasRunResponse) -> AtlasRunResponse:
        now = datetime.now(timezone.utc)
        response = response.model_copy(update={"updated_at": now})
        with self.engine.begin() as connection:
            result = connection.execute(
                update(_runs)
                .where(_runs.c.run_id == response.run_id)
                .values(
                    plan_id=response.plan.plan_id,
                    dataset_id=response.plan.dataset_id,
                    state=response.plan.state.value,
                    updated_at=now,
                    snapshot=self._snapshot(response),
                    cancellation_requested=response.cancellation_requested,
                )
            )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found."
            )
        return self.get(response.run_id)

    def cancellation_requested(self, run_id: str) -> bool:
        with self.engine.connect() as connection:
            value = connection.execute(
                select(_runs.c.cancellation_requested).where(_runs.c.run_id == run_id)
            ).scalar_one_or_none()
        if value is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found."
            )
        return bool(value)

    def request_cancel(self, run_id: str) -> AtlasRunResponse:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(_runs)
                .where(_runs.c.run_id == run_id)
                .values(cancellation_requested=True, updated_at=datetime.now(timezone.utc))
            )
        if result.rowcount != 1:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found."
            )
        return self.get(run_id)

    def append_event(
        self,
        run_id: str,
        event_type: AtlasRunEventType,
        *,
        specialist: Optional[AtlasSpecialistId] = None,
        step_id: Optional[str] = None,
        payload: Optional[dict[str, object]] = None,
    ) -> AtlasRunEvent:
        # A short retry is purposeful: an event journal must never gamble with
        # duplicate sequence numbers when two workers complete safe independent steps.
        for attempt in range(3):
            event = AtlasRunEvent(
                event_id=f"evt_{uuid.uuid4().hex}",
                run_id=run_id,
                sequence=1,
                type=event_type,
                occurred_at=datetime.now(timezone.utc),
                specialist=specialist,
                step_id=step_id,
                payload=cast(dict[str, object], redact_atlas_payload(payload or {})),
            )
            try:
                with self.engine.begin() as connection:
                    row = (
                        connection.execute(
                            select(_runs.c.event_sequence)
                            .where(_runs.c.run_id == run_id)
                            .with_for_update()
                        )
                        .mappings()
                        .first()
                    )
                    if row is None:
                        raise HTTPException(
                            status_code=status.HTTP_404_NOT_FOUND, detail="Atlas run was not found."
                        )
                    current = int(row["event_sequence"])
                    sequence = current + 1
                    advanced = connection.execute(
                        update(_runs)
                        .where((_runs.c.run_id == run_id) & (_runs.c.event_sequence == current))
                        .values(event_sequence=sequence, updated_at=event.occurred_at)
                    )
                    if advanced.rowcount != 1:
                        raise OperationalError(
                            "event sequence race", {}, RuntimeError("sequence race")
                        )
                    event = event.model_copy(update={"sequence": sequence})
                    connection.execute(
                        insert(_events).values(
                            event_id=event.event_id,
                            run_id=run_id,
                            sequence=sequence,
                            event_type=event.type.value,
                            step_id=step_id,
                            specialist=None if specialist is None else specialist.value,
                            occurred_at=event.occurred_at,
                            payload=json.dumps(
                                event.payload, separators=(",", ":"), sort_keys=True
                            ),
                        )
                    )
                return event
            except (IntegrityError, OperationalError):
                if attempt == 2:
                    raise
                time.sleep(0.01 * (attempt + 1))
        raise AssertionError("unreachable")
