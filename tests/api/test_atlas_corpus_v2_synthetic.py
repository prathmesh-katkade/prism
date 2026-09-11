from __future__ import annotations

from datetime import datetime, timezone

from prism_api.atlas_bench_corpus import all_tasks as all_v1_tasks
from prism_api.atlas_bench_corpus_v2 import all_tasks as all_v2_tasks
from prism_api.atlas_corpus_v2_synthetic import (
    DurableAtlasSyntheticTeacherStore,
    build_manifest,
    build_synthetic_teacher_corpus,
    build_verified_synthetic_teacher_corpus,
    check_atlasbench_v1_leakage,
    check_atlasbench_v2_leakage,
    check_intra_corpus_near_duplicates,
    check_license_validation,
    check_secret_scan,
    manifest_content_hash,
)
from prism_api_contracts import (
    AtlasSyntheticTeacherExample,
    AtlasSyntheticTeacherSkillArea,
    AtlasSyntheticTeacherValidationStatus,
)


def test_corpus_is_a_real_wave_covering_every_skill_area() -> None:
    examples = build_synthetic_teacher_corpus()
    assert len(examples) >= 40, "Wave 1 should be a real batch, not a handful of placeholders"
    assert all(example.source_kind == "synthetic_teacher" for example in examples)
    covered = {example.skill_area for example in examples}
    assert covered == set(AtlasSyntheticTeacherSkillArea)


def test_corpus_build_is_deterministic() -> None:
    first = build_synthetic_teacher_corpus()
    second = build_synthetic_teacher_corpus()
    assert [item.teacher_example_id for item in first] == [item.teacher_example_id for item in second]
    assert [item.content_hash for item in first] == [item.content_hash for item in second]
    assert manifest_content_hash(first) == manifest_content_hash(second)


def test_every_example_has_real_generation_provenance() -> None:
    for example in build_synthetic_teacher_corpus():
        assert example.generation_policy_version
        assert example.teacher_model
        assert example.teacher_revision
        assert example.license
        assert example.validation_status in set(AtlasSyntheticTeacherValidationStatus)
        assert example.validation_note


def test_manifest_aggregates_real_skill_area_counts() -> None:
    examples = build_synthetic_teacher_corpus()
    manifest = build_manifest(
        examples, v1_leakage_guard_passed=True, v2_leakage_guard_passed=True, duplicate_guard_passed=True
    )
    assert manifest.example_count == len(examples)
    assert sum(item.example_count for item in manifest.skill_area_counts) == len(examples)
    assert {item.skill_area for item in manifest.skill_area_counts} == set(AtlasSyntheticTeacherSkillArea)


def test_the_real_wave_passes_every_quality_gate() -> None:
    """The actual wave-1 content must never overlap AtlasBench V1 or V2,
    must not contain accidental near-duplicates, must declare only
    recognized licenses, and must contain no secret-shaped content -- this
    is the release gate, not just a guard-mechanism smoke test."""
    examples = build_synthetic_teacher_corpus()
    assert check_atlasbench_v1_leakage(examples) == []
    assert check_atlasbench_v2_leakage(examples) == []
    assert check_intra_corpus_near_duplicates(examples) == []
    assert check_license_validation(examples) == []
    assert check_secret_scan(examples) == []
    # build_verified_synthetic_teacher_corpus() must therefore not raise.
    verified = build_verified_synthetic_teacher_corpus()
    assert len(verified) == len(examples)


def test_license_guard_catches_an_unrecognized_license() -> None:
    unrecognized = build_synthetic_teacher_corpus()[0].model_copy(update={"license": "unverified-scraped-cc-by"})
    findings = check_license_validation([unrecognized])
    assert findings, "the license guard failed to catch a license outside the recognized allowlist"


def test_secret_scan_catches_an_embedded_api_key() -> None:
    leaking = build_synthetic_teacher_corpus()[0].model_copy(
        update={"output": "Use this key: sk-abcdefghijklmnopqrstuvwx to authenticate."}
    )
    findings = check_secret_scan([leaking])
    assert findings, "the secret scan failed to catch an embedded API-key-shaped string"


def _example(instruction: str, output: str, *, teacher_example_id: str) -> AtlasSyntheticTeacherExample:
    return AtlasSyntheticTeacherExample(
        teacher_example_id=teacher_example_id,
        generation_policy_version="synthetic-teacher-v1",
        teacher_model="claude-sonnet-5",
        teacher_revision="session-configured-2026-09",
        skill_area=AtlasSyntheticTeacherSkillArea.EVIDENCE,
        topic="synthetic_leak_test",
        license="internal-generated",
        instruction=instruction,
        output=output,
        validation_status=AtlasSyntheticTeacherValidationStatus.REVIEWED,
        validation_note="synthetic test fixture",
        content_hash="0" * 64,
        created_at=datetime.now(timezone.utc),
    )


def test_v1_leakage_guard_actually_catches_a_copied_benchmark_task() -> None:
    """Proves the guard is a real check, not a rubber stamp."""
    real_task = all_v1_tasks()[0]
    leaking = _example(real_task.prompt, "Deliberately reuses a V1 prompt verbatim.", teacher_example_id="leak_v1")
    findings = check_atlasbench_v1_leakage([leaking])
    assert findings, "the V1 leakage guard failed to catch a verbatim-copied AtlasBench V1 prompt"
    assert any(real_task.task_id in finding for finding in findings)


def test_v2_leakage_guard_actually_catches_a_copied_holdout_task() -> None:
    real_task = all_v2_tasks()[0]
    leaking = _example(real_task.prompt, "Deliberately reuses a V2 prompt verbatim.", teacher_example_id="leak_v2")
    findings = check_atlasbench_v2_leakage([leaking])
    assert findings, "the V2 leakage guard failed to catch a verbatim-copied AtlasBench V2 prompt"
    assert any(real_task.task_id in finding for finding in findings)


def test_leakage_guards_do_not_flag_unrelated_short_text() -> None:
    benign = _example(
        "What is our current signup conversion rate for the mobile app this month?",
        "I computed this directly from the real signup and session data for this exact date range.",
        teacher_example_id="benign",
    )
    assert check_atlasbench_v1_leakage([benign]) == []
    assert check_atlasbench_v2_leakage([benign]) == []


def test_intra_corpus_duplicate_guard_catches_a_real_near_duplicate() -> None:
    original = build_synthetic_teacher_corpus()[0]
    near_duplicate = _example(original.instruction, original.output, teacher_example_id="deliberate_near_dup")
    findings = check_intra_corpus_near_duplicates([original, near_duplicate])
    assert findings, "the intra-corpus duplicate guard failed to catch a deliberately near-identical example"


def test_durable_store_release_is_immutable_and_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasSyntheticTeacherStore(database_url=f"sqlite:///{tmp_path / 'synthetic-teacher.db'}")
    examples = build_verified_synthetic_teacher_corpus()
    manifest = build_manifest(
        examples, v1_leakage_guard_passed=True, v2_leakage_guard_passed=True, duplicate_guard_passed=True
    )

    first = store.release(examples, manifest)
    assert first.generation_policy_version == manifest.generation_policy_version

    # Idempotent: releasing the same version again returns the existing
    # manifest rather than inserting a second, possibly-conflicting copy.
    second = store.release(examples, manifest)
    assert second.aggregate_content_hash == first.aggregate_content_hash

    fetched = store.get_manifest(manifest.generation_policy_version)
    assert fetched is not None
    assert fetched.example_count == len(examples)

    stored_examples = store.examples(manifest.generation_policy_version)
    assert len(stored_examples) == len(examples)
    assert {item.teacher_example_id for item in stored_examples} == {item.teacher_example_id for item in examples}

    versions = store.list_manifests()
    assert manifest.generation_policy_version in {item.generation_policy_version for item in versions}


def test_a_never_persisted_version_returns_none(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasSyntheticTeacherStore(database_url=f"sqlite:///{tmp_path / 'synthetic-teacher-empty.db'}")
    assert store.get_manifest("synthetic-teacher-v999-never-released") is None
    assert store.examples("synthetic-teacher-v999-never-released") == []
