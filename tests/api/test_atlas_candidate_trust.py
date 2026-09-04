from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from prism_api import atlas_foundry_routes
from prism_api.atlas_candidate_trust import (
    AtlasCandidateVerificationState,
    verify_candidate,
)
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasCandidateArtifact,
    AtlasTrainingRecipe,
    AtlasTrainingRecipeMethod,
)


def _recipe(recipe_id: str, *, base_model: str = "Qwen/Qwen2.5-0.5B-Instruct", dataset_version_id: str = "trainset_1") -> AtlasTrainingRecipe:
    return AtlasTrainingRecipe(
        recipe_id=recipe_id,
        base_model=base_model,
        method=AtlasTrainingRecipeMethod.QLORA,
        task="sft",
        dataset_version_id=dataset_version_id,
        created_at=datetime.now(timezone.utc),
    )


def _candidate(candidate_id: str, recipe: AtlasTrainingRecipe, adapter_path: Path) -> AtlasCandidateArtifact:
    return AtlasCandidateArtifact(
        candidate_id=candidate_id,
        job_id=f"foundryjob_{uuid.uuid4().hex}",
        recipe_id=recipe.recipe_id,
        base_model=recipe.base_model,
        method=recipe.method,
        adapter_path=str(adapter_path),
        dataset_version_id=recipe.dataset_version_id,
        created_at=datetime.now(timezone.utc),
    )


def _write_real_adapter(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "adapter_model.safetensors").write_bytes(b"not-real-weights-but-real-bytes")
    (path / "adapter_config.json").write_text('{"r": 16, "alpha": 32}', encoding="utf-8")


def test_verify_rejects_a_missing_adapter_path(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_missing_1")
    candidate = _candidate("candidate_missing_1", recipe, tmp_path / "never-created")
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "does not exist" in (result.verification_failure_reason or "")


def test_verify_rejects_an_empty_adapter_workspace(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_empty_1")
    workspace = tmp_path / "empty"
    workspace.mkdir()
    candidate = _candidate("candidate_empty_1", recipe, workspace)
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "no files" in (result.verification_failure_reason or "")


def test_verify_rejects_an_invalid_file_type(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_badtype_1")
    workspace = tmp_path / "badtype"
    _write_real_adapter(workspace)
    (workspace / "payload.sh").write_text("#!/bin/sh\necho unexpected\n", encoding="utf-8")
    candidate = _candidate("candidate_badtype_1", recipe, workspace)
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "unexpected file type" in (result.verification_failure_reason or "")


def test_verify_rejects_an_executable_file_masquerading_as_an_allowed_type(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_exec_1")
    workspace = tmp_path / "exec"
    _write_real_adapter(workspace)
    tampered = workspace / "adapter_config.json"
    tampered.chmod(tampered.stat().st_mode | 0o111)  # tamper: make it executable
    candidate = _candidate("candidate_exec_1", recipe, workspace)
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "executable" in (result.verification_failure_reason or "")


def test_verify_rejects_a_symlink_escaping_the_workspace(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_symlink_1")
    workspace = tmp_path / "symlink"
    _write_real_adapter(workspace)
    outside = tmp_path / "outside.json"
    outside.write_text('{"secret": true}', encoding="utf-8")
    try:
        (workspace / "escape.json").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are not available in this environment")
    candidate = _candidate("candidate_symlink_1", recipe, workspace)
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "symlink" in (result.verification_failure_reason or "")


def test_verify_rejects_a_base_model_mismatch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_mismatch_1", base_model="Qwen/Qwen2.5-0.5B-Instruct")
    workspace = tmp_path / "mismatch"
    _write_real_adapter(workspace)
    candidate = _candidate("candidate_mismatch_1", recipe, workspace).model_copy(
        update={"base_model": "totally-different-model"}
    )
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "base-model mismatch" in (result.verification_failure_reason or "")


def test_verify_rejects_a_dataset_version_mismatch(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_dsmismatch_1", dataset_version_id="trainset_real")
    workspace = tmp_path / "dsmismatch"
    _write_real_adapter(workspace)
    candidate = _candidate("candidate_dsmismatch_1", recipe, workspace).model_copy(
        update={"dataset_version_id": "trainset_fabricated"}
    )
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "dataset mismatch" in (result.verification_failure_reason or "")


def test_verify_accepts_a_genuine_adapter_workspace(tmp_path) -> None:  # type: ignore[no-untyped-def]
    recipe = _recipe("recipe_good_1")
    workspace = tmp_path / "good"
    _write_real_adapter(workspace)
    candidate = _candidate("candidate_good_1", recipe, workspace)
    result = verify_candidate(candidate, recipe)
    assert result.verification_state is AtlasCandidateVerificationState.VERIFIED
    assert result.verification_failure_reason is None
    assert result.verified_at is not None
    assert len(result.adapter_files) == 2
    assert result.aggregate_candidate_fingerprint is not None
    # Reproducible: verifying the identical, untouched workspace twice
    # yields the identical fingerprint.
    again = verify_candidate(candidate, recipe)
    assert again.aggregate_candidate_fingerprint == result.aggregate_candidate_fingerprint


def test_unverified_candidate_is_refused_promotion_evaluation_and_promotion(tmp_path) -> None:  # type: ignore[no-untyped-def]
    unique = uuid.uuid4().hex
    recipe = _recipe(f"recipe_unverified_{unique}")
    workspace = tmp_path / "unverified"
    _write_real_adapter(workspace)
    candidate = _candidate(f"candidate_unverified_{unique}", recipe, workspace)

    atlas_foundry_routes._job_store.save_recipe(recipe)
    atlas_foundry_routes._candidate_registry.register(candidate)

    client = TestClient(create_app())

    decision_response = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={
            "candidate_id": candidate.candidate_id,
            "production_run_id": "benchrun_prod_x",
            "candidate_run_id": "benchrun_candidate_x",
        },
    )
    assert decision_response.status_code == 409
    assert "VERIFIED" in decision_response.json()["detail"]

    # An unverified candidate cannot be promoted even if some other decision
    # were ever stored referencing it -- exercised directly against the
    # store to avoid depending on real AtlasBench runs existing.
    from prism_api.atlas_promotion_decisions import DurableAtlasPromotionDecisionStore
    from prism_api_contracts import AtlasPromotionDecision, AtlasPromotionVerdict

    decision_store = DurableAtlasPromotionDecisionStore()
    stored_decision = decision_store.save(
        AtlasPromotionDecision(
            decision_id=f"decision_unverified_{unique}",
            candidate_id=candidate.candidate_id,
            production_run_id="benchrun_prod_x",
            candidate_run_id="benchrun_candidate_x",
            verdict=AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
            overall_production_pass_rate=0.5,
            overall_candidate_pass_rate=0.9,
            critical_regressions=[],
            decided_at=datetime.now(timezone.utc),
        )
    )
    promote_response = client.post(
        "/api/v1/atlas/promotion/promote",
        params={"decision_id": stored_decision.decision_id, "reason": "should be refused"},
    )
    assert promote_response.status_code == 409
    assert "VERIFIED" in promote_response.json()["detail"]


def test_verified_candidate_passes_the_trust_gate_in_promotion_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    unique = uuid.uuid4().hex
    recipe = _recipe(f"recipe_verified_{unique}")
    workspace = tmp_path / "verified"
    _write_real_adapter(workspace)
    candidate = _candidate(f"candidate_verified_{unique}", recipe, workspace)

    atlas_foundry_routes._job_store.save_recipe(recipe)
    atlas_foundry_routes._candidate_registry.register(candidate)

    client = TestClient(create_app())
    verify_response = client.post(f"/api/v1/atlas/foundry/candidates/{candidate.candidate_id}/verify")
    assert verify_response.status_code == 201
    assert verify_response.json()["verification_state"] == "verified"

    history_response = client.get(f"/api/v1/atlas/foundry/candidates/{candidate.candidate_id}/verification")
    assert history_response.status_code == 200
    assert len(history_response.json()) == 1

    # The trust gate is now open; the request fails for an unrelated, honest
    # reason (no such AtlasBench runs exist) rather than the 409 trust error.
    decision_response = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={
            "candidate_id": candidate.candidate_id,
            "production_run_id": "benchrun_prod_missing",
            "candidate_run_id": "benchrun_candidate_missing",
        },
    )
    assert decision_response.status_code == 404
    assert "VERIFIED" not in decision_response.json()["detail"]


def test_verify_route_404s_for_an_unregistered_candidate() -> None:
    client = TestClient(create_app())
    response = client.post("/api/v1/atlas/foundry/candidates/candidate_never_registered/verify")
    assert response.status_code == 404
