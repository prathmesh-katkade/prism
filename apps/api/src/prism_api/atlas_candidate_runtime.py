"""Durable runtime bindings for trained Atlas candidates.

A promotion pointer is only meaningful if the runtime can resolve it to an
actual inference artifact.  This module keeps that mapping append-only and
provider-specific without making Soup a runtime dependency.  Today the only
live binding is Ollama: Foundry may export/deploy a candidate there, then Atlas
can resolve the current production pointer to the recorded Ollama model name.

The environment-configured model remains the safe fallback when no production
pointer/binding exists, preserving local-first startup and rollback compatibility.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, insert, select
from sqlalchemy.engine import Engine

from .durable_registry import history_database_url

_MODEL_NAME = re.compile(r"^[A-Za-z0-9._:/-]{1,300}$")

_metadata = MetaData()
_bindings = Table(
    "prism_atlas_candidate_runtime_bindings",
    _metadata,
    Column("binding_id", String(120), primary_key=True),
    Column("candidate_id", String(120), nullable=False, index=True),
    Column("provider", String(32), nullable=False, index=True),
    Column("runtime_model", String(300), nullable=False),
    Column("runtime_model_digest", String(200), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


@dataclass(frozen=True)
class AtlasCandidateRuntimeBinding:
    binding_id: str
    candidate_id: str
    provider: str
    runtime_model: str
    runtime_model_digest: Optional[str]
    created_at: datetime


class DurableAtlasCandidateRuntimeStore:
    """Append-only candidate -> runtime binding history."""

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    @staticmethod
    def _record(row: object) -> AtlasCandidateRuntimeBinding:
        return AtlasCandidateRuntimeBinding(
            binding_id=row["binding_id"],  # type: ignore[index]
            candidate_id=row["candidate_id"],  # type: ignore[index]
            provider=row["provider"],  # type: ignore[index]
            runtime_model=row["runtime_model"],  # type: ignore[index]
            runtime_model_digest=row["runtime_model_digest"],  # type: ignore[index]
            created_at=row["created_at"],  # type: ignore[index]
        )

    def bind_ollama(
        self,
        candidate_id: str,
        runtime_model: str,
        *,
        runtime_model_digest: Optional[str] = None,
    ) -> AtlasCandidateRuntimeBinding:
        candidate_id = candidate_id.strip()
        runtime_model = runtime_model.strip()
        if not candidate_id or len(candidate_id) > 120:
            raise ValueError("candidate_id must contain 1-120 characters.")
        if not _MODEL_NAME.fullmatch(runtime_model):
            raise ValueError("runtime_model contains unsupported characters or exceeds 300 characters.")
        if runtime_model_digest is not None and len(runtime_model_digest) > 200:
            raise ValueError("runtime_model_digest exceeds 200 characters.")
        record = AtlasCandidateRuntimeBinding(
            binding_id=f"runtimebind_{uuid.uuid4().hex}",
            candidate_id=candidate_id,
            provider="ollama",
            runtime_model=runtime_model,
            runtime_model_digest=runtime_model_digest,
            created_at=datetime.now(timezone.utc),
        )
        with self.engine.begin() as connection:
            connection.execute(
                insert(_bindings).values(
                    binding_id=record.binding_id,
                    candidate_id=record.candidate_id,
                    provider=record.provider,
                    runtime_model=record.runtime_model,
                    runtime_model_digest=record.runtime_model_digest,
                    created_at=record.created_at,
                )
            )
        return record

    def latest(self, candidate_id: str, *, provider: str = "ollama") -> Optional[AtlasCandidateRuntimeBinding]:
        row = (
            self.engine.connect()
            .execute(
                select(_bindings)
                .where(_bindings.c.candidate_id == candidate_id, _bindings.c.provider == provider)
                .order_by(_bindings.c.created_at.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        return None if row is None else self._record(row)


def resolve_current_ollama_model(configured_model: str) -> str:
    """Resolve the production pointer to a real Ollama model when possible.

    Imports promotion storage lazily to keep Atlas runtime/provider imports
    acyclic.  Missing/corrupt optional history never prevents Atlas startup;
    the explicitly configured local model remains the deterministic fallback.
    """

    try:
        from .atlas_promotion import DurableAtlasPromotionStore

        production = DurableAtlasPromotionStore().current_production()
        if production is None:
            return configured_model
        binding = DurableAtlasCandidateRuntimeStore().latest(production.candidate_id)
        return configured_model if binding is None else binding.runtime_model
    except (OSError, ValueError):
        return configured_model
