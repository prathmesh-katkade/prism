from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import HTTPException
from prism_api import atlas_foundry_routes
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore
from prism_api_contracts import AtlasTrainingRecipe, AtlasTrainingRecipeMethod, AtlasTrainingSplit


def test_candidate_runtime_binding_is_durable_and_append_only(tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'candidate-runtime.db'}"
    first_store = DurableAtlasCandidateRuntimeStore(database_url)
    first = first_store.bind_ollama(
        "candidate_1",
        "atlas-candidate-deadbeef",
        runtime_model_digest="digest-1",
    )
    second = first_store.bind_ollama(
        "candidate_1",
        "atlas-candidate-cafebabe",
        runtime_model_digest="digest-2",
    )

    restarted = DurableAtlasCandidateRuntimeStore(database_url)
    latest = restarted.latest("candidate_1")

    assert latest is not None
    assert latest.binding_id == second.binding_id
    assert latest.runtime_model == "atlas-candidate-cafebabe"
    assert latest.runtime_model_digest == "digest-2"
    assert first.binding_id != second.binding_id


def test_candidate_runtime_binding_rejects_command_shaped_model_names(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasCandidateRuntimeStore(f"sqlite:///{tmp_path / 'candidate-runtime.db'}")

    with pytest.raises(ValueError, match="unsupported characters"):
        store.bind_ollama("candidate_1", "candidate; rm -rf /")


class _NoTrainDatasetStore:
    def get_version(self, version_id: str) -> object:
        return object()

    def preview(self, version_id: str, *, split=None, limit: int = 10):  # type: ignore[no-untyped-def]
        assert split is AtlasTrainingSplit.TRAIN
        assert limit == 100_000
        return []


def test_foundry_job_refuses_validation_test_only_dataset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(atlas_foundry_routes, "_training_dataset_store", _NoTrainDatasetStore())
    recipe = AtlasTrainingRecipe(
        recipe_id="recipe_train_only",
        base_model="Qwen/Qwen2.5-0.5B-Instruct",
        method=AtlasTrainingRecipeMethod.QLORA,
        task="sft",
        dataset_version_id="trainset_no_train",
        created_at=datetime.now(timezone.utc),
    )

    with pytest.raises(HTTPException) as exc:
        atlas_foundry_routes.start_foundry_job(recipe, "trainset_no_train")

    assert exc.value.status_code == 409
    assert "no TRAIN examples" in str(exc.value.detail)
