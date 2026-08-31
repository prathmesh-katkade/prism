"""Durable, append-only storage for the analytical-object graph.

Phase 9 keeps the Phase 8 read model and its deterministic traversal semantics,
but moves its source of truth into the repository's existing SQLAlchemy stack.
SQLite is a useful local default; deployments must configure a managed database
through ``PRISM_ANALYTICAL_HISTORY_DATABASE_URL``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable, Optional

from prism_analytical_schemas import AnalyticalObject, ObjectKind, sanitize_provenance_parameters
from prism_analytical_schemas.registry import PathResult, TraversalResult
from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    desc,
    insert,
    select,
    text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

_metadata = MetaData()
_objects = Table(
    "prism_analytical_objects", _metadata,
    Column("object_id", String(255), primary_key=True),
    Column("dataset_id", String(255), nullable=False, index=True),
    Column("dataset_revision", Integer, nullable=False, index=True),
    Column("source_fingerprint", String(255), nullable=False, index=True),
    Column("kind", String(64), nullable=False, index=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("snapshot", Text, nullable=False),
)
_edges = Table(
    "prism_analytical_lineage_edges", _metadata,
    Column("parent_object_id", String(255), primary_key=True),
    Column("child_object_id", String(255), primary_key=True),
    Column("relation", String(128), nullable=False),
)
_schema = Table(
    "prism_analytical_schema_version", _metadata,
    Column("version", Integer, primary_key=True),
)


def history_database_url() -> str:
    configured = os.environ.get("PRISM_ANALYTICAL_HISTORY_DATABASE_URL")
    if configured:
        return configured
    path = Path(".prism/runtime/analytical-history.sqlite").resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path.as_posix()}"


class DurableAnalyticalObjectRegistry:
    """SQL-backed equivalent of the Phase 8 registry.

    Registration is one transaction: object snapshot and every direct lineage
    edge commit together. The primary key is the idempotency boundary, so a retry
    cannot create duplicate history. Traversals issue indexed graph lookups rather
    than loading the registry into process memory.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine: Engine = create_engine(url, future=True, pool_pre_ping=True, connect_args=connect_args)
        _metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            if connection.execute(select(_schema.c.version).limit(1)).scalar_one_or_none() is None:
                connection.execute(insert(_schema).values(version=1))

    @staticmethod
    def _restore(snapshot: str) -> AnalyticalObject:
        return AnalyticalObject.model_validate(json.loads(snapshot))

    @staticmethod
    def _dump(record: AnalyticalObject) -> str:
        return json.dumps(record.model_dump(mode="json"), separators=(",", ":"), sort_keys=True)

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True

    def register(self, record: AnalyticalObject) -> AnalyticalObject:
        if any(parent.object_id == record.object_id for parent in record.provenance.parent_refs):
            raise ValueError("An analytical object cannot reference itself as a parent.")
        # Phase 8 producers already sanitize at their boundary, but persistence is
        # a second, mandatory boundary: a future producer cannot turn an accidental
        # payload credential into durable history simply by bypassing a helper.
        record = record.model_copy(update={"payload": sanitize_provenance_parameters(record.payload)})
        values = {
            "object_id": record.object_id,
            "dataset_id": record.provenance.dataset.dataset_id,
            "dataset_revision": record.provenance.dataset.revision,
            "source_fingerprint": record.provenance.dataset.source_fingerprint,
            "kind": record.kind.value,
            "created_at": record.provenance.created_at,
            "snapshot": self._dump(record),
        }
        try:
            with self.engine.begin() as connection:
                connection.execute(insert(_objects).values(**values))
                for parent in record.provenance.parent_refs:
                    connection.execute(insert(_edges).values(
                        parent_object_id=parent.object_id, child_object_id=record.object_id, relation=parent.relation
                    ))
        except IntegrityError as error:
            # A duplicate object id is the expected idempotent-retry race.  Any
            # other constraint failure is kept visible to the caller.
            existing = self.get(record.object_id)
            if existing is not None:
                raise ValueError(f"Analytical object {record.object_id!r} is already registered.") from error
            raise
        return self.get(record.object_id) or record

    def ensure(self, record: AnalyticalObject) -> AnalyticalObject:
        existing = self.get(record.object_id)
        if existing is not None:
            return existing
        try:
            return self.register(record)
        except ValueError:
            winner = self.get(record.object_id)
            if winner is not None:
                return winner
            raise

    def get(self, object_id: str) -> Optional[AnalyticalObject]:
        with self.engine.connect() as connection:
            snapshot = connection.execute(select(_objects.c.snapshot).where(_objects.c.object_id == object_id)).scalar_one_or_none()
        return None if snapshot is None else self._restore(snapshot)

    def exists(self, object_id: str) -> bool:
        return self.get(object_id) is not None

    def list_for_dataset(self, dataset_id: str, revision: Optional[int] = None, kind: Optional[ObjectKind] = None) -> list[AnalyticalObject]:
        statement = select(_objects.c.snapshot).where(_objects.c.dataset_id == dataset_id)
        if revision is not None:
            statement = statement.where(_objects.c.dataset_revision == revision)
        if kind is not None:
            statement = statement.where(_objects.c.kind == kind.value)
        statement = statement.order_by(desc(_objects.c.created_at), desc(_objects.c.object_id))
        with self.engine.connect() as connection:
            return [self._restore(snapshot) for snapshot in connection.execute(statement).scalars()]

    def list_recent(self, limit: int = 100, kind: Optional[ObjectKind] = None) -> list[AnalyticalObject]:
        """Return a bounded, newest-first history feed without exposing a write path."""
        statement = select(_objects.c.snapshot)
        if kind is not None:
            statement = statement.where(_objects.c.kind == kind.value)
        statement = statement.order_by(desc(_objects.c.created_at), desc(_objects.c.object_id)).limit(limit)
        with self.engine.connect() as connection:
            return [self._restore(snapshot) for snapshot in connection.execute(statement).scalars()]

    def _neighbor_ids(self, object_id: str, direction: str) -> list[str]:
        column = _edges.c.parent_object_id if direction == "ancestors" else _edges.c.child_object_id
        match = _edges.c.child_object_id if direction == "ancestors" else _edges.c.parent_object_id
        with self.engine.connect() as connection:
            return sorted(connection.execute(select(column).where(match == object_id)).scalars())

    def _records(self, object_ids: Iterable[str]) -> list[AnalyticalObject]:
        ids = sorted(set(object_ids))
        if not ids:
            return []
        with self.engine.connect() as connection:
            rows = connection.execute(select(_objects.c.object_id, _objects.c.snapshot).where(_objects.c.object_id.in_(ids))).all()
        by_id = {object_id: self._restore(snapshot) for object_id, snapshot in rows}
        return [by_id[object_id] for object_id in ids if object_id in by_id]

    def get_parents(self, object_id: str) -> Optional[list[AnalyticalObject]]:
        if not self.exists(object_id):
            return None
        return self._records(self._neighbor_ids(object_id, "ancestors"))

    def get_children(self, object_id: str) -> Optional[list[AnalyticalObject]]:
        if not self.exists(object_id):
            return None
        return self._records(self._neighbor_ids(object_id, "descendants"))

    def _traverse(self, object_id: str, direction: str, max_depth: Optional[int]) -> Optional[TraversalResult]:
        if not self.exists(object_id):
            return None
        depth_by_id = {object_id: 0}
        frontier = [object_id]
        edges: set[tuple[str, str]] = set()
        depth = 0
        truncated = False
        while frontier:
            if max_depth is not None and depth >= max_depth:
                truncated = any(self._neighbor_ids(item, direction) for item in frontier)
                break
            next_frontier: list[str] = []
            for current in frontier:
                for neighbor in self._neighbor_ids(current, direction):
                    edges.add((neighbor, current) if direction == "ancestors" else (current, neighbor))
                    if neighbor not in depth_by_id:
                        depth_by_id[neighbor] = depth + 1
                        next_frontier.append(neighbor)
            if not next_frontier:
                break
            frontier = sorted(set(next_frontier))
            depth += 1
        records = {record.object_id: record for record in self._records(depth_by_id)}
        nodes = [(records[oid], depth_by_id[oid]) for oid in sorted(records) if oid != object_id]
        nodes.sort(key=lambda item: (item[1], item[0].object_id))
        return TraversalResult(nodes=nodes, edges=sorted(edges), truncated=truncated)

    def ancestors(self, object_id: str, max_depth: Optional[int] = None) -> Optional[TraversalResult]:
        return self._traverse(object_id, "ancestors", max_depth)

    def descendants(self, object_id: str, max_depth: Optional[int] = None) -> Optional[TraversalResult]:
        return self._traverse(object_id, "descendants", max_depth)

    def shortest_path(self, from_object_id: str, to_object_id: str) -> Optional[PathResult]:
        if not self.exists(from_object_id) or not self.exists(to_object_id):
            return None
        if from_object_id == to_object_id:
            return PathResult(nodes=[], edges=[], found=True)
        seen = {from_object_id}
        predecessor: dict[str, tuple[str, str]] = {}
        frontier = [from_object_id]
        while frontier:
            next_frontier: list[str] = []
            for current in frontier:
                parents = [(oid, "parent") for oid in self._neighbor_ids(current, "ancestors")]
                children = [(oid, "child") for oid in self._neighbor_ids(current, "descendants")]
                for neighbor, relation in sorted(parents + children):
                    if neighbor in seen:
                        continue
                    seen.add(neighbor)
                    predecessor[neighbor] = (current, relation)
                    if neighbor == to_object_id:
                        chain = [to_object_id]
                        while chain[-1] != from_object_id:
                            chain.append(predecessor[chain[-1]][0])
                        chain.reverse()
                        records = {item.object_id: item for item in self._records(chain)}
                        nodes = [(records[oid], index) for index, oid in enumerate(chain[1:], start=1)]
                        edges = [
                            (chain[index], chain[index - 1]) if predecessor[chain[index]][1] == "parent" else (chain[index - 1], chain[index])
                            for index in range(1, len(chain))
                        ]
                        return PathResult(nodes=nodes, edges=edges, found=True)
                    next_frontier.append(neighbor)
            frontier = sorted(set(next_frontier))
        return PathResult(nodes=[], edges=[], found=False)


def create_history_registry() -> DurableAnalyticalObjectRegistry:
    return DurableAnalyticalObjectRegistry()
