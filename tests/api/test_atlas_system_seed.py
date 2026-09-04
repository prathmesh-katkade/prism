from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient
from prism_api.atlas_bench_corpus import all_tasks
from prism_api.atlas_system_seed import (
    DurableAtlasSystemSeedStore,
    build_manifest,
    build_system_seed_corpus,
    build_verified_system_seed_corpus,
    check_atlasbench_leakage,
    manifest_content_hash,
)
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasSystemSeedDomain,
    AtlasSystemSeedExample,
    AtlasSystemSeedReviewStatus,
)


def test_corpus_is_a_real_substantial_reviewed_set() -> None:
    examples = build_system_seed_corpus()
    assert 120 <= len(examples) <= 200
    assert all(example.source_kind == "system_seed" for example in examples)
    assert all(example.review_status is AtlasSystemSeedReviewStatus.REVIEWED for example in examples)
    covered_domains = {example.domain for example in examples}
    assert covered_domains == set(AtlasSystemSeedDomain)


def test_corpus_build_is_deterministic() -> None:
    first = build_system_seed_corpus()
    second = build_system_seed_corpus()
    assert [item.seed_example_id for item in first] == [item.seed_example_id for item in second]
    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    assert manifest_content_hash(first) == manifest_content_hash(second)


def test_manifest_aggregates_real_domain_counts() -> None:
    examples = build_system_seed_corpus()
    manifest = build_manifest(examples, leakage_guard_passed=True)
    assert manifest.example_count == len(examples)
    assert sum(item.example_count for item in manifest.domain_counts) == len(examples)
    assert {item.domain for item in manifest.domain_counts} == set(AtlasSystemSeedDomain)
    assert manifest.leakage_guard_passed is True


def test_the_real_released_corpus_passes_its_own_leakage_guard() -> None:
    """The actual V1 content must never overlap AtlasBench's real tasks --
    this is the release gate, not just a guard-mechanism smoke test."""
    examples = build_system_seed_corpus()
    findings = check_atlasbench_leakage(examples)
    assert findings == []
    # build_verified_system_seed_corpus() must therefore not raise.
    verified = build_verified_system_seed_corpus()
    assert len(verified) == len(examples)


def test_leakage_guard_actually_catches_a_copied_benchmark_task() -> None:
    """Proves the guard is a real check, not a rubber stamp: an example that
    verbatim-copies a real AtlasBench prompt must be flagged."""
    real_task = all_tasks()[0]
    leaking_example = AtlasSystemSeedExample(
        seed_example_id="seed_synthetic_leak_test",
        seed_version="system-seed-v1",
        domain=AtlasSystemSeedDomain.EVIDENCE,
        topic="synthetic_leak_test",
        user_request=real_task.prompt,
        final_answer="This answer deliberately reuses the benchmark prompt verbatim to test the leakage guard.",
        uncertainty=None,
        review_status=AtlasSystemSeedReviewStatus.REVIEWED,
        content_hash="0" * 64,
        created_at=datetime.now(timezone.utc),
    )
    findings = check_atlasbench_leakage([leaking_example])
    assert findings, "the leakage guard failed to catch a verbatim-copied AtlasBench prompt"
    assert any(real_task.task_id in finding for finding in findings)


def test_leakage_guard_does_not_flag_unrelated_short_text() -> None:
    benign_example = AtlasSystemSeedExample(
        seed_example_id="seed_synthetic_benign_test",
        seed_version="system-seed-v1",
        domain=AtlasSystemSeedDomain.EVIDENCE,
        topic="synthetic_benign_test",
        user_request="What is our current signup conversion rate for the mobile app this month?",
        final_answer="I computed this directly from the real signup and session data for this exact date range.",
        uncertainty=None,
        review_status=AtlasSystemSeedReviewStatus.REVIEWED,
        content_hash="1" * 64,
        created_at=datetime.now(timezone.utc),
    )
    assert check_atlasbench_leakage([benign_example]) == []


def test_durable_store_release_is_immutable_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasSystemSeedStore(database_url=f"sqlite:///{tmp_path / 'system-seed.db'}")
    examples = build_system_seed_corpus()
    manifest = build_manifest(examples, leakage_guard_passed=True)

    first = store.release(examples, manifest)
    assert first.seed_version == manifest.seed_version

    # Idempotent: releasing the same version again returns the existing
    # manifest rather than inserting a second, possibly-conflicting copy.
    second = store.release(examples, manifest)
    assert second.aggregate_content_hash == first.aggregate_content_hash

    fetched_manifest = store.get_manifest(manifest.seed_version)
    assert fetched_manifest is not None
    assert fetched_manifest.example_count == len(examples)

    stored_examples = store.examples(manifest.seed_version, limit=1_000)
    assert len(stored_examples) == len(examples)
    assert {item.seed_example_id for item in stored_examples} == {item.seed_example_id for item in examples}

    versions = store.list_manifests()
    assert manifest.seed_version in {item.seed_version for item in versions}


def test_a_never_persisted_seed_version_returns_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasSystemSeedStore(database_url=f"sqlite:///{tmp_path / 'system-seed-empty.db'}")
    assert store.get_manifest("system-seed-v999-never-released") is None
    assert store.examples("system-seed-v999-never-released") == []


def test_system_seed_release_route_is_idempotent_and_previewable() -> None:
    client = TestClient(create_app())
    first = client.post("/api/v1/atlas/foundry/system-seed/release")
    assert first.status_code == 201
    body = first.json()
    assert 120 <= body["example_count"] <= 200
    assert body["leakage_guard_passed"] is True

    second = client.post("/api/v1/atlas/foundry/system-seed/release")
    assert second.status_code == 201
    assert second.json()["aggregate_content_hash"] == body["aggregate_content_hash"]

    listed = client.get("/api/v1/atlas/foundry/system-seed")
    assert listed.status_code == 200
    assert body["seed_version"] in {item["seed_version"] for item in listed.json()}

    preview = client.get(f"/api/v1/atlas/foundry/system-seed/{body['seed_version']}/preview", params={"limit": 3})
    assert preview.status_code == 200
    assert len(preview.json()) == 3
    assert all(item["source_kind"] == "system_seed" for item in preview.json())


def test_combined_training_source_summary_keeps_source_classes_separate() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/atlas/foundry/training-datasets:combined-summary")
    assert response.status_code == 200
    body = response.json()
    assert body["system_seed_examples"] >= 120
    assert body["verified_history_examples"] >= 0
    assert body["user_correction_examples"] >= 0
    assert body["total_eligible"] == (
        body["system_seed_examples"] + body["verified_history_examples"] + body["user_correction_examples"]
    )
