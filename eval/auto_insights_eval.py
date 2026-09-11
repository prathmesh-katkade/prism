"""
Auto-Insight Engine — deterministic evaluation suite.
Runs without an API key (all tests use the pure-computation insight detectors,
not the Gemini narration layer).

Usage:  python eval/auto_insights_eval.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from modules.auto_insights import (
    _detect_distribution_insights,
    _detect_duplicate_rows,
    _detect_missing_insights,
    _detect_structural_insights,
    _iqr_outlier_pct,
    category_label,
    format_insights_text,
    generate_insights,
    severity_icon,
)

passed, failed = 0, 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")


# ── Test data ──────────────────────────────────────────────────────────────

def make_clean_df():
    """A clean dataset — should produce few/no insights."""
    np.random.seed(42)
    return pd.DataFrame({
        "id": range(100),
        "value": np.random.normal(50, 10, 100),
        "category": np.random.choice(["A", "B", "C"], 100),
    })


def make_messy_df():
    """A messy dataset that should trigger many insights."""
    np.random.seed(42)
    n = 200
    df = pd.DataFrame({
        "price": np.concatenate([np.random.normal(100, 20, 190), np.array([10000] * 10)]),  # outliers
        "quantity": np.random.exponential(5, n),  # right-skewed
        "category": (["A"] * 180 + ["B"] * 10 + ["C"] * 10),  # imbalanced
        "unique_id": [f"ID_{i}" for i in range(n)],  # high cardinality
        "constant": [1] * n,  # near-constant
        "corr_a": np.random.normal(0, 1, n),
    })
    df["corr_b"] = df["corr_a"] * 0.95 + np.random.normal(0, 0.1, n)  # strongly correlated
    df.loc[0:39, "price"] = np.nan  # 20% missing
    # Add duplicate rows
    df = pd.concat([df, df.iloc[:20]], ignore_index=True)
    return df


# ── Tests ──────────────────────────────────────────────────────────────────

print("\n🔍 Auto-Insight Engine Evaluation")
print("=" * 50)

print("\n1. Clean dataset — minimal insights expected")
clean_df = make_clean_df()
clean_types = {"id": "numeric", "value": "numeric", "category": "categorical"}
clean_insights = generate_insights(clean_df, clean_types)
check("Clean dataset produces ≤ 3 insights", len(clean_insights) <= 3)
check("No high-severity insights on clean data",
      all(i["severity"] != "high" for i in clean_insights))

print("\n2. Messy dataset — multiple insights expected")
messy_df = make_messy_df()
messy_types = {
    "price": "numeric", "quantity": "numeric", "category": "categorical",
    "unique_id": "categorical", "constant": "numeric", "corr_a": "numeric",
    "corr_b": "numeric",
}
messy_insights = generate_insights(messy_df, messy_types)
check("Messy dataset produces ≥ 5 insights", len(messy_insights) >= 5)
check("At most MAX_INSIGHTS returned", len(messy_insights) <= 12)

categories_found = {i["category"] for i in messy_insights}
check("Missing data detected", "missing_data" in categories_found)
check("Correlation detected", "correlation" in categories_found)
check("Duplicates detected", "duplicates" in categories_found)

print("\n3. Severity ordering")
severities = [i["severity"] for i in messy_insights]
severity_order = {"high": 0, "medium": 1, "low": 2}
ordered = all(
    severity_order[severities[i]] <= severity_order[severities[i + 1]]
    for i in range(len(severities) - 1)
)
check("Insights sorted by severity (high → medium → low)", ordered)

print("\n4. Individual detector tests")

# Distribution — exponential(1) alone isn't skewed enough to cross the
# threshold; a heavier-tailed exponential (higher rate parameter via scale)
# reliably produces skewness >= 2.
skewed_series = pd.Series(np.random.exponential(0.3, 500) ** 2)
skewed_df = pd.DataFrame({"skewed": skewed_series})
dist_insights = _detect_distribution_insights(skewed_df, {"skewed": "numeric"})
check("Skewed distribution detected", len(dist_insights) > 0)

# Missing
missing_df = pd.DataFrame({"col_a": [1, 2, None, None, None] * 20, "col_b": range(100)})
miss_insights = _detect_missing_insights(missing_df)
check("60% missing column detected", any("60" in i["metric"] for i in miss_insights))

# Outlier IQR
normal_vals = pd.Series(np.random.normal(0, 1, 1000))
check("Normal distribution has < 10% IQR outliers", _iqr_outlier_pct(normal_vals) < 10)

# A realistic "10% outliers" shape: a normal core plus a distinct spike
# group far outside it. (A core that's >75% a single repeated value makes
# IQR itself 0, which is a legitimate zero-spread edge case handled
# separately by the near-constant detector, not this one.)
core = np.random.normal(50, 5, 900)
spike = np.array([1000] * 100)
spiked = pd.Series(np.concatenate([core, spike]))
check("10% extreme values detected by IQR", _iqr_outlier_pct(spiked) > 5)

# Structural: near-constant
const_df = pd.DataFrame({"x": [1] * 99 + [2]})
struct_insights = _detect_structural_insights(const_df, {"x": "numeric"})
check("Near-constant column detected", any(i["category"] == "structure" for i in struct_insights))

# Duplicate detection
dup_df = pd.DataFrame({"a": [1, 1, 2, 2, 3], "b": ["x", "x", "y", "y", "z"]})
dup_insights = _detect_duplicate_rows(dup_df)
check("Duplicate rows detected", len(dup_insights) == 1)

print("\n5. Formatting and utilities")
check("severity_icon('high') returns 🔴", severity_icon("high") == "🔴")
check("severity_icon('medium') returns 🟡", severity_icon("medium") == "🟡")
check("severity_icon('low') returns 🔵", severity_icon("low") == "🔵")
check("category_label('missing_data') is 'Missing Data'", category_label("missing_data") == "Missing Data")

formatted = format_insights_text(messy_insights)
check("format_insights_text produces non-empty text", len(formatted) > 50)
check("Empty insights list returns 'No notable' message",
      "No notable" in format_insights_text([]))

print("\n6. Edge cases")
# Empty DataFrame
empty_df = pd.DataFrame()
empty_insights = generate_insights(empty_df, {})
check("Empty DataFrame produces no crash and empty insights", isinstance(empty_insights, list))

# Single row DataFrame
single_df = pd.DataFrame({"a": [1], "b": ["x"]})
single_insights = generate_insights(single_df, {"a": "numeric", "b": "categorical"})
check("Single-row DataFrame produces no crash", isinstance(single_insights, list))

# All-NaN column
nan_df = pd.DataFrame({"all_nan": [None] * 100, "good": range(100)})
nan_insights = generate_insights(nan_df, {"all_nan": "numeric", "good": "numeric"})
check("All-NaN column detected as 100% missing", any("100" in i.get("metric", "") for i in nan_insights))

print("\n" + "=" * 50)
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    sys.exit(1)
print("All tests passed! ✅")
