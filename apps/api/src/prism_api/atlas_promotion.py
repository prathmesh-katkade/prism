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

import random
import time
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
    Integer,
    MetaData,
    String,
    Table,
    create_engine,
    desc,
    insert,
    inspect,
    select,
    text,
    update,
)
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import IntegrityError, OperationalError

from .atlas_bench_runner import AtlasBenchSubject, run_suite
from .atlas_schema_utils import ensure_index
from .durable_registry import history_database_url

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
    """Compare two AtlasBench suite runs and produce a typed verdict."""
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
    """Run production and candidate through the identical task set."""
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


_metadata = MetaData()
_events = Table(
    "prism_atlas_production_pointer_events",
    _metadata,
    Column("event_id", String(120), primary_key=True),
    # True insertion order, independent of clock resolution: a configured
    # MySQL DATETIME column can give two promotions within the same second
    # an identical `promoted_at`, leaving ORDER BY promoted_at with no
    # tiebreaker -- current_production()/history() could then non-
    # deterministically resolve to the wrong event, and rollback() (which
    # reads the two most recent via history()) could restore the wrong
    # candidate. `sequence` is allocated under a row lock in _append() and
    # is what ordering now relies on; promoted_at is kept for display only.
    Column("sequence", Integer, nullable=False),
    Column("candidate_id", String(120), nullable=False, index=True),
    Column("previous_candidate_id", String(120), nullable=True),
    Column("decision_id", String(120), nullable=True),
    Column("is_rollback", Boolean, nullable=False),
    Column("reason", String(1_000), nullable=False),
    Column("promoted_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasPromotionStore:
    """Append-only production pointer history."""

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
            existing = {str(item["name"]) for item in inspect(connection).get_columns("prism_atlas_production_pointer_events")}
            if "sequence" not in existing:
                # A table that pre-dates the `sequence` tiebreaker: add it
                # nullable (a non-empty table cannot take a NOT NULL column
                # without a default in one ALTER) and backfill every existing
                # row from its promoted_at order -- the real promotion events
                # already on disk were each separated by a live inference
                # call, so promoted_at correctly orders them even though it
                # is not trusted for that going forward.
                connection.execute(text("ALTER TABLE prism_atlas_production_pointer_events ADD COLUMN sequence INTEGER"))
                rows = connection.execute(
                    select(_events.c.event_id).order_by(_events.c.promoted_at, _events.c.event_id)
                ).all()
                for backfilled_sequence, row in enumerate(rows):
                    connection.execute(
                        update(_events).where(_events.c.event_id == row.event_id).values(sequence=backfilled_sequence)
                    )
            # `sequence` has no legitimate duplicate the way a dataset
            # revision number can (branching after an undo intentionally
            # keeps an abandoned row at the same revision) -- a UNIQUE index
            # is the correct, database-enforced guarantee here, not just a
            # best-effort lock. `with_for_update()` in _append() is a no-op
            # on SQLite, so without this, two concurrent appends could both
            # read the same max sequence and both insert it; with this, the
            # loser's insert raises IntegrityError and the retry loop in
            # _append_with_retry() re-reads the now-committed state.
            ensure_index(
                connection,
                "prism_atlas_production_pointer_events",
                "ux_prism_atlas_production_pointer_events_sequence",
                "CREATE UNIQUE INDEX ux_prism_atlas_production_pointer_events_sequence "
                "ON prism_atlas_production_pointer_events (sequence)",
            )

    @staticmethod
    def _append(
        connection: Connection,
        *,
        candidate_id: str,
        previous_candidate_id: Optional[str],
        decision_id: Optional[str],
        is_rollback: bool,
        reason: str,
        now: datetime,
    ) -> None:
        """Allocate the next `sequence` under a row lock and insert.

        Must run inside the caller's `engine.begin()` transaction so the lock
        (a real row lock on MySQL/InnoDB, a no-op on SQLite whose own
        single-writer file lock instead raises OperationalError on the
        loser) is held for the insert too -- otherwise two concurrent
        appends could both read the same max sequence and allocate the same
        next one.
        """
        last_sequence = connection.execute(
            select(_events.c.sequence).order_by(desc(_events.c.sequence)).limit(1).with_for_update()
        ).scalar_one_or_none()
        next_sequence = 0 if last_sequence is None else last_sequence + 1
        connection.execute(
            insert(_events).values(
                event_id=f"promo_{uuid.uuid4().hex}",
                sequence=next_sequence,
                candidate_id=candidate_id,
                previous_candidate_id=previous_candidate_id,
                decision_id=decision_id,
                is_rollback=is_rollback,
                reason=reason,
                promoted_at=now,
            )
        )

    def _append_with_retry(self, **kwargs: object) -> None:
        max_attempts = 20
        for attempt in range(max_attempts):
            try:
                with self.engine.begin() as connection:
                    self._append(connection, **kwargs)  # type: ignore[arg-type]
                return
            except (IntegrityError, OperationalError):
                if attempt == max_attempts - 1:
                    raise
                time.sleep(0.01 * (attempt + 1) + random.uniform(0, 0.01))

    def bootstrap(self, candidate_id: str, *, reason: str) -> AtlasProductionPointer:
        """Persist the already-configured production model once.

        This is not a promotion and has no evaluator decision. It creates the
        immutable rollback anchor that existed before Atlas's first trained
        candidate can ever become production. Repeated calls are idempotent.
        """
        current = self.current_production()
        if current is not None:
            return current
        self._append_with_retry(
            candidate_id=candidate_id,
            previous_candidate_id=None,
            decision_id=None,
            is_rollback=False,
            reason=reason,
            now=datetime.now(timezone.utc),
        )
        record = self.current_production()
        assert record is not None
        return record

    def promote(self, decision: AtlasPromotionDecision, *, reason: str) -> AtlasProductionPointer:
        """Append an eligible candidate as production."""
        if decision.verdict is not AtlasPromotionVerdict.PROMOTE_ELIGIBLE:
            raise ValueError(
                f"Refusing to promote candidate {decision.candidate_id!r}: "
                f"its decision verdict was {decision.verdict.value}, not promote_eligible."
            )
        current = self.current_production()
        self._append_with_retry(
            candidate_id=decision.candidate_id,
            previous_candidate_id=current.candidate_id if current else None,
            decision_id=decision.decision_id,
            is_rollback=False,
            reason=reason,
            now=datetime.now(timezone.utc),
        )
        record = self.current_production()
        assert record is not None
        return record

    def rollback(self, *, reason: str) -> AtlasProductionPointer:
        """Restore the previous production candidate as a new explicit event."""
        history = self.history(limit=2)
        if len(history) < 2:
            raise ValueError("No prior production candidate to roll back to.")
        current, previous = history[0], history[1]
        self._append_with_retry(
            candidate_id=previous.candidate_id,
            previous_candidate_id=current.candidate_id,
            decision_id=None,
            is_rollback=True,
            reason=reason,
            now=datetime.now(timezone.utc),
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
        with self.engine.connect() as connection:
            row = connection.execute(select(_events).order_by(desc(_events.c.sequence)).limit(1)).mappings().first()
        return None if row is None else self._record(row)

    def history(self, *, limit: int = 100) -> list[AtlasProductionPointer]:
        statement = select(_events).order_by(desc(_events.c.sequence)).limit(limit)
        with self.engine.connect() as connection:
            rows = connection.execute(statement).mappings().all()
        return [self._record(row) for row in rows]
