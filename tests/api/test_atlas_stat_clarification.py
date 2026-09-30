from __future__ import annotations

import time
from types import SimpleNamespace

import pandas as pd
import pytest
from fastapi import HTTPException
from prism_api import atlas_runtime, atlas_stat_adapter, overview, stats
from prism_api.atlas_run_admission import AtlasRunAdmission
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api.durable_dataset_store import DurableDatasetStore
from prism_api_contracts import (
    AtlasModelProviderName,
    AtlasRunRequest,
    AtlasStatAnalysis,
    StatTestKind,
)


def _setup(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    url = f"sqlite:///{(tmp_path / 'history.sqlite').as_posix()}"
    datasets = DurableDatasetStore(url)
    dataset = datasets.put(pd.DataFrame({
        "exposure": [1, 2, 3, 4, 5], "outcome": [2, 4, 6, 8, 10],
    }), "paired.csv", "c" * 64)
    monkeypatch.setattr(overview, "store", datasets)
    monkeypatch.setattr(atlas_stat_adapter, "dataset_store", datasets)
    monkeypatch.setattr(stats, "register_statistical_test", lambda *_: SimpleNamespace(object_id="stats_test_object"))
    monkeypatch.setattr(atlas_runtime, "run_admission", AtlasRunAdmission(max_concurrent_runs=1, max_queued_runs=0))
    run_store = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(url))
    monkeypatch.setattr(atlas_runtime, "runs", run_store)
    return url, datasets, dataset, run_store


def test_stat_question_survives_restart_and_resumes_without_reprofiling(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    url, _datasets, dataset, run_store = _setup(tmp_path, monkeypatch)
    run = run_store.create(AtlasRunRequest(dataset_id=dataset.dataset_id, objective="Test correlation significance"), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    waiting = run_store.get(run.run_id)
    assert waiting.plan.state.value == "waiting"
    assert len(waiting.clarifications) == 1
    assert waiting.clarifications[0].state == "open"
    assert next(step for step in waiting.plan.steps if step.step_id == "profile").attempts == 1
    restarted = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(url))
    monkeypatch.setattr(atlas_runtime, "runs", restarted)
    assert restarted.get(run.run_id).plan.state.value == "waiting"
    analysis = AtlasStatAnalysis(test=StatTestKind.PEARSON, col_a="exposure", col_b="outcome", design="linear_association")
    atlas_runtime.answer_stat_clarification(run.run_id, waiting.clarifications[0].question_id, analysis)
    for _ in range(100):
        completed = restarted.get(run.run_id)
        if completed.plan.state.value in {"completed", "failed"}:
            break
        time.sleep(0.05)
    assert completed.plan.state.value == "completed"
    assert completed.clarifications[0].state == "answered"
    assert next(step for step in completed.plan.steps if step.step_id == "profile").attempts == 1
    stat_event = next(event for event in completed.events if isinstance(event.payload.get("output"), dict)
                      and event.payload["output"].get("method") == "pearson")
    output = stat_event.payload["output"]
    assert output["result"]["statistic"] == pytest.approx(1.0)
    assert output["analyzed_rows"] == 5
    assert output["excluded_rows"] == 0
    assert output["dataset_revision"] == 0
    assert [message.sequence for message in completed.messages] == list(range(1, len(completed.messages) + 1))
    stat_message = next(message for message in completed.messages if message.specialist.value == "stat" and message.task_id == "statistical_analysis")
    assert stat_message.kind == "computed_observation"
    assert stat_message.origin == "deterministic_service"
    assert stat_message.model_binding is None
    assert stat_message.input_refs == [f"stat:{run.run_id}:statistical_analysis"]
    assert stat_message.reply_to == completed.messages[0].message_id
    auditor_message = next(message for message in completed.messages if message.specialist.value == "auditor" and message.kind == "computed_observation")
    assert f"stat:{run.run_id}:statistical_analysis" in auditor_message.input_refs
    assert restarted.get(run.run_id).messages == completed.messages
    assert "not a causal conclusion, statistical result" not in (completed.uncertainty or "")
    assert "The declared statistical test ran" in next(
        item.conclusion for item in completed.council if item.specialist.value == "stat" and "declared statistical test" in item.conclusion
    )
    assert atlas_runtime.answer_stat_clarification(run.run_id, waiting.clarifications[0].question_id, analysis).plan.state.value == "completed"


def test_stat_answer_rejects_stale_revision_and_preserves_waiting_question(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _url, datasets, dataset, run_store = _setup(tmp_path, monkeypatch)
    run = run_store.create(AtlasRunRequest(dataset_id=dataset.dataset_id, objective="Test correlation significance"), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    waiting = run_store.get(run.run_id)
    datasets.add_revision(dataset.dataset_id, pd.DataFrame({"exposure": [1, 2, 3], "outcome": [1, 4, 9]}), "d" * 64)
    with pytest.raises(HTTPException) as error:
        atlas_runtime.answer_stat_clarification(run.run_id, waiting.clarifications[0].question_id,
            AtlasStatAnalysis(test=StatTestKind.PEARSON, col_a="exposure", col_b="outcome", design="linear_association"))
    assert error.value.status_code == 409
    assert run_store.get(run.run_id).clarifications[0].state == "open"


def test_waiting_run_cancels_without_losing_completed_profile(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _url, _datasets, dataset, run_store = _setup(tmp_path, monkeypatch)
    run = run_store.create(AtlasRunRequest(dataset_id=dataset.dataset_id, objective="Test correlation significance"), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    run_store.request_cancel(run.run_id)
    atlas_runtime._cancel_run(run.run_id)
    cancelled = run_store.get(run.run_id)
    assert cancelled.plan.state.value == "cancelled"
    assert next(step for step in cancelled.plan.steps if step.kind.value == "statistical_analysis").state.value == "cancelled"
    assert any(item.kind == "overview_profile" for item in cancelled.evidence)


def test_disabled_stat_blocks_dependent_audit_without_dispatch(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _url, _datasets, dataset, run_store = _setup(tmp_path, monkeypatch)
    monkeypatch.setenv("PRISM_ATLAS_DISABLED_TOOLS", "stats.declared_test")
    run = run_store.create(AtlasRunRequest(
        dataset_id=dataset.dataset_id, objective="Test correlation significance",
        stat_analysis=AtlasStatAnalysis(test=StatTestKind.PEARSON, col_a="exposure", col_b="outcome", design="linear_association"),
    ), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)
    assert completed.plan.state.value == "completed"
    assert next(step for step in completed.plan.steps if step.step_id == "statistical_analysis").state.value == "blocked"
    audit = next(step for step in completed.plan.steps if step.step_id == "audit")
    assert audit.state.value == "blocked"
    assert "statistical_analysis" in (audit.error or "")
    assert not any(event.payload.get("output", {}).get("method") == "pearson" for event in completed.events)


def test_plan_cycle_fails_before_dispatch(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _url, _datasets, dataset, run_store = _setup(tmp_path, monkeypatch)
    run = run_store.create(AtlasRunRequest(dataset_id=dataset.dataset_id, objective="Profile this dataset"), AtlasModelProviderName.DETERMINISTIC)
    steps = [step.model_copy(update={"dependencies": ["audit"]}) if step.step_id == "profile" else step
             for step in run.plan.steps]
    with pytest.raises(HTTPException) as error:
        atlas_runtime.DynamicAtlasPlanner.validate(run.plan.model_copy(update={"steps": steps}))
    assert error.value.status_code == 422


def test_descriptive_comparison_with_causal_request_refuses_causality_without_stat_wait(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _url, _datasets, dataset, run_store = _setup(tmp_path, monkeypatch)
    run = run_store.create(AtlasRunRequest(
        dataset_id=dataset.dataset_id, objective="Use SQL to compare groups and test causal attribution.",
    ), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)
    assert completed.plan.state.value == "completed"
    assert completed.clarifications == []
    assert "Causal attribution was not performed" in (completed.answer or "")
    assert any(step.tool_name == "sql_lab.review_required" and step.state.value == "blocked" for step in completed.plan.steps)


def test_stat_worker_timeout_and_active_cancel_do_not_register_evidence(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _url, _datasets, dataset, _run_store = _setup(tmp_path, monkeypatch)
    registered = []
    monkeypatch.setattr(stats, "register_statistical_test", lambda *_: registered.append("registered"))
    analysis = AtlasStatAnalysis(test=StatTestKind.PEARSON, col_a="exposure", col_b="outcome", design="linear_association")
    monkeypatch.setattr(atlas_stat_adapter, "TIMEOUT_SECONDS", 0.001)
    with pytest.raises(TimeoutError, match="12 second limit"):
        atlas_stat_adapter.execute_declared_test(dataset.dataset_id, analysis, lambda: False)
    monkeypatch.setattr(atlas_stat_adapter, "TIMEOUT_SECONDS", 12.0)
    calls = 0

    def cancel_after_dispatch() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    with pytest.raises(RuntimeError, match="cancelled or disabled while active"):
        atlas_stat_adapter.execute_declared_test(dataset.dataset_id, analysis, cancel_after_dispatch)
    assert registered == []
