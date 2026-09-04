"""10P: AtlasBench runner -- scores a subject against the frozen task corpus.

A "subject" is anything that can answer a multiple-choice
``AtlasBenchTask``: today, deterministic reference subjects used to prove the
harness itself is correct (see ``atlas_bench_runner_test``-style fixtures);
tomorrow, a thin adapter wrapping the production Atlas provider or a
Foundry candidate. The runner and scoring logic do not change size or shape
based on who's being tested -- Shadow Brain (10Q) runs both the current and
a candidate subject through this exact same path for a fair comparison.

The corpus itself (``atlas_bench_corpus``) is never imported by, exposed to,
or reachable from subject code: a subject receives only ``task.prompt`` and
``task.choices`` through ``AtlasBenchSubject.answer()``, never ``task`` in
full (which would include ``correct_choice``). That boundary -- not
obfuscation -- is what keeps a candidate from seeing its own answer key.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Protocol, Sequence

from prism_api_contracts import (
    AtlasBenchCategory,
    AtlasBenchCategoryScore,
    AtlasBenchSuiteRun,
    AtlasBenchTask,
    AtlasBenchTaskResult,
)


class AtlasBenchSubject(Protocol):
    """What AtlasBench needs from anything it evaluates."""

    subject_id: str

    def answer(self, prompt: str, choices: Sequence[str]) -> int:
        """Return the index into ``choices`` the subject selects."""
        ...


class _BaseSubject(ABC):
    def __init__(self, subject_id: str) -> None:
        self.subject_id = subject_id

    @abstractmethod
    def answer(self, prompt: str, choices: Sequence[str]) -> int: ...


class PerfectReferenceSubject(_BaseSubject):
    """Test-only: always answers correctly. Exists to prove the runner's
    scoring logic itself is correct, not to claim any real capability."""

    def __init__(self, corpus: Sequence[AtlasBenchTask], *, subject_id: str = "reference_perfect") -> None:
        super().__init__(subject_id)
        self._answers = {task.task_id: task.correct_choice for task in corpus}
        self._by_prompt = {task.prompt: task.correct_choice for task in corpus}

    def answer(self, prompt: str, choices: Sequence[str]) -> int:
        return self._by_prompt.get(prompt, 0)


class WorstReferenceSubject(_BaseSubject):
    """Test-only: always answers incorrectly when possible."""

    def __init__(self, corpus: Sequence[AtlasBenchTask], *, subject_id: str = "reference_worst") -> None:
        super().__init__(subject_id)
        self._by_prompt = {task.prompt: task.correct_choice for task in corpus}

    def answer(self, prompt: str, choices: Sequence[str]) -> int:
        correct = self._by_prompt.get(prompt, -1)
        for index in range(len(choices)):
            if index != correct:
                return index
        return 0


class FirstChoiceSubject(_BaseSubject):
    """Trivial baseline: always picks the first option. A useful sanity
    floor -- a real subject should clearly beat this."""

    def __init__(self, *, subject_id: str = "baseline_first_choice") -> None:
        super().__init__(subject_id)

    def answer(self, prompt: str, choices: Sequence[str]) -> int:
        return 0


def run_suite(
    subject: AtlasBenchSubject,
    tasks: Sequence[AtlasBenchTask],
    *,
    corpus_version: str,
    corpus_hash_value: str,
) -> tuple[AtlasBenchSuiteRun, list[AtlasBenchTaskResult]]:
    """Score ``subject`` against every task, in task_id order (deterministic).

    Returns the suite-level rollup and every individual task result --
    durable persistence and interpretation (pass/hold/reject) are the
    caller's concern; this function only measures.
    """
    started = datetime.now(timezone.utc)
    results: list[AtlasBenchTaskResult] = []
    for task in sorted(tasks, key=lambda item: item.task_id):
        now = datetime.now(timezone.utc)
        chosen = subject.answer(task.prompt, task.choices)
        correct = chosen == task.correct_choice
        results.append(
            AtlasBenchTaskResult(
                task_id=task.task_id,
                category=task.category,
                subject_id=subject.subject_id,
                chosen_choice=chosen if 0 <= chosen < len(task.choices) else None,
                correct=correct,
                raw_answer=task.choices[chosen] if 0 <= chosen < len(task.choices) else "",
                evaluated_at=now,
            )
        )
    completed = datetime.now(timezone.utc)

    by_category: dict[AtlasBenchCategory, list[AtlasBenchTaskResult]] = {}
    for result in results:
        by_category.setdefault(result.category, []).append(result)
    category_scores = [
        AtlasBenchCategoryScore(
            category=category,
            total=len(items),
            passed=sum(1 for item in items if item.correct),
        )
        for category, items in sorted(by_category.items(), key=lambda entry: entry[0].value)
    ]

    suite_run = AtlasBenchSuiteRun(
        run_id=f"benchrun_{uuid.uuid4().hex}",
        subject_id=subject.subject_id,
        corpus_version=corpus_version,
        corpus_hash=corpus_hash_value,
        total_tasks=len(results),
        total_passed=sum(1 for item in results if item.correct),
        category_scores=category_scores,
        started_at=started,
        completed_at=completed,
    )
    return suite_run, results


def replay_hash(results: Sequence[AtlasBenchTaskResult]) -> str:
    """Deterministic hash over a set of results -- lets a stored run be
    proven byte-identical to a fresh replay against the same subject and
    corpus, the tamper-resistance property AtlasBench needs."""
    canonical = json.dumps(
        [
            {"task_id": item.task_id, "chosen_choice": item.chosen_choice, "correct": item.correct}
            for item in sorted(results, key=lambda item: item.task_id)
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()
