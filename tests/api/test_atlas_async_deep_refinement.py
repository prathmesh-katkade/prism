from __future__ import annotations

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient
from prism_api import atlas_runtime
from prism_api.atlas_candidate_runtime import DurableAtlasCandidateRuntimeStore
from prism_api.atlas_deep_refinement_store import DurableAtlasDeepRefinementStore
from prism_api.atlas_promotion import DurableAtlasPromotionStore
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api.main import create_app
from prism_api_contracts import AtlasDeepRefinementState
from sqlalchemy import text


def _wait_for(client: TestClient, run_id: str, state: str) -> dict[str, object]:
    for _ in range(80):
        response = client.get(f"/api/v1/atlas/runs/{run_id}/refinement")
        if response.status_code == 200 and response.json()["state"] == state:
            return response.json()
        time.sleep(0.025)
    raise AssertionError(f"refinement did not reach {state}")


def test_fast_plan_returns_before_deep_finishes_and_acceptance_creates_one_child(monkeypatch, tmp_path, request: pytest.FixtureRequest) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{(tmp_path / 'async.db').as_posix()}"
    monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_OLLAMA_MODEL", "fast-test-model")
    monkeypatch.setenv("PRISM_ATLAS_DEEP_OLLAMA_MODEL", "untrusted-env-model")
    monkeypatch.setattr(atlas_runtime.runs, "_store", DurableAtlasRunStore(database_url))
    monkeypatch.setattr(atlas_runtime, "deep_refinements", DurableAtlasDeepRefinementStore(database_url))
    DurableAtlasPromotionStore(database_url).bootstrap("deep_test_candidate", reason="test deep pointer", tier="deep")
    DurableAtlasCandidateRuntimeStore(database_url).bind_ollama(
        "deep_test_candidate", "deep-test-model", runtime_model_digest="verified-test-digest",
    )
    deep_started = threading.Event()
    release_deep = threading.Event()
    request.addfinalizer(release_deep.set)
    calls: list[str] = []

    class _Response:
        def __init__(self, steps: list[dict[str, str]]) -> None:
            self.steps = steps

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, str]:
            return {"response": json.dumps({"steps": self.steps})}

    def _post(_url: str, *, json: dict[str, object], timeout: float) -> _Response:
        model = str(json["model"])
        calls.append(model)
        if model == "deep-test-model":
            deep_started.set()
            assert release_deep.wait(5)
            return _Response([{"kind": "methodology_review", "tool_name": "atlas.methodology_review", "title": "Review causal readiness", "rationale": "Check evidence."}])
        assert model == "fast-test-model"
        return _Response([{"kind": "data_quality", "tool_name": "overview.quality_review", "title": "Review quality", "rationale": "Check data."}])

    monkeypatch.setattr(atlas_runtime.httpx, "post", _post)
    client = TestClient(create_app())
    dataset = client.post("/api/v1/overview/datasets", files={"file": ("probe.csv", b"segment,revenue\na,10\nb,12\n", "text/csv")})
    assert dataset.status_code == 201
    started = time.monotonic()
    created = client.post("/api/v1/atlas/runs", json={
        "dataset_id": dataset.json()["dataset_id"],
        "objective": "Investigate whether segment causes a significant revenue change.",
    })
    elapsed = time.monotonic() - started
    assert created.status_code == 202, created.text
    assert elapsed < 2
    source_id = created.json()["run_id"]
    assert deep_started.wait(2)
    assert calls[0] == "fast-test-model"
    assert "untrusted-env-model" not in calls
    assert client.get(f"/api/v1/atlas/runs/{source_id}/refinement").json()["state"] in {"queued", "running"}

    release_deep.set()
    ready = _wait_for(client, source_id, "ready")
    assert ready["runtime_model"] == "deep-test-model"
    assert ready["runtime_model_digest"] == "verified-test-digest"
    assert len(ready["proposed_steps"]) == 1
    for _ in range(80):
        source = client.get(f"/api/v1/atlas/runs/{source_id}").json()
        if source["plan"]["state"] == "completed":
            break
        time.sleep(0.025)
    assert source["plan"]["state"] == "completed"
    original_plan_id = source["plan"]["plan_id"]

    with atlas_runtime.deep_refinements.engine.begin() as connection:
        connection.execute(text("UPDATE prism_atlas_deep_refinements SET source_fingerprint = 'stale' WHERE run_id = :run_id"), {"run_id": source_id})
    stale = client.post(f"/api/v1/atlas/runs/{source_id}/refinement/accept")
    assert stale.status_code == 409
    with atlas_runtime.deep_refinements.engine.begin() as connection:
        connection.execute(text("UPDATE prism_atlas_deep_refinements SET source_fingerprint = :fingerprint WHERE run_id = :run_id"), {"run_id": source_id, "fingerprint": ready["source_fingerprint"]})

    accepted = client.post(f"/api/v1/atlas/runs/{source_id}/refinement/accept")
    assert accepted.status_code == 202, accepted.text
    child_id = accepted.json()["run_id"]
    assert child_id != source_id
    child_plan_event = next(item for item in accepted.json()["events"] if item["type"] == "plan_created")
    assert child_plan_event["payload"]["model_tier"] == "deep"
    assert child_plan_event["payload"]["source_run_id"] == source_id
    assert child_plan_event["payload"]["model_proposal"] == "accepted"
    again = client.post(f"/api/v1/atlas/runs/{source_id}/refinement/accept")
    assert again.status_code == 202
    assert again.json()["run_id"] == child_id
    assert client.get(f"/api/v1/atlas/runs/{source_id}").json()["plan"]["plan_id"] == original_plan_id
    assert client.get(f"/api/v1/atlas/runs/{source_id}/refinement").json()["state"] == "accepted"
    assert calls.count("deep-test-model") == 1


def test_restart_marks_orphaned_deep_job_failed(monkeypatch, tmp_path) -> None:  # type: ignore[no-untyped-def]
    database_url = f"sqlite:///{(tmp_path / 'restart.db').as_posix()}"
    monkeypatch.setenv("PRISM_ANALYTICAL_HISTORY_DATABASE_URL", database_url)
    monkeypatch.setenv("PRISM_AI_PROVIDER", "deterministic")
    monkeypatch.setattr(atlas_runtime.runs, "_store", DurableAtlasRunStore(database_url))
    monkeypatch.setattr(atlas_runtime, "deep_refinements", DurableAtlasDeepRefinementStore(database_url))
    client = TestClient(create_app())
    dataset = client.post("/api/v1/overview/datasets", files={"file": ("probe.csv", b"x,y\n1,2\n", "text/csv")})
    run = client.post("/api/v1/atlas/runs", json={"dataset_id": dataset.json()["dataset_id"], "objective": "Profile this dataset."})
    run_id = run.json()["run_id"]
    atlas_runtime.deep_refinements.create(run_id, state=AtlasDeepRefinementState.QUEUED, reason="interrupted test job")
    monkeypatch.setattr(atlas_runtime, "_deep_startup_done", False)
    assert atlas_runtime.reconcile_deep_refinements_once() == 1
    record = client.get(f"/api/v1/atlas/runs/{run_id}/refinement").json()
    assert record["state"] == "failed"
    assert "restart" in record["reason"].lower()
    assert atlas_runtime.reconcile_deep_refinements_once() == 0
