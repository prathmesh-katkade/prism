"""10P: durable, append-only AtlasBench run history.

A suite run and its task results are never mutated once recorded -- the same
immutable-history discipline Phase 8/9 established for AnalyticalObjects.
Re-running the suite produces a new ``run_id``, never an edit to an old one,
so promotion decisions (10Q) always have a full, replayable trail rather
than a single overwritten "latest score."
"""

from __future__ import annotations

import json
from typing import Optional

from prism_api_contracts import (
    AtlasBenchCategory,
    AtlasBenchCategoryScore,
    AtlasBenchSuiteRun,
    AtlasBenchTaskResult,
)
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    insert,
    inspect,
    select,
    text,
)
from sqlalchemy.engine import Engine

from .atlas_schema_utils import ensure_index
from .durable_registry import history_database_url

_metadata = MetaData()
_runs = Table(
    "prism_atlas_bench_runs",
    _metadata,
    Column("run_id", String(120), primary_key=True),
    Column("subject_id", String(120), nullable=False, index=True),
    Column("corpus_version", String(64), nullable=False),
    Column("corpus_hash", String(64), nullable=False, index=True),
    Column("total_tasks", Integer, nullable=False),
    Column("total_passed", Integer, nullable=False),
    Column("category_scores_payload", Text, nullable=False),
    Column("started_at", DateTime(timezone=True), nullable=False),
    Column("completed_at", DateTime(timezone=True), nullable=False, index=True),
    Column("subject_kind", String(16), nullable=False, server_default="generic"),
    Column("candidate_id", String(120), nullable=True, index=True),
    Column("candidate_fingerprint", String(64), nullable=True),
    Column("trust_verification_id", String(120), nullable=True),
    Column("runtime_model", String(300), nullable=True),
    Column("runtime_model_digest", String(200), nullable=True),
    Column("provider", String(32), nullable=True),
    Column("evaluation_policy_id", String(64), nullable=True),
)
_task_results = Table(
    "prism_atlas_bench_task_results",
    _metadata,
    Column("result_id", String(160), primary_key=True),
    Column("run_id", String(120), nullable=False, index=True),
    Column("task_id", String(120), nullable=False, index=True),
    Column("category", String(32), nullable=False, index=True),
    Column("subject_id", String(120), nullable=False),
    Column("chosen_choice", Integer, nullable=True),
    Column("correct", Boolean, nullable=False),
    Column("raw_answer", Text, nullable=False),
    Column("evaluated_at", DateTime(timezone=True), nullable=False),
)


class DurableAtlasBenchStore:
    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)
        with self.engine.begin() as connection:
            existing = {str(item["name"]) for item in inspect(connection).get_columns("prism_atlas_bench_runs")}
            additions = {
                "subject_kind": "VARCHAR(16) NOT NULL DEFAULT 'generic'",
                "candidate_id": "VARCHAR(120)", "candidate_fingerprint": "VARCHAR(64)",
                "trust_verification_id": "VARCHAR(120)", "runtime_model": "VARCHAR(300)",
                "runtime_model_digest": "VARCHAR(200)", "provider": "VARCHAR(32)",
                "evaluation_policy_id": "VARCHAR(64)",
            }
            for name, definition in additions.items():
                if name not in existing:
                    connection.execute(text(f"ALTER TABLE prism_atlas_bench_runs ADD COLUMN {name} {definition}"))
            ensure_index(
                connection,
                "prism_atlas_bench_task_results",
                "ix_prism_atlas_bench_task_results_run_task",
                "CREATE INDEX ix_prism_atlas_bench_task_results_run_task "
                "ON prism_atlas_bench_task_results (run_id, task_id)",
            )
            ensure_index(
                connection,
                "prism_atlas_bench_runs",
                "ix_prism_atlas_bench_runs_subject_completed",
                "CREATE INDEX ix_prism_atlas_bench_runs_subject_completed "
                "ON prism_atlas_bench_runs (subject_id, completed_at)",
            )

    def save(self, suite_run: AtlasBenchSuiteRun, results: list[AtlasBenchTaskResult]) -> AtlasBenchSuiteRun:
        with self.engine.begin() as connection:
            connection.execute(
                insert(_runs).values(
                    run_id=suite_run.run_id,
                    subject_id=suite_run.subject_id,
                    corpus_version=suite_run.corpus_version,
                    corpus_hash=suite_run.corpus_hash,
                    total_tasks=suite_run.total_tasks,
                    total_passed=suite_run.total_passed,
                    category_scores_payload=json.dumps(
                        [score.model_dump(mode="json") for score in suite_run.category_scores], sort_keys=True
                    ),
                    started_at=suite_run.started_at,
                    completed_at=suite_run.completed_at,
                    subject_kind=suite_run.subject_kind,
                    candidate_id=suite_run.candidate_id,
                    candidate_fingerprint=suite_run.candidate_fingerprint,
                    trust_verification_id=suite_run.trust_verification_id,
                    runtime_model=suite_run.runtime_model,
                    runtime_model_digest=suite_run.runtime_model_digest,
                    provider=suite_run.provider,
                    evaluation_policy_id=suite_run.evaluation_policy_id,
                )
            )
            for result in results:
                connection.execute(
                    insert(_task_results).values(
                        result_id=f"{suite_run.run_id}_{result.task_id}",
                        run_id=suite_run.run_id,
                        task_id=result.task_id,
                        category=result.category.value,
                        subject_id=result.subject_id,
                        chosen_choice=result.chosen_choice,
                        correct=result.correct,
                        raw_answer=result.raw_answer,
                        evaluated_at=result.evaluated_at,
                    )
                )
        return suite_run

    def get_run(self, run_id: str) -> Optional[AtlasBenchSuiteRun]:
        with self.engine.connect() as connection:
            row = connection.execute(select(_runs).where(_runs.c.run_id == run_id)).mappings().first()
        return None if row is None else self._run_record(row)

    @staticmethod
    def _run_record(row: object) -> AtlasBenchSuiteRun:
        scores = [
            AtlasBenchCategoryScore.model_validate(item)
            for item in json.loads(row["category_scores_payload"])  # type: ignore[index]
        ]
        return AtlasBenchSuiteRun(
            run_id=row["run_id"],  # type: ignore[index]
            subject_id=row["subject_id"],  # type: ignore[index]
            corpus_version=row["corpus_version"],  # type: ignore[index]
            corpus_hash=row["corpus_hash"],  # type: ignore[index]
            total_tasks=row["total_tasks"],  # type: ignore[index]
            total_passed=row["total_passed"],  # type: ignore[index]
            category_scores=scores,
            started_at=row["started_at"],  # type: ignore[index]
            completed_at=row["completed_at"],  # type: ignore[index]
            subject_kind=row["subject_kind"],  # type: ignore[index]
            candidate_id=row["candidate_id"],  # type: ignore[index]
            candidate_fingerprint=row["candidate_fingerprint"],  # type: ignore[index]
            trust_verification_id=row["trust_verification_id"],  # type: ignore[index]
            runtime_model=row["runtime_model"],  # type: ignore[index]
            runtime_model_digest=row["runtime_model_digest"],  # type: ignore[index]
            provider=row["provider"],  # type: ignore[index]
            evaluation_policy_id=row["evaluation_policy_id"],  # type: ignore[index]
        )

    def list_runs_for_subject(self, subject_id: str, *, limit: int = 50) -> list[AtlasBenchSuiteRun]:
        statement = (
            select(_runs)
            .where(_runs.c.subject_id == subject_id)
            .order_by(_runs.c.completed_at.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._run_record(row) for row in rows]

    def list_runs_for_corpus(self, corpus_version: str, corpus_hash: str, *, limit: int = 200) -> list[AtlasBenchSuiteRun]:
        """Return immutable run evidence for one exact frozen corpus only."""
        statement = (
            select(_runs)
            .where(_runs.c.corpus_version == corpus_version, _runs.c.corpus_hash == corpus_hash)
            .order_by(_runs.c.completed_at.desc(), _runs.c.run_id.desc())
            .limit(limit)
        )
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._run_record(row) for row in rows]

    def task_results(self, run_id: str, *, limit: int = 500) -> list[AtlasBenchTaskResult]:
        statement = select(_task_results).where(_task_results.c.run_id == run_id).order_by(_task_results.c.task_id).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [
            AtlasBenchTaskResult(
                task_id=row["task_id"],
                category=AtlasBenchCategory(row["category"]),
                subject_id=row["subject_id"],
                chosen_choice=row["chosen_choice"],
                correct=bool(row["correct"]),
                raw_answer=row["raw_answer"],
                evaluated_at=row["evaluated_at"],
            )
            for row in rows
        ]

    def failed_tasks(self, run_id: str, *, limit: int = 200) -> list[AtlasBenchTaskResult]:
        return [result for result in self.task_results(run_id, limit=limit) if not result.correct]
