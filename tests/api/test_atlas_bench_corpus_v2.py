from __future__ import annotations

import re

from prism_api.atlas_bench_corpus import all_tasks as all_v1_tasks
from prism_api.atlas_bench_corpus_v2 import CORPUS_V2_VERSION, all_tasks, corpus_v2_hash
from prism_api.atlas_bench_runner import (
    FirstChoiceSubject,
    PerfectReferenceSubject,
    WorstReferenceSubject,
    run_suite,
)
from prism_api_contracts import AtlasBenchCategory

_WORDS = re.compile(r"[a-z0-9]+")


def _normalized_tokens(text: str) -> set[str]:
    return set(_WORDS.findall(text.lower()))


def test_v2_corpus_has_unique_ids_and_valid_answers() -> None:
    tasks = all_tasks()
    assert len(tasks) >= 45, "AtlasBench V2 waves 1+2 should be a real batch, not a handful of placeholders"
    ids = [task.task_id for task in tasks]
    assert len(set(ids)) == len(ids), "every V2 task_id must be unique"
    assert all(task_id.startswith("v2_") for task_id in ids), "V2 task ids must be clearly distinguishable from v1"
    for task in tasks:
        assert 0 <= task.correct_choice < len(task.choices)
        assert len(task.choices) >= 2


def test_v2_corpus_covers_every_required_category() -> None:
    categories_present = {task.category for task in all_tasks()}
    assert categories_present == set(AtlasBenchCategory), "every AtlasBenchCategory must appear at least once in V2"


def test_v2_corpus_hash_is_deterministic() -> None:
    assert corpus_v2_hash() == corpus_v2_hash()


def test_v2_corpus_version_is_distinct_from_v1() -> None:
    from prism_api.atlas_bench_corpus import CORPUS_VERSION

    assert CORPUS_V2_VERSION != CORPUS_VERSION


def test_v2_perfect_subject_scores_100_percent() -> None:
    tasks = all_tasks()
    subject = PerfectReferenceSubject(tasks, subject_id="v2_reference_perfect")
    suite_run, results = run_suite(subject, tasks, corpus_version=CORPUS_V2_VERSION, corpus_hash_value=corpus_v2_hash())
    assert suite_run.total_passed == suite_run.total_tasks == len(tasks)
    assert all(result.correct for result in results)
    assert all(score.passed == score.total for score in suite_run.category_scores)


def test_v2_worst_subject_scores_zero() -> None:
    tasks = all_tasks()
    subject = WorstReferenceSubject(tasks, subject_id="v2_reference_worst")
    suite_run, _results = run_suite(subject, tasks, corpus_version=CORPUS_V2_VERSION, corpus_hash_value=corpus_v2_hash())
    assert suite_run.total_passed == 0


def test_v2_first_choice_baseline_is_not_perfect() -> None:
    # Same labeling-bias regression guard used for v1: if always picking
    # option 0 were a perfect score, the corpus would be trivially gameable.
    tasks = all_tasks()
    subject = FirstChoiceSubject(subject_id="v2_baseline_first_choice")
    suite_run, _results = run_suite(subject, tasks, corpus_version=CORPUS_V2_VERSION, corpus_hash_value=corpus_v2_hash())
    assert suite_run.total_passed < suite_run.total_tasks


def test_v2_holdout_is_not_a_near_duplicate_of_v1() -> None:
    """AtlasBench V2 must never become training data; the first, structural
    check for that is that it is not simply v1 copied or lightly reworded.
    A near-duplicate is flagged by high normalized-token overlap between a
    V2 prompt and any V1 prompt."""
    v1_prompts = [(task.task_id, _normalized_tokens(task.prompt)) for task in all_v1_tasks()]
    near_duplicates: list[tuple[str, str, float]] = []
    for v2_task in all_tasks():
        v2_tokens = _normalized_tokens(v2_task.prompt)
        for v1_id, v1_tokens in v1_prompts:
            if not v2_tokens or not v1_tokens:
                continue
            overlap = len(v2_tokens & v1_tokens) / len(v2_tokens | v1_tokens)
            if overlap >= 0.6:
                near_duplicates.append((v2_task.task_id, v1_id, overlap))
    assert not near_duplicates, f"V2 tasks too textually similar to v1 (leakage risk): {near_duplicates}"


def test_v2_task_ids_do_not_collide_with_v1() -> None:
    v1_ids = {task.task_id for task in all_v1_tasks()}
    v2_ids = {task.task_id for task in all_tasks()}
    assert v1_ids.isdisjoint(v2_ids)


def test_v2_corpus_has_no_internal_near_duplicates() -> None:
    """Wave 2 was authored from the same predeclared taxonomy as wave 1, not
    by rewording wave 1 (or any other V2 task) for volume. Guard that
    structurally rather than just by policy."""
    tasks = all_tasks()
    tokenized = [(task.task_id, _normalized_tokens(task.prompt)) for task in tasks]
    near_duplicates: list[tuple[str, str, float]] = []
    for i, (task_id_a, tokens_a) in enumerate(tokenized):
        for task_id_b, tokens_b in tokenized[i + 1 :]:
            if not tokens_a or not tokens_b:
                continue
            overlap = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
            if overlap >= 0.6:
                near_duplicates.append((task_id_a, task_id_b, overlap))
    assert not near_duplicates, f"V2 tasks too textually similar to each other: {near_duplicates}"
