from __future__ import annotations

from datetime import datetime, timezone

from prism_api.atlas_foundry_dataset import (
    AtlasTrainingDatasetBuilder,
    DurableAtlasTrainingDatasetStore,
    eligibility_reason,
    example_from_run,
    export_jsonl,
    manifest_content_hash,
)
from prism_api.durable_atlas_store import DurableAtlasRunStore
from prism_api_contracts import (
    AtlasCouncilConclusion,
    AtlasEvidenceReference,
    AtlasModelProviderName,
    AtlasPlanState,
    AtlasPlanStep,
    AtlasRunRequest,
    AtlasSpecialistId,
    AtlasStepKind,
    AtlasStepState,
    AtlasStructuredPlan,
    AtlasTrainingSplit,
)


def _plan(dataset_id: str, objective: str, *, plan_id: str, tool_args: dict[str, object] | None = None) -> AtlasStructuredPlan:
    return AtlasStructuredPlan(
        plan_id=plan_id,
        objective=objective,
        dataset_id=dataset_id,
        provider=AtlasModelProviderName.DETERMINISTIC,
        created_at=datetime.now(timezone.utc),
        steps=[
            AtlasPlanStep(
                step_id="profile",
                title="Profile the dataset",
                kind=AtlasStepKind.PROFILE_DATASET,
                specialist=AtlasSpecialistId.SCOUT,
                tool_name="overview.profile",
                tool_args=tool_args or {},
                state=AtlasStepState.COMPLETED,
            )
        ],
    )


def _completed_run(store: DurableAtlasRunStore, *, dataset_id: str, objective: str, plan_id: str, tool_args: dict[str, object] | None = None):  # type: ignore[no-untyped-def]
    plan = _plan(dataset_id, objective, plan_id=plan_id, tool_args=tool_args)
    run = store.create(
        AtlasRunRequest(dataset_id=dataset_id, objective=objective), AtlasModelProviderName.DETERMINISTIC, plan
    )
    completed = run.model_copy(
        update={
            "plan": plan.model_copy(update={"state": AtlasPlanState.COMPLETED}),
            "answer": f"Grounded assessment of {dataset_id}.",
            "uncertainty": "This is a profile, not a causal claim.",
            "evidence": [
                AtlasEvidenceReference(
                    evidence_id="ev_1", kind="dataset_revision", summary="Active revision.", dataset_id=dataset_id, dataset_revision=1, source_fingerprint="f" * 16
                )
            ],
            "council": [
                AtlasCouncilConclusion(
                    specialist=AtlasSpecialistId.SCOUT, conclusion="Data looks clean.", confidence="high", objections=["Do not infer causality."]
                )
            ],
        }
    )
    return store.save(completed)


def _store(tmp_path) -> DurableAtlasRunStore:  # type: ignore[no-untyped-def]
    return DurableAtlasRunStore(f"sqlite:///{(tmp_path / 'atlas.sqlite').as_posix()}")


def test_eligibility_rejects_incomplete_unevidenced_or_answerless_runs(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    plan = _plan("ds_1", "Understand this dataset.", plan_id="plan_a")
    draft_run = store.create(AtlasRunRequest(dataset_id="ds_1", objective="Understand this dataset."), AtlasModelProviderName.DETERMINISTIC, plan)
    assert eligibility_reason(draft_run) == "run state is draft, not completed"

    completed = _completed_run(store, dataset_id="ds_1", objective="Understand this dataset.", plan_id="plan_b")
    assert eligibility_reason(completed) is None

    no_evidence = completed.model_copy(update={"evidence": []})
    assert eligibility_reason(no_evidence) == "run has no evidence references"

    no_answer = completed.model_copy(update={"answer": None})
    assert eligibility_reason(no_answer) == "run has no final grounded answer"


def test_example_redacts_secrets_and_never_carries_raw_dataset_rows(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    run = _completed_run(
        store,
        dataset_id="ds_secret",
        objective="Check this dataset.",
        plan_id="plan_secret",
        tool_args={"api_key": "sk-should-never-survive-1234567890", "column": "revenue"},
    )
    example = example_from_run(run)
    assert example.plan_steps[0].tool_args["api_key"] == "[REDACTED]"
    assert example.plan_steps[0].tool_args["column"] == "revenue"
    assert example.dataset_metadata == {"dataset_id": "ds_secret"}


def test_build_is_deterministic_across_runs_over_unchanged_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    _completed_run(store, dataset_id="ds_1", objective="Question one.", plan_id="plan_1")
    _completed_run(store, dataset_id="ds_2", objective="Question two.", plan_id="plan_2")
    builder = AtlasTrainingDatasetBuilder(store)
    examples_a, excluded_a = builder.build()
    examples_b, excluded_b = builder.build()
    assert [item.example_id for item in examples_a] == [item.example_id for item in examples_b]
    assert manifest_content_hash(examples_a) == manifest_content_hash(examples_b)
    assert len(examples_a) == 2 and excluded_a == excluded_b == []


def test_duplicate_content_is_excluded_not_double_counted(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    _completed_run(store, dataset_id="ds_dup", objective="Same question.", plan_id="plan_dup_a")
    _completed_run(store, dataset_id="ds_dup", objective="Same question.", plan_id="plan_dup_b")
    builder = AtlasTrainingDatasetBuilder(store)
    examples, excluded = builder.build()
    assert len(examples) == 1
    assert any("duplicate" in item.reason for item in excluded)


def test_split_assignment_never_straddles_the_same_dataset(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    for index in range(6):
        _completed_run(store, dataset_id="ds_family", objective=f"Question {index}.", plan_id=f"plan_family_{index}")
    builder = AtlasTrainingDatasetBuilder(store)
    examples, _ = builder.build()
    splits = {example.split for example in examples}
    assert len(splits) == 1  # every example from ds_family lands in the same split


def test_export_jsonl_is_sorted_and_matches_manifest_hash(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = _store(tmp_path)
    _completed_run(store, dataset_id="ds_1", objective="Question one.", plan_id="plan_1")
    _completed_run(store, dataset_id="ds_2", objective="Question two.", plan_id="plan_2")
    examples, _ = AtlasTrainingDatasetBuilder(store).build()
    out_path = tmp_path / "export.jsonl"
    content_hash = export_jsonl(examples, out_path)
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == len(examples)
    assert content_hash == manifest_content_hash(examples)
    ids_in_file = [line.split('"example_id":"')[1].split('"')[0] for line in lines]
    assert ids_in_file == sorted(ids_in_file)


def test_durable_dataset_store_is_idempotent_and_supports_preview_and_exclusions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    run_store = _store(tmp_path)
    _completed_run(run_store, dataset_id="ds_1", objective="Question one.", plan_id="plan_1")
    failed_plan = _plan("ds_2", "Question two.", plan_id="plan_fail")
    failed_run = run_store.create(AtlasRunRequest(dataset_id="ds_2", objective="Question two."), AtlasModelProviderName.DETERMINISTIC, failed_plan)
    run_store.save(failed_run.model_copy(update={"plan": failed_plan.model_copy(update={"state": AtlasPlanState.FAILED})}))

    examples, excluded = AtlasTrainingDatasetBuilder(run_store).build()
    dataset_store = DurableAtlasTrainingDatasetStore(f"sqlite:///{(tmp_path / 'training.sqlite').as_posix()}")
    manifest_a = dataset_store.save(examples, excluded)
    manifest_b = dataset_store.save(examples, excluded)  # rebuild over identical history
    assert manifest_a.version_id == manifest_b.version_id
    assert manifest_a.train_count + manifest_a.validation_count + manifest_a.test_count == len(examples)
    assert manifest_a.excluded_count == len(excluded)

    preview = dataset_store.preview(manifest_a.version_id, limit=10)
    assert [item.example_id for item in preview] == [item.example_id for item in examples]

    train_only = dataset_store.preview(manifest_a.version_id, split=AtlasTrainingSplit.TRAIN, limit=10)
    assert all(item.split is AtlasTrainingSplit.TRAIN for item in train_only)

    stored_exclusions = dataset_store.exclusions(manifest_a.version_id)
    assert any(item.run_id == failed_run.run_id for item in stored_exclusions)
    assert dataset_store.list_versions()[0].version_id == manifest_a.version_id
