from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from prism_api.atlas_runtime import AtlasRunStore, DynamicAtlasPlanner, cortex_graph
from prism_api.durable_atlas_store import DurableAtlasRunStore, redact_atlas_payload
from prism_api_contracts import (
    AtlasModelProviderName,
    AtlasRunEventType,
    AtlasRunRequest,
    AtlasStepKind,
    AtlasStepState,
)


def _store(tmp_path) -> AtlasRunStore:  # type: ignore[no-untyped-def]
    return AtlasRunStore(
        DurableAtlasRunStore(f"sqlite:///{(tmp_path / 'atlas.sqlite').as_posix()}")
    )


def test_atlas_run_and_journal_survive_an_independent_store_restart(tmp_path) -> None:  # type: ignore[no-untyped-def]
    writer = _store(tmp_path)
    run = writer.create(
        AtlasRunRequest(dataset_id="ds_1", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    writer.append_event(
        run.run_id,
        AtlasRunEventType.STEP_STARTED,
        step_id="profile",
        payload={"token": "sk-never-persist-this"},
    )
    recovered = _store(tmp_path).get(run.run_id)
    assert recovered.run_id == run.run_id
    assert [event.sequence for event in recovered.events] == [1, 2, 3]
    assert recovered.events[-1].payload["token"] == "[REDACTED]"


def test_atlas_event_sequence_is_unique_and_ordered_under_concurrent_appends(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    run = store.create(
        AtlasRunRequest(dataset_id="ds_1", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(
            workers.map(
                lambda _: store.append_event(run.run_id, AtlasRunEventType.STEP_STARTED), range(8)
            )
        )
    recovered = _store(tmp_path).get(run.run_id)
    assert [event.sequence for event in recovered.events] == list(range(1, 11))


def test_cancellation_is_durable_and_cortex_reads_the_same_durable_run(
    tmp_path, monkeypatch
) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    run = store.create(
        AtlasRunRequest(dataset_id="ds_1", objective="Profile this dataset."),
        AtlasModelProviderName.DETERMINISTIC,
    )
    store.request_cancel(run.run_id)
    assert _store(tmp_path).get(run.run_id).cancellation_requested is True
    import prism_api.atlas_runtime as runtime

    monkeypatch.setattr(runtime, "runs", _store(tmp_path))
    graph = cortex_graph(run.run_id)
    assert any(node.source_id == run.run_id for node in graph.nodes)
    assert any(node.source_id == "ds_1" for node in graph.nodes)


def test_dynamic_planner_only_selects_declared_tools_and_blocks_unqualified_modeling() -> None:
    plan = DynamicAtlasPlanner().create(
        AtlasRunRequest(
            dataset_id="ds_1", objective="Train a classification model and chart the outcome."
        ),
        AtlasModelProviderName.DETERMINISTIC,
    )
    assert all(step.tool_name in runtime_tools() for step in plan.steps)
    model = next(step for step in plan.steps if step.kind is AtlasStepKind.MACHINE_LEARNING)
    assert (
        model.tool_name == "ml.declared_target_required" and model.state is AtlasStepState.PENDING
    )


def runtime_tools() -> set[str]:
    from prism_api.atlas_runtime import TOOL_REGISTRY

    return set(TOOL_REGISTRY)


def test_redaction_never_retains_nested_secret_shaped_values() -> None:
    assert redact_atlas_payload({"details": {"authorization": "Bearer example-secret-value"}}) == {
        "details": {"authorization": "[REDACTED]"}
    }
