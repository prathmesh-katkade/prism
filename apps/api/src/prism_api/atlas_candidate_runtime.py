"""Durable runtime bindings for trained Atlas candidates.

A promotion pointer is only meaningful if the runtime can resolve it to an
actual inference artifact. This module keeps that mapping append-only and
provider-specific without making Soup a runtime dependency. Today the only
live binding is Ollama: Foundry may export/deploy a candidate there, then Atlas
resolves the production pointer to the recorded Ollama model name.
"""

from __future__ import annotations

import hashlib
import os
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


def configured_ollama_model() -> str:
    return os.environ.get(
        "PRISM_ATLAS_OLLAMA_MODEL",
        os.environ.get("PRISM_OLLAMA_MODEL", "llama3.2:3b"),
    )


def resolve_current_ollama_model(configured_model: str) -> str:
    """Resolve the durable production pointer to its Ollama runtime binding."""
    try:
        from .atlas_promotion import DurableAtlasPromotionStore

        production = DurableAtlasPromotionStore().current_production()
        if production is None:
            return configured_model
        binding = DurableAtlasCandidateRuntimeStore().latest(production.candidate_id)
        return configured_model if binding is None else binding.runtime_model
    except (OSError, ValueError):
        return configured_model


def activate_current_ollama_model() -> str:
    """Apply the durable production pointer to the live Atlas process."""
    model = resolve_current_ollama_model(configured_ollama_model())
    os.environ["PRISM_ATLAS_OLLAMA_MODEL"] = model
    return model


def ensure_configured_production_baseline(*, runtime_model_digest: Optional[str] = None) -> str:
    """Create the rollback anchor for the pre-Foundry configured model once.

    Only active Ollama deployments are bootstrapped. The synthetic identity is
    derived from the configured model name and optional digest; no user data or
    benchmark information enters the identifier.
    """
    if os.environ.get("PRISM_AI_PROVIDER", "deterministic").lower() != "ollama":
        return configured_ollama_model()

    from .atlas_promotion import DurableAtlasPromotionStore

    promotion_store = DurableAtlasPromotionStore()
    current = promotion_store.current_production()
    if current is not None:
        return activate_current_ollama_model()

    model = configured_ollama_model()
    identity_material = f"{model}:{runtime_model_digest or 'digest-unavailable'}"
    baseline_id = f"production_env_{hashlib.sha256(identity_material.encode()).hexdigest()[:24]}"
    runtime_store = DurableAtlasCandidateRuntimeStore()
    if runtime_store.latest(baseline_id) is None:
        runtime_store.bind_ollama(
            baseline_id,
            model,
            runtime_model_digest=runtime_model_digest,
        )
    promotion_store.bootstrap(
        baseline_id,
        reason="Bootstrap the configured Ollama production model as Atlas's rollback anchor.",
    )
    return activate_current_ollama_model()
