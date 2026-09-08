from __future__ import annotations

from datetime import datetime, timezone

from prism_api.atlas_combined_sft_dataset import (
    DurableAtlasCombinedSftStore,
    build_combined_records,
    check_cross_split_leakage,
    export_alpaca_jsonl,
)
from prism_api.atlas_system_seed import build_verified_system_seed_corpus, manifest_content_hash
from prism_api_contracts import AtlasSftTrainingRecord, AtlasTrainingSplit


def test_seed_corpus_builds_source_neutral_trainable_records_without_run_ids() -> None:
    seeds = build_verified_system_seed_corpus()
    records = build_combined_records(seeds, [])
    assert len(records) == len(seeds)
    assert {record.source_kind for record in records} == {"system_seed"}
    assert all("run_id" not in record.provenance for record in records)
    assert check_cross_split_leakage(records) == []


def test_alpaca_export_is_train_only_and_byte_stable(tmp_path) -> None:  # type: ignore[no-untyped-def]
    now = datetime.now(timezone.utc)
    records = [
        AtlasSftTrainingRecord(record_id="sft_train", source_kind="system_seed", source_ref="seed1", source_version="v1", instruction="Explain safe joins", output="Use explicit keys.", split=AtlasTrainingSplit.TRAIN, content_hash="1" * 64, created_at=now),
        AtlasSftTrainingRecord(record_id="sft_eval", source_kind="system_seed", source_ref="seed2", source_version="v1", instruction="Evaluation-only", output="Never export me.", split=AtlasTrainingSplit.TEST, content_hash="2" * 64, created_at=now),
    ]
    path = tmp_path / "train.jsonl"
    file_hash, provenance_hash = export_alpaca_jsonl(records, path)
    first = path.read_bytes()
    assert b"Evaluation-only" not in first
    assert set(__import__("json").loads(first.decode()).keys()) == {"instruction", "input", "output"}
    second_hash, second_provenance_hash = export_alpaca_jsonl(list(reversed(records)), path)
    assert path.read_bytes() == first
    assert (file_hash, provenance_hash) == (second_hash, second_provenance_hash)


def test_cross_split_duplicate_fails_closed() -> None:
    now = datetime.now(timezone.utc)
    one = AtlasSftTrainingRecord(record_id="one", source_kind="system_seed", source_ref="one", source_version="v1", instruction="A stable repeated instruction", output="A stable repeated answer", split=AtlasTrainingSplit.TRAIN, content_hash="3" * 64, created_at=now)
    two = one.model_copy(update={"record_id": "two", "source_ref": "two", "split": AtlasTrainingSplit.TEST})
    assert check_cross_split_leakage([one, two])


def test_combined_manifest_is_immutable_and_reproducible(tmp_path) -> None:  # type: ignore[no-untyped-def]
    seeds = build_verified_system_seed_corpus()
    records = build_combined_records(seeds, [])
    store = DurableAtlasCombinedSftStore(database_url=f"sqlite:///{tmp_path / 'combined.db'}")
    first = store.save(records, seed_version=seeds[0].seed_version, seed_hash=manifest_content_hash(seeds), history_version=None, history_hash=None)
    second = store.save(records, seed_version=seeds[0].seed_version, seed_hash=manifest_content_hash(seeds), history_version=None, history_hash=None)
    assert first.version_id == second.version_id
    assert first.system_seed_count == len(seeds)
    assert first.atlas_history_count == 0
    assert len(store.records(first.version_id)) == len(seeds)
