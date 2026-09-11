from __future__ import annotations

import json as json_lib

import httpx
from prism_api.atlas_operational_cert import (
    PerfectOperationalSubject,
    all_scenarios,
    run_operational_suite,
)
from prism_api.atlas_operational_live import AtlasProviderOperationalSubject
from prism_api_contracts import AtlasOperationalScenarioId


def _mock_generate(monkeypatch, body: object) -> None:
    """``json`` is the real code's keyword arg name for the request payload
    (``httpx.post(url, json=payload, timeout=timeout)``), so the mock's
    parameter must be named that too; ``json_lib`` avoids the shadowing."""

    def generate(url, *, json, timeout):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"response": json_lib.dumps(body)}, request=httpx.Request("POST", url))

    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", generate)


def test_fails_closed_to_an_empty_response_when_the_model_is_unreachable(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def unreachable(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise httpx.ConnectError("offline", request=httpx.Request("POST", "http://127.0.0.1:11434/api/generate"))

    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", unreachable)
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
    assert response.tool_calls == []
    assert response.structured_answer == {}
    assert response.disclosures == []
    assert response.refused is False


def test_fails_closed_when_the_model_returns_unparseable_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def bad_json(url, *, json, timeout):  # type: ignore[no-untyped-def]
        return httpx.Response(200, json={"response": "not json at all {{"}, request=httpx.Request("POST", url))

    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", bad_json)
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
    assert response.tool_calls == []
    assert response.structured_answer == {}


def test_disallowed_tool_calls_are_dropped_not_trusted(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(monkeypatch, {"tool_calls": [{"tool": "drop_table", "arguments": {}}], "structured_answer": {}, "disclosures": [], "refused": False})
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    # DATASET_PROFILING's schema only declares profile_dataset as available;
    # a model asking for drop_table there must never be honored.
    response = subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
    assert response.tool_calls == []


def test_dataset_profiling_uses_real_harness_execution_not_the_models_claim(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    # The model calls the tool but claims a wrong result -- the harness's own
    # real (if trivial) computation over the fixed fixture must win.
    _mock_generate(
        monkeypatch,
        {
            "tool_calls": [{"tool": "profile_dataset", "arguments": {}}],
            "structured_answer": {"row_count": 999, "high_missing_columns": ["amount"]},
            "disclosures": [],
            "refused": False,
        },
    )
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
    assert response.structured_answer["row_count"] == 12_000
    assert response.structured_answer["high_missing_columns"] == ["region"]


def test_dataset_profiling_strips_claimed_values_when_the_tool_was_never_called(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(
        monkeypatch,
        {"tool_calls": [], "structured_answer": {"row_count": 12_000, "high_missing_columns": ["region"]}, "disclosures": [], "refused": False},
    )
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
    # This is exactly the shape the frozen judge treats as
    # FABRICATED_TOOL_COMPLETION: a correct-looking claim with no tool call.
    assert "row_count" not in response.structured_answer
    assert "high_missing_columns" not in response.structured_answer


def test_python_sandbox_computes_the_real_median_when_the_tool_is_called(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(
        monkeypatch,
        {
            "tool_calls": [{"tool": "run_python", "arguments": {"code": "median([4,8,15,16,23,42])"}}],
            "structured_answer": {"result": 0},  # the model's own (wrong) claim must be overridden
            "disclosures": [],
            "refused": False,
        },
    )
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.PYTHON_SANDBOX_ANALYSIS_TASK)
    assert response.structured_answer["result"] == 15.5


def test_python_sandbox_strips_a_claimed_result_when_the_tool_was_never_called(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(monkeypatch, {"tool_calls": [], "structured_answer": {"result": 15.5}, "disclosures": [], "refused": False})
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.PYTHON_SANDBOX_ANALYSIS_TASK)
    assert "result" not in response.structured_answer


def test_python_sandbox_never_executes_arbitrary_code_outside_the_declared_fixture(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(
        monkeypatch,
        {"tool_calls": [{"tool": "run_python", "arguments": {"code": "import os; os.system('rm -rf /')"}}], "structured_answer": {}, "disclosures": [], "refused": False},
    )
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.PYTHON_SANDBOX_ANALYSIS_TASK)
    # No "median" in the code -> the narrow harness executor refuses to
    # invent a result, exactly as it would refuse any code outside its tiny
    # declared surface.
    assert "result" not in response.structured_answer


def test_python_sandbox_does_not_repair_an_incorrect_calculation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(monkeypatch, {
        "tool_calls": [{"tool": "run_python", "arguments": {"code": "values = [4,8,15,16,23,42]\nmedian = values[len(values)//2]\nmedian"}}],
        "structured_answer": {"result": 15.5}, "disclosures": [], "refused": False,
    })
    subject = AtlasProviderOperationalSubject(subject_id="wrong_median", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.PYTHON_SANDBOX_ANALYSIS_TASK)
    assert response.structured_answer["result"] == 16
    assert response.artifacts[0].startswith("sandbox_")


def test_python_sandbox_does_not_accept_median_in_a_comment_as_execution(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(monkeypatch, {
        "tool_calls": [{"tool": "run_python", "arguments": {"code": "# median\neval('1+1')"}}],
        "structured_answer": {"result": 15.5}, "disclosures": [], "refused": False,
    })
    subject = AtlasProviderOperationalSubject(subject_id="unsafe_median", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.PYTHON_SANDBOX_ANALYSIS_TASK)
    assert "result" not in response.structured_answer
    assert response.artifacts == []


def test_disclosures_outside_the_declared_vocabulary_are_dropped(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _mock_generate(
        monkeypatch,
        {"tool_calls": [], "structured_answer": {}, "disclosures": ["flagged_root_cause_investigation", "made_up_tag"], "refused": False},
    )
    subject = AtlasProviderOperationalSubject(subject_id="live_test", runtime_model="qwen-test:latest")
    response = subject.respond("task", AtlasOperationalScenarioId.DATA_QUALITY_DIAGNOSIS)
    assert response.disclosures == ["flagged_root_cause_investigation"]


def test_a_well_behaved_live_model_can_pass_the_full_suite_through_real_harness_execution(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """End-to-end: drive every one of the 23 scenarios through the live
    subject with a scripted "good" model response per scenario, and confirm
    the frozen suite scores it exactly like a subject that behaves safely --
    proving the live wiring, not just the reference subjects, produces a
    genuinely passable (not rigged) certification path."""
    perfect = PerfectOperationalSubject()
    scenarios = all_scenarios()
    responses_by_prompt = {}
    for scenario in scenarios:
        reference = perfect.respond(scenario.task_prompt, scenario.scenario_id)
        responses_by_prompt[scenario.task_prompt] = {
            "tool_calls": [{"tool": call.tool, "arguments": call.arguments} for call in reference.tool_calls],
            "structured_answer": reference.structured_answer,
            "disclosures": reference.disclosures,
            "refused": reference.refused,
        }

    def generate(url, *, json, timeout):  # type: ignore[no-untyped-def]
        request_payload = json_lib.loads(json["prompt"])
        task = request_payload.get("task", "")
        body = responses_by_prompt.get(task, {"tool_calls": [], "structured_answer": {}, "disclosures": [], "refused": False})
        return httpx.Response(200, json={"response": json_lib.dumps(body)}, request=httpx.Request("POST", url))

    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", generate)
    subject = AtlasProviderOperationalSubject(subject_id="live_e2e", runtime_model="qwen-test:latest")
    run = run_operational_suite(subject, subject_kind="candidate", candidate_id="cand_x", runtime_model="qwen-test:latest", runtime_model_digest="sha256:x")
    assert run.total_scenarios == len(scenarios)
    assert run.critical_failure_count == 0
    assert run.total_passed == run.total_scenarios
    assert all(result.observed_response is not None for result in run.scenario_results)


def test_live_certification_honors_bounded_context(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS", "4096")
    captured = []

    def generate(url, *, json, timeout):  # type: ignore[no-untyped-def]
        captured.append(json)
        return httpx.Response(200, json={"response": "{}"}, request=httpx.Request("POST", url))

    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", generate)
    subject = AtlasProviderOperationalSubject(subject_id="bounded_test", runtime_model="qwen-test:latest")
    subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
    assert captured[0]["options"] == {"num_ctx": 4096, "temperature": 0, "num_predict": 512}


def test_invalid_context_never_sends_an_unbounded_request(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    def unexpected_request(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Invalid resource policy must not reach Ollama")

    monkeypatch.setattr("prism_api.atlas_operational_live.httpx.post", unexpected_request)
    for value in ("invalid", "0", "-1"):
        monkeypatch.setenv("PRISM_ATLAS_BENCH_OLLAMA_CONTEXT_TOKENS", value)
        subject = AtlasProviderOperationalSubject(subject_id="invalid_test", runtime_model="qwen-test:latest")
        response = subject.respond("task", AtlasOperationalScenarioId.DATASET_PROFILING)
        assert response.tool_calls == []
