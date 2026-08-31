"""Durable DatasetStore implementation for Phase 9.

DatasetStore remains the authority for active revision semantics. This adapter
persists its revision frames in the same configured history database so exact
same-revision reruns can survive an API restart without trusting a registry
snapshot as a substitute for source data.
"""

from __future__ import annotations

import io
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from fastapi import HTTPException, status
from prism_api_contracts import OverviewDataset
from sqlalchemy import Boolean, Column, DateTime, Integer, MetaData, String, Table, Text, and_, create_engine, desc, insert, select, update

from .durable_registry import history_database_url

_metadata = MetaData()
_revisions = Table(
    "prism_dataset_revisions", _metadata,
    Column("dataset_id", String(255), primary_key=True),
    Column("revision", Integer, primary_key=True),
    Column("source_fingerprint", String(255), primary_key=True),
    Column("source_name", String(1024), nullable=False),
    Column("row_count", Integer, nullable=False),
    Column("column_count", Integer, nullable=False),
    Column("frame_json", Text, nullable=False),
    Column("is_active", Boolean, nullable=False, index=True),
    Column("activated_at", DateTime(timezone=True), nullable=False, index=True),
)


@dataclass(frozen=True)
class StoredDataset:
    dataset: OverviewDataset
    frame: pd.DataFrame
    source_fingerprint: str


class DurableDatasetStore:
    """Append-only revision frames with the original DatasetStore API.

    Revert changes only the active branch marker. Abandoned revisions remain
    immutable audit material but are intentionally absent from ``revisions()``,
    preserving the existing fingerprint-aware same-revision safety contract.
    """

    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)

    @staticmethod
    def _stored(row) -> StoredDataset:  # type: ignore[no-untyped-def]
        frame = pd.read_json(io.StringIO(row["frame_json"]), orient="table")
        dataset = OverviewDataset(dataset_id=row["dataset_id"], revision=row["revision"], source_name=row["source_name"], source_fingerprint=row["source_fingerprint"], row_count=row["row_count"], column_count=row["column_count"])
        return StoredDataset(dataset=dataset, frame=frame, source_fingerprint=row["source_fingerprint"])

    @staticmethod
    def _frame_json(frame: pd.DataFrame) -> str:
        return frame.to_json(orient="table", date_format="iso", index=True)

    def put(self, frame: pd.DataFrame, source_name: str, source_fingerprint: str) -> OverviewDataset:
        dataset = OverviewDataset(dataset_id=f"ds_{uuid.uuid4().hex}", revision=0, source_name=source_name, source_fingerprint=source_fingerprint, row_count=len(frame), column_count=len(frame.columns))
        with self.engine.begin() as connection:
            connection.execute(insert(_revisions).values(dataset_id=dataset.dataset_id, revision=0, source_fingerprint=source_fingerprint, source_name=source_name, row_count=len(frame), column_count=len(frame.columns), frame_json=self._frame_json(frame), is_active=True, activated_at=datetime.now(timezone.utc)))
        return dataset

    def get(self, dataset_id: str) -> StoredDataset:
        statement = select(_revisions).where(and_(_revisions.c.dataset_id == dataset_id, _revisions.c.is_active.is_(True))).order_by(desc(_revisions.c.activated_at)).limit(1)
        with self.engine.connect() as connection:
            row = connection.execute(statement).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Overview dataset was not found.")
        return self._stored(row)

    def latest(self) -> StoredDataset | None:
        with self.engine.connect() as connection:
            row = connection.execute(select(_revisions).where(_revisions.c.is_active.is_(True)).order_by(desc(_revisions.c.activated_at)).limit(1)).mappings().first()
        return None if row is None else self._stored(row)

    def revisions(self, dataset_id: str) -> list[StoredDataset]:
        self.get(dataset_id)
        with self.engine.connect() as connection:
            rows = connection.execute(select(_revisions).where(and_(_revisions.c.dataset_id == dataset_id, _revisions.c.is_active.is_(True))).order_by(_revisions.c.revision, _revisions.c.activated_at)).mappings().all()
        return [self._stored(row) for row in rows]

    def add_revision(self, dataset_id: str, frame: pd.DataFrame, fingerprint: str) -> OverviewDataset:
        current = self.get(dataset_id)
        dataset = OverviewDataset(dataset_id=dataset_id, revision=current.dataset.revision + 1, source_name=current.dataset.source_name, source_fingerprint=fingerprint, row_count=len(frame), column_count=len(frame.columns))
        with self.engine.begin() as connection:
            connection.execute(insert(_revisions).values(dataset_id=dataset_id, revision=dataset.revision, source_fingerprint=fingerprint, source_name=dataset.source_name, row_count=len(frame), column_count=len(frame.columns), frame_json=self._frame_json(frame), is_active=True, activated_at=datetime.now(timezone.utc)))
        return dataset

    def revert(self, dataset_id: str, revision: int) -> OverviewDataset:
        current = self.get(dataset_id)
        available = self.revisions(dataset_id)
        target = next((item for item in available if item.dataset.revision == revision), None)
        if target is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Revision {revision} was not found for this dataset.")
        with self.engine.begin() as connection:
            connection.execute(update(_revisions).where(and_(_revisions.c.dataset_id == dataset_id, _revisions.c.is_active.is_(True), _revisions.c.revision > revision)).values(is_active=False))
            connection.execute(update(_revisions).where(and_(_revisions.c.dataset_id == dataset_id, _revisions.c.revision == target.dataset.revision, _revisions.c.source_fingerprint == target.source_fingerprint)).values(is_active=True, activated_at=datetime.now(timezone.utc)))
        del current
        return target.dataset
