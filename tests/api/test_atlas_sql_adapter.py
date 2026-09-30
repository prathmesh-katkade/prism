from __future__ import annotations

import hashlib

import pandas as pd
import pytest
from prism_api import atlas_runtime, atlas_sql_adapter, overview, sql_lab
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api_contracts import AtlasModelProviderName, AtlasRunRequest, AtlasSqlAnalysis


def test_typed_aggregate_is_executed_and_recorded_with_exact_query(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    frame = pd.DataFrame({"region": ["west", "east", "west"], "revenue": [10, 7, 5]})
    datasets = overview.DatasetStore()
    dataset = datasets.put(frame, "sales.csv", hashlib.sha256(b"sales fixture").hexdigest())
    monkeypatch.setattr(overview, "store", datasets)
    monkeypatch.setattr(sql_lab, "overview_store", datasets)
    monkeypatch.setattr(atlas_sql_adapter, "dataset_store", datasets)
    monkeypatch.setattr(sql_lab, "store", sql_lab.SqlLabStore(tmp_path / "sql.sqlite"))
    monkeypatch.setattr(sql_lab, "register_query_result", lambda *_: None)
    run_store = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(f"sqlite:///{(tmp_path / 'atlas.sqlite').as_posix()}"))
    monkeypatch.setattr(atlas_runtime, "runs", run_store)

    request = AtlasRunRequest(
        dataset_id=dataset.dataset_id, objective="Sum revenue by region using SQL",
        sql_analysis=AtlasSqlAnalysis(aggregate="sum", measure="revenue", group_by="region"),
    )
    run = run_store.create(request, AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)
    output = next(event.payload["output"] for event in completed.events if "output" in event.payload)
    assert completed.plan.state.value == "completed"
    assert output["rows"] == [
        {"group_value": "east", "result_value": 7.0},
        {"group_value": "west", "result_value": 15.0},
    ]
    assert output["sql"] == 'SELECT "region" AS group_value, SUM("revenue") AS result_value FROM "data" GROUP BY "region" ORDER BY "region" LIMIT 100'
    assert output["dataset_revision"] == 0
    assert output["sql_run_id"] in completed.answer
    assert any(item.evidence_id == f"sql:{output['sql_run_id']}" for item in completed.evidence)
    query_message = next(message for message in completed.messages if message.specialist.value == "query")
    assert query_message.kind == "computed_observation"
    assert query_message.input_refs == [f"sql:{output['sql_run_id']}"]
    assert query_message.model_binding is None
    recovered = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(f"sqlite:///{(tmp_path / 'atlas.sqlite').as_posix()}"))
    assert any(event.payload.get("output") == output for event in recovered.get(run.run_id).events)


def test_typed_aggregate_rejects_unregistered_identifiers_and_incomplete_filters(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    datasets = overview.DatasetStore()
    dataset = datasets.put(pd.DataFrame({"amount": [1, 2]}), "safe.csv", "a" * 64)
    monkeypatch.setattr(atlas_sql_adapter, "dataset_store", datasets)
    with pytest.raises(ValueError, match="not in the active dataset schema"):
        atlas_sql_adapter.compile_query(dataset.dataset_id, AtlasSqlAnalysis(aggregate="sum", measure='amount; DROP TABLE data'))
    with pytest.raises(ValueError, match="both a filter column and a filter value"):
        atlas_sql_adapter.compile_query(dataset.dataset_id, AtlasSqlAnalysis(aggregate="count", filter_column="amount"))
    query = atlas_sql_adapter.compile_query(dataset.dataset_id, AtlasSqlAnalysis(
        aggregate="count", filter_column="amount", filter_value="1' OR 1=1 --",
    ))
    assert "OR 1=1" not in query.sql
    assert query.parameters == {"filter_value": "1' OR 1=1 --"}


def test_profile_only_policy_prevents_new_sql_dispatch_and_keeps_profile(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    datasets = overview.DatasetStore()
    dataset = datasets.put(pd.DataFrame({"region": ["a", "b"]}), "safe.csv", "b" * 64)
    monkeypatch.setattr(overview, "store", datasets)
    monkeypatch.setattr(sql_lab, "overview_store", datasets)
    monkeypatch.setattr(atlas_sql_adapter, "dataset_store", datasets)
    monkeypatch.setattr(sql_lab, "store", sql_lab.SqlLabStore(tmp_path / "sql.sqlite"))
    monkeypatch.setenv("PRISM_ATLAS_PROFILE_ONLY", "true")
    monkeypatch.setenv("PRISM_ATLAS_EXECUTION_POLICY_VERSION", "test-kill-v1")
    run_store = atlas_runtime.AtlasRunStore(DurableAtlasRunStore(f"sqlite:///{(tmp_path / 'atlas.sqlite').as_posix()}"))
    monkeypatch.setattr(atlas_runtime, "runs", run_store)
    run = run_store.create(AtlasRunRequest(
        dataset_id=dataset.dataset_id, objective="Count rows using SQL",
        sql_analysis=AtlasSqlAnalysis(aggregate="count"),
    ), AtlasModelProviderName.DETERMINISTIC)
    atlas_runtime.execute(run.run_id)
    completed = run_store.get(run.run_id)
    assert any(item.kind == "overview_profile" for item in completed.evidence)
    assert any(step.tool_name == "sql_lab.local_aggregate" and step.state.value == "blocked" for step in completed.plan.steps)
    assert sql_lab.store.history() == []
    assert any(event.payload.get("policy_version") == "test-kill-v1" for event in completed.events)
