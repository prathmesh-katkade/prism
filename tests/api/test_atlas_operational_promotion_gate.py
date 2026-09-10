from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from prism_api import atlas_foundry_routes, atlas_operational_cert
from prism_api.atlas_base_model_trust import (
    DurableAtlasBaseModelVerificationStore,
    DurableAtlasVerifiedBaseModelRegistry,
    compute_base_model_candidate_id,
    verify_base_model_candidate,
)
from prism_api.atlas_bench_corpus import CORPUS_VERSION, corpus_hash
from prism_api.atlas_bench_store import DurableAtlasBenchStore
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore
from prism_api.atlas_operational_cert import (
    SUITE_VERSION,
    DurableAtlasOperationalCertStore,
    PerfectOperationalSubject,
    UnsafeOperationalSubject,
    run_operational_suite,
    suite_hash,
)
from prism_api.atlas_promotion import DurableAtlasPromotionStore
from prism_api.atlas_promotion_decisions import DurableAtlasPromotionDecisionStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasBaseModelVerification,
    AtlasBenchCategoryScore,
    AtlasBenchSuiteRun,
    AtlasCandidateVerificationState,
    AtlasOperationalSuiteRun,
    AtlasVerifiedBaseModelCandidate,
)


def _base_model_candidate(unique: str, *, runtime_model: str, digest: str) -> AtlasVerifiedBaseModelCandidate:
    return AtlasVerifiedBaseModelCandidate(
        candidate_id=compute_base_model_candidate_id(
            upstream_model_id="Qwen/Qwen3-4B-Instruct-2507", upstream_revision=f"rev-{unique}", runtime_model=runtime_model
        ),
        upstream_model_id="Qwen/Qwen3-4B-Instruct-2507",
        upstream_revision=f"rev-{unique}",
        license="Apache-2.0",
        official_source="https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
        runtime_model=runtime_model,
        declared_runtime_digest=digest,
        quantization="Q4_K_M",
        declared_manifest_digest=None,
        declared_blob_digests=[],
        parameter_count=4_022_468_096,
        created_at=datetime.now(timezone.utc),
    )


def _wire_shared_stores(monkeypatch, database_url: str) -> dict[str, object]:
    """Redirect every module-level singleton store touched by this flow --
    in both atlas_foundry_routes and atlas_operational_cert -- to the exact
    same isolated instances, so registering/verifying/binding a candidate
    through one router is visible to the other, matching how they share a
    single real database in production."""
    base_model_registry = DurableAtlasVerifiedBaseModelRegistry(database_url=database_url)
    base_model_verification_store = DurableAtlasBaseModelVerificationStore(database_url=database_url)
    runtime_store = DurableAtlasCandidateRuntimeStore(database_url=database_url)
    promotion_store = DurableAtlasPromotionStore(database_url=database_url)
    promotion_decision_store = DurableAtlasPromotionDecisionStore(database_url=database_url)
    bench_store = DurableAtlasBenchStore(database_url=database_url)
    opcert_store = DurableAtlasOperationalCertStore(database_url=database_url)

    for target in (atlas_foundry_routes, atlas_operational_cert):
        monkeypatch.setattr(target, "_base_model_registry", base_model_registry)
        monkeypatch.setattr(target, "_base_model_verification_store", base_model_verification_store)
        monkeypatch.setattr(target, "_candidate_runtime_store", runtime_store)
    monkeypatch.setattr(atlas_foundry_routes, "_promotion_store", promotion_store)
    monkeypatch.setattr(atlas_foundry_routes, "_promotion_decision_store", promotion_decision_store)
    monkeypatch.setattr(atlas_foundry_routes, "_bench_store", bench_store)
    monkeypatch.setattr(atlas_operational_cert, "_store", opcert_store)
    return {
        "base_model_registry": base_model_registry,
        "base_model_verification_store": base_model_verification_store,
        "runtime_store": runtime_store,
        "promotion_store": promotion_store,
        "promotion_decision_store": promotion_decision_store,
        "bench_store": bench_store,
        "opcert_store": opcert_store,
    }


def _register_verify_bind(
    stores: dict[str, object], unique: str, *, runtime_model: str, digest: str
) -> tuple[AtlasVerifiedBaseModelCandidate, AtlasBaseModelVerification]:
    candidate = _base_model_candidate(unique, runtime_model=runtime_model, digest=digest)
    stores["base_model_registry"].register(candidate)  # type: ignore[attr-defined]
    verification = verify_base_model_candidate(
        candidate, resolve_live_digest=lambda model: digest, resolve_manifest=lambda model: {"digest": "sha256:manifest-ok"}
    )
    assert verification.verification_state is AtlasCandidateVerificationState.VERIFIED
    stores["base_model_verification_store"].save(verification)  # type: ignore[attr-defined]
    stores["runtime_store"].bind_ollama(candidate.candidate_id, runtime_model, runtime_model_digest=digest)  # type: ignore[attr-defined]
    return candidate, verification


def _bench_run(
    *,
    run_id: str,
    subject_kind: str,
    candidate: AtlasVerifiedBaseModelCandidate,
    digest: str,
    passed: int,
    total: int,
    verification: AtlasBaseModelVerification | None = None,
) -> AtlasBenchSuiteRun:
    now = datetime.now(timezone.utc)
    return AtlasBenchSuiteRun(
        run_id=run_id,
        subject_id=f"subject_{run_id}",
        corpus_version=CORPUS_VERSION,
        corpus_hash=corpus_hash(),
        total_tasks=total,
        total_passed=passed,
        category_scores=[AtlasBenchCategoryScore(category="sql", total=total, passed=passed)],
        started_at=now,
        completed_at=now,
        subject_kind=subject_kind,
        candidate_id=candidate.candidate_id,
        candidate_fingerprint=verification.aggregate_candidate_fingerprint if verification else None,
        trust_verification_id=verification.verification_id if verification else None,
        runtime_model=candidate.runtime_model,
        runtime_model_digest=digest,
        provider="ollama",
        evaluation_policy_id="a" * 64,
    )


def _good_operational_run(*, candidate: AtlasVerifiedBaseModelCandidate, digest: str) -> AtlasOperationalSuiteRun:
    return run_operational_suite(
        PerfectOperationalSubject(),
        subject_kind="candidate",
        candidate_id=candidate.candidate_id,
        runtime_model=candidate.runtime_model,
        runtime_model_digest=digest,
    )


def _set_up_production_and_candidate_bench_runs(stores: dict[str, object], unique: str):  # type: ignore[no-untyped-def]
    """Common scaffolding for the promotion-gate tests: a bootstrapped
    production candidate and a VERIFIED challenger, each with a matching
    fresh V1-style AtlasBench run bound to its exact runtime/verification
    identity -- everything ``compute_promotion_decision`` requires *except*
    Operational Certification, which each test supplies (or doesn't)."""
    production, _ = _register_verify_bind(stores, f"prod-{unique}", runtime_model=f"prod-{unique}:latest", digest=f"sha256:prod-{unique}")
    stores["promotion_store"].bootstrap(production.candidate_id, reason="test bootstrap")  # type: ignore[attr-defined]
    candidate, candidate_verification = _register_verify_bind(stores, f"cand-{unique}", runtime_model=f"cand-{unique}:latest", digest=f"sha256:cand-{unique}")

    production_run = stores["bench_store"].save(  # type: ignore[attr-defined]
        _bench_run(run_id=f"benchrun_prod_{unique}", subject_kind="production", candidate=production, digest=f"sha256:prod-{unique}", passed=74, total=90), []
    )
    candidate_run = stores["bench_store"].save(  # type: ignore[attr-defined]
        _bench_run(
            run_id=f"benchrun_cand_{unique}",
            subject_kind="candidate",
            candidate=candidate,
            digest=f"sha256:cand-{unique}",
            passed=90,
            total=90,
            verification=candidate_verification,
        ),
        [],
    )
    return candidate, production_run, candidate_run


def test_promote_route_refuses_without_any_operational_certification_run(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'gate.db'}"
    stores = _wire_shared_stores(monkeypatch, database_url)
    unique = uuid.uuid4().hex
    candidate, production_run, candidate_run = _set_up_production_and_candidate_bench_runs(stores, unique)

    client = TestClient(create_app())
    decision_response = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={"candidate_id": candidate.candidate_id, "production_run_id": production_run.run_id, "candidate_run_id": candidate_run.run_id},
    )
    assert decision_response.status_code == 201, decision_response.text
    decision = decision_response.json()
    assert decision["verdict"] == "promote_eligible"

    promote_response = client.post(
        "/api/v1/atlas/promotion/promote", params={"decision_id": decision["decision_id"], "reason": "no opcert yet"}
    )
    assert promote_response.status_code == 409
    assert "Operational Certification prerequisite not met" in promote_response.json()["detail"]
    assert "No live Operational Certification run" in promote_response.json()["detail"]


def test_promote_route_refuses_when_the_operational_run_has_a_critical_failure(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'gate-critical.db'}"
    stores = _wire_shared_stores(monkeypatch, database_url)
    unique = uuid.uuid4().hex
    candidate, production_run, candidate_run = _set_up_production_and_candidate_bench_runs(stores, unique)

    unsafe_run = run_operational_suite(
        UnsafeOperationalSubject(),
        subject_kind="candidate",
        candidate_id=candidate.candidate_id,
        runtime_model=candidate.runtime_model,
        runtime_model_digest=f"sha256:cand-{unique}",
    )
    assert unsafe_run.critical_failure_count > 0
    stores["opcert_store"].save(unsafe_run)  # type: ignore[attr-defined]

    client = TestClient(create_app())
    decision = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={"candidate_id": candidate.candidate_id, "production_run_id": production_run.run_id, "candidate_run_id": candidate_run.run_id},
    ).json()

    promote_response = client.post(
        "/api/v1/atlas/promotion/promote", params={"decision_id": decision["decision_id"], "reason": "should still be refused"}
    )
    assert promote_response.status_code == 409
    assert "critical failure" in promote_response.json()["detail"]


def test_promote_route_succeeds_once_a_fresh_clean_operational_run_is_on_record(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'gate-success.db'}"
    stores = _wire_shared_stores(monkeypatch, database_url)
    unique = uuid.uuid4().hex
    candidate, production_run, candidate_run = _set_up_production_and_candidate_bench_runs(stores, unique)

    good_run = _good_operational_run(candidate=candidate, digest=f"sha256:cand-{unique}")
    assert good_run.critical_failure_count == 0
    assert good_run.total_passed == good_run.total_scenarios
    assert good_run.suite_version == SUITE_VERSION
    assert good_run.suite_hash == suite_hash()
    stores["opcert_store"].save(good_run)  # type: ignore[attr-defined]

    client = TestClient(create_app())
    decision = client.post(
        "/api/v1/atlas/promotion/decisions",
        params={"candidate_id": candidate.candidate_id, "production_run_id": production_run.run_id, "candidate_run_id": candidate_run.run_id},
    ).json()

    promote_response = client.post(
        "/api/v1/atlas/promotion/promote", params={"decision_id": decision["decision_id"], "reason": "operational certification cleared"}
    )
    assert promote_response.status_code == 200, promote_response.text
    pointer = promote_response.json()
    assert pointer["candidate_id"] == candidate.candidate_id

    current = client.get("/api/v1/atlas/promotion/current").json()
    assert current["candidate_id"] == candidate.candidate_id


def test_live_candidate_run_route_requires_verification_and_runtime_binding(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'live-route.db'}"
    _wire_shared_stores(monkeypatch, database_url)

    client = TestClient(create_app())
    missing = client.post("/api/v1/atlas/operational-cert/candidates/nope/runs")
    assert missing.status_code == 404


def test_live_candidate_run_route_refuses_on_live_digest_drift(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'live-route-drift.db'}"
    stores = _wire_shared_stores(monkeypatch, database_url)
    unique = uuid.uuid4().hex
    candidate, _verification = _register_verify_bind(stores, unique, runtime_model=f"cand-{unique}:latest", digest=f"sha256:cand-{unique}")

    monkeypatch.setattr("prism_api.atlas_operational_cert.probe_live_ollama_digest", lambda model: "sha256:drifted-away")

    client = TestClient(create_app())
    response = client.post(f"/api/v1/atlas/operational-cert/candidates/{candidate.candidate_id}/runs")
    assert response.status_code == 409
    assert "drifted" in response.json()["detail"]


def test_live_candidate_run_route_records_a_real_candidate_run_on_success(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{tmp_path / 'live-route-success.db'}"
    stores = _wire_shared_stores(monkeypatch, database_url)
    unique = uuid.uuid4().hex
    digest = f"sha256:cand-{unique}"
    candidate, _verification = _register_verify_bind(stores, unique, runtime_model=f"cand-{unique}:latest", digest=digest)

    monkeypatch.setattr("prism_api.atlas_operational_cert.probe_live_ollama_digest", lambda model: digest)

    def unreachable_model(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("offline", request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"))

    # The live model itself is unreachable in this sandbox -- the harness must
    # still fail closed to a real (all-failing, zero-critical) durable run,
    # never refuse to record evidence or fabricate a pass.
    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", unreachable_model)

    client = TestClient(create_app())
    response = client.post(f"/api/v1/atlas/operational-cert/candidates/{candidate.candidate_id}/runs")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["subject_kind"] == "candidate"
    assert body["candidate_id"] == candidate.candidate_id
    assert body["runtime_model_digest"] == digest
    assert body["total_scenarios"] > 0
    assert body["total_passed"] == 0  # an unreachable model fails closed, never a fabricated pass
    assert body["critical_failure_count"] == 0  # honest non-attempt, not a safety violation

    listed = client.get(f"/api/v1/atlas/operational-cert/candidates/{candidate.candidate_id}/runs").json()
    assert len(listed) == 1
    assert listed[0]["run_id"] == body["run_id"]
