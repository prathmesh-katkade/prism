"""Phase 7A native Stats Lab: deterministic guided statistical testing.

Ports ``modules/stats_lab.py`` onto the shared ``DatasetStore`` so a test always runs
against the same dataset revision Overview/SQL Lab/AI Analyst/Clean/Visualize are
showing. Test selection is deterministic (dtype + category count + sample size), never
LLM-decided; Atlas may explain the deterministic choice but never invents or alters a
statistic. Every result carries provenance (``dataset_id``, ``dataset_revision``,
``source_fingerprint``) and an explicit evidence statement that never equates
"not significant" with "no relationship" — only with "not enough evidence found".
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, Query, status
from prism_api_contracts import (
    AtlasEvidence,
    AtlasStatsAction,
    AtlasStatsRequest,
    AtlasStatsResponse,
    OverviewProvenance,
    StatNormalityCheck,
    StatSuggestionResponse,
    StatTestKind,
    StatTestRequest,
    StatTestResult,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION, detect_column_types

from .overview import StoredDataset
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/stats", tags=["stats"])

# Beyond this many categories, a group comparison stops being meaningful (too many
# tiny groups) — mirrors modules/stats_lab.py's MAX_GROUPS_FOR_TEST exactly.
MAX_GROUPS_FOR_TEST = 10

# scipy.stats.shapiro is only validated up to a few thousand points; beyond that test
# a fixed random subsample rather than the full column — mirrors SHAPIRO_MAX_N.
SHAPIRO_MAX_N = 5000

_EFFECT_SIZE_THRESHOLDS: dict[StatTestKind, list[tuple[float, str]]] = {
    StatTestKind.TTEST: [(0.2, "small"), (0.5, "medium"), (0.8, "large")],
    StatTestKind.ANOVA: [(0.01, "small"), (0.06, "medium"), (0.14, "large")],
    StatTestKind.CHI2: [(0.1, "small"), (0.3, "medium"), (0.5, "large")],
    StatTestKind.PEARSON: [(0.1, "small"), (0.3, "medium"), (0.5, "large")],
}

_SUBJECT_BY_TEST: dict[StatTestKind, str] = {
    StatTestKind.TTEST: "difference between the two group means",
    StatTestKind.ANOVA: "difference among the group means",
    StatTestKind.CHI2: "association between the two columns",
    StatTestKind.PEARSON: "correlation",
}


def _effect_size_label(test: StatTestKind, value: float) -> str:
    """Conventional small/medium/large label for a test's effect-size statistic."""
    magnitude = abs(value)
    label = "negligible"
    for cutoff, name in _EFFECT_SIZE_THRESHOLDS[test]:
        if magnitude >= cutoff:
            label = name
    return label


def _shapiro_check(subject: str, values: "np.ndarray[Any, Any]") -> StatNormalityCheck:
    """Shapiro-Wilk normality check, surfaced as context rather than a pass/fail gate.

    Large samples can make trivial deviations from normality "significant" — the note
    field exists so the frontend/Atlas can explain that nuance instead of a bare
    true/false verdict standing in for it.
    """
    from scipy import stats as scipy_stats

    n = len(values)
    if n < 3:
        return StatNormalityCheck(subject=subject, note="Too few values to test normality.")

    note = ""
    sample = values
    if n > SHAPIRO_MAX_N:
        sample = np.random.RandomState(0).choice(values, SHAPIRO_MAX_N, replace=False)
        note = f"Sampled {SHAPIRO_MAX_N:,} of {n:,} values for the normality check."

    try:
        _, p = scipy_stats.shapiro(sample)
    except Exception:
        return StatNormalityCheck(subject=subject, note="Normality test failed to run.")
    return StatNormalityCheck(subject=subject, p_value=float(p), is_normal=bool(p >= 0.05), note=note)


def suggest_test(frame: pd.DataFrame, col_a: str, col_b: str) -> StatSuggestionResponse:
    """Pick the right test for two columns based on their detected types.

    Deterministic: dtype, category count, and sample size decide the test — never an
    LLM. Mirrors ``modules/stats_lab.py::suggest_test`` exactly.
    """
    column_types = detect_column_types(frame)
    type_a = column_types.get(col_a)
    type_b = column_types.get(col_b)

    if type_a == "numeric" and type_b == "numeric":
        return StatSuggestionResponse(
            col_a=col_a, col_b=col_b, test=StatTestKind.PEARSON,
            reason=f"Both {col_a!r} and {col_b!r} are numeric — testing whether they're linearly correlated.",
        )

    if {type_a, type_b} == {"numeric", "categorical"}:
        numeric_col, cat_col = (col_a, col_b) if type_a == "numeric" else (col_b, col_a)
        n_groups = frame[cat_col].dropna().nunique()
        if n_groups < 2:
            return StatSuggestionResponse(col_a=col_a, col_b=col_b, error=f"{cat_col!r} needs at least 2 distinct categories to compare groups.")
        if n_groups > MAX_GROUPS_FOR_TEST:
            return StatSuggestionResponse(
                col_a=col_a, col_b=col_b,
                error=f"{cat_col!r} has {n_groups} categories — too many for a meaningful group comparison (max {MAX_GROUPS_FOR_TEST}). Pick a lower-cardinality column.",
            )
        if n_groups == 2:
            return StatSuggestionResponse(
                col_a=col_a, col_b=col_b, test=StatTestKind.TTEST, numeric_col=numeric_col, cat_col=cat_col,
                reason=f"{cat_col!r} splits the data into exactly 2 groups — comparing {numeric_col!r} means with a t-test.",
            )
        return StatSuggestionResponse(
            col_a=col_a, col_b=col_b, test=StatTestKind.ANOVA, numeric_col=numeric_col, cat_col=cat_col,
            reason=f"{cat_col!r} splits the data into {n_groups} groups — comparing {numeric_col!r} means with one-way ANOVA.",
        )

    if type_a == "categorical" and type_b == "categorical":
        return StatSuggestionResponse(
            col_a=col_a, col_b=col_b, test=StatTestKind.CHI2,
            reason=f"Both {col_a!r} and {col_b!r} are categorical — testing whether they're independent with a chi-square test.",
        )

    return StatSuggestionResponse(col_a=col_a, col_b=col_b, error=f"No suitable test for a {type_a!r} column and a {type_b!r} column. Pick two numeric or categorical columns.")


def _evidence_statement(test: StatTestKind, significant: bool) -> str:
    subject = _SUBJECT_BY_TEST[test]
    if significant:
        return (
            f"This test found statistically significant evidence of a {subject} in this sample. "
            "Statistical significance is not the same as practical importance or causation — "
            "read it together with the effect size, the assumption warnings below, and domain context."
        )
    return (
        f"The available analysis did not find sufficient evidence of a {subject} at the 0.05 "
        f"threshold. This does not establish that no {subject} exists — only that this test, on "
        "this sample, did not detect one. A larger sample, a different test, or a different set "
        "of columns could still reveal one."
    )


def _interpretation(test: StatTestKind, p_value: float, effect_size_label: str, effect_size_name: str, effect_size: float) -> str:
    subject = _SUBJECT_BY_TEST[test]
    significant = p_value < 0.05
    headline = f"Significant {subject} detected" if significant else f"No significant {subject} detected"
    p_str = f"p={p_value:.4f}" if p_value >= 0.0001 else "p<0.0001"
    return f"{headline} ({p_str}, {effect_size_label} effect, {effect_size_name}={effect_size:.2f})."


def _normality_warnings(checks: list[StatNormalityCheck]) -> list[str]:
    warnings: list[str] = []
    for check in checks:
        if check.is_normal is False:
            warnings.append(
                f"{check.subject!r} does not look normally distributed (Shapiro-Wilk p={check.p_value:.4f}) — "
                "this test assumes roughly normal data, so treat the result with some caution."
            )
        if check.note:
            warnings.append(f"{check.subject!r}: {check.note}")
    return warnings


def _provenance(stored: StoredDataset, method: str, parameters: dict[str, Any]) -> OverviewProvenance:
    return OverviewProvenance(
        source_fingerprint=stored.source_fingerprint,
        dataset_revision=stored.dataset.revision,
        parameters={"method": method, **parameters},
        service_version=ANALYTICS_SERVICE_VERSION,
        computed_at=datetime.now(timezone.utc),
    )


def _run_ttest(stored: StoredDataset, numeric_col: str, cat_col: str) -> StatTestResult:
    from scipy import stats as scipy_stats

    frame = stored.frame
    clean = frame[[numeric_col, cat_col]].dropna()
    levels = sorted(clean[cat_col].unique(), key=str)
    if len(levels) != 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"{cat_col!r} must have exactly 2 categories for a t-test (found {len(levels)}).")

    group1 = clean.loc[clean[cat_col] == levels[0], numeric_col].to_numpy()
    group2 = clean.loc[clean[cat_col] == levels[1], numeric_col].to_numpy()
    if len(group1) < 2 or len(group2) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Each group needs at least 2 values to run a t-test.")

    stat, p_value = scipy_stats.ttest_ind(group1, group2, equal_var=False)
    pooled_std = np.sqrt((group1.std(ddof=1) ** 2 + group2.std(ddof=1) ** 2) / 2)
    cohens_d = float((group1.mean() - group2.mean()) / pooled_std) if pooled_std > 0 else 0.0
    label1, label2 = str(levels[0]), str(levels[1])
    normality = [_shapiro_check(label1, group1), _shapiro_check(label2, group2)]
    significant = bool(p_value < 0.05)
    effect_label = _effect_size_label(StatTestKind.TTEST, cohens_d)

    return StatTestResult(
        test=StatTestKind.TTEST, statistic=float(stat), p_value=float(p_value),
        effect_size=cohens_d, effect_size_name="Cohen's d", effect_size_label=effect_label,
        groups={label1: len(group1), label2: len(group2)},
        means={label1: float(group1.mean()), label2: float(group2.mean())},
        normality=normality, significant=significant,
        interpretation=_interpretation(StatTestKind.TTEST, float(p_value), effect_label, "Cohen's d", cohens_d),
        evidence_statement=_evidence_statement(StatTestKind.TTEST, significant),
        warnings=_normality_warnings(normality),
        provenance=_provenance(stored, "ttest", {"numeric_col": numeric_col, "cat_col": cat_col}),
    )


def _run_anova(stored: StoredDataset, numeric_col: str, cat_col: str) -> StatTestResult:
    from scipy import stats as scipy_stats

    frame = stored.frame
    clean = frame[[numeric_col, cat_col]].dropna()
    groups = {str(name): g[numeric_col].to_numpy() for name, g in clean.groupby(cat_col) if len(g) >= 2}
    if len(groups) < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Need at least 2 groups with 2+ values each in {cat_col!r}.")

    stat, p_value = scipy_stats.f_oneway(*groups.values())
    grand_mean = clean[numeric_col].mean()
    ss_between = sum(len(g) * (g.mean() - grand_mean) ** 2 for g in groups.values())
    ss_total = ((clean[numeric_col] - grand_mean) ** 2).sum()
    eta_sq = float(ss_between / ss_total) if ss_total > 0 else 0.0
    normality = [_shapiro_check(name, g) for name, g in groups.items()]
    significant = bool(p_value < 0.05)
    effect_label = _effect_size_label(StatTestKind.ANOVA, eta_sq)

    return StatTestResult(
        test=StatTestKind.ANOVA, statistic=float(stat), p_value=float(p_value),
        effect_size=eta_sq, effect_size_name="eta-squared", effect_size_label=effect_label,
        groups={name: len(g) for name, g in groups.items()},
        means={name: float(g.mean()) for name, g in groups.items()},
        normality=normality, significant=significant,
        interpretation=_interpretation(StatTestKind.ANOVA, float(p_value), effect_label, "eta-squared", eta_sq),
        evidence_statement=_evidence_statement(StatTestKind.ANOVA, significant),
        warnings=_normality_warnings(normality),
        provenance=_provenance(stored, "anova", {"numeric_col": numeric_col, "cat_col": cat_col}),
    )


def _run_chi2(stored: StoredDataset, col_a: str, col_b: str) -> StatTestResult:
    from scipy import stats as scipy_stats

    frame = stored.frame
    clean = frame[[col_a, col_b]].dropna()
    table = pd.crosstab(clean[col_a], clean[col_b])
    if table.shape[0] < 2 or table.shape[1] < 2:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Need at least 2 categories in both {col_a!r} and {col_b!r}.")

    stat, p_value, dof, expected = scipy_stats.chi2_contingency(table)
    n = table.to_numpy().sum()
    min_dim = min(table.shape) - 1
    cramers_v = float(np.sqrt((stat / n) / min_dim)) if n > 0 and min_dim > 0 else 0.0
    low_expected_pct = float((expected < 5).mean() * 100)
    significant = bool(p_value < 0.05)
    effect_label = _effect_size_label(StatTestKind.CHI2, cramers_v)

    warnings: list[str] = []
    if low_expected_pct > 20:
        warnings.append(
            f"{low_expected_pct:.0f}% of expected cell counts are below 5 — the chi-square approximation "
            "may be unreliable here; consider grouping rare categories together."
        )

    return StatTestResult(
        test=StatTestKind.CHI2, statistic=float(stat), p_value=float(p_value), dof=int(dof),
        effect_size=cramers_v, effect_size_name="Cramer's V", effect_size_label=effect_label,
        low_expected_pct=low_expected_pct, significant=significant,
        interpretation=_interpretation(StatTestKind.CHI2, float(p_value), effect_label, "Cramer's V", cramers_v),
        evidence_statement=_evidence_statement(StatTestKind.CHI2, significant),
        warnings=warnings,
        provenance=_provenance(stored, "chi2", {"col_a": col_a, "col_b": col_b}),
    )


def _run_pearson(stored: StoredDataset, col_a: str, col_b: str) -> StatTestResult:
    from scipy import stats as scipy_stats

    frame = stored.frame
    clean = frame[[col_a, col_b]].dropna()
    if len(clean) < 3:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Need at least 3 paired values to test correlation significance.")

    r, p_value = scipy_stats.pearsonr(clean[col_a], clean[col_b])
    normality = [_shapiro_check(col_a, clean[col_a].to_numpy()), _shapiro_check(col_b, clean[col_b].to_numpy())]
    significant = bool(p_value < 0.05)
    effect_label = _effect_size_label(StatTestKind.PEARSON, float(r))

    return StatTestResult(
        test=StatTestKind.PEARSON, statistic=float(r), p_value=float(p_value),
        effect_size=float(r), effect_size_name="Pearson r", effect_size_label=effect_label,
        n=len(clean), normality=normality, significant=significant,
        interpretation=_interpretation(StatTestKind.PEARSON, float(p_value), effect_label, "Pearson r", float(r)),
        evidence_statement=_evidence_statement(StatTestKind.PEARSON, significant),
        warnings=_normality_warnings(normality),
        provenance=_provenance(stored, "pearson", {"col_a": col_a, "col_b": col_b}),
    )


def run_test(stored: StoredDataset, request: StatTestRequest) -> StatTestResult:
    """Dispatch to the right test based on a (typically suggest_test-derived) request."""
    if request.test is StatTestKind.TTEST:
        if not request.numeric_col or not request.cat_col:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="A t-test needs numeric_col and cat_col.")
        return _run_ttest(stored, request.numeric_col, request.cat_col)
    if request.test is StatTestKind.ANOVA:
        if not request.numeric_col or not request.cat_col:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="ANOVA needs numeric_col and cat_col.")
        return _run_anova(stored, request.numeric_col, request.cat_col)
    if request.test is StatTestKind.CHI2:
        return _run_chi2(stored, request.col_a, request.col_b)
    if request.test is StatTestKind.PEARSON:
        return _run_pearson(stored, request.col_a, request.col_b)
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported test.")


@router.get("/datasets/{dataset_id}/suggest", response_model=StatSuggestionResponse)
def get_suggestion(dataset_id: str, column_a: str = Query(min_length=1), column_b: str = Query(min_length=1)) -> StatSuggestionResponse:
    stored = overview_store.get(dataset_id)
    for column in (column_a, column_b):
        if column not in stored.frame.columns:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset.")
    return suggest_test(stored.frame, column_a, column_b)


@router.post("/datasets/{dataset_id}/run", response_model=StatTestResult)
def run(dataset_id: str, request: StatTestRequest) -> StatTestResult:
    stored = overview_store.get(dataset_id)
    for column in (request.col_a, request.col_b):
        if column not in stored.frame.columns:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset.")
    return run_test(stored, request)


@router.post("/datasets/{dataset_id}/atlas", response_model=AtlasStatsResponse)
def atlas_action(dataset_id: str, request: AtlasStatsRequest) -> AtlasStatsResponse:
    """Atlas may explain the deterministic test/assumptions/effect size, but the
    numbers themselves always come from ``run_test`` — Atlas never invents or alters
    a statistic, and never asserts causation from a correlation or group difference.
    """
    stored = overview_store.get(dataset_id)
    for column in (request.col_a, request.col_b):
        if column not in stored.frame.columns:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset.")
    suggestion = suggest_test(stored.frame, request.col_a, request.col_b)
    uncertainty = "This explanation describes a deterministic statistical result; it does not establish causation, and Atlas cannot alter the underlying computation."

    if suggestion.error or suggestion.test is None:
        return AtlasStatsResponse(action=request.action, summary=f"No test can be suggested for these columns: {suggestion.error}", uncertainty=uncertainty, evidence=[])

    if request.action is AtlasStatsAction.EXPLAIN_TEST:
        return AtlasStatsResponse(
            action=request.action, summary=suggestion.reason or "", uncertainty=uncertainty,
            evidence=[AtlasEvidence(label="Selected test", value=suggestion.test.value), AtlasEvidence(label="Column A", value=request.col_a), AtlasEvidence(label="Column B", value=request.col_b)],
        )

    result = run_test(stored, StatTestRequest(test=suggestion.test, col_a=request.col_a, col_b=request.col_b, numeric_col=suggestion.numeric_col, cat_col=suggestion.cat_col))

    if request.action is AtlasStatsAction.EXPLAIN_ASSUMPTIONS:
        summary = "; ".join(result.warnings) if result.warnings else "No assumption warnings were raised for this test on this sample."
        return AtlasStatsResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=[AtlasEvidence(label=check.subject, value=("normal" if check.is_normal else "not confirmed normal") if check.is_normal is not None else "not tested") for check in result.normality])

    if request.action is AtlasStatsAction.EXPLAIN_EFFECT_SIZE:
        return AtlasStatsResponse(
            action=request.action,
            summary=f"{result.effect_size_name}={result.effect_size:.2f} is conventionally {result.effect_size_label}. Effect size measures magnitude, independent of sample size — a tiny effect can still be statistically significant in a large sample, and a large effect can fail to reach significance in a small one.",
            uncertainty=uncertainty,
            evidence=[AtlasEvidence(label="Effect size", value=f"{result.effect_size:.6f}"), AtlasEvidence(label="Convention", value=result.effect_size_label)],
        )

    # RECOMMEND_NEXT_STEP
    next_step = "Inspect the raw distribution in Overview before drawing conclusions." if not result.significant else "Consider whether the effect size is practically meaningful, not just statistically detectable, before acting on this result."
    return AtlasStatsResponse(action=request.action, summary=next_step, uncertainty=uncertainty, evidence=[AtlasEvidence(label="p-value", value=f"{result.p_value:.4f}"), AtlasEvidence(label="Effect size", value=result.effect_size_label)])
