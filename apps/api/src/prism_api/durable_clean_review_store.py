"""One-use, revision-bound Clean review tickets.

Tickets are durable so a browser reload cannot silently turn an old preview into
an unreviewed apply. A ticket binds the exact request or recipe version to a
dataset revision and fingerprint. Consumption is a conditional database update.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    update,
)

from .durable_registry import history_database_url

_metadata = MetaData()
_reviews = Table(
    "prism_clean_reviews", _metadata,
    Column("token", String(64), primary_key=True),
    Column("dataset_id", String(255), nullable=False, index=True),
    Column("revision", Integer, nullable=False),
    Column("fingerprint", String(255), nullable=False),
    Column("operation_digest", String(64), nullable=False),
    Column("consumed", Boolean, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)


def operation_digest(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class DurableCleanReviewStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True,
                                    connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)

    def issue(self, dataset_id: str, revision: int, fingerprint: str, operation: Any) -> str:
        token = uuid.uuid4().hex
        with self.engine.begin() as connection:
            connection.execute(insert(_reviews).values(
                token=token, dataset_id=dataset_id, revision=revision, fingerprint=fingerprint,
                operation_digest=operation_digest(operation), consumed=False, created_at=datetime.now(timezone.utc),
            ))
        return token

    def consume(self, token: str | None, dataset_id: str, revision: int, fingerprint: str, operation: Any) -> None:
        if not token:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                detail="Preview the operation or recipe before applying it.")
        with self.engine.begin() as connection:
            result = connection.execute(update(_reviews).where(
                (_reviews.c.token == token) & (_reviews.c.dataset_id == dataset_id) &
                (_reviews.c.revision == revision) & (_reviews.c.fingerprint == fingerprint) &
                (_reviews.c.operation_digest == operation_digest(operation)) &
                (_reviews.c.consumed.is_(False))
            ).values(consumed=True))
            if result.rowcount != 1:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                                    detail="This preview is stale, was changed, or was already applied. Preview the current dataset again.")
