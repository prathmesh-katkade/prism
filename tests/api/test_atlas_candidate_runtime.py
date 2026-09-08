from __future__ import annotations

import os
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from prism_api import atlas_foundry_routes
from prism_api.atlas_candidate_runtime import (
    DurableAtlasCandidateRuntimeStore,
    activate_current_ollama_model,
    ensure_configured_production_baseline,
)
from prism_api.atlas_promotion import DurableAtlasPromotionStore
from prism_api_contracts import (
    AtlasBenchSuiteRun,
    AtlasPromotionDecision,
    AtlasPromotionVerdict,
    AtlasTrainingRecipe,
    AtlasTrainingRecipeMethod,
    AtlasTrainingSplit,
)


def _bound_bench_run(*, run_id: str, candidate_id: str, subject_kind: str, corpus_hash: str = "a" * 64) -> AtlasBenchSuiteRun:
    now = datetime.now(timezone.utc)
    return AtlasBenchSuiteRun(
        run_id=run_id,
        subject_id=f"subject_{run_id}",
        corpus_version="atlasbench-v1",
        corpus_hash=corpus_hash,
        total_tasks=1,
        total_passed=1,
        category_scores=[],
        started_at=now,
        completed_at=now,
        subject_kind=subject_kind,  # type: ignore[arg-type]
        candidate_id=candidate_id,
        candidate_fingerprint="candidate-fingerprint" if subject_kind == "candidate" else None,
        trust_verification_id="verification-1" if subject_kind == "candidate" else None,
        runtime_model=f"{candidate_id}-model",
        runtime_model_digest=f"{candidate_id}-digest",
        provider="ollama",
    )


def _configure_promotion_decision_dependencies(monkeypatch, candidate_run: AtlasBenchSuiteRun, production_run: AtlasBenchSuiteRun) -> None:  # type: ignore[no-untyped-def]
    candidate_binding = SimpleNamespace(provider="ollama", runtime_model="candidate_a-model", runtime_model_digest="candidate_a-digest")
    production_binding = SimpleNamespace(provider="ollama", runtime_model="production-model", runtime_model_digest="production-digest")
    monkeypatch.setattr(atlas_foundry_routes, "_candidate_registry", SimpleNamespace(get=lambda _: object()))
    monkeypatch.setattr(atlas_foundry_routes, "is_verified", lambda *_: True)
    monkeypatch.setattr(atlas_foundry_routes, "_candidate_verification_store", SimpleNamespace(latest=lambda _: SimpleNamespace(verification_id="verification-1", aggregate_candidate_fingerprint="candidate-fingerprint")))
    monkeypatch.setattr(atlas_foundry_routes, "_candidate_runtime_store", SimpleNamespace(latest=lambda candidate_id: candidate_binding if candidate_id == "candidate_a" else production_binding))
    monkeypatch.setattr(atlas_foundry_routes, "_bench_store", SimpleNamespace(get_run=lambda run_id: candidate_run if run_id == "candidate-run" else production_run))
    monkeypatch.setattr(atlas_foundry_routes, "_promotion_store", SimpleNamespace(current_production=lambda: SimpleNamespace(candidate_id="production")))


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


@pytest.mark.parametrize(
    "candidate_update",
    [
        {"candidate_id": "candidate_b"},
        {"subject_kind": "generic"},
        {"candidate_fingerprint": "substituted-fingerprint"},
    ],
)
def test_promotion_decision_rejects_substituted_or_unbound_candidate_benchmark(
    monkeypatch, candidate_update: dict[str, str]
) -> None:  # type: ignore[no-untyped-def]
    candidate = _bound_bench_run(run_id="candidate-run", candidate_id="candidate_a", subject_kind="candidate").model_copy(update=candidate_update)
    production = _bound_bench_run(run_id="production-run", candidate_id="production", subject_kind="production")
    _configure_promotion_decision_dependencies(monkeypatch, candidate, production)

    with pytest.raises(HTTPException, match="server-bound"):
        atlas_foundry_routes.compute_promotion_decision("candidate_a", "production-run", "candidate-run")


def test_promotion_decision_rejects_a_corpus_mismatch_after_trust_binding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    candidate = _bound_bench_run(run_id="candidate-run", candidate_id="candidate_a", subject_kind="candidate")
    production = _bound_bench_run(run_id="production-run", candidate_id="production", subject_kind="production", corpus_hash="b" * 64)
    _configure_promotion_decision_dependencies(monkeypatch, candidate, production)

    with pytest.raises(HTTPException, match="identical AtlasBench corpus"):
        atlas_foundry_routes.compute_promotion_decision("candidate_a", "production-run", "candidate-run")


def test_unverified_ollama_configuration_does_not_create_production_pointer(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'unverified-bootstrap.db'}"
    monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_OLLAMA_MODEL", "configured-but-unprobed:1")

    active = ensure_configured_production_baseline()

    assert active == "configured-but-unprobed:1"
    assert DurableAtlasPromotionStore(database_url).current_production() is None


def test_configured_ollama_bootstrap_is_durable_idempotent_and_runtime_effective(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'bootstrap.db'}"
    monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_OLLAMA_MODEL", "production-model:1")

    active = ensure_configured_production_baseline(runtime_model_digest="prod-digest")
    promotion_store = DurableAtlasPromotionStore(database_url)
    pointer = promotion_store.current_production()

    assert active == "production-model:1"
    assert pointer is not None
    assert pointer.decision_id is None
    binding = DurableAtlasCandidateRuntimeStore(database_url).latest(pointer.candidate_id)
    assert binding is not None
    assert binding.runtime_model == "production-model:1"
    assert binding.runtime_model_digest == "prod-digest"

    first_event_id = pointer.event_id
    assert ensure_configured_production_baseline(runtime_model_digest="different-digest") == "production-model:1"
    current = promotion_store.current_production()
    assert current is not None
    assert current.event_id == first_event_id
    assert len(promotion_store.history()) == 1


def test_promotion_activation_and_rollback_restore_exact_bound_model(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'promotion-runtime.db'}"
    monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_OLLAMA_MODEL", "production-model:1")

    ensure_configured_production_baseline(runtime_model_digest="prod-digest")
    runtime_store = DurableAtlasCandidateRuntimeStore(database_url)
    runtime_store.bind_ollama(
        "candidate_1",
        "candidate-model:1",
        runtime_model_digest="candidate-digest",
    )
    decision = AtlasPromotionDecision(
        decision_id="decision_1",
        candidate_id="candidate_1",
        production_run_id="bench_prod",
        candidate_run_id="bench_candidate",
        verdict=AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
        overall_production_pass_rate=0.5,
        overall_candidate_pass_rate=0.6,
        critical_regressions=[],
        decided_at=datetime.now(timezone.utc),
    )
    promotion_store = DurableAtlasPromotionStore(database_url)

    promoted = promotion_store.promote(decision, reason="test promotion")
    assert promoted.candidate_id == "candidate_1"
    assert activate_current_ollama_model() == "candidate-model:1"
    assert os.environ.get("PRISM_ATLAS_OLLAMA_MODEL") == "candidate-model:1"

    rolled_back = promotion_store.rollback(reason="test rollback")
    assert rolled_back.candidate_id != "candidate_1"
    assert activate_current_ollama_model() == "production-model:1"
    assert os.environ.get("PRISM_ATLAS_OLLAMA_MODEL") == "production-model:1"
    assert len(promotion_store.history()) == 3


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
