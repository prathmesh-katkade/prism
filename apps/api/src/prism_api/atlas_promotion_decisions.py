"""Durable server-owned promotion decisions for Atlas Evolution Activation.

A promotion verdict is evaluator output, never client input. This store keeps
those decisions immutable so a later promote request can prove exactly which
production/candidate AtlasBench runs made a candidate eligible. Recomputing a
comparison creates a new decision_id; historical decisions are never edited.
"""

from __future__ import annotations

import json
from typing import Optional

from prism_api_contracts import (
    AtlasCriticalRegression,
    AtlasPromotionDecision,
    AtlasPromotionVerdict,
)
from sqlalchemy import Column, DateTime, MetaData, String, Table, Text, create_engine, insert, select
from sqlalchemy.engine import Engine

from .atlas_schema_utils import ensure_index
from .durable_registry import history_database_url

_metadata = MetaData()
_decisions = Table(
    "prism_atlas_promotion_decisions",
    _metadata,
    Column("decision_id", String(120), primary_key=True),
    Column("candidate_id", String(120), nullable=False, index=True),
    Column("production_run_id", String(120), nullable=False, index=True),
    Column("candidate_run_id", String(120), nullable=False, index=True),
    Column("verdict", String(32), nullable=False, index=True),
    Column("overall_production_pass_rate", String(32), nullable=False),
    Column("overall_candidate_pass_rate", String(32), nullable=False),
    Column("critical_regressions_payload", Text, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableAtlasPromotionDecisionStore:
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
            ensure_index(
                connection,
                "prism_atlas_promotion_decisions",
                "ix_prism_atlas_promotion_decisions_candidate_decided",
                "CREATE INDEX ix_prism_atlas_promotion_decisions_candidate_decided "
                "ON prism_atlas_promotion_decisions (candidate_id, decided_at)",
            )

    def save(self, decision: AtlasPromotionDecision) -> AtlasPromotionDecision:
        with self.engine.begin() as connection:
            existing = connection.execute(
                select(_decisions.c.decision_id).where(_decisions.c.decision_id == decision.decision_id)
            ).scalar_one_or_none()
            if existing is None:
                connection.execute(
                    insert(_decisions).values(
                        decision_id=decision.decision_id,
                        candidate_id=decision.candidate_id,
                        production_run_id=decision.production_run_id,
                        candidate_run_id=decision.candidate_run_id,
                        verdict=decision.verdict.value,
                        overall_production_pass_rate=repr(decision.overall_production_pass_rate),
                        overall_candidate_pass_rate=repr(decision.overall_candidate_pass_rate),
                        critical_regressions_payload=json.dumps(
                            [item.model_dump(mode="json") for item in decision.critical_regressions],
                            sort_keys=True,
                        ),
                        decided_at=decision.decided_at,
                    )
                )
        return decision

    @staticmethod
    def _record(row: object) -> AtlasPromotionDecision:
        return AtlasPromotionDecision(
            decision_id=row["decision_id"],  # type: ignore[index]
            candidate_id=row["candidate_id"],  # type: ignore[index]
            production_run_id=row["production_run_id"],  # type: ignore[index]
            candidate_run_id=row["candidate_run_id"],  # type: ignore[index]
            verdict=AtlasPromotionVerdict(row["verdict"]),  # type: ignore[index]
            overall_production_pass_rate=float(row["overall_production_pass_rate"]),  # type: ignore[index]
            overall_candidate_pass_rate=float(row["overall_candidate_pass_rate"]),  # type: ignore[index]
            critical_regressions=[
                AtlasCriticalRegression.model_validate(item)
                for item in json.loads(row["critical_regressions_payload"])  # type: ignore[index]
            ],
            decided_at=row["decided_at"],  # type: ignore[index]
        )

    def get(self, decision_id: str) -> Optional[AtlasPromotionDecision]:
        row = (
            self.engine.connect()
            .execute(select(_decisions).where(_decisions.c.decision_id == decision_id))
            .mappings()
            .first()
        )
        return None if row is None else self._record(row)

    def list_for_candidate(self, candidate_id: str, *, limit: int = 50) -> list[AtlasPromotionDecision]:
        statement = (
            select(_decisions)
            .where(_decisions.c.candidate_id == candidate_id)
            .order_by(_decisions.c.decided_at.desc())
            .limit(limit)
        )
        return [self._record(row) for row in self.engine.connect().execute(statement).mappings().all()]
