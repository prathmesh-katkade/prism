"""Durable Atlas memory and offline-first lexical project knowledge.

Memory is an operational aid, never a rewrite of Phase 8/9 evidence.  Every
mutation has an append-only audit record and every retrieved project chunk keeps
its exact source/version/location so it can be inspected or removed.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Mapping, Optional

from fastapi import HTTPException, status
from prism_api_contracts import (
    AtlasEvidenceReference,
    AtlasKnowledgeChunk,
    AtlasKnowledgeSearchRequest,
    AtlasKnowledgeSourceRequest,
    AtlasMemoryQuery,
    AtlasMemoryRecord,
    AtlasMemoryWriteRequest,
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
    delete,
    insert,
    select,
    update,
)
from sqlalchemy.engine import Engine

from .atlas_schema_utils import ensure_index
from .durable_atlas_store import redact_atlas_payload
from .durable_registry import history_database_url

_metadata = MetaData()
_memories = Table("prism_atlas_memories", _metadata, Column("memory_id", String(120), primary_key=True), Column("dedupe_key", String(64), nullable=False, unique=True), Column("scope", String(32), nullable=False, index=True), Column("knowledge_class", String(32), nullable=False, index=True), Column("content", Text, nullable=False), Column("source", String(500), nullable=False), Column("source_ref", String(2000)), Column("confidence", String(16), nullable=False), Column("project_id", String(200), index=True), Column("workspace_id", String(200), index=True), Column("sensitivity", String(16), nullable=False), Column("user_editable", Boolean, nullable=False), Column("deletable", Boolean, nullable=False), Column("provenance", Text, nullable=False), Column("reinforcement", Integer, nullable=False, default=0), Column("contradictions", Text, nullable=False), Column("superseded_by", String(120)), Column("created_at", DateTime(timezone=True), nullable=False), Column("updated_at", DateTime(timezone=True), nullable=False), Column("last_used_at", DateTime(timezone=True)))
_memory_audit = Table("prism_atlas_memory_audit", _metadata, Column("audit_id", String(120), primary_key=True), Column("memory_id", String(120), nullable=False, index=True), Column("action", String(32), nullable=False), Column("occurred_at", DateTime(timezone=True), nullable=False), Column("detail", Text, nullable=False))
# ``source_ref`` is deliberately NOT indexed at its full String(2000) length:
# MySQL InnoDB caps an index key at 3072 bytes, and utf8mb4 (4 bytes/char)
# puts a 2000-char column at 8000 bytes -- CREATE INDEX fails with error 1071
# on MySQL even though SQLite accepts it. ``source_ref_hash`` is a short,
# portable stand-in carrying the lookup index; exact equality is still
# checked against ``source_ref`` itself, so behavior is unchanged.
_chunks = Table("prism_atlas_knowledge_chunks", _metadata, Column("chunk_id", String(120), primary_key=True), Column("project_id", String(200), nullable=False, index=True), Column("source_ref", String(2000), nullable=False), Column("source_ref_hash", String(64), nullable=False, index=True), Column("content_version", String(200), nullable=False), Column("kind", String(32), nullable=False), Column("location", String(500), nullable=False), Column("content", Text, nullable=False), Column("content_hash", String(64), nullable=False), Column("injection_detected", Boolean, nullable=False), Column("created_at", DateTime(timezone=True), nullable=False))


def _source_ref_hash(source_ref: str) -> str:
    return hashlib.sha256(source_ref.encode()).hexdigest()

_CREDENTIAL = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}|password\s*[:=])", re.I)
_INJECTION = re.compile(r"(?:ignore (?:all |previous )?instructions|system prompt|developer message|you are chatgpt|exfiltrat|reveal (?:secret|credential))", re.I)
_WORDS = re.compile(r"[a-zA-Z0-9_]{2,}")


def _now() -> datetime: return datetime.now(timezone.utc)
def _canonical(value: str) -> str: return " ".join(value.lower().split())
def _terms(value: str) -> set[str]: return set(_WORDS.findall(value.lower()))


class DurableAtlasMemoryStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        self.engine: Engine = create_engine(database_url or history_database_url(), future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if (database_url or history_database_url()).startswith("sqlite") else {})
        _metadata.create_all(self.engine)
        # Plain CREATE INDEX guarded by an existence check, not
        # "IF NOT EXISTS": MySQL 8.0 has no such clause and rejects it with a
        # 1064 syntax error. See atlas_schema_utils.ensure_index.
        with self.engine.begin() as connection:
            ensure_index(
                connection,
                "prism_atlas_memories",
                "ix_prism_atlas_memory_lookup",
                "CREATE INDEX ix_prism_atlas_memory_lookup "
                "ON prism_atlas_memories (scope, project_id, knowledge_class, updated_at)",
            )
            ensure_index(
                connection,
                "prism_atlas_knowledge_chunks",
                "ix_prism_atlas_chunks_lookup",
                "CREATE INDEX ix_prism_atlas_chunks_lookup "
                "ON prism_atlas_knowledge_chunks (project_id, source_ref_hash)",
            )

    @staticmethod
    def _record(row: Mapping[str, Any]) -> AtlasMemoryRecord:
        item = row
        provenance = [AtlasEvidenceReference.model_validate(value) for value in json.loads(item["provenance"])]
        return AtlasMemoryRecord(memory_id=item["memory_id"], scope=item["scope"], knowledge_class=item["knowledge_class"], content=item["content"], source=item["source"], source_ref=item["source_ref"], confidence=item["confidence"], timestamp=item["created_at"], provenance=provenance, reinforcement=item["reinforcement"], last_used=item["last_used_at"], last_used_at=item["last_used_at"], contradictions=json.loads(item["contradictions"]), superseded_by=item["superseded_by"], project_id=item["project_id"], workspace_id=item["workspace_id"], sensitivity=item["sensitivity"], user_editable=item["user_editable"], deletable=item["deletable"], created_at=item["created_at"], updated_at=item["updated_at"])

    def _audit(self, connection: object, memory_id: str, action: str, detail: dict[str, object]) -> None:
        connection.execute(insert(_memory_audit).values(audit_id=f"memory_audit_{uuid.uuid4().hex}", memory_id=memory_id, action=action, occurred_at=_now(), detail=json.dumps(redact_atlas_payload(detail), sort_keys=True)))  # type: ignore[attr-defined]

    def create_or_reinforce(self, request: AtlasMemoryWriteRequest) -> AtlasMemoryRecord:
        if _CREDENTIAL.search(request.content) or redact_atlas_payload(request.content) != request.content:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Atlas memory rejects credentials and secret-shaped values.")
        dedupe = hashlib.sha256("|".join([request.scope.value, request.knowledge_class.value, request.project_id or "", request.workspace_id or "", _canonical(request.content)]).encode()).hexdigest()
        now = _now()
        with self.engine.begin() as connection:
            existing = connection.execute(select(_memories).where(_memories.c.dedupe_key == dedupe)).mappings().first()
            if existing:
                connection.execute(update(_memories).where(_memories.c.memory_id == existing["memory_id"]).values(reinforcement=int(existing["reinforcement"]) + 1, updated_at=now, last_used_at=now))
                self._audit(connection, str(existing["memory_id"]), "reinforced", {"source": request.source})
                row = connection.execute(select(_memories).where(_memories.c.memory_id == existing["memory_id"])).mappings().one()
                return self._record(row)
            memory_id = f"memory_{uuid.uuid4().hex}"
            connection.execute(insert(_memories).values(memory_id=memory_id, dedupe_key=dedupe, scope=request.scope.value, knowledge_class=request.knowledge_class.value, content=request.content, source=request.source, source_ref=request.source_ref, confidence=request.confidence, project_id=request.project_id, workspace_id=request.workspace_id, sensitivity=request.sensitivity, user_editable=request.user_editable, deletable=True, provenance=json.dumps([item.model_dump(mode="json") for item in request.provenance]), reinforcement=0, contradictions="[]", superseded_by=None, created_at=now, updated_at=now, last_used_at=None))
            self._audit(connection, memory_id, "created", {"source": request.source, "source_ref": request.source_ref or ""})
            row = connection.execute(select(_memories).where(_memories.c.memory_id == memory_id)).mappings().one()
            return self._record(row)

    def query(self, query: AtlasMemoryQuery) -> list[AtlasMemoryRecord]:
        statement = select(_memories).order_by(_memories.c.updated_at.desc()).limit(query.limit)
        for column, value in (("scope", query.scope.value if query.scope else None), ("knowledge_class", query.knowledge_class.value if query.knowledge_class else None), ("project_id", query.project_id), ("workspace_id", query.workspace_id)):
            if value is not None:
                statement = statement.where(getattr(_memories.c, column) == value)
        if query.updated_after:
            statement = statement.where(_memories.c.updated_at >= query.updated_after)
        rank = {"low": 0, "medium": 1, "high": 2}
        records = [self._record(row) for row in self.engine.connect().execute(statement).mappings().all()]
        return [record for record in records if query.min_confidence is None or rank[record.confidence] >= rank[query.min_confidence]]

    def supersede(self, memory_id: str, successor_id: str, contradiction: str) -> AtlasMemoryRecord:
        with self.engine.begin() as connection:
            result = connection.execute(update(_memories).where(_memories.c.memory_id == memory_id).values(superseded_by=successor_id, contradictions=json.dumps([contradiction]), updated_at=_now()))
            if result.rowcount != 1:
                raise HTTPException(status_code=404, detail="Atlas memory was not found.")
            self._audit(connection, memory_id, "superseded", {"successor": successor_id, "contradiction": contradiction})
            return self._record(connection.execute(select(_memories).where(_memories.c.memory_id == memory_id)).mappings().one())

    def delete_memory(self, memory_id: str) -> None:
        with self.engine.begin() as connection:
            row = connection.execute(select(_memories.c.deletable).where(_memories.c.memory_id == memory_id)).first()
            if row is None:
                raise HTTPException(status_code=404, detail="Atlas memory was not found.")
            if not row[0]:
                raise HTTPException(status_code=409, detail="This Atlas memory is retained by policy.")
            self._audit(connection, memory_id, "deleted", {})
            connection.execute(delete(_memories).where(_memories.c.memory_id == memory_id))

    def index_source(self, request: AtlasKnowledgeSourceRequest) -> list[AtlasKnowledgeChunk]:
        if _CREDENTIAL.search(request.content):
            raise HTTPException(status_code=422, detail="Project knowledge rejects credentials and secret-shaped values.")
        parts = [request.content[index:index + 1200] for index in range(0, len(request.content), 1000)]
        now = _now()
        source_ref_hash = _source_ref_hash(request.source_ref)
        with self.engine.begin() as connection:
            connection.execute(delete(_chunks).where((_chunks.c.project_id == request.project_id) & (_chunks.c.source_ref_hash == source_ref_hash) & (_chunks.c.source_ref == request.source_ref)))
            for index, content in enumerate(parts):
                connection.execute(insert(_chunks).values(chunk_id=f"chunk_{uuid.uuid4().hex}", project_id=request.project_id, source_ref=request.source_ref, source_ref_hash=source_ref_hash, content_version=request.content_version, kind=request.kind, location=f"chars:{index * 1000}-{min(len(request.content), index * 1000 + 1200)}", content=content, content_hash=hashlib.sha256(content.encode()).hexdigest(), injection_detected=bool(_INJECTION.search(content)), created_at=now))
        return self.search(AtlasKnowledgeSearchRequest(project_id=request.project_id, query=" ".join(_terms(request.content)), limit=len(parts)))

    def search(self, request: AtlasKnowledgeSearchRequest) -> list[AtlasKnowledgeChunk]:
        query_terms = _terms(request.query)
        rows = self.engine.connect().execute(select(_chunks).where(_chunks.c.project_id == request.project_id)).mappings().all()
        values = []
        for row in rows:
            overlap = len(query_terms & _terms(str(row["content"])))
            if overlap:
                values.append(AtlasKnowledgeChunk(chunk_id=row["chunk_id"], project_id=row["project_id"], source_ref=row["source_ref"], content_version=row["content_version"], location=row["location"], content=row["content"], injection_detected=bool(row["injection_detected"]), score=overlap / max(1, len(query_terms))))
        return sorted(values, key=lambda item: item.score, reverse=True)[:request.limit]

    def delete_source(self, project_id: str, source_ref: str) -> None:
        with self.engine.begin() as connection:
            connection.execute(delete(_chunks).where((_chunks.c.project_id == project_id) & (_chunks.c.source_ref_hash == _source_ref_hash(source_ref)) & (_chunks.c.source_ref == source_ref)))
