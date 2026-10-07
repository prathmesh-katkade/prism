"""Durable store for Clean Pattern Review decisions (accept family / ignore this
revision / suppress rule). A decision is append-only and source-bound: it records
which (dataset_id, revision, fingerprint) it was made against, so a revision-only
"ignore" never silently carries into a new upload of the same dataset - re-running
discovery on a new revision produces fresh findings with no decisions attached
unless the user decides again. Revocation is itself a new append-only decision
(revokes_decision_id pointing at the one it cancels) rather than a destructive
delete or edit, so prior decision records are always inspectable - see ADR 0025.
Survives an API restart via the same history database every other durable store
in this app uses.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from prism_api_contracts import (
    PatternReviewDecision,
    PatternReviewDecisionKind,
    PatternReviewDecisionRequest,
)
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    insert,
    inspect,
    select,
    text,
)

from .durable_registry import history_database_url

_metadata = MetaData()
_decisions = Table(
    "prism_clean_pattern_decisions", _metadata,
    Column("decision_id", String(255), primary_key=True),
    Column("dataset_id", String(255), nullable=False, index=True),
    Column("column_name", String(500), nullable=False),
    Column("decision", String(64), nullable=False),
    Column("family_signatures_json", String(4000), nullable=False),
    Column("detector_kind", String(64), nullable=True),
    Column("detector_version", String(16), nullable=True),
    Column("revokes_decision_id", String(255), nullable=True),
    Column("source_revision", String(32), nullable=False),
    Column("source_fingerprint", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurablePatternReviewStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)
        existing = {column["name"] for column in inspect(self.engine).get_columns("prism_clean_pattern_decisions")}
        with self.engine.begin() as connection:
            if "detector_version" not in existing:
                connection.execute(text("ALTER TABLE prism_clean_pattern_decisions ADD COLUMN detector_version VARCHAR(16)"))
            if "revokes_decision_id" not in existing:
                connection.execute(text("ALTER TABLE prism_clean_pattern_decisions ADD COLUMN revokes_decision_id VARCHAR(255)"))

    def create(self, dataset_id: str, request: PatternReviewDecisionRequest, source_revision: int, source_fingerprint: str) -> PatternReviewDecision:
        decision = PatternReviewDecision(
            decision_id=f"patterndecision_{uuid.uuid4().hex}", dataset_id=dataset_id, column=request.column,
            decision=request.decision, family_signatures=request.family_signatures or [],
            detector_kind=request.detector_kind, detector_version=request.detector_version,
            revokes_decision_id=request.revokes_decision_id,
            source_revision=source_revision, source_fingerprint=source_fingerprint, created_at=datetime.now(timezone.utc),
        )
        with self.engine.begin() as connection:
            connection.execute(insert(_decisions).values(
                decision_id=decision.decision_id, dataset_id=decision.dataset_id, column_name=decision.column,
                decision=decision.decision.value, family_signatures_json=json.dumps(decision.family_signatures),
                detector_kind=decision.detector_kind.value if decision.detector_kind else None,
                detector_version=str(decision.detector_version) if decision.detector_version is not None else None,
                revokes_decision_id=decision.revokes_decision_id,
                source_revision=str(decision.source_revision), source_fingerprint=decision.source_fingerprint,
                created_at=decision.created_at,
            ))
        return decision

    def list_for_dataset(self, dataset_id: str) -> list[PatternReviewDecision]:
        with self.engine.begin() as connection:
            rows = connection.execute(
                select(_decisions).where(_decisions.c.dataset_id == dataset_id).order_by(_decisions.c.created_at)
            ).mappings().all()
        decisions = [_row_to_decision(row) for row in rows]
        revoked_ids = {decision.revokes_decision_id for decision in decisions if decision.revokes_decision_id}
        for decision in decisions:
            if decision.decision_id in revoked_ids:
                decision.revoked = True
        return decisions

    def get(self, decision_id: str) -> PatternReviewDecision | None:
        with self.engine.begin() as connection:
            row = connection.execute(select(_decisions).where(_decisions.c.decision_id == decision_id)).mappings().first()
        return _row_to_decision(row) if row is not None else None


def _row_to_decision(row: object) -> PatternReviewDecision:
    mapping = dict(row)  # type: ignore[call-overload]
    detector_version = mapping.get("detector_version")
    return PatternReviewDecision(
        decision_id=mapping["decision_id"], dataset_id=mapping["dataset_id"], column=mapping["column_name"],
        decision=PatternReviewDecisionKind(mapping["decision"]), family_signatures=json.loads(mapping["family_signatures_json"]),
        detector_kind=mapping["detector_kind"], detector_version=int(detector_version) if detector_version else None,
        revokes_decision_id=mapping.get("revokes_decision_id"),
        source_revision=int(mapping["source_revision"]),
        source_fingerprint=mapping["source_fingerprint"], created_at=mapping["created_at"],
    )
