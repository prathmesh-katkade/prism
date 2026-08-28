"""
Smart Type Coercion — detect text columns that actually encode numbers
(currency symbols, thousands separators, percent signs, K/M/B suffixes) and
convert them to true numeric columns with a before/after preview.
"""

from __future__ import annotations

import re

import pandas as pd

_CURRENCY_SYMBOLS = "₹$€£¥"
_SUFFIX_MULTIPLIERS = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}

# Matches values like: "$1,200.50"  "1.2K"  "85%"  "-€400"  "3M"  "1234"
_NUMERIC_LIKE_RE = re.compile(
    rf"^\s*-?\s*[{_CURRENCY_SYMBOLS}]?\s*-?[\d,]*\.?\d+\s*%?\s*[KMB]?\s*$", re.IGNORECASE
)

# Accounting-style negatives — "(1,234.56)" meaning -1234.56 — are common
# enough in financial exports (P&L statements, expense reports) to be worth
# a dedicated check rather than folding parens into the main regex above,
# which would make it noticeably harder to read.
_PAREN_NEGATIVE_RE = re.compile(r"^\((.*)\)$")

# A column qualifies as a "numeric candidate" if at least this share of its
# non-null values match the pattern above.
MATCH_THRESHOLD_PCT = 70.0


def _strip_paren_negative(text: str) -> tuple[str, bool]:
    """'(1,234.56)' -> ('1,234.56', True); anything else -> (text, False)."""
    m = _PAREN_NEGATIVE_RE.match(text)
    return (m.group(1), True) if m else (text, False)


def _looks_numeric_like(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    text, _ = _strip_paren_negative(value.strip())
    return bool(_NUMERIC_LIKE_RE.match(text))


def detect_numeric_candidates(df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Scan text/categorical columns for values that look like formatted numbers.

    Returns a list of {"column": str, "match_pct": float, "sample_before": [...]}
    for columns where most non-null values match the pattern.
    """
    candidates = []
    for col, ctype in column_types.items():
        if ctype not in ("text", "categorical"):
            continue
        non_null = df[col].dropna().astype(str)
        if non_null.empty:
            continue
        match_pct = 100 * non_null.apply(_looks_numeric_like).mean()
        if match_pct >= MATCH_THRESHOLD_PCT:
            candidates.append(
                {"column": col, "match_pct": round(match_pct, 1), "sample_before": non_null.head(5).tolist()}
            )
    return candidates


def parse_one(value) -> float:
    """Parse a single formatted-number string into a float. NaN on anything unparseable."""
    if pd.isna(value):
        return float("nan")
    text = str(value).strip()
    if not text:
        return float("nan")

    text, paren_negative = _strip_paren_negative(text)
    negative = paren_negative or text.startswith("-")
    text = text.lstrip("-").strip()
    for sym in _CURRENCY_SYMBOLS:
        text = text.replace(sym, "")
    is_percent = "%" in text
    text = text.replace("%", "").replace(",", "").strip()

    multiplier = 1
    if text and text[-1].upper() in _SUFFIX_MULTIPLIERS:
        multiplier = _SUFFIX_MULTIPLIERS[text[-1].upper()]
        text = text[:-1].strip()

    if not text:
        return float("nan")
    try:
        result = float(text) * multiplier
    except ValueError:
        return float("nan")

    if is_percent:
        result = result / 100
    return -result if negative else result


def convert_column(df: pd.DataFrame, column: str) -> tuple[pd.DataFrame, pd.Series]:
    """Convert a detected column to numeric.

    Returns (new_df, preview_series) where preview_series holds the
    converted values, for a before/after display before committing.
    """
    new_df = df.copy()
    converted = df[column].apply(parse_one)
    new_df[column] = converted
    return new_df, converted
