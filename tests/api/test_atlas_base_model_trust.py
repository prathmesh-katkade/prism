from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
import pytest
from fastapi.testclient import TestClient
from prism_api import atlas_foundry_routes
from prism_api.atlas_base_model_trust import (
    APPROVED_MODEL_LICENSES,
    DurableAtlasBaseModelVerificationStore,
    DurableAtlasVerifiedBaseModelRegistry,
    compute_base_model_candidate_id,
    is_base_model_verified,
    verify_base_model_candidate,
)
from prism_api.atlas_bench_live import run_candidate_benchmark
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasCandidateKind,
    AtlasCandidateVerificationState,
    AtlasVerifiedBaseModelCandidate,
)


def _candidate(
    *,
    upstream_model_id: str = "Qwen/Qwen3-4B-Instruct-2507",
    upstream_revision: str = "cdbee75f17c01a7cc42f958dc650907174af0554",
    runtime_model: str = "qwen3:4b-instruct-2507-q4_K_M",
    declared_runtime_digest: str = "0edcdef34593eac1aa2be9c7d06c432dcf81945adca5eca2f27662c18f168ba0",
    license: str = "Apache-2.0",
    official_source: str | None = None,
    declared_manifest_digest: str | None = None,
) -> AtlasVerifiedBaseModelCandidate:
    candidate_id = compute_base_model_candidate_id(
        upstream_model_id=upstream_model_id, upstream_revision=upstream_revision, runtime_model=runtime_model
    )
    return AtlasVerifiedBaseModelCandidate(
        candidate_id=candidate_id,
        upstream_model_id=upstream_model_id,
        upstream_revision=upstream_revision,
        license=license,
        official_source=official_source or f"https://huggingface.co/{upstream_model_id}",
        runtime_model=runtime_model,
        declared_runtime_digest=declared_runtime_digest,
        quantization="Q4_K_M",
        declared_manifest_digest=declared_manifest_digest,
        declared_blob_digests=[],
        parameter_count=4_022_468_096,
        created_at=datetime.now(timezone.utc),
    )


def test_candidate_id_is_deterministic_and_namespaced_away_from_trained_candidates() -> None:
    candidate = _candidate()
    again = _candidate()
    assert candidate.candidate_id == again.candidate_id
    assert candidate.candidate_id.startswith("basemodel_")
    assert "candidate_foundryjob_" not in candidate.candidate_id


def test_registering_the_same_declared_identity_twice_is_idempotent(tmp_path) -> None:  # type: ignore[no-untyped-def]
    registry = DurableAtlasVerifiedBaseModelRegistry(database_url=f"sqlite:///{tmp_path / 'registry.db'}")
    candidate = _candidate()
    first = registry.register(candidate)
    second = registry.register(candidate.model_copy(update={"quantization": "different"}))
    # The durable row from the first call wins; the second call's differing
    # field is silently discarded rather than mutating the stored candidate.
    assert first.quantization == second.quantization == candidate.quantization
    assert first.candidate_id == second.candidate_id
    stored = registry.get(candidate.candidate_id)
    assert stored is not None
    assert stored.quantization == candidate.quantization
    assert [item.candidate_id for item in registry.list()] == [candidate.candidate_id]


def test_verify_base_model_candidate_happy_path_produces_a_stable_fingerprint() -> None:
    candidate = _candidate()
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    assert verification.verification_state is AtlasCandidateVerificationState.VERIFIED
    assert verification.verification_failure_reason is None
    assert verification.live_runtime_digest == candidate.declared_runtime_digest
    assert verification.aggregate_candidate_fingerprint is not None
    assert len(verification.aggregate_candidate_fingerprint) == 64

    repeated = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    assert repeated.aggregate_candidate_fingerprint == verification.aggregate_candidate_fingerprint
    assert repeated.verification_id != verification.verification_id  # a new append-only row, not an edit


@pytest.mark.parametrize("license", ["GPL-3.0", "proprietary", "", "unknown"])
def test_verify_rejects_a_license_not_on_the_allowlist(license: str) -> None:
    if license == "":
        pytest.skip("empty license is rejected by the contract's min_length, not this function")
    candidate = _candidate(license=license)
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    assert verification.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "license" in verification.verification_failure_reason
    assert license not in APPROVED_MODEL_LICENSES


def test_verify_rejects_a_source_that_does_not_match_the_declared_model_id() -> None:
    candidate = _candidate(official_source="https://huggingface.co/SomeoneElse/different-model")
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    assert verification.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "official_source" in verification.verification_failure_reason


def test_verify_fails_closed_when_the_local_model_is_not_found() -> None:
    candidate = _candidate()
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: None,
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    assert verification.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "not found" in verification.verification_failure_reason or "unreachable" in verification.verification_failure_reason


def test_verify_rejects_a_declared_digest_that_does_not_match_the_live_digest() -> None:
    """The core identity-substitution guard: a client cannot claim a digest
    the live daemon does not actually have for this model name."""
    candidate = _candidate()
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: "sha256:some-other-digest-entirely",
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    assert verification.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "identity substitution" in verification.verification_failure_reason
    assert verification.live_runtime_digest == "sha256:some-other-digest-entirely"


def test_verify_fails_closed_when_the_manifest_cannot_be_retrieved() -> None:
    candidate = _candidate()
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: None,
    )
    assert verification.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "manifest" in verification.verification_failure_reason


def test_verify_rejects_a_declared_manifest_digest_mismatch() -> None:
    candidate = _candidate(declared_manifest_digest="sha256:claimed-but-wrong")
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: {"digest": "sha256:actual-live-manifest"},
    )
    assert verification.verification_state is AtlasCandidateVerificationState.REJECTED
    assert "manifest digest" in verification.verification_failure_reason


def test_base_model_verification_history_is_append_only_and_latest_wins(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasBaseModelVerificationStore(database_url=f"sqlite:///{tmp_path / 'verify.db'}")
    candidate = _candidate()

    rejected = verify_base_model_candidate(candidate, resolve_live_digest=lambda model: None, resolve_manifest=lambda model: None)
    store.save(rejected)
    assert is_base_model_verified(store, candidate.candidate_id) is False

    verified = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: candidate.declared_runtime_digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifestdigest"},
    )
    store.save(verified)
    assert is_base_model_verified(store, candidate.candidate_id) is True

    # A later REJECTED re-verification (e.g. the model was swapped out from
    # under the daemon) must immediately revoke trust -- never silently keep
    # riding the old VERIFIED record.
    revoked = verify_base_model_candidate(candidate, resolve_live_digest=lambda model: None, resolve_manifest=lambda model: None)
    store.save(revoked)
    assert is_base_model_verified(store, candidate.candidate_id) is False

    history = store.history(candidate.candidate_id)
    assert [item.verification_id for item in history] == [
        revoked.verification_id,
        verified.verification_id,
        rejected.verification_id,
    ]


def test_get_and_list_routes_404_for_unregistered_candidate() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/atlas/base-model-candidates/basemodel_never_registered")
    assert response.status_code == 404
    verify_response = client.post("/api/v1/atlas/base-model-candidates/basemodel_never_registered/verify")
    assert verify_response.status_code == 404


def test_register_and_verify_route_opens_the_same_promotion_trust_gate_as_trained(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    unique = uuid.uuid4().hex
    upstream_model_id = f"Qwen/Qwen3-4B-Instruct-2507-{unique}"
    runtime_model = f"qwen3-test-{unique}:latest"
    digest = f"sha256:{unique}"

    client = TestClient(create_app())
    register_response = client.post(
        "/api/v1/atlas/base-model-candidates",
        json={
            "upstream_model_id": upstream_model_id,
            "upstream_revision": "rev1",
            "license": "Apache-2.0",
            "official_source": f"https://huggingface.co/{upstream_model_id}",
            "runtime_model": runtime_model,
            "declared_runtime_digest": digest,
        },
    )
    assert register_response.status_code == 201
    candidate_id = register_response.json()["candidate_id"]
    assert candidate_id.startswith("basemodel_")

    def fake_get(url, *args, **kwargs):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"models": [{"name": runtime_model, "digest": digest}]}, request=httpx.Request("GET", url))

    def fake_post(url, *args, **kwargs):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"digest": "sha256:manifest-ok"}, request=httpx.Request("POST", url))

    monkeypatch.setattr("prism_api.atlas_base_model_trust.httpx.get", fake_get)
    monkeypatch.setattr("prism_api.atlas_base_model_trust.httpx.post", fake_post)

    verify_response = client.post(f"/api/v1/atlas/base-model-candidates/{candidate_id}/verify")
    assert verify_response.status_code == 201
    assert verify_response.json()["verification_state"] == "verified"

    history_response = client.get(f"/api/v1/atlas/base-model-candidates/{candidate_id}/verification")
    assert history_response.status_code == 200
    assert len(history_response.json()) == 1

    # Exactly like a trained candidate: the trust gate is now open, so the
    # promotion-decision route fails for the honest, unrelated reason that no
    # such AtlasBench runs exist -- not the 409 trust error.
    decision_response = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={
            "candidate_id": candidate_id,
            "production_run_id": "benchrun_missing_prod",
            "candidate_run_id": "benchrun_missing_candidate",
        },
    )
    assert decision_response.status_code == 404
    assert "VERIFIED" not in decision_response.json()["detail"]


def test_unverified_base_model_candidate_is_refused_promotion_evaluation() -> None:
    unique = uuid.uuid4().hex
    candidate = _candidate(upstream_revision=f"rev-{unique}")
    atlas_foundry_routes._base_model_registry.register(candidate)

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


def test_run_candidate_benchmark_converges_a_verified_base_model_onto_the_candidate_path(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    """The exact same AtlasBench candidate evaluation path a trained Foundry
    candidate uses must also serve a verified off-the-shelf base model --
    same subject_kind, same runtime binding, same downstream shape."""
    database_url = f"sqlite:///{tmp_path / 'convergence.db'}"
    monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

    unique = uuid.uuid4().hex
    runtime_model = f"qwen3-converge-{unique}:latest"
    digest = f"sha256:{unique}"
    candidate = _candidate(upstream_revision=f"rev-{unique}", runtime_model=runtime_model, declared_runtime_digest=digest)

    registry = DurableAtlasVerifiedBaseModelRegistry(database_url=database_url)
    registry.register(candidate)
    verification_store = DurableAtlasBaseModelVerificationStore(database_url=database_url)
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifest-ok"},
    )
    verification_store.save(verification)
    assert verification.verification_state is AtlasCandidateVerificationState.VERIFIED

    runtime_store = DurableAtlasCandidateRuntimeStore(database_url=database_url)
    runtime_store.bind_ollama(candidate.candidate_id, runtime_model, runtime_model_digest=digest)

    def fake_get(url, *args, **kwargs):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"models": [{"name": runtime_model, "digest": digest}]}, request=httpx.Request("GET", url))

    def fake_post(url, *, json, timeout):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"response": '{"choice_index": 0}'}, request=httpx.Request("POST", url))

    monkeypatch.setattr("prism_api.atlas_bench_live.httpx.get", fake_get)
    monkeypatch.setattr("prism_api.atlas_bench_live.httpx.post", fake_post)

    suite = run_candidate_benchmark(candidate.candidate_id)

    assert suite.subject_kind == "candidate"
    assert suite.candidate_id == candidate.candidate_id
    assert suite.candidate_fingerprint == verification.aggregate_candidate_fingerprint
    assert suite.trust_verification_id == verification.verification_id
    assert suite.runtime_model == runtime_model
    assert suite.runtime_model_digest == digest
    assert suite.total_tasks > 0


def test_candidate_kind_enum_values_are_stable() -> None:
    assert AtlasCandidateKind.TRAINED_ADAPTER.value == "trained_adapter"
    assert AtlasCandidateKind.VERIFIED_BASE_MODEL.value == "verified_base_model"
