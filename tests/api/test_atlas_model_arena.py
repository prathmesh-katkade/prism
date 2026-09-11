from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from prism_api import atlas_model_arena
from prism_api_contracts import AtlasBenchCategory, AtlasBenchCategoryScore, AtlasBenchSuiteRun


def _run(
    run_id: str,
    *,
    subject_kind: str,
    score: int,
    runtime_model: str = "model:latest",
    digest: str = "digest",
) -> AtlasBenchSuiteRun:
    now = datetime.now(timezone.utc)
    scores = [
        AtlasBenchCategoryScore(category=AtlasBenchCategory.SQL, total=10, passed=7 if score == 72 else 2),
        AtlasBenchCategoryScore(category=AtlasBenchCategory.GENERAL, total=10, passed=10),
    ]
    return AtlasBenchSuiteRun(
        run_id=run_id,
        subject_id=f"subject_{run_id}",
        corpus_version="atlasbench-v1",
        corpus_hash="a" * 64,
        total_tasks=90,
        total_passed=score,
        category_scores=scores,
        started_at=now,
        completed_at=now + timedelta(milliseconds=125),
        subject_kind=subject_kind,  # type: ignore[arg-type]
        runtime_model=runtime_model,
        runtime_model_digest=digest,
        provider="ollama",
    )


def test_arena_only_compares_same_corpus_digest_bound_evidence(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    production = _run("production", subject_kind="production", score=72, runtime_model="prod:latest", digest="prod")
    candidate = _run("candidate", subject_kind="candidate", score=12, runtime_model="candidate:latest", digest="candidate")
    generic = _run("generic", subject_kind="generic", score=90, runtime_model="unbound:latest", digest="unbound")

    monkeypatch.setattr(atlas_model_arena, "CORPUS_VERSION", "atlasbench-v1")
    monkeypatch.setattr(atlas_model_arena, "corpus_hash", lambda: "a" * 64)
    monkeypatch.setattr(
        atlas_model_arena,
        "_promotion_store",
        SimpleNamespace(current_production=lambda: SimpleNamespace(candidate_id=None)),
    )
    monkeypatch.setattr(
        atlas_model_arena,
        "_bench_store",
        SimpleNamespace(list_runs_for_corpus=lambda *_args, **_kwargs: [candidate, generic, production]),
    )

    summary = atlas_model_arena.build_arena_summary()

    assert summary.production_run_id == "production"
    assert [entry.run_id for entry in summary.entries] == ["production", "candidate"]
    rejected = next(entry for entry in summary.entries if entry.run_id == "candidate")
    assert rejected.production_delta == -60
    assert rejected.critical_regression_categories == [AtlasBenchCategory.SQL]
    assert rejected.elapsed_ms == 125
