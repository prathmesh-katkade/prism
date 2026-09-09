from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from prism_api.atlas_combined_sft_dataset import (
    DurableAtlasCombinedSftStore,
    build_combined_records,
    check_cross_split_leakage,
    export_alpaca_jsonl,
)
from prism_api.atlas_corpus_v2_synthetic import build_verified_synthetic_teacher_corpus
from prism_api.atlas_corpus_v2_synthetic import manifest_content_hash as synthetic_teacher_hash
from prism_api.atlas_system_seed import build_verified_system_seed_corpus, manifest_content_hash
from prism_api.main import create_app
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
    provenance = __import__("json").loads(path.with_suffix(".provenance.json").read_text(encoding="utf-8"))
    assert provenance == [{
        "record_id": "sft_train", "source_kind": "system_seed", "source_ref": "seed1",
        "source_version": "v1", "project_id": None, "dataset_id": None,
        "split": "train", "content_hash": "1" * 64,
    }]
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


def test_synthetic_teacher_examples_combine_as_a_distinct_source_class(tmp_path) -> None:  # type: ignore[no-untyped-def]
    seeds = build_verified_system_seed_corpus()
    teacher = build_verified_synthetic_teacher_corpus()
    records = build_combined_records(seeds, [], synthetic_teacher=teacher)
    assert len(records) == len(seeds) + len(teacher)
    assert {record.source_kind for record in records} == {"system_seed", "synthetic_teacher"}
    assert check_cross_split_leakage(records) == []

    store = DurableAtlasCombinedSftStore(database_url=f"sqlite:///{tmp_path / 'combined-teacher.db'}")
    manifest = store.save(
        records,
        seed_version=seeds[0].seed_version,
        seed_hash=manifest_content_hash(seeds),
        history_version=None,
        history_hash=None,
        synthetic_teacher_version=teacher[0].generation_policy_version,
        synthetic_teacher_hash=synthetic_teacher_hash(teacher),
    )
    assert manifest.system_seed_count == len(seeds)
    assert manifest.synthetic_teacher_count == len(teacher)
    assert manifest.total_sft_count == len(seeds) + len(teacher)
    assert manifest.source_manifests["synthetic_teacher"] == synthetic_teacher_hash(teacher)


def test_combined_manifest_identity_includes_source_lineage(tmp_path) -> None:  # type: ignore[no-untyped-def]
    seeds = build_verified_system_seed_corpus()
    records = build_combined_records(seeds, [])
    store = DurableAtlasCombinedSftStore(database_url=f"sqlite:///{tmp_path / 'combined.db'}")
    first = store.save(records, seed_version=seeds[0].seed_version, seed_hash=manifest_content_hash(seeds), history_version=None, history_hash=None)
    relined = [record.model_copy(update={"source_version": "system-seed-v2"}) for record in records]
    second = store.save(relined, seed_version="system-seed-v2", seed_hash=manifest_content_hash(seeds), history_version=None, history_hash=None)
    assert second.version_id != first.version_id


def test_combined_sft_dataset_route_includes_synthetic_teacher_end_to_end() -> None:
    """Real HTTP round trip through the actual app wiring, not just the
    library functions directly -- proves the route actually assembles and
    releases the synthetic-teacher source, not only that it's importable."""
    client = TestClient(create_app())

    release = client.post("/api/v1/atlas/foundry/synthetic-teacher/release")
    assert release.status_code == 201
    release_body = release.json()
    assert release_body["example_count"] >= 40
    assert release_body["atlasbench_v1_leakage_guard_passed"] is True
    assert release_body["atlasbench_v2_leakage_guard_passed"] is True
    assert release_body["intra_corpus_duplicate_guard_passed"] is True

    listed = client.get("/api/v1/atlas/foundry/synthetic-teacher")
    assert listed.status_code == 200
    assert release_body["generation_policy_version"] in {item["generation_policy_version"] for item in listed.json()}

    preview = client.get(
        f"/api/v1/atlas/foundry/synthetic-teacher/{release_body['generation_policy_version']}/preview",
        params={"limit": 3},
    )
    assert preview.status_code == 200
    assert len(preview.json()) == 3
    assert all(item["source_kind"] == "synthetic_teacher" for item in preview.json())

    combined = client.post("/api/v1/atlas/foundry/combined-sft-datasets")
    assert combined.status_code == 201
    combined_body = combined.json()
    assert combined_body["synthetic_teacher_count"] >= 40
    assert combined_body["synthetic_teacher_version"] == release_body["generation_policy_version"]
    assert combined_body["total_sft_count"] == (
        combined_body["system_seed_count"] + combined_body["atlas_history_count"] + combined_body["synthetic_teacher_count"]
    )

    combined_preview = client.get(
        f"/api/v1/atlas/foundry/combined-sft-datasets/{combined_body['version_id']}/preview",
        params={"limit": 100},
    )
    assert combined_preview.status_code == 200
    assert any(item["source_kind"] == "synthetic_teacher" for item in combined_preview.json())
