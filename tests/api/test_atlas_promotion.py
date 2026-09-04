from __future__ import annotations

from prism_api.atlas_adapter_foundation import (
    report_adapter_capability,
    report_all_adapter_capabilities,
)
from prism_api.atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from prism_api.atlas_bench_runner import (
    FirstChoiceSubject,
    PerfectReferenceSubject,
    WorstReferenceSubject,
    run_suite,
)
from prism_api.atlas_promotion import (
    CRITICAL_CATEGORIES,
    DurableAtlasPromotionStore,
    decide_promotion,
    shadow_compare,
)
from prism_api_contracts import AtlasAdapterId, AtlasPromotionVerdict


def _runs():  # type: ignore[no-untyped-def]
    tasks = all_tasks()
    production_run, _ = run_suite(WorstReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    return tasks, production_run


def test_a_strictly_better_candidate_with_no_critical_regression_is_promote_eligible() -> None:
    tasks, production_run = _runs()
    candidate_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.PROMOTE_ELIGIBLE
    assert decision.critical_regressions == []
    assert decision.overall_candidate_pass_rate > decision.overall_production_pass_rate


def test_identical_performance_is_hold() -> None:
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    candidate_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.HOLD


def test_a_worse_candidate_that_regresses_a_critical_category_is_rejected_even_with_overall_improvement_impossible() -> None:
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    candidate_run, _ = run_suite(WorstReferenceSubject(tasks, subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.REJECT
    assert decision.critical_regressions
    assert all(item.category in CRITICAL_CATEGORIES for item in decision.critical_regressions)


def test_critical_regression_blocks_promotion_even_if_aggregate_score_would_otherwise_pass() -> None:
    # A candidate that aces every non-critical category but regresses even one
    # critical category must still be rejected -- "cannot win on aggregate
    # score while catastrophically regressing a critical category."
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())

    class _MostlyPerfectButFailsOneCritical:
        subject_id = "candidate"

        def __init__(self, tasks):  # type: ignore[no-untyped-def]
            self._correct = {task.task_id: task.correct_choice for task in tasks}

        def answer(self, prompt, choices):  # type: ignore[no-untyped-def]
            for task in tasks:
                if task.prompt == prompt:
                    if task.task_id == "sql_001":  # SQL is a critical category
                        return next(i for i in range(len(choices)) if i != task.correct_choice)
                    return task.correct_choice
            return 0

    candidate_run, _ = run_suite(_MostlyPerfectButFailsOneCritical(tasks), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is AtlasPromotionVerdict.REJECT
    assert decision.overall_candidate_pass_rate < 1.0  # sanity: it really did miss one


def test_shadow_compare_runs_both_subjects_and_returns_a_decision() -> None:
    tasks = all_tasks()
    production_run, candidate_run, decision = shadow_compare(
        WorstReferenceSubject(tasks, subject_id="prod"),
        PerfectReferenceSubject(tasks, subject_id="candidate"),
        tasks,
        corpus_version=CORPUS_VERSION,
        corpus_hash_value=corpus_hash(),
    )
    assert production_run.subject_id == "prod"
    assert candidate_run.subject_id == "candidate"
    assert decision.verdict is AtlasPromotionVerdict.PROMOTE_ELIGIBLE


def test_promotion_store_refuses_to_promote_a_non_eligible_decision(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tasks = all_tasks()
    production_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="prod"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    candidate_run, _ = run_suite(FirstChoiceSubject(subject_id="candidate"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision = decide_promotion("candidate", production_run, candidate_run)
    assert decision.verdict is not AtlasPromotionVerdict.PROMOTE_ELIGIBLE

    store = DurableAtlasPromotionStore(f"sqlite:///{(tmp_path / 'promotion.sqlite').as_posix()}")
    try:
        store.promote(decision, reason="should not be allowed")
    except ValueError as error:
        assert "not promote_eligible" in str(error)
    else:
        raise AssertionError("promoting a non-eligible decision should have raised")
    assert store.current_production() is None


def test_promotion_is_atomic_auditable_and_never_overwrites_history(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tasks, production_run = _runs()
    store = DurableAtlasPromotionStore(f"sqlite:///{(tmp_path / 'promotion.sqlite').as_posix()}")

    candidate_a_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate_a"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision_a = decide_promotion("candidate_a", production_run, candidate_a_run)
    pointer_a = store.promote(decision_a, reason="first promotion")
    assert pointer_a.candidate_id == "candidate_a"
    assert pointer_a.previous_candidate_id is None

    candidate_b_run, _ = run_suite(PerfectReferenceSubject(tasks, subject_id="candidate_b"), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    decision_b = decide_promotion("candidate_b", candidate_a_run, candidate_b_run)
    # candidate_b ties candidate_a (both perfect) -> HOLD, not eligible; use a
    # synthetic eligible decision to exercise a second real promotion instead.
    import datetime as _dt

    from prism_api_contracts import AtlasPromotionDecision

    forced_eligible = AtlasPromotionDecision(
        decision_id=decision_b.decision_id,
        candidate_id="candidate_b",
        production_run_id=decision_b.production_run_id,
        candidate_run_id=decision_b.candidate_run_id,
        verdict=AtlasPromotionVerdict.PROMOTE_ELIGIBLE,
        overall_production_pass_rate=decision_b.overall_production_pass_rate,
        overall_candidate_pass_rate=decision_b.overall_candidate_pass_rate,
        critical_regressions=[],
        decided_at=_dt.datetime.now(_dt.timezone.utc),
    )
    pointer_b = store.promote(forced_eligible, reason="second promotion")
    assert pointer_b.candidate_id == "candidate_b"
    assert pointer_b.previous_candidate_id == "candidate_a"

    history = store.history()
    assert [item.candidate_id for item in history] == ["candidate_b", "candidate_a"]
    assert store.current_production().candidate_id == "candidate_b"  # type: ignore[union-attr]

    rolled_back = store.rollback(reason="candidate_b regressed in production")
    assert rolled_back.candidate_id == "candidate_a"
    assert rolled_back.is_rollback is True
    assert store.current_production().candidate_id == "candidate_a"  # type: ignore[union-attr]
    # Rollback is a new event, not a deletion: all three events remain.
    assert len(store.history()) == 3


def test_rollback_without_prior_production_raises(tmp_path) -> None:  # type: ignore[no-untyped-def]
    store = DurableAtlasPromotionStore(f"sqlite:///{(tmp_path / 'promotion.sqlite').as_posix()}")
    try:
        store.rollback(reason="nothing to roll back to")
    except ValueError as error:
        assert "No prior production candidate" in str(error)
    else:
        raise AssertionError("rollback with no history should have raised")


def test_adapter_capabilities_are_honestly_all_unsupported_right_now() -> None:
    for adapter in AtlasAdapterId:
        capability = report_adapter_capability(adapter)
        assert capability.can_load is False
        assert capability.can_unload is False
        assert capability.can_hot_swap is False
        assert "falls back to its core" in capability.detail
    assert len(report_all_adapter_capabilities()) == len(list(AtlasAdapterId))
