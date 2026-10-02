"""Reusable, named validation rules for Clean: uniqueness, nonnegative values, and
date ordering. A rule is read-only — running it reports violations against the
dataset's current revision, it never mutates data. Rules are durable and reusable
across datasets with a matching schema (the same way a recipe is), independent of
any single dataset.
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    ValidationRule,
    ValidationRuleCreateRequest,
    ValidationRuleKind,
    ValidationRunResult,
)

from .clean import _require_column, _sample
from .durable_validation_rule_store import DurableValidationRuleStore
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/clean", tags=["clean-validation"])
SAMPLE_VIOLATIONS = 10

rules = DurableValidationRuleStore()


@router.post("/validation-rules", response_model=ValidationRule, status_code=status.HTTP_201_CREATED)
def create_validation_rule(request: ValidationRuleCreateRequest) -> ValidationRule:
    if request.kind in (ValidationRuleKind.UNIQUENESS, ValidationRuleKind.NONNEGATIVE) and not request.column:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"A column is required for a {request.kind.value} rule.")
    if request.kind is ValidationRuleKind.DATE_ORDER and not (request.before_column and request.after_column):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Both a before-column and an after-column are required for a date_order rule.")
    return rules.create(request)


@router.get("/validation-rules", response_model=list[ValidationRule])
def list_validation_rules() -> list[ValidationRule]:
    return rules.list_all()


@router.delete("/validation-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
def delete_validation_rule(rule_id: str) -> None:
    rules.delete(rule_id)


def _run_rule(frame: pd.DataFrame, rule: ValidationRule) -> tuple[int, pd.DataFrame]:
    """Returns (total_checked, violating_rows). Never mutates ``frame``."""
    if rule.kind is ValidationRuleKind.UNIQUENESS:
        column = _require_column(frame, rule.column)
        checked = frame.loc[frame[column].notna()]
        mask = checked.duplicated(subset=[column], keep=False)
        return len(checked), checked.loc[mask]
    if rule.kind is ValidationRuleKind.NONNEGATIVE:
        column = _require_column(frame, rule.column)
        numeric = pd.to_numeric(frame[column], errors="coerce")
        mask = numeric < 0
        return int(numeric.notna().sum()), frame.loc[mask.fillna(False)]
    if rule.kind is ValidationRuleKind.DATE_ORDER:
        before_column = _require_column(frame, rule.before_column)
        after_column = _require_column(frame, rule.after_column)
        before = pd.to_datetime(frame[before_column], errors="coerce", format="mixed")
        after = pd.to_datetime(frame[after_column], errors="coerce", format="mixed")
        valid_pair = before.notna() & after.notna()
        mask = valid_pair & (before > after)
        return int(valid_pair.sum()), frame.loc[mask]
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported validation rule kind.")


@router.post("/datasets/{dataset_id}/validation-rules/{rule_id}/run", response_model=ValidationRunResult)
def run_validation_rule(dataset_id: str, rule_id: str) -> ValidationRunResult:
    rule = rules.get(rule_id)
    stored = overview_store.get(dataset_id)
    total_checked, violating = _run_rule(stored.frame, rule)
    violation_count = len(violating)
    return ValidationRunResult(
        rule=rule, dataset_revision=stored.dataset.revision, total_checked=total_checked,
        violation_count=violation_count, passed=violation_count == 0,
        sample_violations=_sample(violating, SAMPLE_VIOLATIONS),
    )
