from __future__ import annotations

from prism_api.atlas_foundry_preference import (
    AtlasPreferenceDatasetBuilder,
    DurableAtlasPreferenceDatasetStore,
    exclusion_reason,
    manifest_content_hash,
)
from prism_api.atlas_memory import DurableAtlasMemoryStore
from prism_api_contracts import (
    AtlasMemoryClass,
    AtlasMemoryScope,
    AtlasMemoryWriteRequest,
    AtlasTrainingSplit,
)


def _store(tmp_path) -> DurableAtlasMemoryStore:  # type: ignore[no-untyped-def]
    return DurableAtlasMemoryStore(f"sqlite:///{(tmp_path / 'memory.sqlite').as_posix()}")


def _memory(store: DurableAtlasMemoryStore, content: str, *, project_id: str = "proj-a"):  # type: ignore[no-untyped-def]
    return store.create_or_reinforce(
        AtlasMemoryWriteRequest(
            scope=AtlasMemoryScope.PROJECT,
            knowledge_class=AtlasMemoryClass.USER_MEMORY,
            content=content,
            source="user correction",
            confidence="high",
            project_id=project_id,
        )
    )


def test_no_supersession_means_no_pairs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    _memory(store, "Retention is active over eligible customers.")
    pairs, excluded = AtlasPreferenceDatasetBuilder(store).build()
    assert pairs == [] and excluded == []


def test_real_supersession_becomes_a_dpo_pair(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    original = _memory(store, "Churn rate is total customers lost.")
    correction = _memory(store, "Churn rate is customers lost during the period divided by starting customers.")
    store.supersede(original.memory_id, correction.memory_id, "Original definition omitted the denominator.")

    pairs, excluded = AtlasPreferenceDatasetBuilder(store).build()
    assert excluded == []
    assert len(pairs) == 1
    pair = pairs[0]
    assert pair.rejected_response == original.content
    assert pair.chosen_response == correction.content
    assert pair.evaluator_label == "Original definition omitted the denominator."
    assert pair.rejected_memory_id == original.memory_id
    assert pair.chosen_memory_id == correction.memory_id


def test_dangling_successor_is_excluded_not_fabricated(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    original = _memory(store, "Some claim.")
    store.supersede(original.memory_id, "memory_does_not_exist", "Superseded by a memory that was later deleted.")
    superseded = store.get(original.memory_id)
    assert superseded is not None
    assert exclusion_reason(superseded, None) == "successor memory referenced by superseded_by no longer exists"

    pairs, excluded = AtlasPreferenceDatasetBuilder(store).build()
    assert pairs == []
    assert len(excluded) == 1 and excluded[0].memory_id == original.memory_id


def test_no_op_correction_is_excluded(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    original = _memory(store, "Same text, project x.", project_id="proj-b")
    # A dedupe-key collision on identical (scope, class, project, content)
    # would collapse into one memory row, so put the identical content in a
    # different project to force a distinct successor row, then supersede
    # with genuinely no-op (unchanged) content.
    other = _memory(store, "Same text, project x.", project_id="proj-c")
    store.supersede(original.memory_id, other.memory_id, "No real change.")
    pairs, excluded = AtlasPreferenceDatasetBuilder(store).build()
    assert pairs == []
    assert any("identical" in item.reason for item in excluded)


def test_pairs_from_the_same_project_never_straddle_splits(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    for index in range(6):
        original = _memory(store, f"Claim {index}.", project_id="proj-family")
        correction = _memory(store, f"Corrected claim {index}.", project_id="proj-family")
        store.supersede(original.memory_id, correction.memory_id, f"Reason {index}.")
    pairs, _ = AtlasPreferenceDatasetBuilder(store).build()
    assert len(pairs) == 6
    assert len({pair.split for pair in pairs}) == 1


def test_build_is_deterministic(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    original = _memory(store, "Old claim.")
    correction = _memory(store, "New claim.")
    store.supersede(original.memory_id, correction.memory_id, "Verified correction.")
    pairs_a, _ = AtlasPreferenceDatasetBuilder(store).build()
    pairs_b, _ = AtlasPreferenceDatasetBuilder(store).build()
    assert [item.pair_id for item in pairs_a] == [item.pair_id for item in pairs_b]
    assert manifest_content_hash(pairs_a) == manifest_content_hash(pairs_b)


def test_durable_preference_store_is_idempotent_and_supports_preview(tmp_path) -> None:  # type: ignore[no-untyped-def]
    memory_store = _store(tmp_path)
    original = _memory(memory_store, "Old claim.")
    correction = _memory(memory_store, "New claim.")
    memory_store.supersede(original.memory_id, correction.memory_id, "Verified correction.")

    pairs, excluded = AtlasPreferenceDatasetBuilder(memory_store).build()
    dataset_store = DurableAtlasPreferenceDatasetStore(f"sqlite:///{(tmp_path / 'preference.sqlite').as_posix()}")
    manifest_a = dataset_store.save(pairs, excluded)
    manifest_b = dataset_store.save(pairs, excluded)
    assert manifest_a.version_id == manifest_b.version_id
    assert manifest_a.train_count + manifest_a.validation_count + manifest_a.test_count == len(pairs)

    preview = dataset_store.preview(manifest_a.version_id)
    assert [item.pair_id for item in preview] == [item.pair_id for item in pairs]

    only_train = dataset_store.preview(manifest_a.version_id, split=AtlasTrainingSplit.TRAIN)
    assert all(item.split is AtlasTrainingSplit.TRAIN for item in only_train)
    assert dataset_store.list_versions()[0].version_id == manifest_a.version_id
