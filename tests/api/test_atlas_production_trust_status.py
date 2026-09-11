from __future__ import annotations

import uuid
from datetime import datetime, timezone

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
    DurableAtlasOperationalCertStore,
    PerfectOperationalSubject,
    run_operational_suite,
)
from prism_api.atlas_promotion import DurableAtlasPromotionStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasBenchCategoryScore,
    AtlasBenchSuiteRun,
    AtlasCandidateVerificationState,
    AtlasVerifiedBaseModelCandidate,
)


def test_current_status_is_all_none_with_no_production() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/atlas/promotion/current-status")
    assert response.status_code == 200
    body = response.json()
    assert body["production"] is None
    assert body["candidate_kind"] is None
    assert body["runtime_model"] is None


def test_current_status_surfaces_real_verified_base_model_production(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: register + verify + bind + promote a base-model candidate,
    record a real V1 bench run and a real Operational Certification run for
    it, then confirm the read-only status route surfaces exactly that real
    state -- never a guess or a fabricated field.

    The route reads through atlas_foundry_routes's module-level singleton
    stores (constructed once at import time) plus a freshly-constructed
    ``DurableAtlasOperationalCertStore`` per call; both are redirected to an
    isolated tmp database here so this test cannot collide with promotion
    state left behind by any other test sharing the default database.
    """
    database_url = f"sqlite:///{tmp_path / 'trust-status.db'}"

    base_model_registry = DurableAtlasVerifiedBaseModelRegistry(database_url=database_url)
    base_model_verification_store = DurableAtlasBaseModelVerificationStore(database_url=database_url)
    runtime_store = DurableAtlasCandidateRuntimeStore(database_url=database_url)
    promotion_store = DurableAtlasPromotionStore(database_url=database_url)
    bench_store = DurableAtlasBenchStore(database_url=database_url)

    monkeypatch.setattr(atlas_foundry_routes, "_base_model_registry", base_model_registry)
    monkeypatch.setattr(atlas_foundry_routes, "_base_model_verification_store", base_model_verification_store)
    monkeypatch.setattr(atlas_foundry_routes, "_candidate_runtime_store", runtime_store)
    monkeypatch.setattr(atlas_foundry_routes, "_promotion_store", promotion_store)
    monkeypatch.setattr(atlas_foundry_routes, "_bench_store", bench_store)
    # The route constructs DurableAtlasOperationalCertStore() fresh per call
    # using the default database resolver -- redirect that resolver too so
    # it lands in the same isolated tmp database as everything else here.
    monkeypatch.setattr(atlas_operational_cert, "history_database_url", lambda: database_url)

    unique = uuid.uuid4().hex
    runtime_model = f"qwen3-status-{unique}:latest"
    digest = f"sha256:{unique}"
    candidate = AtlasVerifiedBaseModelCandidate(
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

    base_model_registry.register(candidate)
    verification = verify_base_model_candidate(
        candidate,
        resolve_live_digest=lambda model: digest,
        resolve_manifest=lambda model: {"digest": "sha256:manifest-ok"},
    )
    base_model_verification_store.save(verification)
    assert verification.verification_state is AtlasCandidateVerificationState.VERIFIED

    runtime_store.bind_ollama(candidate.candidate_id, runtime_model, runtime_model_digest=digest)
    promotion_store.bootstrap(candidate.candidate_id, reason="test: make this candidate production directly")

    now = datetime.now(timezone.utc)
    suite = AtlasBenchSuiteRun(
        run_id=f"benchrun_{unique}",
        subject_id=f"subject_{unique}",
        corpus_version=CORPUS_VERSION,
        corpus_hash=corpus_hash(),
        total_tasks=90,
        total_passed=90,
        category_scores=[AtlasBenchCategoryScore(category="sql", total=10, passed=10)],
        started_at=now,
        completed_at=now,
        subject_kind="production",
        candidate_id=candidate.candidate_id,
        runtime_model=runtime_model,
        runtime_model_digest=digest,
        provider="ollama",
    )
    bench_store.save(suite, [])

    opcert_run = run_operational_suite(
        PerfectOperationalSubject(), subject_kind="candidate", candidate_id=candidate.candidate_id,
        trust_verification_id=verification.verification_id, runtime_model=runtime_model, runtime_model_digest=digest,
    )
    DurableAtlasOperationalCertStore(database_url=database_url).save(opcert_run)

    client = TestClient(create_app())
    response = client.get("/api/v1/atlas/promotion/current-status")
    assert response.status_code == 200
    body = response.json()
    assert body["candidate_kind"] == "verified_base_model"
    assert body["runtime_model"] == runtime_model
    assert body["runtime_model_digest"] == digest
    assert body["trust_verification_state"] == "verified"
    assert body["latest_v1_run_id"] == f"benchrun_{unique}"
    assert body["latest_v1_total_passed"] == 90
    assert body["latest_v1_total_tasks"] == 90
    assert body["latest_operational_cert_run_id"] == opcert_run.run_id
    assert body["latest_operational_cert_critical_failures"] == 0
