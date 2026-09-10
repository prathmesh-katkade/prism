from __future__ import annotations

import uuid
from datetime import datetime, timezone

import httpx
from fastapi.testclient import TestClient
from prism_api.atlas_base_model_trust import (
    DurableAtlasBaseModelVerificationStore,
    DurableAtlasVerifiedBaseModelRegistry,
    verify_base_model_candidate,
)
from prism_api.atlas_bench_corpus_v2 import CORPUS_V2_VERSION, corpus_v2_hash
from prism_api.atlas_bench_live import run_candidate_benchmark
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore
from prism_api.main import create_app
from prism_api_contracts import (
    AtlasBenchCorpusId,
    AtlasCandidateVerificationState,
    AtlasVerifiedBaseModelCandidate,
)


def _candidate(unique: str) -> AtlasVerifiedBaseModelCandidate:
    from prism_api.atlas_base_model_trust import compute_base_model_candidate_id

    runtime_model = f"qwen3-v2test-{unique}:latest"
    return AtlasVerifiedBaseModelCandidate(
        candidate_id=compute_base_model_candidate_id(
            upstream_model_id="Qwen/Qwen3-4B-Instruct-2507",
            upstream_revision=f"rev-{unique}",
            runtime_model=runtime_model,
        ),
        upstream_model_id="Qwen/Qwen3-4B-Instruct-2507",
        upstream_revision=f"rev-{unique}",
        license="Apache-2.0",
        official_source="https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
        runtime_model=runtime_model,
        declared_runtime_digest=f"sha256:{unique}",
        quantization="Q4_K_M",
        declared_manifest_digest=None,
        declared_blob_digests=[],
        parameter_count=4_022_468_096,
        created_at=datetime.now(timezone.utc),
    )


def test_candidate_route_rejects_an_invalid_corpus_selector() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/atlas/bench/candidates/whatever/runs",
        params={"corpus": "not-a-real-corpus"},
    )
    assert response.status_code == 422


def test_production_route_rejects_an_invalid_corpus_selector() -> None:
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/atlas/bench/runs",
        params={"provider": "deterministic", "corpus": "not-a-real-corpus"},
    )
    assert response.status_code == 422


def test_corpus_selector_route_never_accepts_client_supplied_task_data() -> None:
    """The client may only name an existing server-owned corpus id -- never
    tasks, answers, or scoring, regardless of what else it tries to pass."""
    client = TestClient(create_app())
    response = client.post(
        "/api/v1/atlas/bench/candidates/whatever/runs",
        params={
            "corpus": "atlasbench-v1",
            "tasks": '[{"prompt": "fake", "correct_choice": 0}]',
            "correct_choice": 0,
            "rationale": "fabricated",
        },
    )
    # Extra unrecognized query params are ignored by FastAPI, not consumed as
    # task/answer data -- the request still resolves through the real,
    # frozen server-owned corpus and fails only because the candidate does
    # not exist, never because it accepted fabricated task content.
    assert response.status_code == 409
    assert "correct_choice" not in response.text
    assert "rationale" not in response.text


def test_run_candidate_benchmark_defaults_to_v1_when_corpus_omitted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Backward compatibility: existing callers that never pass ``corpus``
    keep getting exactly the V1 behavior that existed before this selector."""
    unique = uuid.uuid4().hex
    database_url_env = "PRISM_ANALYTICAL_HISTORY_DATABASE_URL"

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        database_url = f"sqlite:///{tmp}/v1-default.db"
        monkeypatch.setenv(database_url_env, database_url)
        monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

        runtime_model = f"qwen3-v1default-{unique}:latest"
        digest = f"sha256:{unique}"
        candidate = _candidate(unique)
        candidate = candidate.model_copy(update={"runtime_model": runtime_model, "declared_runtime_digest": digest})

        DurableAtlasVerifiedBaseModelRegistry(database_url=database_url).register(candidate)
        verification = verify_base_model_candidate(
            candidate,
            resolve_live_digest=lambda model: digest,
            resolve_manifest=lambda model: {"digest": "sha256:manifest-ok"},
        )
        DurableAtlasBaseModelVerificationStore(database_url=database_url).save(verification)
        assert verification.verification_state is AtlasCandidateVerificationState.VERIFIED
        DurableAtlasCandidateRuntimeStore(database_url=database_url).bind_ollama(
            candidate.candidate_id, runtime_model, runtime_model_digest=digest
        )

        def fake_get(url, *args, **kwargs):  # type: ignore[no-untyped-def]
            return httpx.Response(200, json={"models": [{"name": runtime_model, "digest": digest}]}, request=httpx.Request("GET", url))

        def fake_post(url, *, json, timeout):  # type: ignore[no-untyped-def]
            return httpx.Response(200, json={"response": '{"choice_index": 0}'}, request=httpx.Request("POST", url))

        monkeypatch.setattr("prism_api.atlas_bench_live.httpx.get", fake_get)
        monkeypatch.setattr("prism_api.atlas_bench_live.httpx.post", fake_post)

        suite = run_candidate_benchmark(candidate.candidate_id)
        from prism_api.atlas_bench_corpus import CORPUS_VERSION, corpus_hash

        assert suite.corpus_version == CORPUS_VERSION
        assert suite.corpus_hash == corpus_hash()


def test_run_candidate_benchmark_can_select_the_v2_holdout_corpus(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    unique = uuid.uuid4().hex
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        database_url = f"sqlite:///{tmp}/v2-select.db"
        monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
        monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

        runtime_model = f"qwen3-v2select-{unique}:latest"
        digest = f"sha256:{unique}"
        candidate = _candidate(unique).model_copy(update={"runtime_model": runtime_model, "declared_runtime_digest": digest})

        DurableAtlasVerifiedBaseModelRegistry(database_url=database_url).register(candidate)
        verification = verify_base_model_candidate(
            candidate,
            resolve_live_digest=lambda model: digest,
            resolve_manifest=lambda model: {"digest": "sha256:manifest-ok"},
        )
        DurableAtlasBaseModelVerificationStore(database_url=database_url).save(verification)
        DurableAtlasCandidateRuntimeStore(database_url=database_url).bind_ollama(
            candidate.candidate_id, runtime_model, runtime_model_digest=digest
        )

        def fake_get(url, *args, **kwargs):  # type: ignore[no-untyped-def]
            return httpx.Response(200, json={"models": [{"name": runtime_model, "digest": digest}]}, request=httpx.Request("GET", url))

        def fake_post(url, *, json, timeout):  # type: ignore[no-untyped-def]
            return httpx.Response(200, json={"response": '{"choice_index": 0}'}, request=httpx.Request("POST", url))

        monkeypatch.setattr("prism_api.atlas_bench_live.httpx.get", fake_get)
        monkeypatch.setattr("prism_api.atlas_bench_live.httpx.post", fake_post)

        suite = run_candidate_benchmark(candidate.candidate_id, corpus=AtlasBenchCorpusId.ATLASBENCH_V2_HOLDOUT)

        assert suite.corpus_version == CORPUS_V2_VERSION
        assert suite.corpus_hash == corpus_v2_hash()
        assert suite.total_tasks >= 75
        assert suite.subject_kind == "candidate"
        assert suite.candidate_id == candidate.candidate_id


def test_run_candidate_benchmark_refuses_a_digest_that_drifted_since_binding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """If the live Ollama model changed after the durable runtime binding was
    recorded, the candidate run must refuse rather than silently evaluate
    whatever is live now under the old binding's identity."""
    import pytest
    from prism_api.atlas_bench_live import AtlasBenchSubjectUnavailable

    unique = uuid.uuid4().hex
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        database_url = f"sqlite:///{tmp}/digest-drift.db"
        monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
        monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

        runtime_model = f"qwen3-drift-{unique}:latest"
        bound_digest = f"sha256:bound-{unique}"
        live_digest = f"sha256:drifted-{unique}"  # the live daemon now reports a different digest
        candidate = _candidate(unique).model_copy(
            update={"runtime_model": runtime_model, "declared_runtime_digest": bound_digest}
        )

        DurableAtlasVerifiedBaseModelRegistry(database_url=database_url).register(candidate)
        verification = verify_base_model_candidate(
            candidate,
            resolve_live_digest=lambda model: bound_digest,
            resolve_manifest=lambda model: {"digest": "sha256:manifest-ok"},
        )
        DurableAtlasBaseModelVerificationStore(database_url=database_url).save(verification)
        DurableAtlasCandidateRuntimeStore(database_url=database_url).bind_ollama(
            candidate.candidate_id, runtime_model, runtime_model_digest=bound_digest
        )

        def fake_get(url, *args, **kwargs):  # type: ignore[no-untyped-def]
            return httpx.Response(
                200, json={"models": [{"name": runtime_model, "digest": live_digest}]}, request=httpx.Request("GET", url)
            )

        monkeypatch.setattr("prism_api.atlas_bench_live.httpx.get", fake_get)

        with pytest.raises(AtlasBenchSubjectUnavailable, match="re-deploy and re-bind"):
            run_candidate_benchmark(candidate.candidate_id)
