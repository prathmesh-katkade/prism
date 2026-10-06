"""Durable store for Clean validation rules: simple CRUD, no versioning needed
since a rule is a declarative check, not an applied transformation with its own
provenance chain. Survives an API restart via the same history database the other
durable stores in this app use.
"""

from __future__ import annotations

import json
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
    Text,
    create_engine,
    delete,
    insert,
    inspect,
    select,
    text,
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
    Column("accepted_families_json", Text, nullable=True),
    Column("missing_value_policy", String(16), nullable=True),
    Column("group_by_column", String(500), nullable=True),
    Column("group_value", String(500), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, index=True),
)


class DurableValidationRuleStore:
    def __init__(self, database_url: str | None = None) -> None:
        url = database_url or history_database_url()
        self.engine = create_engine(url, future=True, pool_pre_ping=True, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
        _metadata.create_all(self.engine)
        # Nullable-add only: these columns are irrelevant to every pre-existing
        # rule kind, so there is nothing to backfill. Idempotent and safe to
        # repeat on every startup, including against MySQL (ADR 0024).
        existing = {column["name"] for column in inspect(self.engine).get_columns("prism_clean_validation_rules")}
        with self.engine.begin() as connection:
            if "accepted_families_json" not in existing:
                connection.execute(text("ALTER TABLE prism_clean_validation_rules ADD COLUMN accepted_families_json TEXT"))
            if "missing_value_policy" not in existing:
                connection.execute(text("ALTER TABLE prism_clean_validation_rules ADD COLUMN missing_value_policy VARCHAR(16)"))
            if "group_by_column" not in existing:
                connection.execute(text("ALTER TABLE prism_clean_validation_rules ADD COLUMN group_by_column VARCHAR(500)"))
            if "group_value" not in existing:
                connection.execute(text("ALTER TABLE prism_clean_validation_rules ADD COLUMN group_value VARCHAR(500)"))

    def create(self, request: ValidationRuleCreateRequest) -> ValidationRule:
        rule = ValidationRule(
            rule_id=f"rule_{uuid.uuid4().hex}", name=request.name, kind=request.kind,
            column=request.column, before_column=request.before_column, after_column=request.after_column,
            accepted_family_signatures=request.accepted_family_signatures,
            missing_value_policy=request.missing_value_policy,
            group_by_column=request.group_by_column, group_value=request.group_value,
            created_at=datetime.now(timezone.utc),
        )
        with self.engine.begin() as connection:
            connection.execute(insert(_rules).values(
                rule_id=rule.rule_id, name=rule.name, kind=rule.kind.value,
                column_name=rule.column, before_column=rule.before_column, after_column=rule.after_column,
                accepted_families_json=json.dumps(rule.accepted_family_signatures) if rule.accepted_family_signatures else None,
                missing_value_policy=rule.missing_value_policy,
                group_by_column=rule.group_by_column, group_value=rule.group_value,
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
    families_json = mapping.get("accepted_families_json")
    return ValidationRule(
        rule_id=mapping["rule_id"], name=mapping["name"], kind=ValidationRuleKind(mapping["kind"]),
        column=mapping["column_name"], before_column=mapping["before_column"], after_column=mapping["after_column"],
        accepted_family_signatures=json.loads(families_json) if families_json else None,
        missing_value_policy=mapping.get("missing_value_policy"),
        group_by_column=mapping.get("group_by_column"), group_value=mapping.get("group_value"),
        created_at=mapping["created_at"],
    )
