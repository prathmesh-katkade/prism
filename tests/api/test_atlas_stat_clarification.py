from __future__ import annotations

import time

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
    monkeypatch.setattr(stats, "register_statistical_test", lambda *_: None)
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
