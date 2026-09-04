"""10Q: Shadow Brain comparison and the locked promotion policy.

Shadow Brain runs a production subject and a candidate subject through the
exact same AtlasBench harness (``atlas_bench_runner.run_suite``) on the
exact same task corpus, then compares the results -- it never runs the
candidate against live user/project state. Non-mutation here is structural,
not a promise layered on top: ``AtlasBenchSubject.answer()`` only receives a
prompt and a list of choices and returns an index, so there is nothing for
either subject to mutate even if it wanted to. A future subject that wraps a
real tool-executing Atlas provider must preserve that boundary (dry-run /
no-op tool execution) to remain a legitimate Shadow Brain participant.

Promotion policy is locked: IMPROVE TARGET CAPABILITY + NO UNACCEPTABLE
CRITICAL REGRESSION. A candidate cannot win on aggregate score alone while
regressing a critical category -- ``CRITICAL_CATEGORIES`` makes that
non-negotiable rather than a judgment call applied inconsistently at
promotion time. The candidate has no path to this module or its thresholds:
nothing here is reachable from candidate/subject code, matching the same
"cannot control its own judge" boundary as the AtlasBench corpus itself.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional, Sequence

from prism_api_contracts import (
    AtlasBenchCategory,
    AtlasBenchSuiteRun,
    AtlasBenchTask,
    AtlasCriticalRegression,
    AtlasProductionPointer,
    AtlasPromotionDecision,
    AtlasPromotionVerdict,
)
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    select,
)
from sqlalchemy.engine import Engine

from .atlas_bench_runner import AtlasBenchSubject, run_suite
from .durable_registry import history_database_url

# Evidence correctness, causal safety, tool safety, provenance, schema
# grounding, and critical DS methodology, per the locked policy. Forecasting,
# personality, and general contract validity remain real signals but are not
# treated as promotion-blocking on their own.
CRITICAL_CATEGORIES: frozenset[AtlasBenchCategory] = frozenset(
    {
        AtlasBenchCategory.SQL,
        AtlasBenchCategory.STATISTICS,
        AtlasBenchCategory.MACHINE_LEARNING,
        AtlasBenchCategory.CAUSAL_SAFETY,
        AtlasBenchCategory.AGENTIC,
        AtlasBenchCategory.EVIDENCE,
        AtlasBenchCategory.PYTHON_SANDBOX,
    }
)


def _pass_rate(passed: int, total: int) -> float:
    return passed / total if total else 0.0


def decide_promotion(
    candidate_id: str,
    production_run: AtlasBenchSuiteRun,
    candidate_run: AtlasBenchSuiteRun,
    *,
    critical_regression_tolerance: float = 0.0,
) -> AtlasPromotionDecision:
    """Compare two AtlasBench suite runs and produce a typed verdict.

    ``critical_regression_tolerance`` is a pass-rate delta (0.0 by default:
    any drop at all in a critical category counts, since each category is a
    curated ~8-10 item set where a single regression is meaningful). Raising
    it is a deliberate, auditable policy choice a caller makes explicitly --
    never something a candidate can adjust about its own evaluation.
    """
    production_by_category = {score.category: score for score in production_run.category_scores}
    critical_regressions: list[AtlasCriticalRegression] = []
    improved_any = False
    for candidate_score in candidate_run.category_scores:
        production_score = production_by_category.get(candidate_score.category)
        if production_score is None:
            continue
        candidate_rate = _pass_rate(candidate_score.passed, candidate_score.total)
        production_rate = _pass_rate(production_score.passed, production_score.total)
        if candidate_rate > production_rate:
            improved_any = True
        if (
            candidate_score.category in CRITICAL_CATEGORIES
            and candidate_rate < production_rate - critical_regression_tolerance
        ):
            critical_regressions.append(
                AtlasCriticalRegression(
                    category=candidate_score.category,
                    production_pass_rate=production_rate,
                    candidate_pass_rate=candidate_rate,
                )
            )

    overall_production_rate = _pass_rate(production_run.total_passed, production_run.total_tasks)
    overall_candidate_rate = _pass_rate(candidate_run.total_passed, candidate_run.total_tasks)

    if critical_regressions:
        verdict = AtlasPromotionVerdict.REJECT
    elif overall_candidate_rate > overall_production_rate or improved_any:
        verdict = AtlasPromotionVerdict.PROMOTE_ELIGIBLE
    else:
        verdict = AtlasPromotionVerdict.HOLD

    return AtlasPromotionDecision(
        decision_id=f"promodecision_{uuid.uuid4().hex}",
        candidate_id=candidate_id,
        production_run_id=production_run.run_id,
        candidate_run_id=candidate_run.run_id,
        verdict=verdict,
        overall_production_pass_rate=overall_production_rate,
        overall_candidate_pass_rate=overall_candidate_rate,
        critical_regressions=critical_regressions,
        decided_at=datetime.now(timezone.utc),
    )


def shadow_compare(
    production_subject: AtlasBenchSubject,
    candidate_subject: AtlasBenchSubject,
    tasks: Sequence[AtlasBenchTask],
    *,
    corpus_version: str,
    corpus_hash_value: str,
    critical_regression_tolerance: float = 0.0,
) -> tuple[AtlasBenchSuiteRun, AtlasBenchSuiteRun, AtlasPromotionDecision]:
    """Run production and candidate through the identical task set and
    produce a promotion decision. Neither subject mutates anything -- see
    module docstring -- so running this comparison is always safe to do
    speculatively, on any schedule, without touching live state.
    """
    production_run, _ = run_suite(
        production_subject, tasks, corpus_version=corpus_version, corpus_hash_value=corpus_hash_value
    )
    candidate_run, _ = run_suite(
        candidate_subject, tasks, corpus_version=corpus_version, corpus_hash_value=corpus_hash_value
    )
    decision = decide_promotion(
        candidate_subject.subject_id,
        production_run,
        candidate_run,
        critical_regression_tolerance=critical_regression_tolerance,
    )
    return production_run, candidate_run, decision


# --- durable production pointer / rollback history --------------------------

_metadata = MetaData()
_events = Table(
    "prism_atlas_production_pointer_events",
    _metadata,
    Column("event_id", String(120), primary_key=True),
    Column("candidate_id", String(120), nullable=False, index=True),
    Column("previous_candidate_id", String(120), nullable=True),
    Column("decision_id", String(120), nullable=True),
    Column("is_rollback", Boolean, nullable=False),
    Column("reason", String(1_000), nullable=False),
    Column("promoted_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasPromotionStore:
    """Append-only production-pointer history. The latest row (by
    ``promoted_at``) is current production; every prior row is retained --
    that full history IS the rollback list, never a separately maintained
    structure that could drift from what actually happened.
    """

    def __init__(self, database_url: Optional[str] = None) -> None:
        url = database_url or history_database_url()
        self.engine: Engine = create_engine(
            url,
            future=True,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _metadata.create_all(self.engine)

    def promote(self, decision: AtlasPromotionDecision, *, reason: str) -> AtlasProductionPointer:
        """Atomically append a new production pointer. Refuses to promote a
        candidate whose own decision was not PROMOTE_ELIGIBLE -- the policy
        is enforced at this boundary too, not only by a well-behaved caller.
        """
        if decision.verdict is not AtlasPromotionVerdict.PROMOTE_ELIGIBLE:
            raise ValueError(
                f"Refusing to promote candidate {decision.candidate_id!r}: "
                f"its decision verdict was {decision.verdict.value}, not promote_eligible."
            )
        current = self.current_production()
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            connection.execute(
                insert(_events).values(
                    event_id=f"promo_{uuid.uuid4().hex}",
                    candidate_id=decision.candidate_id,
                    previous_candidate_id=current.candidate_id if current else None,
                    decision_id=decision.decision_id,
                    is_rollback=False,
                    reason=reason,
                    promoted_at=now,
                )
            )
        record = self.current_production()
        assert record is not None
        return record

    def rollback(self, *, reason: str) -> AtlasProductionPointer:
        """Restore the previous production candidate as a new, explicit
        event -- never a silent undo of the current row, so the full
        promote/rollback sequence stays visible in history.
        """
        history = self.history(limit=2)
        if len(history) < 2:
            raise ValueError("No prior production candidate to roll back to.")
        current, previous = history[0], history[1]
        now = datetime.now(timezone.utc)
        with self.engine.begin() as connection:
            connection.execute(
                insert(_events).values(
                    event_id=f"promo_{uuid.uuid4().hex}",
                    candidate_id=previous.candidate_id,
                    previous_candidate_id=current.candidate_id,
                    decision_id=None,
                    is_rollback=True,
                    reason=reason,
                    promoted_at=now,
                )
            )
        record = self.current_production()
        assert record is not None
        return record

    @staticmethod
    def _record(row: object) -> AtlasProductionPointer:
        return AtlasProductionPointer(
            event_id=row["event_id"],  # type: ignore[index]
            candidate_id=row["candidate_id"],  # type: ignore[index]
            previous_candidate_id=row["previous_candidate_id"],  # type: ignore[index]
            decision_id=row["decision_id"],  # type: ignore[index]
            is_rollback=bool(row["is_rollback"]),  # type: ignore[index]
            reason=row["reason"],  # type: ignore[index]
            promoted_at=row["promoted_at"],  # type: ignore[index]
        )

    def current_production(self) -> Optional[AtlasProductionPointer]:
        row = (
            self.engine.connect()
            .execute(select(_events).order_by(_events.c.promoted_at.desc()).limit(1))
            .mappings()
            .first()
        )
        return None if row is None else self._record(row)

    def history(self, *, limit: int = 100) -> list[AtlasProductionPointer]:
        statement = select(_events).order_by(_events.c.promoted_at.desc()).limit(limit)
        return [self._record(row) for row in self.engine.connect().execute(statement).mappings().all()]

