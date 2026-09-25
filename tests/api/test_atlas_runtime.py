from __future__ import annotations

import json
import time

import httpx
from fastapi.testclient import TestClient
from prism_api.main import create_app
from prism_api_contracts import AtlasPlanState, AtlasRunResponse, CortexGraphState


def _dataset(client: TestClient) -> str:
    response = client.post(
        "/api/v1/overview/datasets",
        files={"file": ("unknown.csv", b"segment,revenue\na,10\nb,12\na,8\n", "text/csv")},
    )
    assert response.status_code == 201
    return str(response.json()["dataset_id"])


def _terminal_run(client: TestClient, run_id: str) -> AtlasRunResponse:
    for _ in range(100):
        response = client.get(f"/api/v1/atlas/runs/{run_id}")
        assert response.status_code == 200
        run = AtlasRunResponse.model_validate(response.json())
        if run.plan.state in {
            AtlasPlanState.COMPLETED,
            AtlasPlanState.FAILED,
            AtlasPlanState.CANCELLED,
        }:
            return run
        time.sleep(0.01)
    raise AssertionError("Atlas first-wave run did not reach a terminal state")


def test_atlas_profiles_an_uploaded_dataset_with_visible_council_and_evidence() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)

    started = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Understand this unknown dataset safely."},
    )

    assert started.status_code == 202
    run = _terminal_run(client, started.json()["run_id"])
    assert run.plan.state is AtlasPlanState.COMPLETED
    assert [step.state.value for step in run.plan.steps] == ["completed", "completed", "completed"]
    assert {conclusion.specialist.value for conclusion in run.council} == {
        "scout",
        "stat",
        "auditor",
    }
    assert run.answer is not None and "deterministic first-pass assessment" in run.answer
    assert run.uncertainty is not None and "not a causal conclusion" in run.uncertainty
    assert all(item.source_fingerprint for item in run.evidence)
    assert any(
        "Do not infer causality" in objection
        for conclusion in run.council
        for objection in conclusion.objections
    )


def test_atlas_sse_and_cortex_are_projections_of_stored_run_state() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    run_id = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Profile and audit the data."},
    ).json()["run_id"]
    _terminal_run(client, run_id)

    events = client.get(f"/api/v1/atlas/runs/{run_id}/events")
    cortex = client.get(f"/api/v1/atlas/runs/{run_id}/cortex")

    assert events.status_code == 200
    assert events.headers["content-type"].startswith("text/event-stream")
    assert '"type":"plan_created"' in events.text
    assert '"type":"run_completed"' in events.text
    graph = CortexGraphState.model_validate(cortex.json())
    assert graph.run_id == run_id
    assert all(node.source_id for node in graph.nodes)
    assert any(edge.relation == "supports" or edge.relation == "produced" for edge in graph.edges)
    assert not any("thought" in node.label.lower() for node in graph.nodes)


def test_recent_runs_are_listed_newest_first_for_the_activity_browser(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # Isolated to a temp durable store: `runs` is a process-wide singleton
    # shared with every other test's Atlas run history, and the Foundry
    # combined-SFT builder elsewhere in the suite scans that same run
    # history for eligible examples -- two more real completed runs here
    # would otherwise be real, unrelated cross-contamination for it.
    from prism_api.atlas_runtime import runs as run_store
    from prism_api.durable_atlas_store import DurableAtlasRunStore

    monkeypatch.setattr(run_store, "_store", DurableAtlasRunStore(f"sqlite:///{tmp_path}/isolated-runs.db"))

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    first_run = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "First investigation."},
    ).json()["run_id"]
    time.sleep(0.01)  # force a distinct created_at from the first run
    second_run = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Second investigation."},
    ).json()["run_id"]
    _terminal_run(client, first_run)
    _terminal_run(client, second_run)

    response = client.get("/api/v1/atlas/runs", params={"limit": 2})
    assert response.status_code == 200
    recent_ids = response.json()
    assert recent_ids[:2] == [second_run, first_run]

    bounded = client.get("/api/v1/atlas/runs", params={"limit": 1})
    assert bounded.json() == [second_run]


def test_atlas_exposes_a_deterministic_provider_and_atlas_as_sole_voice() -> None:
    client = TestClient(create_app())

    providers = client.get("/api/v1/atlas/providers").json()
    specialists = client.get("/api/v1/atlas/specialists").json()

    assert any(item["provider"] == "deterministic" and item["available"] for item in providers)
    assert [item["specialist"] for item in specialists] == [
        "atlas",
        "scout",
        "curator",
        "stat",
        "researcher",
        "librarian",
        "auditor",
    ]
    assert [item["display_name"] for item in specialists if item["speaks_to_user"]] == ["Atlas"]


def test_atlas_memory_delete_returns_204_with_no_body() -> None:
    # Regression guard: FastAPI infers ``response_model`` from a bare ``-> None``
    # return annotation as the *class* ``NoneType`` (truthy), which previously
    # tripped FastAPI's "status code 204 must not have a response body" assert
    # at import time -- breaking every test and script that imports the app.
    client = TestClient(create_app())
    created = client.post(
        "/api/v1/atlas/memories",
        json={
            "scope": "project",
            "knowledge_class": "user_memory",
            "content": "Prefer explicit uncertainty in statistical answers.",
            "source": "user correction",
            "confidence": "high",
            "project_id": "project-a",
        },
    )
    assert created.status_code == 201
    memory_id = created.json()["memory_id"]

    deleted = client.delete(f"/api/v1/atlas/memories/{memory_id}")
    assert deleted.status_code == 204
    assert deleted.content == b""


def test_planner_timeout_seconds_falls_back_to_default_on_missing_or_unparseable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.delenv("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS", raising=False)
    assert atlas_runtime.planner_timeout_seconds() == atlas_runtime._DEFAULT_PLANNER_TIMEOUT_SECONDS  # noqa: SLF001

    for raw in ("not-a-number", "", "NaN", "inf", "-inf"):
        monkeypatch.setenv("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS", raw)
        assert atlas_runtime.planner_timeout_seconds() == atlas_runtime._DEFAULT_PLANNER_TIMEOUT_SECONDS  # noqa: SLF001


def test_planner_timeout_seconds_accepts_a_valid_value_within_range(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS", "10.5")
    assert atlas_runtime.planner_timeout_seconds() == 10.5


def test_planner_timeout_seconds_clamps_out_of_range_values(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS", "0.1")
    assert atlas_runtime.planner_timeout_seconds() == 1.0

    monkeypatch.setenv("PRISM_ATLAS_PLANNER_TIMEOUT_SECONDS", "999")
    assert atlas_runtime.planner_timeout_seconds() == 30.0


def _plan_created_payload(client: TestClient, run_id: str) -> dict[str, object]:
    run = client.get(f"/api/v1/atlas/runs/{run_id}").json()
    event = next(event for event in run["events"] if event["type"] == "plan_created")
    return dict(event["payload"])


def test_ollama_plan_proposal_timeout_is_distinguished_and_recorded(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # No live Ollama involved: httpx.post is monkeypatched to simulate the
    # exact failure mode a slow/unloaded local model produces under the
    # configurable planner timeout.
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

    def _raise_timeout(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        raise atlas_runtime.httpx.TimeoutException("simulated planner timeout")

    monkeypatch.setattr(atlas_runtime.httpx, "post", _raise_timeout)

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    run_id = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Profile this dataset."},
    ).json()["run_id"]

    payload = _plan_created_payload(client, run_id)
    assert payload["model_proposal"] == "timed_out"
    assert payload["model_proposal_steps_accepted"] == 0


def test_planning_tier_rule_is_deterministic_and_defaults_fast() -> None:
    from prism_api.atlas_runtime import choose_planning_tier

    assert choose_planning_tier("Profile the dataset.", {}) == ("fast", "default")
    assert choose_planning_tier("Investigate causal claims.", {}) == ("deep", "causal_or_significance")
    assert choose_planning_tier("Decide whether to deploy despite financial risk.", {}) == ("deep", "decision_with_consequences")
    assert choose_planning_tier("Profile the dataset.", {"health": 69}) == ("deep", "dataset_health_below_70")
    assert choose_planning_tier("Profile the dataset.", {"health": None}) == ("fast", "default")
    assert choose_planning_tier("Profile the dataset.", {"previous_deterministic_fallback": True}) == ("deep", "previous_deterministic_fallback")


def test_high_stakes_route_uses_only_a_promoted_deep_binding(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    monkeypatch.setenv("PRISM_ATLAS_OLLAMA_MODEL", "fast-model")
    monkeypatch.setenv("PRISM_ATLAS_DEEP_OLLAMA_MODEL", "untrusted-env-model")
    requested_models: list[str] = []

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {"response": '{"steps": []}'}

    def _fake_post(_url, *, json, timeout):  # type: ignore[no-untyped-def]
        requested_models.append(json["model"])
        return _FakeResponse()

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)
    monkeypatch.setattr(atlas_runtime, "resolve_deep_ollama_model", lambda: None)
    client = TestClient(create_app())
    dataset_id = _dataset(client)
    run_id = client.post("/api/v1/atlas/runs", json={"dataset_id": dataset_id, "objective": "Investigate a causal claim."}).json()["run_id"]
    payload = _plan_created_payload(client, run_id)
    assert requested_models[-1] == "fast-model"
    assert payload["model_tier"] == "fast"
    assert payload["model_tier_reason"] == "deep_unavailable:causal_or_significance"

    monkeypatch.setattr(atlas_runtime, "resolve_deep_ollama_model", lambda: "verified-deep-model")
    run_id = client.post("/api/v1/atlas/runs", json={"dataset_id": dataset_id, "objective": "Investigate a causal claim."}).json()["run_id"]
    payload = _plan_created_payload(client, run_id)
    assert requested_models[-1] == "fast-model"
    assert payload["model_tier"] == "fast"
    assert payload["model_tier_reason"] == "deep_refinement_queued:causal_or_significance"
    assert client.get(f"/api/v1/atlas/runs/{run_id}/refinement").json()["state"] == "unavailable"


def test_ollama_plan_proposal_accepted_is_recorded_with_step_count(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "response": json.dumps(
                    {
                        "steps": [
                            {
                                "kind": "data_quality",
                                "tool_name": "overview.quality_review",
                                "title": "Check data quality",
                                "rationale": "Model-proposed step.",
                            }
                        ]
                    }
                )
            }

    def _fake_post(*_args, **_kwargs):  # type: ignore[no-untyped-def]
        return _FakeResponse()

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)

    client = TestClient(create_app())
    dataset_id = _dataset(client)
    run_id = client.post(
        "/api/v1/atlas/runs",
        json={"dataset_id": dataset_id, "objective": "Profile this dataset."},
    ).json()["run_id"]

    payload = _plan_created_payload(client, run_id)
    assert payload["model_proposal"] == "accepted"
    assert payload["model_proposal_steps_accepted"] == 1


def test_plan_response_schema_covers_every_allowed_tool_registry_entry_and_excludes_reserved_kinds() -> None:
    from prism_api import atlas_runtime

    expected_pairs = {
        (kind.value, tool_name)
        for tool_name, kinds in atlas_runtime.TOOL_REGISTRY.items()
        for kind in kinds
        if kind not in {atlas_runtime.AtlasStepKind.PROFILE_DATASET, atlas_runtime.AtlasStepKind.AUDIT_EVIDENCE}
    }
    assert set(atlas_runtime.ALLOWED_STEP_PAIRS) == expected_pairs
    assert len(atlas_runtime.ALLOWED_STEP_PAIRS) == len(atlas_runtime.TOOL_REGISTRY) - 2

    schema = atlas_runtime.PLAN_RESPONSE_SCHEMA
    variants = schema["properties"]["steps"]["items"]["oneOf"]  # type: ignore[index]
    schema_pairs = {
        (variant["properties"]["kind"]["const"], variant["properties"]["tool_name"]["const"])
        for variant in variants
    }
    assert schema_pairs == expected_pairs
    for reserved in (atlas_runtime.AtlasStepKind.PROFILE_DATASET, atlas_runtime.AtlasStepKind.AUDIT_EVIDENCE):
        assert reserved.value not in {pair[0] for pair in schema_pairs}


def test_plan_response_schema_rejects_an_empty_steps_array() -> None:
    # Round 3 found the cheapest schema-legal answer: {"steps": []}, valid
    # JSON and schema-conformant at 0% acceptance cost to the model. The
    # schema itself must forbid it, not just discourage it in prose.
    from prism_api import atlas_runtime

    steps_schema = atlas_runtime.PLAN_RESPONSE_SCHEMA["properties"]["steps"]  # type: ignore[index]
    assert steps_schema["minItems"] == 1  # type: ignore[index]

    def _steps_array_is_schema_valid(steps: list[object]) -> bool:
        min_items = steps_schema["minItems"]  # type: ignore[index]
        max_items = steps_schema["maxItems"]  # type: ignore[index]
        return min_items <= len(steps) <= max_items

    assert not _steps_array_is_schema_valid([])
    assert _steps_array_is_schema_valid([{"kind": "data_quality", "tool_name": "overview.quality_review"}])


def test_schema_constrained_plan_response_parses_and_survives_validation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    calls: list[dict[str, object]] = []

    class _FakeResponse:
        status_code = 200

        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, object]:
            return {
                "response": json.dumps(
                    {
                        "steps": [
                            {
                                "kind": "forecast",
                                "tool_name": "forecast.declared_time_column_required",
                                "title": "Forecast revenue",
                                "rationale": "Model-proposed step.",
                            }
                        ]
                    }
                )
            }

    def _fake_post(url, *, json, timeout):  # type: ignore[no-untyped-def]
        calls.append(json)
        return _FakeResponse()

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)

    provider = atlas_runtime.OllamaAtlasProvider()
    result = provider.propose_plan_detailed("Forecast next quarter revenue.", {"dataset_id": "x"})

    assert result.status == "ok"
    accepted = atlas_runtime.DynamicAtlasPlanner._validated_proposal(result.steps or [])  # noqa: SLF001
    assert len(accepted) == 1
    assert accepted[0].kind is atlas_runtime.AtlasStepKind.FORECAST

    assert len(calls) == 1
    assert calls[0]["format"] == atlas_runtime.PLAN_RESPONSE_SCHEMA
    assert calls[0]["think"] is False
    assert calls[0]["options"] == {"temperature": 0, "num_predict": 1800, "num_ctx": 4096}
    prompt = json.loads(calls[0]["prompt"])  # type: ignore[arg-type]
    assert prompt["prompt_schema_version"] == atlas_runtime.PLAN_PROMPT_SCHEMA_VERSION_V2
    assert "declared_tool_kind_pairs" in prompt


def test_schema_format_rejected_fails_closed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from prism_api import atlas_runtime

    monkeypatch.setenv("PRISM_AI_PROVIDER", "ollama")
    calls: list[dict[str, object]] = []

    class _RejectedResponse:
        # Only status_code is ever read on this leg: propose_plan_detailed
        # checks it before calling raise_for_status()/json(), which real
        # Ollama versions predating structured outputs never reach either.
        status_code = 400

        def raise_for_status(self) -> None:
            raise httpx.HTTPStatusError("schema rejected", request=httpx.Request("POST", "http://localhost"), response=httpx.Response(400))

    def _fake_post(url, *, json, timeout):  # type: ignore[no-untyped-def]
        calls.append(json)
        return _RejectedResponse()

    monkeypatch.setattr(atlas_runtime.httpx, "post", _fake_post)

    provider = atlas_runtime.OllamaAtlasProvider()
    result = provider.propose_plan_detailed("Review data quality.", {"dataset_id": "x"})

    assert result.status == "invalid"
    assert len(calls) == 1
    assert calls[0]["format"] == atlas_runtime.PLAN_RESPONSE_SCHEMA
