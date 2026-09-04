from __future__ import annotations

from prism_api.atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from prism_api.atlas_bench_runner import (
    FirstChoiceSubject,
    PerfectReferenceSubject,
    WorstReferenceSubject,
    replay_hash,
    run_suite,
)
from prism_api.atlas_bench_store import DurableAtlasBenchStore
from prism_api_contracts import AtlasBenchCategory


def test_corpus_has_a_meaningful_task_count_across_every_required_category() -> None:
    tasks = all_tasks()
    assert len(tasks) >= 80, "AtlasBench should be a meaningful initial wave, not five toy prompts"
    ids = [task.task_id for task in tasks]
    assert len(set(ids)) == len(ids), "every task_id must be unique"
    categories_present = {task.category for task in tasks}
    assert categories_present == set(AtlasBenchCategory), "every required category must have at least one task"
    for task in tasks:
        assert 0 <= task.correct_choice < len(task.choices)
        assert len(task.choices) >= 2


def test_corpus_hash_is_deterministic() -> None:
    assert corpus_hash() == corpus_hash()


def test_perfect_subject_scores_100_percent() -> None:
    tasks = all_tasks()
    subject = PerfectReferenceSubject(tasks)
    suite_run, results = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    assert suite_run.total_passed == suite_run.total_tasks == len(tasks)
    assert all(result.correct for result in results)
    assert all(score.passed == score.total for score in suite_run.category_scores)


def test_worst_subject_scores_at_or_near_zero() -> None:
    tasks = all_tasks()
    subject = WorstReferenceSubject(tasks)
    suite_run, results = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    assert suite_run.total_passed == 0
    assert all(not result.correct for result in results)


def test_first_choice_baseline_is_not_perfect() -> None:
    # A real regression guard: if a trivial "always pick option 0" baseline
    # ever scores 100%, the corpus has a labeling bias worth investigating.
    tasks = all_tasks()
    subject = FirstChoiceSubject()
    suite_run, _ = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    assert suite_run.total_passed < suite_run.total_tasks


def test_suite_run_is_deterministic_across_identical_runs() -> None:
    tasks = all_tasks()
    subject = PerfectReferenceSubject(tasks)
    run_a, results_a = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    run_b, results_b = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    assert run_a.total_passed == run_b.total_passed
    assert replay_hash(results_a) == replay_hash(results_b)


def test_replay_hash_changes_if_a_single_answer_changes() -> None:
    tasks = all_tasks()
    perfect_hash = replay_hash(run_suite(PerfectReferenceSubject(tasks), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())[1])
    worst_hash = replay_hash(run_suite(WorstReferenceSubject(tasks), tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())[1])
    assert perfect_hash != worst_hash


def test_durable_store_persists_a_run_and_its_task_results_and_failed_tasks(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tasks = all_tasks()
    subject = WorstReferenceSubject(tasks)
    suite_run, results = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())

    store = DurableAtlasBenchStore(f"sqlite:///{(tmp_path / 'bench.sqlite').as_posix()}")
    store.save(suite_run, results)

    fetched = store.get_run(suite_run.run_id)
    assert fetched is not None
    assert fetched.total_tasks == suite_run.total_tasks
    assert fetched.total_passed == 0
    assert len(fetched.category_scores) == len(suite_run.category_scores)

    stored_results = store.task_results(suite_run.run_id)
    assert len(stored_results) == len(tasks)

    failed = store.failed_tasks(suite_run.run_id)
    assert len(failed) == len(tasks)  # WorstReferenceSubject fails everything

    listed = store.list_runs_for_subject(subject.subject_id)
    assert listed and listed[0].run_id == suite_run.run_id


def test_two_suite_runs_are_both_retained_never_overwritten(tmp_path) -> None:  # type: ignore[no-untyped-def]
    tasks = all_tasks()
    store = DurableAtlasBenchStore(f"sqlite:///{(tmp_path / 'bench.sqlite').as_posix()}")

    subject = PerfectReferenceSubject(tasks)
    run_1, results_1 = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    store.save(run_1, results_1)
    run_2, results_2 = run_suite(subject, tasks, corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
    store.save(run_2, results_2)

    assert run_1.run_id != run_2.run_id
    listed = store.list_runs_for_subject(subject.subject_id)
    assert {item.run_id for item in listed} == {run_1.run_id, run_2.run_id}
