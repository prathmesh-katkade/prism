"""10N: verified training-dataset generator for the Atlas Self-Improvement Foundry.

Builds a durable, inspectable SFT corpus from real, already-durable Atlas run
history -- never from fabricated or hypothetical interactions. Every example
traces back to a real ``run_id`` a human can open in the Atlas Operations
Desk. Hidden chain-of-thought is never a source: ``plan_steps`` and
``council`` reuse the exact typed, already-user-visible structures Atlas
exposes (declared tool calls and their state, visible specialist conclusions
and objections) -- there is no private reasoning field to leak. Dataset
context is a compact id/revision reference, never raw dataset rows.

Soup (the training subsystem, 10M) consumes this module's deterministic
JSONL export; this module has no dependency on Soup and works standalone.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence, cast

from prism_api_contracts import (
    AtlasPlanState,
    AtlasRunResponse,
    AtlasStepState,
    AtlasTrainingDatasetVersion,
    AtlasTrainingExample,
    AtlasTrainingExampleSource,
    AtlasTrainingExclusion,
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
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Connection, Engine

from .atlas_schema_utils import ensure_index
from .durable_atlas_store import DurableAtlasRunStore, redact_atlas_payload
from .durable_registry import history_database_url

# --- eligibility -----------------------------------------------------------


def eligibility_reason(run: AtlasRunResponse) -> Optional[str]:
    """Why a run is NOT eligible for training-example extraction, or ``None``
    if it is. Eligible means: a completed run with a real grounded answer,
    at least one piece of evidence backing it, and at least one tool step
    that actually completed -- an "insufficient context" run that only
    blocked is real Atlas behavior, but it teaches "decline safely," not
    "here is a completed analysis," so it is excluded from this SFT source.
    """
    if run.plan.state is not AtlasPlanState.COMPLETED:
        return f"run state is {run.plan.state.value}, not completed"
    if not run.answer:
        return "run has no final grounded answer"
    if not run.evidence:
        return "run has no evidence references"
    if not any(step.state is AtlasStepState.COMPLETED for step in run.plan.steps):
        return "run has no completed tool steps"
    return None


# --- example construction ---------------------------------------------------


def _assign_split(dataset_id: str) -> AtlasTrainingSplit:
    """Deterministic ~80/10/10 split keyed on dataset_id.

    Every example sharing a dataset_id lands in the same split, so
    near-duplicate examples from the same dataset/run family never straddle
    train and eval -- the leakage this project was explicitly told to avoid.
    """
    bucket = int(hashlib.sha256(dataset_id.encode()).hexdigest(), 16) % 100
    if bucket < 80:
        return AtlasTrainingSplit.TRAIN
    if bucket < 90:
        return AtlasTrainingSplit.VALIDATION
    return AtlasTrainingSplit.TEST


def _content_hash(run: AtlasRunResponse) -> str:
    canonical = json.dumps(
        {
            "objective": run.plan.objective,
            "tools": [step.tool_name for step in run.plan.steps],
            "answer": run.answer,
        },
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def example_from_run(run: AtlasRunResponse) -> AtlasTrainingExample:
    """Build one training example from a single eligible run.

    Callers should check ``eligibility_reason(run) is None`` first; this
    raises rather than guess if ``run.answer`` is missing.
    """
    if run.answer is None:
        raise ValueError(f"run {run.run_id} has no answer; check eligibility_reason() first")
    content_hash = _content_hash(run)
    # A second redaction pass at the training-data boundary, defense in
    # depth: durable_atlas_store already redacts secret-shaped values before
    # persistence, but a training export is a second place a credential must
    # never survive even if a future write path skipped that first boundary.
    sanitized_steps = [
        step.model_copy(update={"tool_args": cast(dict[str, object], redact_atlas_payload(step.tool_args))})
        for step in run.plan.steps
    ]
    return AtlasTrainingExample(
        example_id=f"trainex_{content_hash[:32]}",
        source=AtlasTrainingExampleSource.ATLAS_RUN,
        source_run_id=run.run_id,
        dataset_id=run.plan.dataset_id,
        split=_assign_split(run.plan.dataset_id),
        user_request=run.plan.objective,
        # Compact reference only -- never the underlying dataset's rows.
        dataset_metadata={"dataset_id": run.plan.dataset_id},
        plan_steps=sanitized_steps,
        evidence=run.evidence,
        council=run.council,
        final_answer=run.answer,
        uncertainty=run.uncertainty,
        quality_label="verified_success",
        content_hash=content_hash,
        created_at=run.updated_at or run.created_at or datetime.now(timezone.utc),
    )


def manifest_content_hash(examples: Sequence[AtlasTrainingExample]) -> str:
    """Deterministic hash over an export's exact example set -- two builds
    over identical run history must produce the identical hash, proving the
    export is reproducible rather than merely re-runnable."""
    canonical = json.dumps(
        sorted(example.content_hash for example in examples), sort_keys=True
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


class AtlasTrainingDatasetBuilder:
    """Builds a deterministic, inspectable SFT corpus from durable Atlas runs."""

    def __init__(self, run_store: DurableAtlasRunStore) -> None:
        self._run_store = run_store

    def eligible_runs(self, *, limit: int = 1000) -> tuple[list[AtlasRunResponse], list[AtlasTrainingExclusion]]:
        included: list[AtlasRunResponse] = []
        excluded: list[AtlasTrainingExclusion] = []
        for run_id in self._run_store.list_run_ids(limit=limit):
            run = self._run_store.get(run_id)
            reason = eligibility_reason(run)
            if reason is not None:
                excluded.append(AtlasTrainingExclusion(run_id=run_id, reason=reason))
            else:
                included.append(run)
        return included, excluded

    def build(self, *, limit: int = 1000) -> tuple[list[AtlasTrainingExample], list[AtlasTrainingExclusion]]:
        """Deterministic: rebuilding over unchanged run history yields the
        same example_ids, the same splits, and the same manifest hash."""
        runs, excluded = self.eligible_runs(limit=limit)
        examples: list[AtlasTrainingExample] = []
        seen_hashes: set[str] = set()
        for run in runs:
            example = example_from_run(run)
            if example.content_hash in seen_hashes:
                excluded.append(
                    AtlasTrainingExclusion(
                        run_id=run.run_id,
                        reason="duplicate of an already-included example's objective/tools/answer",
                    )
                )
                continue
            seen_hashes.add(example.content_hash)
            examples.append(example)
        return examples, excluded


def export_jsonl(examples: Sequence[AtlasTrainingExample], path: Path) -> str:
    """Write one JSON object per line, sorted by example_id for a byte-stable
    file across identical runs. Returns the manifest content hash. This is
    the Soup-compatible manifest format 10M's FoundryBackend reads."""
    ordered = sorted(examples, key=lambda item: item.example_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for example in ordered:
            handle.write(json.dumps(example.model_dump(mode="json"), sort_keys=True, separators=(",", ":")))
            handle.write("\n")
    return manifest_content_hash(ordered)


# --- durable persistence ----------------------------------------------------

_metadata = MetaData()
_versions = Table(
    "prism_atlas_training_dataset_versions",
    _metadata,
    Column("version_id", String(120), primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
    Column("source_run_count", Integer, nullable=False),
    Column("excluded_count", Integer, nullable=False),
    Column("train_count", Integer, nullable=False),
    Column("validation_count", Integer, nullable=False),
    Column("test_count", Integer, nullable=False),
    Column("content_hash", String(64), nullable=False),
)
_examples = Table(
    "prism_atlas_training_examples",
    _metadata,
    # The same immutable example can legitimately belong to multiple immutable
    # corpus versions as new verified runs arrive. Its content identity is only
    # unique *within* a version; a global primary key would make a later
    # reindex fail or silently omit prior evidence.
    Column("version_id", String(120), primary_key=True),
    Column("example_id", String(120), primary_key=True),
    Column("split", String(16), nullable=False, index=True),
    Column("dataset_id", String(255), nullable=False, index=True),
    Column("source_run_id", String(120), nullable=False, index=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)
_exclusions = Table(
    "prism_atlas_training_exclusions",
    _metadata,
    Column("exclusion_id", String(160), primary_key=True),
    Column("version_id", String(120), nullable=False, index=True),
    Column("run_id", String(120), nullable=False),
    Column("reason", String(500), nullable=False),
)


class DurableAtlasTrainingDatasetStore:
    """SQL-backed manifest + example persistence, portable across SQLite and
    MySQL (see ``atlas_schema_utils.ensure_index`` for why that needs care).
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        with self.engine.begin() as connection:
            self._drop_legacy_example_indexes(connection)
            _metadata.create_all(connection)
            self._migrate_example_identity(connection)
            ensure_index(
                connection,
                "prism_atlas_training_examples",
                "ix_prism_atlas_training_examples_version_split",
                "CREATE INDEX ix_prism_atlas_training_examples_version_split "
                "ON prism_atlas_training_examples (version_id, split)",
            )

    @staticmethod
    def _drop_legacy_example_indexes(connection: Connection) -> None:
        """Clear SQLite index names before rebuilding a legacy table.

        SQLite keeps an index's globally scoped name when a table is renamed.
        Removing the legacy indexes first lets SQLAlchemy create equivalent
        indexes on the replacement table, then the legacy rows can be copied
        without losing data.
        """
        inspector = inspect(connection)
        legacy = "prism_atlas_training_examples_legacy"
        if not inspector.has_table(legacy):
            return
        if connection.dialect.name != "sqlite":
            raise RuntimeError("Unexpected interrupted Atlas training-example migration.")
        for item in inspector.get_indexes(legacy):
            name = str(item["name"])
            safe_name = name.replace('"', '""')
            connection.execute(text(f'DROP INDEX IF EXISTS "{safe_name}"'))

    @staticmethod
    def _migrate_example_identity(connection: Connection) -> None:
        """Upgrade the pre-release global-example primary key in place.

        Corpus versions are append-only snapshots, so older rows must remain
        addressable when a later snapshot repeats their immutable example. The
        initial Phase 10 schema accidentally made ``example_id`` globally
        unique. SQLite requires a table rebuild for a primary-key change;
        MySQL can alter the key directly. Other dialects intentionally fail
        closed instead of pretending the history migration succeeded.
        """
        inspector = inspect(connection)
        legacy = "prism_atlas_training_examples_legacy"
        columns = inspector.get_pk_constraint("prism_atlas_training_examples").get("constrained_columns") or []
        if inspector.has_table(legacy):
            if columns != ["version_id", "example_id"]:
                raise RuntimeError("Interrupted Atlas training-example migration has an unsafe replacement table.")
            connection.execute(
                text(
                    "INSERT INTO prism_atlas_training_examples "
                    "(version_id, example_id, split, dataset_id, source_run_id, payload, created_at) "
                    "SELECT version_id, example_id, split, dataset_id, source_run_id, payload, created_at "
                    "FROM prism_atlas_training_examples_legacy"
                )
            )
            connection.execute(text("DROP TABLE prism_atlas_training_examples_legacy"))
            return
        if columns == ["version_id", "example_id"]:
            return
        if columns != ["example_id"]:
            raise RuntimeError("Unexpected Atlas training-example primary key; refusing unsafe migration.")

        dialect = connection.dialect.name
        if dialect == "sqlite":
            for item in inspector.get_indexes("prism_atlas_training_examples"):
                name = str(item["name"])
                safe_name = name.replace('"', '""')
                connection.execute(text(f'DROP INDEX IF EXISTS "{safe_name}"'))
            connection.execute(text("ALTER TABLE prism_atlas_training_examples RENAME TO prism_atlas_training_examples_legacy"))
            _examples.create(connection)
            connection.execute(
                text(
                    "INSERT INTO prism_atlas_training_examples "
                    "(version_id, example_id, split, dataset_id, source_run_id, payload, created_at) "
                    "SELECT version_id, example_id, split, dataset_id, source_run_id, payload, created_at "
                    "FROM prism_atlas_training_examples_legacy"
                )
            )
            connection.execute(text("DROP TABLE prism_atlas_training_examples_legacy"))
            return
        if dialect == "mysql":
            connection.execute(
                text(
                    "ALTER TABLE prism_atlas_training_examples "
                    "DROP PRIMARY KEY, ADD PRIMARY KEY (version_id, example_id)"
                )
            )
            return
        raise RuntimeError("Atlas training-example identity migration supports SQLite and MySQL only.")

    def save(
        self, examples: list[AtlasTrainingExample], exclusions: list[AtlasTrainingExclusion]
    ) -> AtlasTrainingDatasetVersion:
        content_hash = manifest_content_hash(examples)
        version_id = f"trainset_{content_hash[:24]}"
        existing = self.get_version(version_id)
        if existing is not None:
            # Identical run history was rebuilt: the manifest is already
            # durable under this content hash, so this is a no-op, not an
            # error -- rebuilding must be safe to call repeatedly.
            return existing
        now = datetime.now(timezone.utc)
        manifest = AtlasTrainingDatasetVersion(
            version_id=version_id,
            created_at=now,
            source_run_count=len(examples) + len(exclusions),
            excluded_count=len(exclusions),
            train_count=sum(1 for item in examples if item.split is AtlasTrainingSplit.TRAIN),
            validation_count=sum(1 for item in examples if item.split is AtlasTrainingSplit.VALIDATION),
            test_count=sum(1 for item in examples if item.split is AtlasTrainingSplit.TEST),
            content_hash=content_hash,
        )
        with self.engine.begin() as connection:
            connection.execute(
                insert(_versions).values(
                    version_id=version_id,
                    created_at=now,
                    source_run_count=manifest.source_run_count,
                    excluded_count=manifest.excluded_count,
                    train_count=manifest.train_count,
                    validation_count=manifest.validation_count,
                    test_count=manifest.test_count,
                    content_hash=content_hash,
                )
            )
            for example in examples:
                connection.execute(
                    insert(_examples).values(
                        example_id=example.example_id,
                        version_id=version_id,
                        split=example.split.value,
                        dataset_id=example.dataset_id,
                        source_run_id=example.source_run_id,
                        payload=json.dumps(example.model_dump(mode="json"), sort_keys=True),
                        created_at=example.created_at,
                    )
                )
            for exclusion in exclusions:
                connection.execute(
                    insert(_exclusions).values(
                        exclusion_id=f"{version_id}_{uuid.uuid4().hex}",
                        version_id=version_id,
                        run_id=exclusion.run_id,
                        reason=exclusion.reason,
                    )
                )
        return manifest

    def get_version(self, version_id: str) -> Optional[AtlasTrainingDatasetVersion]:
        with self.engine.connect() as connection:
            row = connection.execute(select(_versions).where(_versions.c.version_id == version_id)).mappings().first()
        if row is None:
            return None
        return AtlasTrainingDatasetVersion(
            version_id=str(row["version_id"]),
            created_at=row["created_at"],
            source_run_count=int(row["source_run_count"]),
            excluded_count=int(row["excluded_count"]),
            train_count=int(row["train_count"]),
            validation_count=int(row["validation_count"]),
            test_count=int(row["test_count"]),
            content_hash=str(row["content_hash"]),
        )

    def list_versions(self, *, limit: int = 50) -> list[AtlasTrainingDatasetVersion]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(select(_versions).order_by(_versions.c.created_at.desc()).limit(limit))
                .mappings()
                .all()
            )
        return [
            AtlasTrainingDatasetVersion(
                version_id=str(row["version_id"]),
                created_at=row["created_at"],
                source_run_count=int(row["source_run_count"]),
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
    ) -> list[AtlasTrainingExample]:
        statement = select(_examples.c.payload).where(_examples.c.version_id == version_id).order_by(_examples.c.example_id).limit(limit)
        if split is not None:
            statement = statement.where(_examples.c.split == split.value)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).scalars().all()
        return [AtlasTrainingExample.model_validate(json.loads(row)) for row in rows]

    def exclusions(self, version_id: str, *, limit: int = 200) -> list[AtlasTrainingExclusion]:
        statement = select(_exclusions.c.run_id, _exclusions.c.reason).where(_exclusions.c.version_id == version_id).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [AtlasTrainingExclusion(run_id=str(row["run_id"]), reason=str(row["reason"])) for row in rows]
