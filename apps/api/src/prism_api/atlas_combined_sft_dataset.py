"""Immutable, source-neutral SFT corpus for the physical Foundry path.

Historical Atlas runs and reviewed system seed records are deliberately
normalised only at this boundary.  The originals remain separate durable
sources; no seed record ever gains a fake run identifier or dataset lineage.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Sequence

from prism_api_contracts import (
    AtlasCombinedSftDatasetVersion,
    AtlasSftTrainingRecord,
    AtlasSystemSeedExample,
    AtlasTrainingExample,
    AtlasTrainingSplit,
)
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .atlas_system_seed import _shingles, check_atlasbench_leakage
from .durable_registry import history_database_url

_metadata = MetaData()
_versions = Table(
    "prism_atlas_combined_sft_versions", _metadata,
    Column("version_id", String(120), primary_key=True),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)
_records = Table(
    "prism_atlas_combined_sft_records", _metadata,
    Column("version_id", String(120), primary_key=True),
    Column("record_id", String(120), primary_key=True),
    Column("split", String(16), nullable=False, index=True),
    Column("source_kind", String(32), nullable=False, index=True),
    Column("payload", Text, nullable=False),
)


class AtlasCombinedSftLeakageError(RuntimeError):
    pass


def _seed_split(seed: AtlasSystemSeedExample) -> AtlasTrainingSplit:
    # Topic/domain family is the stable grouping key.  It stops variations of
    # one teaching family leaking across train/eval while retaining ~80/10/10.
    group = f"{seed.seed_version}:{seed.domain.value}:{seed.topic.lower().strip()}"
    bucket = int(hashlib.sha256(group.encode()).hexdigest(), 16) % 100
    if bucket < 80:
        return AtlasTrainingSplit.TRAIN
    if bucket < 90:
        return AtlasTrainingSplit.VALIDATION
    return AtlasTrainingSplit.TEST


def _hash(payload: object) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _seed_record(seed: AtlasSystemSeedExample) -> AtlasSftTrainingRecord:
    return AtlasSftTrainingRecord(
        record_id=f"sft_{seed.content_hash[:32]}", source_kind="system_seed",
        source_ref=seed.seed_example_id, source_version=seed.seed_version,
        instruction=seed.user_request, output=seed.final_answer, uncertainty=seed.uncertainty,
        split=_seed_split(seed), content_hash=seed.content_hash,
        provenance={"seed_version": seed.seed_version, "domain": seed.domain.value, "topic": seed.topic},
        created_at=seed.created_at,
    )


def _history_record(example: AtlasTrainingExample, history_version: str) -> AtlasSftTrainingRecord:
    # Only compact typed metadata, never raw data rows or unexposed reasoning.
    input_text = json.dumps(example.dataset_metadata, sort_keys=True, separators=(",", ":"))
    return AtlasSftTrainingRecord(
        record_id=f"sft_{example.content_hash[:32]}", source_kind="atlas_run",
        source_ref=example.source_run_id, source_version=history_version, dataset_id=example.dataset_id,
        instruction=example.user_request, input=input_text, output=example.final_answer,
        uncertainty=example.uncertainty, split=example.split, content_hash=example.content_hash,
        provenance={"run_id": example.source_run_id, "dataset_id": example.dataset_id}, created_at=example.created_at,
    )


def check_cross_split_leakage(records: Sequence[AtlasSftTrainingRecord]) -> list[str]:
    """Fail closed on exact or meaningful phrase overlap across partitions."""
    findings: list[str] = []
    seen_hashes: dict[str, AtlasSftTrainingRecord] = {}
    seen_shingles: dict[str, AtlasSftTrainingRecord] = {}
    for record in sorted(records, key=lambda item: item.record_id):
        prior = seen_hashes.get(record.content_hash)
        if prior is not None and prior.split != record.split:
            findings.append(f"exact duplicate {record.record_id} crosses {prior.split.value}/{record.split.value}")
        seen_hashes[record.content_hash] = record
        for shingle in _shingles(f"{record.instruction} {record.output}"):
            prior = seen_shingles.get(shingle)
            if prior is not None and prior.split != record.split:
                findings.append(f"near duplicate {record.record_id} crosses {prior.split.value}/{record.split.value}")
                break
            seen_shingles[shingle] = record
    return findings


def build_combined_records(
    seeds: Sequence[AtlasSystemSeedExample], history: Sequence[AtlasTrainingExample], *, history_version: str = "history-empty"
) -> list[AtlasSftTrainingRecord]:
    # The seed guard is retained at the precise physical training boundary.
    seed_findings = check_atlasbench_leakage(list(seeds))
    if seed_findings:
        raise AtlasCombinedSftLeakageError("AtlasBench leakage: " + "; ".join(seed_findings[:10]))
    records = [_seed_record(seed) for seed in seeds] + [_history_record(item, history_version) for item in history]
    ids = [record.record_id for record in records]
    if len(ids) != len(set(ids)):
        raise AtlasCombinedSftLeakageError("Duplicate combined SFT record identity.")
    findings = check_cross_split_leakage(records)
    if findings:
        raise AtlasCombinedSftLeakageError("Cross-split leakage: " + "; ".join(findings[:10]))
    return sorted(records, key=lambda item: item.record_id)


def export_alpaca_jsonl(records: Sequence[AtlasSftTrainingRecord], path: Path) -> tuple[str, str]:
    train = sorted((record for record in records if record.split is AtlasTrainingSplit.TRAIN), key=lambda item: item.record_id)
    if not train:
        raise ValueError("Combined SFT corpus contains no TRAIN records.")
    path.parent.mkdir(parents=True, exist_ok=True)
    provenance_path = path.with_suffix(".provenance.json")
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in train:
            handle.write(json.dumps({"instruction": record.instruction, "input": record.input, "output": record.output}, sort_keys=True, separators=(",", ":")) + "\n")
    provenance = [{"record_id": r.record_id, "source_kind": r.source_kind, "source_ref": r.source_ref, "source_version": r.source_version, "content_hash": r.content_hash} for r in train]
    # ``Path.write_text`` did not accept ``newline`` on the Python 3.9 floor.
    # Keep the sidecar byte-stable by explicitly controlling newline translation.
    with provenance_path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(provenance, sort_keys=True, separators=(",", ":")) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest(), hashlib.sha256(provenance_path.read_bytes()).hexdigest()


class DurableAtlasCombinedSftStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        self.engine: Engine = create_engine(database_url or history_database_url(), future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if (database_url or history_database_url()).startswith("sqlite") else {})
        _metadata.create_all(self.engine)

    def save(self, records: Sequence[AtlasSftTrainingRecord], *, seed_version: str, seed_hash: str, history_version: str | None, history_hash: str | None) -> AtlasCombinedSftDatasetVersion:
        aggregate = _hash([r.content_hash for r in sorted(records, key=lambda item: item.record_id)])
        version_id = f"combinedsft_{aggregate[:24]}"
        existing = self.get_version(version_id)
        if existing is not None:
            return existing
        manifest = AtlasCombinedSftDatasetVersion(version_id=version_id, seed_version=seed_version, history_dataset_version=history_version, history_dataset_hash=history_hash, system_seed_count=sum(r.source_kind == "system_seed" for r in records), atlas_history_count=sum(r.source_kind == "atlas_run" for r in records), total_sft_count=len(records), train_count=sum(r.split is AtlasTrainingSplit.TRAIN for r in records), validation_count=sum(r.split is AtlasTrainingSplit.VALIDATION for r in records), test_count=sum(r.split is AtlasTrainingSplit.TEST for r in records), aggregate_content_hash=aggregate, source_manifests={"system_seed": seed_hash, "atlas_history": history_hash or ""}, created_at=datetime.now(timezone.utc))
        with self.engine.begin() as c:
            c.execute(insert(_versions).values(version_id=version_id, payload=manifest.model_dump_json(), created_at=manifest.created_at))
            for r in records:
                c.execute(insert(_records).values(version_id=version_id, record_id=r.record_id, split=r.split.value, source_kind=r.source_kind, payload=r.model_dump_json()))
        return manifest

    def get_version(self, version_id: str) -> Optional[AtlasCombinedSftDatasetVersion]:
        row = self.engine.connect().execute(select(_versions.c.payload).where(_versions.c.version_id == version_id)).scalar_one_or_none()
        return None if row is None else AtlasCombinedSftDatasetVersion.model_validate_json(row)

    def list_versions(self, limit: int = 50) -> list[AtlasCombinedSftDatasetVersion]:
        rows = self.engine.connect().execute(select(_versions.c.payload).order_by(_versions.c.created_at.desc()).limit(limit)).scalars().all()
        return [AtlasCombinedSftDatasetVersion.model_validate_json(row) for row in rows]

    def records(self, version_id: str, split: Optional[AtlasTrainingSplit] = None, limit: int = 100_000) -> list[AtlasSftTrainingRecord]:
        stmt = select(_records.c.payload).where(_records.c.version_id == version_id)
        if split is not None:
            stmt = stmt.where(_records.c.split == split.value)
        rows = self.engine.connect().execute(stmt.order_by(_records.c.record_id).limit(limit)).scalars().all()
        return [AtlasSftTrainingRecord.model_validate_json(row) for row in rows]
