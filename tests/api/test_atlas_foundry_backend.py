from __future__ import annotations

from datetime import datetime, timezone

import yaml
from prism_api.atlas_foundry_backend import (
    MockFoundryBackend,
    SoupFoundryBackend,
    write_recipe_config,
)
from prism_api_contracts import (
    AtlasFoundryBackendName,
    AtlasTrainingJobState,
    AtlasTrainingRecipe,
    AtlasTrainingRecipeMethod,
)


def _recipe(**overrides) -> AtlasTrainingRecipe:  # type: ignore[no-untyped-def]
    defaults: dict[str, object] = dict(
        recipe_id="recipe_1",
        base_model="TinyLlama/TinyLlama-1.1B-Chat-v1.0",
        method=AtlasTrainingRecipeMethod.QLORA,
        task="sft",
        dataset_version_id="trainset_abc123",
        created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    return AtlasTrainingRecipe.model_validate(defaults)


def test_recipe_renders_to_a_valid_soup_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe(quantization="4bit", lora_r=8, epochs=2, target_modules=["q_proj", "k_proj"])
    config_path = write_recipe_config(
        recipe,
        dataset_path=tmp_path / "train.jsonl",
        output_dir=tmp_path / "output",
        config_path=tmp_path / "config.yaml",
    )
    parsed = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert parsed["base"] == recipe.base_model
    assert parsed["task"] == "sft"
    assert parsed["backend"] == "transformers"
    assert parsed["data"]["train"] == str(tmp_path / "train.jsonl")
    assert parsed["training"]["quantization"] == "4bit"
    assert parsed["training"]["epochs"] == 2
    assert parsed["training"]["lora"]["r"] == 8
    assert parsed["training"]["lora"]["target_modules"] == ["q_proj", "k_proj"]
    assert parsed["output"] == str(tmp_path / "output")


def test_recipe_rejects_out_of_range_hyperparameters() -> None:
    try:
        _recipe(epochs=0)
    except Exception as error:
        assert "epochs" in str(error) or "greater than or equal to 1" in str(error)
    else:
        raise AssertionError("epochs=0 should have been rejected")


def test_mock_backend_runs_a_full_deterministic_lifecycle(tmp_path) -> None:  # type: ignore[no-untyped-def]
    backend = MockFoundryBackend()
    capability = backend.capability()
    assert capability.backend is AtlasFoundryBackendName.MOCK
    assert capability.can_pause is False  # honest: no backend implements real pause

    recipe = _recipe()
    preflight = backend.preflight(recipe)
    assert preflight.compatible is True

    dataset_path = tmp_path / "train.jsonl"
    dataset_path.write_text('{"messages": []}\n', encoding="utf-8")
    job = backend.start(recipe, dataset_path=dataset_path)
    assert job.state is AtlasTrainingJobState.COMPLETED
    assert job.backend is AtlasFoundryBackendName.MOCK

    polled = backend.poll(job)
    assert polled.state is AtlasTrainingJobState.COMPLETED

    metrics = backend.metrics(job)
    assert len(metrics) == 1 and metrics[0].job_id == job.job_id

    checkpoints = backend.checkpoints(job)
    assert len(checkpoints) == 1

    # Cancelling an already-terminal job is a no-op, not an error.
    cancelled = backend.cancel(job)
    assert cancelled.state is AtlasTrainingJobState.COMPLETED


def test_soup_backend_reports_absence_honestly_rather_than_crashing(tmp_path) -> None:  # type: ignore[no-untyped-def]
    # This environment has no `soup` binary installed; every method must
    # degrade to a clear, typed "unavailable" result -- never a crash, and
    # never a pretended success.
    backend = SoupFoundryBackend(workspace_root=tmp_path / "foundry")
    capability = backend.capability()
    assert capability.soup_available is False
    assert capability.can_train is False
    assert capability.backend is AtlasFoundryBackendName.SOUP

    recipe = _recipe()
    preflight = backend.preflight(recipe)
    assert preflight.compatible is False
    assert "not installed" in preflight.detail

    dataset_path = tmp_path / "train.jsonl"
    dataset_path.write_text('{"messages": []}\n', encoding="utf-8")
    job = backend.start(recipe, dataset_path=dataset_path)
    assert job.state is AtlasTrainingJobState.FAILED
    assert job.error is not None and "not installed" in job.error

    # A never-started (no process_id) job is safe to poll/cancel/inspect.
    assert backend.poll(job).state is AtlasTrainingJobState.FAILED
    assert backend.cancel(job).state is AtlasTrainingJobState.FAILED
    assert backend.metrics(job) == []
    assert backend.checkpoints(job) == []
