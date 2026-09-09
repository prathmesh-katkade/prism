"""Local-first, provenance-preserving Atlas hybrid retrieval.

Retrieved text is evidence, never executable instruction.  This layer is
deliberately separate from the legacy Atlas memory store so existing callers
keep their historical behaviour while retrieval grows an inspectable lifecycle.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional, Protocol, Sequence

import httpx
from fastapi import HTTPException, status
from prism_api_contracts import (
    AtlasEmbeddingCapability,
    AtlasMemoryClass,
    AtlasRetrievalChunk,
    AtlasRetrievalChunkUpsertRequest,
    AtlasRetrievalQueryRequest,
    AtlasRetrievalResult,
)
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
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

from .atlas_schema_utils import ensure_index
from .durable_atlas_store import redact_atlas_payload
from .durable_registry import history_database_url

_WORDS = re.compile(r"[a-zA-Z0-9_]{2,}")
_INJECTION = re.compile(r"(?:ignore (?:all |previous )?instructions|system prompt|developer message|you are chatgpt|exfiltrat|reveal (?:secret|credential))", re.I)
_CREDENTIAL = re.compile(r"(?:sk-[A-Za-z0-9_-]{12,}|(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{12,}|password\s*[:=])", re.I)
_CONFIDENCE = {"low": 0.35, "medium": 0.65, "high": 1.0}
_CLASS_WEIGHT = {
    "data_evidence": 1.0, "project_knowledge": 0.9, "user_memory": 0.85,
    "model_knowledge": 0.75, "web_research": 0.7,
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: str) -> str:
    return " ".join(text.split())


def _terms(text: str) -> set[str]:
    return set(_WORDS.findall(text.lower()))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return 0.0 if denominator == 0 else sum(a * b for a, b in zip(left, right)) / denominator


class EmbeddingBackend(Protocol):
    def capability(self) -> AtlasEmbeddingCapability: ...
    def embed(self, texts: Sequence[str]) -> Optional[list[list[float]]]: ...


class LexicalOnlyEmbeddingBackend:
    """Safe production default: retrieval works when no embedding runtime exists."""

    def capability(self) -> AtlasEmbeddingCapability:
        return AtlasEmbeddingCapability(provider="lexical", model="none", revision="v1", dimension=None, available=False, detail="Vector embeddings are not configured; deterministic lexical retrieval remains available.")

    def embed(self, texts: Sequence[str]) -> Optional[list[list[float]]]:
        return None


class DeterministicEmbeddingBackend:
    """Hash-based test backend; intentionally not a semantic production model."""

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def capability(self) -> AtlasEmbeddingCapability:
        return AtlasEmbeddingCapability(provider="deterministic-test", model="token-hash", revision="v1", dimension=self.dimension, available=True, detail="Deterministic test embedding backend; not selected by production defaults.")

    def embed(self, texts: Sequence[str]) -> Optional[list[list[float]]]:
        vectors: list[list[float]] = []
        for text in texts:
            vector = [0.0] * self.dimension
            for term in sorted(_terms(text)):
                vector[int(hashlib.sha256(term.encode()).hexdigest()[:8], 16) % self.dimension] += 1.0
            vectors.append(vector)
        return vectors


class OllamaEmbeddingBackend:
    """Optional local Ollama embedding backend; no cloud fallback is permitted."""

    def __init__(self) -> None:
        self.model = os.environ.get("PRISM_RAG_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-0.6B")
        self.base_url = os.environ.get("PRISM_OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")

    def capability(self) -> AtlasEmbeddingCapability:
        return AtlasEmbeddingCapability(provider="ollama", model=self.model, revision="ollama-api-embed-v1", dimension=None, available=True, detail="Local Ollama embedding backend selected; each request is validated at call time and falls back to lexical retrieval on failure.")

    def embed(self, texts: Sequence[str]) -> Optional[list[list[float]]]:
        try:
            response = httpx.post(f"{self.base_url}/api/embed", json={"model": self.model, "input": list(texts)}, timeout=15.0)
            response.raise_for_status()
            values = response.json().get("embeddings")
            if not isinstance(values, list) or len(values) != len(texts):
                return None
            vectors = [[float(value) for value in vector] for vector in values]
            if not vectors or not all(vectors) or len({len(vector) for vector in vectors}) != 1:
                return None
            return vectors
        except (httpx.HTTPError, TypeError, ValueError):
            return None


def configured_embedding_backend() -> EmbeddingBackend:
    return OllamaEmbeddingBackend() if os.environ.get("PRISM_RAG_EMBEDDING_PROVIDER", "").lower() == "ollama" else LexicalOnlyEmbeddingBackend()


_metadata = MetaData()
_chunks = Table(
    "prism_atlas_retrieval_chunks", _metadata,
    Column("chunk_id", String(120), primary_key=True), Column("project_id", String(200), nullable=False, index=True),
    Column("knowledge_class", String(32), nullable=False, index=True), Column("source_type", String(64), nullable=False),
    Column("source_id", String(500), nullable=False), Column("source_version", String(200), nullable=False),
    Column("locator", String(2000), nullable=False), Column("content_hash", String(64), nullable=False),
    Column("normalized_text", Text, nullable=False), Column("embedding_provider", String(80), nullable=False),
    Column("embedding_model", String(300), nullable=False), Column("embedding_revision", String(200), nullable=False),
    Column("embedding_dimension", String(16)), Column("embedding", Text), Column("indexed_at", DateTime(timezone=True), nullable=False),
    Column("freshness", String(16), nullable=False, index=True), Column("confidence", String(16), nullable=False),
    Column("prompt_injection_flag", Boolean, nullable=False), Column("safety_metadata", Text, nullable=False), Column("superseded_by", String(120)),
)


class DurableAtlasRetrievalStore:
    def __init__(self, database_url: Optional[str] = None, *, embedding_backend: Optional[EmbeddingBackend] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        self.backend = embedding_backend or configured_embedding_backend()
        _metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            ensure_index(connection, "prism_atlas_retrieval_chunks", "ix_prism_atlas_retrieval_source", "CREATE INDEX ix_prism_atlas_retrieval_source ON prism_atlas_retrieval_chunks (project_id, source_type, source_id, freshness)")

    def capability(self) -> AtlasEmbeddingCapability:
        return self.backend.capability()

    @staticmethod
    def _record(row: Any) -> AtlasRetrievalChunk:
        return AtlasRetrievalChunk(
            chunk_id=row["chunk_id"], project_id=row["project_id"], knowledge_class=row["knowledge_class"], source_type=row["source_type"], source_id=row["source_id"], source_version=row["source_version"], locator=row["locator"], content_hash=row["content_hash"], normalized_text=row["normalized_text"], embedding_provider=row["embedding_provider"], embedding_model=row["embedding_model"], embedding_revision=row["embedding_revision"], embedding_dimension=int(row["embedding_dimension"]) if row["embedding_dimension"] else None, indexed_at=row["indexed_at"], freshness=row["freshness"], confidence=row["confidence"], prompt_injection_flag=bool(row["prompt_injection_flag"]), safety_metadata=json.loads(row["safety_metadata"]), superseded_by=row["superseded_by"],
        )

    def index(self, request: AtlasRetrievalChunkUpsertRequest, *, authoritative: bool = False) -> AtlasRetrievalChunk:
        if request.knowledge_class is AtlasMemoryClass.DATA_EVIDENCE and not authoritative:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="DATA_EVIDENCE provenance is server-owned and cannot be forged by a client index request.")
        if _CREDENTIAL.search(request.content) or redact_atlas_payload(request.content) != request.content:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Retrieval indexing rejects credentials and secret-shaped content.")
        normalized = _normalize(request.content)
        content_hash = hashlib.sha256(normalized.encode()).hexdigest()
        capability = self.capability()
        vectors = self.backend.embed([normalized]) if capability.available else None
        vector = vectors[0] if vectors else None
        now = _now()
        with self.engine.begin() as connection:
            existing = connection.execute(select(_chunks).where(_chunks.c.project_id == request.project_id, _chunks.c.source_type == request.source_type, _chunks.c.source_id == request.source_id, _chunks.c.locator == request.locator, _chunks.c.freshness == "active").order_by(_chunks.c.indexed_at.desc()).limit(1)).mappings().first()
            if existing and existing["content_hash"] == content_hash and existing["embedding_provider"] == capability.provider and existing["embedding_model"] == capability.model and existing["embedding_revision"] == capability.revision:
                return self._record(existing)
            chunk_id = f"ragchunk_{uuid.uuid4().hex}"
            if existing:
                connection.execute(update(_chunks).where(_chunks.c.chunk_id == existing["chunk_id"]).values(freshness="superseded", superseded_by=chunk_id))
            safety = {"retrieved_content_is_data": True, "prompt_injection_detected": bool(_INJECTION.search(normalized)), "raw_dataset_rows_indexed": False}
            connection.execute(insert(_chunks).values(chunk_id=chunk_id, project_id=request.project_id, knowledge_class=request.knowledge_class.value, source_type=request.source_type, source_id=request.source_id, source_version=request.source_version, locator=request.locator, content_hash=content_hash, normalized_text=normalized, embedding_provider=capability.provider, embedding_model=capability.model, embedding_revision=capability.revision, embedding_dimension=str(len(vector)) if vector else None, embedding=json.dumps(vector) if vector else None, indexed_at=now, freshness="active", confidence=request.confidence, prompt_injection_flag=safety["prompt_injection_detected"], safety_metadata=json.dumps(safety, sort_keys=True), superseded_by=None))
            row = connection.execute(select(_chunks).where(_chunks.c.chunk_id == chunk_id)).mappings().one()
        return self._record(row)

    def index_authoritative_evidence(self, request: AtlasRetrievalChunkUpsertRequest) -> AtlasRetrievalChunk:
        """Internal-only entry point for evidence services with durable provenance."""
        if request.knowledge_class is not AtlasMemoryClass.DATA_EVIDENCE:
            raise ValueError("Authoritative evidence must use DATA_EVIDENCE.")
        return self.index(request, authoritative=True)

    def query(self, request: AtlasRetrievalQueryRequest) -> list[AtlasRetrievalResult]:
        statement = select(_chunks).where(_chunks.c.project_id == request.project_id)
        if not request.include_stale:
            statement = statement.where(_chunks.c.freshness == "active")
        if request.knowledge_classes:
            statement = statement.where(_chunks.c.knowledge_class.in_([item.value for item in request.knowledge_classes]))
        query_terms = _terms(request.query)
        query_vectors = self.backend.embed([_normalize(request.query)]) if self.capability().available else None
        query_vector = query_vectors[0] if query_vectors else []
        values: list[AtlasRetrievalResult] = []
        for row in self.engine.connect().execute(statement).mappings().all():
            chunk_terms = _terms(str(row["normalized_text"]))
            lexical = len(query_terms & chunk_terms) / math.sqrt(max(1, len(query_terms)) * max(1, len(chunk_terms)))
            stored_vector = json.loads(row["embedding"]) if row["embedding"] else []
            vector = max(0.0, _cosine(query_vector, stored_vector))
            age_days = max(0.0, (_now() - row["indexed_at"].replace(tzinfo=timezone.utc) if row["indexed_at"].tzinfo is None else _now() - row["indexed_at"]).total_seconds() / 86400)
            recency = 1.0 / (1.0 + age_days / 30.0)
            confidence = _CONFIDENCE[str(row["confidence"])]
            class_weight = _CLASS_WEIGHT[str(row["knowledge_class"])]
            hybrid = class_weight * (0.55 * lexical + 0.30 * vector + 0.10 * recency + 0.05 * confidence)
            if lexical == 0 and vector == 0:
                continue
            values.append(AtlasRetrievalResult(**self._record(row).model_dump(), lexical_score=lexical, vector_score=vector, recency_score=recency, confidence_score=confidence, scope_score=1.0, class_weight=class_weight, hybrid_score=hybrid))
        return sorted(values, key=lambda item: (-item.hybrid_score, item.source_id, item.locator, item.chunk_id))[:request.limit]

    def list_chunks(self, project_id: str, *, include_stale: bool = False, limit: int = 100) -> list[AtlasRetrievalChunk]:
        statement = select(_chunks).where(_chunks.c.project_id == project_id)
        if not include_stale:
            statement = statement.where(_chunks.c.freshness == "active")
        return [self._record(row) for row in self.engine.connect().execute(statement.order_by(_chunks.c.indexed_at.desc()).limit(limit)).mappings().all()]

    def delete_source(self, project_id: str, source_type: str, source_id: str) -> int:
        with self.engine.begin() as connection:
            result = connection.execute(update(_chunks).where(_chunks.c.project_id == project_id, _chunks.c.source_type == source_type, _chunks.c.source_id == source_id, _chunks.c.freshness == "active").values(freshness="deleted"))
        return int(result.rowcount or 0)

    def reembed_active(self) -> int:
        """Backfill vectors when an embedding backend is deliberately changed."""
        capability = self.capability()
        if not capability.available:
            return 0
        rows = self.engine.connect().execute(select(_chunks).where(_chunks.c.freshness == "active")).mappings().all()
        changed = 0
        with self.engine.begin() as connection:
            for row in rows:
                if (row["embedding_provider"], row["embedding_model"], row["embedding_revision"]) == (capability.provider, capability.model, capability.revision):
                    continue
                vectors = self.backend.embed([str(row["normalized_text"])])
                if not vectors:
                    continue
                connection.execute(update(_chunks).where(_chunks.c.chunk_id == row["chunk_id"]).values(embedding_provider=capability.provider, embedding_model=capability.model, embedding_revision=capability.revision, embedding_dimension=str(len(vectors[0])), embedding=json.dumps(vectors[0])))
                changed += 1
        return changed
