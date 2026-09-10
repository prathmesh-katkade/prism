"""Server-owned Model Arena views and non-mutating off-the-shelf baselines.

Arena evaluation intentionally remains separate from the Foundry candidate
path.  An off-the-shelf model may be measured when its local Ollama name and
digest are probed by the server, but it cannot acquire candidate trust,
promotion eligibility, or a production pointer merely by appearing here.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasBenchCategory,
    AtlasBenchSuiteRun,
    AtlasModelArenaEntry,
    AtlasModelArenaSummary,
    AtlasModelProviderName,
)

from .atlas_bench_corpus import CORPUS_VERSION, all_tasks, corpus_hash
from .atlas_bench_live import AtlasBenchSubjectUnavailable, AtlasProviderBenchSubject
from .atlas_bench_runner import run_suite
from .atlas_bench_store import DurableAtlasBenchStore
from .atlas_promotion import CRITICAL_CATEGORIES, DurableAtlasPromotionStore

router = APIRouter(prefix="/api/v1/atlas/arena", tags=["atlas-model-arena"])
_bench_store = DurableAtlasBenchStore()
_promotion_store = DurableAtlasPromotionStore()


def _elapsed_ms(started_at: datetime, completed_at: datetime) -> int:
    started = started_at.astimezone(timezone.utc)
    completed = completed_at.astimezone(timezone.utc)
    return max(0, round((completed - started).total_seconds() * 1000))


def _latest_production_run() -> AtlasBenchSuiteRun:
    production = _promotion_store.current_production()
    if production is None:
        raise ValueError("Model Arena requires a durable production pointer.")
    candidates = [
        run for run in _bench_store.list_runs_for_corpus(CORPUS_VERSION, corpus_hash())
        if run.subject_kind == "production" and run.candidate_id == production.candidate_id
    ]
    if not candidates:
        raise ValueError("No immutable production AtlasBench run exists for the current frozen corpus.")
    return candidates[0]


def build_arena_summary() -> AtlasModelArenaSummary:
    """Rank only same-corpus, digest-bound evidence; never synthesize metrics."""
    production = _latest_production_run()
    if not production.runtime_model or not production.runtime_model_digest:
        raise ValueError("Current production benchmark lacks an exact runtime identity.")
    production_by_category = {score.category: score for score in production.category_scores}
    entries: list[AtlasModelArenaEntry] = []
    for run in _bench_store.list_runs_for_corpus(production.corpus_version, production.corpus_hash):
        if run.subject_kind not in {"production", "candidate", "arena"}:
            continue
        if not run.runtime_model or not run.runtime_model_digest:
            continue
        regressions: list[AtlasBenchCategory] = []
        for score in run.category_scores:
            baseline = production_by_category.get(score.category)
            if baseline is None or score.category not in CRITICAL_CATEGORIES:
                continue
            if score.total and baseline.total and score.passed / score.total < baseline.passed / baseline.total:
                regressions.append(score.category)
        entries.append(
            AtlasModelArenaEntry(
                run_id=run.run_id,
                subject_kind=run.subject_kind,
                runtime_model=run.runtime_model,
                runtime_model_digest=run.runtime_model_digest,
                total_passed=run.total_passed,
                total_tasks=run.total_tasks,
                production_delta=run.total_passed - production.total_passed,
                category_scores=run.category_scores,
                critical_regression_categories=sorted(regressions, key=lambda item: item.value),
                elapsed_ms=_elapsed_ms(run.started_at, run.completed_at),
                candidate_id=run.candidate_id,
                candidate_fingerprint=run.candidate_fingerprint,
            )
        )
    entries.sort(key=lambda entry: (-entry.total_passed, entry.elapsed_ms, entry.run_id))
    return AtlasModelArenaSummary(
        corpus_version=production.corpus_version,
        corpus_hash=production.corpus_hash,
        production_run_id=production.run_id,
        production_runtime_model=production.runtime_model,
        production_runtime_model_digest=production.runtime_model_digest,
        entries=entries,
    )


@router.post("/runs", response_model=AtlasBenchSuiteRun, status_code=status.HTTP_201_CREATED)
def run_arena_baseline(runtime_model: str = Query(min_length=1, max_length=300)) -> AtlasBenchSuiteRun:
    """Benchmark one locally installed Ollama model without mutating production.

    The caller supplies only a model *name*.  The server probes the local
    daemon, captures the resolved digest, and passes only prompt and choices
    into the frozen harness.  This cannot create a Foundry candidate or
    promotion decision.
    """
    try:
        subject = AtlasProviderBenchSubject(AtlasModelProviderName.OLLAMA, model_override=runtime_model)
        suite, results = run_suite(subject, all_tasks(), corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash())
        return _bench_store.save(
            suite.model_copy(
                update={
                    "subject_kind": "arena",
                    "runtime_model": subject.model,
                    "runtime_model_digest": subject.model_digest,
                    "provider": "ollama",
                    "evaluation_policy_id": subject.evaluation_policy_id(
                        corpus_version=CORPUS_VERSION, corpus_hash_value=corpus_hash()
                    ),
                }
            ),
            results,
        )
    except AtlasBenchSubjectUnavailable as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error


@router.get("", response_model=AtlasModelArenaSummary)
def model_arena() -> AtlasModelArenaSummary:
    try:
        return build_arena_summary()
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(error)) from error
