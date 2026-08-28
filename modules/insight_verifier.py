"""
Insight Verifier — a self-verifying safety net on top of Auto Analyst's
Gemini-written findings.

LLM-synthesized summaries can misstate a number even when the underlying
analysis was correct ("plausible but wrong" is the classic failure mode for
agentic EDA). Before a finding is shown to the user, this module recomputes
a broad set of real statistics straight from the DataFrame — row/column
counts, per-column means/medians/nulls, category shares, pairwise
correlations, and bounded group-by means — and checks every number quoted
in the finding against that reference set.

This is deliberately static and non-LLM: no extra Gemini calls, runs in
milliseconds, and never blocks the findings panel even if the check itself
hits an edge case (all-empty df, no numeric columns, etc).
"""

from __future__ import annotations

import re

import pandas as pd

MAX_GROUPBY_COLUMNS = 6  # cap combinatorial blowup on wide datasets
MAX_CATEGORIES_PER_GROUPBY = 50
RELATIVE_TOLERANCE = 0.03  # 3% relative slack for LLM rounding ("about 43%")
ABSOLUTE_TOLERANCE = 1.0  # absolute slack for small numbers / rounded percentages

_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*\s*%?")


def _parse_number(token: str) -> float | None:
    token = token.strip()
    token = token.rstrip("%").replace(",", "").strip()
    if not token or token in ("-", "."):
        return None
    try:
        return float(token)
    except ValueError:
        return None


def extract_numbers(text: str) -> list[float]:
    """Pull every number (including percentages, comma-grouped thousands)
    out of a finding string, in the order they appear.
    """
    numbers = []
    for match in _NUMBER_RE.findall(text):
        value = _parse_number(match)
        if value is not None:
            numbers.append(value)
    return numbers


def _add_rounded(numbers: set[float], value) -> None:
    if value is None or pd.isna(value):
        return
    value = float(value)
    numbers.add(round(value, 2))
    numbers.add(round(value, 1))
    numbers.add(round(value, 0))


def compute_reference_numbers(df: pd.DataFrame, column_types: dict) -> set[float]:
    """Recompute a broad set of real numbers straight from the DataFrame —
    the "ground truth" a finding's numeric claims get checked against.

    Deliberately over-inclusive (it's a safety net, not a strict grader):
    missing a checkable number just means a finding falls back to
    "unverifiable" rather than "flagged" wouldn't be fair.
    """
    numbers: set[float] = set()
    n_rows = len(df)
    numbers.add(float(n_rows))
    numbers.add(float(len(df.columns)))
    if n_rows == 0:
        return numbers

    dup_count = int(df.duplicated().sum())
    numbers.add(float(dup_count))
    _add_rounded(numbers, dup_count / n_rows * 100)

    numeric_cols = [c for c, t in column_types.items() if t == "numeric" and c in df.columns]
    categorical_cols = [c for c, t in column_types.items() if t == "categorical" and c in df.columns]

    for col in numeric_cols:
        series = df[col].dropna()
        null_count = int(df[col].isna().sum())
        numbers.add(float(null_count))
        _add_rounded(numbers, null_count / n_rows * 100)
        if series.empty:
            continue
        for stat_value in (series.mean(), series.median(), series.std(), series.min(), series.max(), series.sum()):
            _add_rounded(numbers, stat_value)

    for col in categorical_cols:
        counts = df[col].value_counts(dropna=True)
        for value_count in counts.head(20):
            numbers.add(float(value_count))
            _add_rounded(numbers, value_count / n_rows * 100)

    if len(numeric_cols) >= 2:
        try:
            corr = df[numeric_cols].corr(numeric_only=True)
            for i, col_a in enumerate(numeric_cols):
                for col_b in numeric_cols[i + 1 :]:
                    value = corr.loc[col_a, col_b]
                    if pd.notna(value):
                        _add_rounded(numbers, value)
                        _add_rounded(numbers, value * 100)  # correlations often quoted as %
        except Exception:
            pass

    # Bounded group-by means — the most common shape of a "segment" finding
    # ("average order value is highest for segment B at 84.2").
    for cat_col in categorical_cols[:MAX_GROUPBY_COLUMNS]:
        if df[cat_col].nunique(dropna=True) > MAX_CATEGORIES_PER_GROUPBY:
            continue
        for num_col in numeric_cols[:MAX_GROUPBY_COLUMNS]:
            try:
                grouped = df.groupby(cat_col)[num_col].mean(numeric_only=True)
            except Exception:
                continue
            for value in grouped:
                _add_rounded(numbers, value)

    return numbers


def _is_close(value: float, reference_numbers: set[float]) -> bool:
    for ref in reference_numbers:
        tol = max(ABSOLUTE_TOLERANCE, abs(ref) * RELATIVE_TOLERANCE)
        if abs(value - ref) <= tol:
            return True
    return False


def verify_finding(text: str, reference_numbers: set[float]) -> dict:
    """Check one finding's numeric claims against the reference set.

    status is one of:
      - "confirmed": every number in the finding matched a real recomputed value
      - "flagged": at least one number didn't match anything recomputable
      - "unverifiable": no numeric claim to check (finding is still shown, just unbadged)
    """
    numbers = extract_numbers(text)
    if not numbers:
        return {"status": "unverifiable", "checked": 0, "matched": 0}

    matched = sum(1 for n in numbers if _is_close(n, reference_numbers))
    status = "confirmed" if matched == len(numbers) else "flagged"
    return {"status": status, "checked": len(numbers), "matched": matched}


def verify_findings(df: pd.DataFrame, column_types: dict, findings: list[str]) -> list[dict]:
    """Verify every Auto Analyst finding against the DataFrame. Returns one
    result dict per finding, in the same order as `findings`.

    Never raises — any internal error (empty df, weird dtypes) degrades to
    "unverifiable" for every finding rather than breaking the panel.
    """
    try:
        reference_numbers = compute_reference_numbers(df, column_types or {})
    except Exception:
        return [{"status": "unverifiable", "checked": 0, "matched": 0} for _ in findings]
    return [verify_finding(f, reference_numbers) for f in findings]
