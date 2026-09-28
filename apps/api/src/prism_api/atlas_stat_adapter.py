"""Atlas's declared statistical work through the tested Stats Lab service."""

from __future__ import annotations

from fastapi import HTTPException
from prism_api_contracts import (
    AtlasStatAnalysis,
    StatSuggestionResponse,
    StatTestKind,
    StatTestRequest,
)

from . import stats
from .overview import store as dataset_store

POLICY_VERSION = "atlas-declared-stat-v1"
DESIGNS = {
    StatTestKind.TTEST: "independent_groups",
    StatTestKind.ANOVA: "one_way_groups",
    StatTestKind.PEARSON: "linear_association",
    StatTestKind.CHI2: "categorical_association",
}


def validate_analysis(dataset_id: str, analysis: AtlasStatAnalysis) -> StatSuggestionResponse:
    stored = dataset_store.get(dataset_id)
    if analysis.col_a == analysis.col_b:
        raise ValueError("Choose two distinct columns for a statistical test.")
    for name in (analysis.col_a, analysis.col_b):
        if name not in stored.frame.columns:
            raise ValueError(f"Column {name!r} is not in the active dataset schema.")
    if DESIGNS[analysis.test] != analysis.design:
        raise ValueError(f"{analysis.test.value} requires the {DESIGNS[analysis.test]} design declaration.")
    suggestion = stats.suggest_test(stored.frame, analysis.col_a, analysis.col_b)
    if suggestion.error or suggestion.test is not analysis.test:
        raise ValueError(suggestion.error or f"The declared {analysis.test.value} method does not match these column types and groups.")
    return suggestion


def execute_declared_test(dataset_id: str, analysis: AtlasStatAnalysis) -> dict[str, object]:
    stored = dataset_store.get(dataset_id)
    before = stored.dataset
    suggestion = validate_analysis(dataset_id, analysis)
    request = StatTestRequest(
        test=analysis.test, col_a=analysis.col_a, col_b=analysis.col_b,
        numeric_col=suggestion.numeric_col, cat_col=suggestion.cat_col,
    )
    try:
        result = stats.run_test(stored, request)
    except HTTPException as error:
        raise ValueError(str(error.detail)) from error
    after = dataset_store.get(dataset_id).dataset
    if before.revision != after.revision or before.source_fingerprint != after.source_fingerprint:
        raise ValueError("Dataset revision changed during statistical execution; result is stale.")
    analyzed = result.n if result.n is not None else sum(result.groups.values())
    return {
        "execution_ref": f"stats:{dataset_id}:r{before.revision}:{analysis.test.value}",
        "policy_version": POLICY_VERSION,
        "dataset_id": dataset_id,
        "dataset_revision": before.revision,
        "source_fingerprint": before.source_fingerprint,
        "method": analysis.test.value,
        "design": analysis.design,
        "col_a": analysis.col_a,
        "col_b": analysis.col_b,
        "input_rows": len(stored.frame),
        "analyzed_rows": analyzed,
        "excluded_rows": len(stored.frame) - analyzed,
        "result": result.model_dump(mode="json"),
        "limitations": ["Observational association does not establish causality.", *result.warnings],
    }
