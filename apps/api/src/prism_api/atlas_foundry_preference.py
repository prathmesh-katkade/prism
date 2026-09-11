"""10O: verified preference-pair (DPO) generator for the Atlas Foundry.

Sources real chosen/rejected pairs from Atlas memory's existing supersession
mechanism (``DurableAtlasMemoryStore.supersede()``, wired at
``POST /api/v1/atlas/memories/{memory_id}/supersede``): when a memory is
superseded, the *original* content is the rejected response, the *successor*
content is the chosen one, and the contradiction text supplied at
supersession time is the evaluator label. This module never manufactures a
negative example -- a pair exists only because a real correction event was
recorded.

KTO is deliberately not implemented here: it requires genuine binary
accept/reject feedback, and no such signal exists in the product yet.
Fabricating one to fill out this module would violate the same rule that
makes DPO here trustworthy in the first place.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from prism_api_contracts import (
    AtlasMemoryRecord,
    AtlasPreferenceDatasetVersion,
    AtlasPreferenceExclusion,
    AtlasPreferencePair,
    AtlasPreferencePairSource,
    AtlasTrainingSplit,
)
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
)
from sqlalchemy.engine import Engine

from .atlas_memory import DurableAtlasMemoryStore
from .atlas_schema_utils import ensure_index
from .durable_registry import history_database_url

# --- eligibility -------------------------------------------------------------


def exclusion_reason(rejected: AtlasMemoryRecord, chosen: Optional[AtlasMemoryRecord]) -> Optional[str]:
    """Why a superseded memory does NOT become a DPO pair, or ``None`` if it
    does. A dangling successor reference or an empty/no-op correction is
    real data hygiene, not something to paper over with a fabricated pair.
    """
    if chosen is None:
        return "successor memory referenced by superseded_by no longer exists"
    if not rejected.contradictions or not rejected.contradictions[-1].strip():
        return "supersession has no evaluator-supplied contradiction reason"
    if rejected.content.strip() == chosen.content.strip():
        return "rejected and chosen content are identical; not a real correction"
    return None


# --- pair construction ---------------------------------------------------


def _split_for(project_id: Optional[str]) -> AtlasTrainingSplit:
    """Deterministic ~80/10/10 split keyed on project_id (falling back to a
    fixed bucket for memories with no project), so pairs from the same
    project never straddle train and eval."""
    key = project_id or "__global__"
    bucket = int(hashlib.sha256(key.encode()).hexdigest(), 16) % 100
    if bucket < 80:
        return AtlasTrainingSplit.TRAIN
    if bucket < 90:
        return AtlasTrainingSplit.VALIDATION
    return AtlasTrainingSplit.TEST


def _content_hash(rejected: AtlasMemoryRecord, chosen: AtlasMemoryRecord, evaluator_label: str) -> str:
    canonical = json.dumps(
        {"rejected": rejected.content, "chosen": chosen.content, "label": evaluator_label}, sort_keys=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def pair_from_memories(rejected: AtlasMemoryRecord, chosen: AtlasMemoryRecord) -> AtlasPreferencePair:
    """Build one DPO pair. Callers should check ``exclusion_reason()`` first."""
    evaluator_label = rejected.contradictions[-1]
    content_hash = _content_hash(rejected, chosen, evaluator_label)
    return AtlasPreferencePair(
        pair_id=f"prefpair_{content_hash[:32]}",
        source=AtlasPreferencePairSource.MEMORY_SUPERSESSION,
        rejected_memory_id=rejected.memory_id,
        chosen_memory_id=chosen.memory_id,
        project_id=rejected.project_id,
        prompt_context=f"{rejected.knowledge_class.value} memory in scope {rejected.scope.value}"[:500],
        rejected_response=rejected.content,
        chosen_response=chosen.content,
        evaluator_label=evaluator_label,
        split=_split_for(rejected.project_id),
        content_hash=content_hash,
        created_at=rejected.updated_at or rejected.created_at or datetime.now(timezone.utc),
    )


def manifest_content_hash(pairs: Sequence[AtlasPreferencePair]) -> str:
    canonical = json.dumps(sorted(pair.content_hash for pair in pairs), sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class AtlasPreferenceDatasetBuilder:
    """Builds a deterministic, inspectable DPO corpus from real Atlas memory
    supersession events."""

    def __init__(self, memory_store: DurableAtlasMemoryStore) -> None:
        self._memory_store = memory_store

    def eligible_pairs(self, *, limit: int = 1000) -> tuple[list[AtlasPreferencePair], list[AtlasPreferenceExclusion]]:
        included: list[AtlasPreferencePair] = []
        excluded: list[AtlasPreferenceExclusion] = []
        seen_hashes: set[str] = set()
        for rejected in self._memory_store.list_superseded(limit=limit):
            chosen = self._memory_store.get(rejected.superseded_by) if rejected.superseded_by else None
            reason = exclusion_reason(rejected, chosen)
            if reason is not None or chosen is None:
                excluded.append(AtlasPreferenceExclusion(memory_id=rejected.memory_id, reason=reason or "no successor"))
                continue
            pair = pair_from_memories(rejected, chosen)
            if pair.content_hash in seen_hashes:
                excluded.append(
                    AtlasPreferenceExclusion(
                        memory_id=rejected.memory_id,
                        reason="duplicate of an already-included pair's rejected/chosen/label",
                    )
                )
                continue
            seen_hashes.add(pair.content_hash)
            included.append(pair)
        return included, excluded

    def build(self, *, limit: int = 1000) -> tuple[list[AtlasPreferencePair], list[AtlasPreferenceExclusion]]:
        return self.eligible_pairs(limit=limit)


def export_jsonl(pairs: Sequence[AtlasPreferencePair], path: Path) -> str:
    ordered = sorted(pairs, key=lambda item: item.pair_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for pair in ordered:
            handle.write(json.dumps(pair.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return manifest_content_hash(ordered)


# --- durable persistence ----------------------------------------------------

_metadata = MetaData()
_versions = Table(
    "prism_atlas_preference_dataset_versions",
    _metadata,
    Column("version_id", String(120), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("source_count", Integer, nullable=False),
    Column("excluded_count", Integer, nullable=False),
    Column("train_count", Integer, nullable=False),
    Column("validation_count", Integer, nullable=False),
    Column("test_count", Integer, nullable=False),
    Column("content_hash", String(64), nullable=False),
)
_pairs = Table(
    "prism_atlas_preference_pairs",
    _metadata,
    Column("pair_id", String(120), primary_key=True),
    Column("version_id", String(120), nullable=False, index=True),
    Column("split", String(16), nullable=False, index=True),
    Column("rejected_memory_id", String(120), nullable=False, index=True),
    Column("chosen_memory_id", String(120), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
_exclusions = Table(
    "prism_atlas_preference_exclusions",
    _metadata,
    Column("exclusion_id", String(160), primary_key=True),
    Column("version_id", String(120), nullable=False, index=True),
    Column("memory_id", String(120), nullable=False),
    Column("reason", String(500), nullable=False),
)


class DurableAtlasPreferenceDatasetStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            ensure_index(
                connection,
                "prism_atlas_preference_pairs",
                "ix_prism_atlas_preference_pairs_version_split",
                "CREATE INDEX ix_prism_atlas_preference_pairs_version_split "
                "ON prism_atlas_preference_pairs (version_id, split)",
            )

    def save(
        self, pairs: list[AtlasPreferencePair], exclusions: list[AtlasPreferenceExclusion]
    ) -> AtlasPreferenceDatasetVersion:
        content_hash = manifest_content_hash(pairs)
        version_id = f"prefset_{content_hash[:24]}"
        existing = self.get_version(version_id)
        if existing is not None:
            return existing
        now = datetime.now(timezone.utc)
        manifest = AtlasPreferenceDatasetVersion(
            version_id=version_id,
            created_at=now,
            source_count=len(pairs) + len(exclusions),
            excluded_count=len(exclusions),
            train_count=sum(1 for item in pairs if item.split is AtlasTrainingSplit.TRAIN),
            validation_count=sum(1 for item in pairs if item.split is AtlasTrainingSplit.VALIDATION),
            test_count=sum(1 for item in pairs if item.split is AtlasTrainingSplit.TEST),
            content_hash=content_hash,
        )
        with self.engine.begin() as connection:
            connection.execute(
                insert(_versions).values(
                    version_id=version_id,
                    created_at=now,
                    source_count=manifest.source_count,
                    excluded_count=manifest.excluded_count,
                    train_count=manifest.train_count,
                    validation_count=manifest.validation_count,
                    test_count=manifest.test_count,
                    content_hash=content_hash,
                )
            )
            for pair in pairs:
                connection.execute(
                    insert(_pairs).values(
                        pair_id=pair.pair_id,
                        version_id=version_id,
                        split=pair.split.value,
                        rejected_memory_id=pair.rejected_memory_id,
                        chosen_memory_id=pair.chosen_memory_id,
                        payload=json.dumps(pair.model_dump(mode="json"), sort_keys=True),
                        created_at=pair.created_at,
                    )
                )
            for exclusion in exclusions:
                connection.execute(
                    insert(_exclusions).values(
                        exclusion_id=f"{version_id}_{uuid.uuid4().hex}",
                        version_id=version_id,
                        memory_id=exclusion.memory_id,
                        reason=exclusion.reason,
                    )
                )
        return manifest

    def get_version(self, version_id: str) -> Optional[AtlasPreferenceDatasetVersion]:
        with self.engine.connect() as connection:
            row = connection.execute(select(_versions).where(_versions.c.version_id == version_id)).mappings().first()
        if row is None:
            return None
        return AtlasPreferenceDatasetVersion(
            version_id=str(row["version_id"]),
            created_at=row["created_at"],
            source_count=int(row["source_count"]),
            excluded_count=int(row["excluded_count"]),
            train_count=int(row["train_count"]),
            validation_count=int(row["validation_count"]),
            test_count=int(row["test_count"]),
            content_hash=str(row["content_hash"]),
        )

    def list_versions(self, *, limit: int = 50) -> list[AtlasPreferenceDatasetVersion]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(select(_versions).order_by(_versions.c.created_at.desc()).limit(limit))
                .mappings()
                .all()
            )
        return [
            AtlasPreferenceDatasetVersion(
                version_id=str(row["version_id"]),
                created_at=row["created_at"],
                source_count=int(row["source_count"]),
                excluded_count=int(row["excluded_count"]),
                train_count=int(row["train_count"]),
                validation_count=int(row["validation_count"]),
                test_count=int(row["test_count"]),
                content_hash=str(row["content_hash"]),
            )
            for row in rows
        ]

    def preview(
        self, version_id: str, *, split: Optional[AtlasTrainingSplit] = None, limit: int = 10
    ) -> list[AtlasPreferencePair]:
        statement = select(_pairs.c.payload).where(_pairs.c.version_id == version_id).order_by(_pairs.c.pair_id).limit(limit)
        if split is not None:
            statement = statement.where(_pairs.c.split == split.value)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).scalars().all()
        return [AtlasPreferencePair.model_validate(json.loads(row)) for row in rows]

    def exclusions(self, version_id: str, *, limit: int = 200) -> list[AtlasPreferenceExclusion]:
        statement = select(_exclusions.c.memory_id, _exclusions.c.reason).where(_exclusions.c.version_id == version_id).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [AtlasPreferenceExclusion(memory_id=str(row["memory_id"]), reason=str(row["reason"])) for row in rows]
