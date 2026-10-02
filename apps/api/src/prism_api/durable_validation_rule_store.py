"""Durable store for Clean validation rules: simple CRUD, no versioning needed
since a rule is a declarative check, not an applied transformation with its own
provenance chain. Survives an API restart via the same history database the other
durable stores in this app use.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from prism_api_contracts import ValidationRule, ValidationRuleCreateRequest, ValidationRuleKind
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    create_engine,
    delete,
    insert,
    select,
)

from .durable_registry import history_database_url

_metadata = MetaData()
_rules = Table(
    "prism_clean_validation_rules", _metadata,
    Column("rule_id", String(255), primary_key=True),
    Column("name", String(500), nullable=False),
    Column("kind", String(64), nullable=False),
    Column("column_name", String(500), nullable=True),
    Column("before_column", String(500), nullable=True),
    Column("after_column", String(500), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableValidationRuleStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)

    def create(self, request: ValidationRuleCreateRequest) -> ValidationRule:
        rule = ValidationRule(
            rule_id=f"rule_{uuid.uuid4().hex}", name=request.name, kind=request.kind,
            column=request.column, before_column=request.before_column, after_column=request.after_column,
            created_at=datetime.now(timezone.utc),
        )
        with self.engine.begin() as connection:
            connection.execute(insert(_rules).values(
                rule_id=rule.rule_id, name=rule.name, kind=rule.kind.value,
                column_name=rule.column, before_column=rule.before_column, after_column=rule.after_column,
                created_at=rule.created_at,
            ))
        return rule

    def list_all(self) -> list[ValidationRule]:
        with self.engine.begin() as connection:
            rows = connection.execute(select(_rules).order_by(_rules.c.created_at)).mappings().all()
        return [_row_to_rule(row) for row in rows]

    def get(self, rule_id: str) -> ValidationRule:
        with self.engine.begin() as connection:
            row = connection.execute(select(_rules).where(_rules.c.rule_id == rule_id)).mappings().first()
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Validation rule {rule_id!r} was not found.")
        return _row_to_rule(row)

    def delete(self, rule_id: str) -> None:
        self.get(rule_id)  # 404s on an unknown id
        with self.engine.begin() as connection:
            connection.execute(delete(_rules).where(_rules.c.rule_id == rule_id))


def _row_to_rule(row: object) -> ValidationRule:
    mapping = dict(row)  # type: ignore[call-overload]
    return ValidationRule(
        rule_id=mapping["rule_id"], name=mapping["name"], kind=ValidationRuleKind(mapping["kind"]),
        column=mapping["column_name"], before_column=mapping["before_column"], after_column=mapping["after_column"],
        created_at=mapping["created_at"],
    )
