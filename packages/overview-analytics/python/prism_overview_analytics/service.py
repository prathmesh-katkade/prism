"""Deterministic dataset profiling with no UI, session, or transport dependencies."""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from typing import Any, Optional, cast

import numpy as np
import pandas as pd

ANALYTICS_SERVICE_VERSION = "overview-analytics/1.0.0"
HEALTH_COMPONENT_WEIGHTS = {
    "completeness": 30,
    "consistency": 25,
    "uniqueness": 15,
    "validity": 15,
    "outlier_burden": 15,
}
ID_LIKE_UNIQUE_RATIO = 0.9
NEAR_CONSTANT_RATIO = 0.95
PII_MATCH_THRESHOLD_PCT = 30.0
_EMAIL_RE = re.compile(r"^[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}$")
_PHONE_RE = re.compile(r"^\+?\d{0,3}[\s.\-]?\(?\d{2,4}\)?[\s.\-]?\d{3,4}[\s.\-]?\d{0,4}$")
_NAME_RE = re.compile(r"^[A-Z][a-z]+(?:\s[A-Z][a-z]+){1,2}$")
_AADHAAR_RE = re.compile(r"^\d{4}\s?\d{4}\s?\d{4}$")
_PAN_RE = re.compile(r"^[A-Z]{5}\d{4}[A-Z]$")
_GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z]\d[A-Z]\d[A-Z]$|^\d{2}[A-Z]{5}\d{4}[A-Z]\dZ[A-Z0-9]$")
_IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")
_INDIAN_MOBILE_RE = re.compile(r"^(?:\+?91[\-\s]?|0)?[6-9]\d{9}$")


def _looks_like_datetime(series: pd.Series) -> bool:
    non_null = series.dropna()
    if non_null.empty or pd.to_numeric(non_null, errors="coerce").notna().mean() > 0.9:
        return False
    return bool(pd.to_datetime(non_null, errors="coerce", format="mixed").notna().mean() > 0.9)


def detect_column_types(df: pd.DataFrame) -> dict[str, str]:
    """Preserves the legacy Overview semantic type rules exactly."""
    column_types: dict[str, str] = {}
    for col in df.columns:
        series = df[col]
        if series.isna().all():
            column_types[col] = "all_null"
        elif pd.api.types.is_bool_dtype(series):
            column_types[col] = "categorical"
        elif pd.api.types.is_numeric_dtype(series):
            column_types[col] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series) or _looks_like_datetime(series):
            column_types[col] = "datetime"
        else:
            non_null = series.dropna()
            unique_ratio = non_null.nunique() / len(non_null) if len(non_null) else 0
            column_types[col] = "categorical" if non_null.nunique() <= 50 and unique_ratio < 0.5 else "text"
    return column_types


def _format_bytes(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} TB"


def detect_outliers_iqr(series: pd.Series) -> tuple[int, float]:
    clean = series.dropna()
    if len(clean) < 4:
        return 0, 0.0
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    outliers = clean[(clean < q1 - 1.5 * iqr) | (clean > q3 + 1.5 * iqr)]
    return len(outliers), round(100 * len(outliers) / len(clean), 2)


def get_data_quality_report(df: pd.DataFrame, column_types: dict[str, str]) -> dict[str, Any]:
    n_rows, n_cols = df.shape
    missing_by_column = {col: round(100 * df[col].isna().sum() / n_rows, 2) for col in df.columns}
    outliers = {
        col: {"count": count, "pct": pct}
        for col, ctype in column_types.items()
        if ctype == "numeric"
        for count, pct in (detect_outliers_iqr(df[col]),)
    }
    total_cells = n_rows * n_cols
    return {
        "n_rows": n_rows,
        "n_cols": n_cols,
        "missing_by_column": missing_by_column,
        "total_missing_cells": int(df.isna().sum().sum()),
        "total_missing_pct": round(100 * df.isna().sum().sum() / total_cells, 2) if total_cells else 0.0,
        "duplicate_rows": int(df.duplicated().sum()),
        "memory_usage": _format_bytes(df.memory_usage(deep=True).sum()),
        "outliers": outliers,
        "all_null_columns": [c for c, t in column_types.items() if t == "all_null"],
    }


def get_health_breakdown(
    quality_report: dict[str, Any], column_types: dict[str, str], pii_detected: bool = False
) -> dict[str, int]:
    n_rows, n_cols = quality_report["n_rows"] or 1, quality_report["n_cols"] or 1
    completeness = 30 * (1 - quality_report["total_missing_pct"] / 100)
    consistency = 25 * (1 - 0.5 * (sum(t == "text" for t in column_types.values()) / n_cols))
    uniqueness = 15 * (1 - (100 * quality_report["duplicate_rows"] / n_rows) / 100)
    validity = 15.0 - (7 if pii_detected else 0) - min(len(quality_report["all_null_columns"]) * 3, 8)
    outlier_pcts = [info["pct"] for info in quality_report["outliers"].values()]
    average_outlier_pct = sum(outlier_pcts) / len(outlier_pcts) if outlier_pcts else 0
    outlier_burden = 15 * (1 - min(average_outlier_pct, 30) / 30)
    components = {
        "completeness": round(max(0, min(30, completeness))),
        "consistency": round(max(0, min(25, consistency))),
        "uniqueness": round(max(0, min(15, uniqueness))),
        "validity": round(max(0, min(15, validity))),
        "outlier_burden": round(max(0, min(15, outlier_burden))),
    }
    components["total"] = max(0, min(100, sum(components.values())))
    return components


def get_health_score(quality_report: dict[str, Any], column_types: Optional[dict[str, str]] = None, pii_detected: bool = False) -> int:
    return get_health_breakdown(quality_report, column_types or {}, pii_detected)["total"]


def _looks_like_phone(value: str) -> bool:
    return bool(_PHONE_RE.match(value.strip()) and 7 <= sum(char.isdigit() for char in value) <= 15)


def detect_pii_present(df: pd.DataFrame, column_types: dict[str, str]) -> bool:
    """Legacy-equivalent privacy signal used only by the Overview health score.

    Raw PII is never emitted by this package; the legacy vault remains the masking UI.
    """
    for column, semantic_type in column_types.items():
        if semantic_type not in ("text", "categorical"):
            continue
        values = df[column].dropna().astype(str)
        if values.empty:
            continue
        def match_rate(check: Any, values_for_column: pd.Series = values) -> float:
            return float(100 * values_for_column.apply(lambda value: bool(check(value.strip()))).mean())
        is_name_column = any(hint in column.lower() for hint in ("name", "employee", "customer", "client", "contact", "person"))
        checks = (
            lambda value: _AADHAAR_RE.match(value), lambda value: _PAN_RE.match(value.upper()),
            lambda value: _GSTIN_RE.match(value.upper()), lambda value: _IFSC_RE.match(value.upper()),
            lambda value: _INDIAN_MOBILE_RE.match(value.replace(" ", "")), lambda value: _EMAIL_RE.match(value),
            _looks_like_phone, _NAME_RE.match if is_name_column else lambda value: False,
        )
        if any(match_rate(check) >= PII_MATCH_THRESHOLD_PCT for check in checks):
            return True
    return False


def _describe_skewness(skew: float) -> str:
    if pd.isna(skew):
        return "not enough data"
    direction, magnitude = ("right" if skew > 0 else "left"), abs(skew)
    if magnitude < 0.5:
        return "approximately symmetric"
    return f"moderately {direction}-skewed" if magnitude < 1 else f"highly {direction}-skewed"


def _describe_kurtosis(kurt: float) -> str:
    if pd.isna(kurt):
        return "not enough data"
    if kurt > 3:
        return "heavy-tailed (prone to extreme outliers)"
    return "light-tailed (unusually flat distribution)" if kurt < -1 else "close to normal tail weight"


def _constant_status(series: pd.Series) -> Optional[str]:
    non_null = series.dropna()
    if len(non_null) < 2:
        return None
    top_ratio = non_null.value_counts(normalize=True).iloc[0]
    if top_ratio >= 1:
        return "constant"
    return "near_constant" if top_ratio >= NEAR_CONSTANT_RATIO else None


def _is_id_like(series: pd.Series) -> bool:
    if pd.api.types.is_float_dtype(series) or pd.api.types.is_datetime64_any_dtype(series):
        return False
    non_null = series.dropna()
    return bool(not non_null.empty and non_null.nunique() / len(non_null) > ID_LIKE_UNIQUE_RATIO)


def profile_column(df: pd.DataFrame, column: str, column_types: dict[str, str], quality_report: dict[str, Any]) -> dict[str, Any]:
    ctype, series = column_types.get(column, "text"), df[column]
    missing_pct = quality_report["missing_by_column"].get(column, 0.0)
    issues: list[str] = []
    warnings: list[str] = []
    if ctype == "all_null":
        issues.append("Column is entirely empty.")
    constant_status = _constant_status(series)
    if constant_status == "constant":
        issues.append("Column has a single constant value — consider dropping it.")
    elif constant_status == "near_constant":
        warnings.append("Column is >95% one value (near-constant) — consider dropping it.")
    id_like = _is_id_like(series)
    if id_like and ctype != "all_null":
        warnings.append("Looks like an ID column (>90% unique values) — excluded from auto-charts.")
    skew_label = kurt_label = None
    if ctype == "numeric":
        skew_label, kurt_label = _describe_skewness(series.skew()), _describe_kurtosis(series.kurt())
        if "highly" in skew_label:
            warnings.append(f"Distribution is {skew_label}.")
    if missing_pct >= 50:
        issues.append(f"{missing_pct}% of values are missing.")
    elif missing_pct >= 10:
        warnings.append(f"{missing_pct}% of values are missing.")
    outlier_info = quality_report["outliers"].get(column)
    if outlier_info and outlier_info["pct"] >= 10:
        warnings.append(f"{outlier_info['pct']}% of values are outliers (IQR method).")
    return {
        "column": column, "type": ctype, "health": "issue" if issues else "warning" if warnings else "good",
        "issues": issues, "warnings": warnings, "skew_label": skew_label, "kurt_label": kurt_label,
        "id_like": id_like, "constant_status": constant_status, "missing_pct": missing_pct,
    }


def profile_all_columns(df: pd.DataFrame, column_types: dict[str, str], quality_report: dict[str, Any]) -> list[dict[str, Any]]:
    return [profile_column(df, column, column_types, quality_report) for column in df.columns]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, (float, np.floating)):
        return None if math.isnan(value) or math.isinf(value) else round(float(value), 6)
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return str(value)
    if pd.isna(value):
        return None
    return str(value)


def _distribution(series: pd.Series, limit: int = 12) -> list[dict[str, Any]]:
    counts = series.value_counts(dropna=True).head(limit)
    return [{"label": _json_value(label), "count": int(count)} for label, count in counts.items()]


def _column_summary(df: pd.DataFrame, column: str, profile: dict[str, Any]) -> dict[str, Any]:
    series = df[column]
    summary: dict[str, Any] = {
        "name": column, "semantic_type": profile["type"], "missing_pct": profile["missing_pct"],
        "unique_count": int(series.nunique(dropna=True)), "health": profile["health"],
        "issues": profile["issues"], "warnings": profile["warnings"], "distribution": _distribution(series),
    }
    if profile["type"] == "numeric":
        clean = series.dropna()
        summary["numeric"] = {
            "min": _json_value(clean.min()) if not clean.empty else None,
            "max": _json_value(clean.max()) if not clean.empty else None,
            "mean": _json_value(clean.mean()) if not clean.empty else None,
            "median": _json_value(clean.median()) if not clean.empty else None,
            "skewness": profile["skew_label"], "kurtosis": profile["kurt_label"],
        }
    return summary


def _correlations(df: pd.DataFrame, column_types: dict[str, str], limit: int = 12) -> list[dict[str, Any]]:
    numeric = [col for col, kind in column_types.items() if kind == "numeric"]
    if len(numeric) < 2:
        return []
    matrix = df[numeric].corr()
    pairs: list[dict[str, Any]] = [
        {"left": numeric[i], "right": numeric[j], "coefficient": round(float(matrix.iloc[i, j]), 6)}
        for i in range(len(numeric)) for j in range(i + 1, len(numeric)) if pd.notna(matrix.iloc[i, j])
    ]
    return sorted(pairs, key=lambda pair: abs(float(cast(Any, pair["coefficient"]))), reverse=True)[:limit]


def _suggestions(quality: dict[str, Any], profiles: Iterable[dict[str, Any]], correlations: list[dict[str, Any]]) -> list[dict[str, str]]:
    suggestions: list[dict[str, str]] = []
    if quality["total_missing_pct"] > 0 or quality["duplicate_rows"] > 0 or quality["all_null_columns"]:
        suggestions.append({"workflow": "clean", "reason": "Resolve missing values, duplicates, or empty columns before downstream analysis."})
    if correlations:
        pair = correlations[0]
        suggestions.append({"workflow": "visualize", "reason": f"Explore the {pair['left']} / {pair['right']} relationship (r={pair['coefficient']:.2f})."})
    if any(profile["type"] == "numeric" for profile in profiles):
        suggestions.append({"workflow": "stats", "reason": "Numeric variables are available for hypothesis tests and distribution checks."})
    suggestions.append({"workflow": "sql-lab", "reason": "Query and segment the active dataset with the legacy SQL Lab bridge."})
    suggestions.append({"workflow": "ai-analyst", "reason": "Ask a grounded follow-up question using the dataset profile as context."})
    return suggestions


def build_overview(df: pd.DataFrame, pii_detected: Optional[bool] = None) -> dict[str, Any]:
    """Build the complete serializable Overview payload without exposing raw rows."""
    column_types = detect_column_types(df)
    pii_detected = detect_pii_present(df, column_types) if pii_detected is None else pii_detected
    quality = get_data_quality_report(df, column_types)
    profiles = profile_all_columns(df, column_types, quality)
    correlations = _correlations(df, column_types)
    return {
        "quality": quality,
        "health": get_health_breakdown(quality, column_types, pii_detected),
        "columns": [_column_summary(df, profile["column"], profile) for profile in profiles],
        "correlations": correlations,
        "suggestions": _suggestions(quality, profiles, correlations),
    }
