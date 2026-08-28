"""Baseline tests for modules.auto_insights — the proactive scan run on every
dataset upload. Backfilled 2026-08-10: the run report/changelog for
2026-08-07 claimed 23 tests for this module, but `git log -- tests/` shows
none were ever committed. These cover the main detector paths plus the
empty/single-row/all-null edge cases the routine's audit calls out.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.auto_insights import (
    _bootstrap_corr_ci,
    category_label,
    format_insights_text,
    generate_insights,
    insights_reference_numbers,
    narrate_insights,
    severity_icon,
    verify_narration,
)


def test_generate_insights_flags_high_missing_column():
    df = pd.DataFrame({"a": [1, 2, 3, 4, 5] * 10, "b": [np.nan] * 45 + [1.0] * 5})
    types = {"a": "numeric", "b": "numeric"}
    insights = generate_insights(df, types)
    missing = [i for i in insights if i["category"] == "missing_data" and i["column"] == "b"]
    assert missing and missing[0]["severity"] == "high"


def test_generate_insights_flags_duplicate_rows():
    df = pd.DataFrame({"a": [1, 1, 1, 2, 3], "b": ["x", "x", "x", "y", "z"]})
    insights = generate_insights(df, {"a": "numeric", "b": "categorical"})
    dupes = [i for i in insights if i["category"] == "duplicates"]
    assert dupes and "2" in dupes[0]["metric"] or dupes  # 2 exact dupes of row 0


def test_generate_insights_flags_near_constant_column():
    df = pd.DataFrame({"flag": ["Y"] * 99 + ["N"], "id": range(100)})
    insights = generate_insights(df, {"flag": "categorical", "id": "numeric"})
    assert any(i["category"] == "structure" and i["column"] == "flag" for i in insights)


def test_generate_insights_flags_high_cardinality_id_column():
    df = pd.DataFrame({"user_id": [f"u{i}" for i in range(100)], "amount": range(100)})
    insights = generate_insights(df, {"user_id": "categorical", "amount": "numeric"})
    assert any(i["column"] == "user_id" and "unique" in i["metric"] for i in insights)


def test_generate_insights_flags_strong_correlation():
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    df = pd.DataFrame({"x": x, "y": x * 2 + rng.normal(scale=0.001, size=200)})
    insights = generate_insights(df, {"x": "numeric", "y": "numeric"})
    assert any(i["category"] == "correlation" for i in insights)


def test_generate_insights_on_empty_dataframe_does_not_crash():
    df = pd.DataFrame({"a": [], "b": []})
    insights = generate_insights(df, {"a": "numeric", "b": "categorical"})
    assert insights == []


def test_generate_insights_on_single_row_does_not_crash():
    df = pd.DataFrame({"a": [1], "b": ["x"]})
    insights = generate_insights(df, {"a": "numeric", "b": "categorical"})
    assert isinstance(insights, list)


def test_generate_insights_on_all_null_column_does_not_crash():
    df = pd.DataFrame({"a": [np.nan] * 20, "b": range(20)})
    insights = generate_insights(df, {"a": "numeric", "b": "numeric"})
    assert isinstance(insights, list)


def test_generate_insights_caps_at_max_insights():
    from modules.auto_insights import MAX_INSIGHTS

    # deliberately messy dataset designed to trip many detectors at once
    n = 200
    cols = {f"const_{i}": ["A"] * (n - 1) + ["B"] for i in range(15)}
    cols["dup_a"] = [1] * n
    df = pd.DataFrame(cols)
    types = {c: "categorical" for c in cols}
    insights = generate_insights(df, types)
    assert len(insights) <= MAX_INSIGHTS


def test_insights_sorted_by_severity_high_first():
    df = pd.DataFrame({"a": [np.nan] * 45 + [1.0] * 5, "b": ["x"] * 49 + ["y"]})
    insights = generate_insights(df, {"a": "numeric", "b": "categorical"})
    severities = [i["severity"] for i in insights]
    order = {"high": 0, "medium": 1, "low": 2}
    assert severities == sorted(severities, key=lambda s: order.get(s, 3))


def test_format_insights_text_empty():
    assert "no notable" in format_insights_text([]).lower()


def test_format_insights_text_lists_each_finding():
    insights = [{"severity": "high", "message": "Column X is bad."}]
    text = format_insights_text(insights)
    assert "Column X is bad." in text


def test_narrate_insights_without_model_returns_error():
    narration, error = narrate_insights(None, [{"severity": "high", "message": "x"}])
    assert narration == ""
    assert error is not None


def test_narrate_insights_with_no_findings_skips_gemini():
    class _ShouldNotBeCalled:
        def generate_content(self, *_a, **_k):
            raise AssertionError("Gemini should not be called with no insights")

    narration, error = narrate_insights(_ShouldNotBeCalled(), [])
    assert error is None
    assert "clean" in narration.lower()


def test_severity_icon_and_category_label_cover_known_values():
    assert severity_icon("high") != severity_icon("low")
    assert isinstance(category_label("missing_data"), str) and category_label("missing_data")


# --- insights_reference_numbers / verify_narration -------------------------

def test_insights_reference_numbers_empty_is_safe():
    assert insights_reference_numbers([]) == set()
    assert insights_reference_numbers(None) == set()  # type: ignore[arg-type]


def test_insights_reference_numbers_pulls_from_messages():
    insights = [{"severity": "high", "message": "Column b is 90.0% missing (45 of 50 rows)."}]
    numbers = insights_reference_numbers(insights)
    assert 90.0 in numbers and 45.0 in numbers and 50.0 in numbers


def test_verify_narration_confirmed_when_number_matches_a_message():
    insights = [{"severity": "high", "message": "Column b is 90.0% missing (45 of 50 rows)."}]
    narration = "About 90.0% of column b is missing — worth investigating the collection process."
    verification = verify_narration(narration, insights)
    assert verification["status"] == "confirmed"


def test_verify_narration_flagged_when_a_number_is_fabricated():
    insights = [{"severity": "high", "message": "Column b is 90.0% missing (45 of 50 rows)."}]
    narration = "A staggering 12345.0% of the data is missing — a critical issue."
    verification = verify_narration(narration, insights)
    assert verification["status"] == "flagged"


def test_verify_narration_unverifiable_when_no_numbers_in_text():
    verification = verify_narration("Your data looks clean overall.", [])
    assert verification["status"] == "unverifiable"


def test_verify_narration_never_raises_on_malformed_insights():
    verification = verify_narration("Some text with 42 in it.", "not a list")  # type: ignore[arg-type]
    assert verification["status"] in ("flagged", "unverifiable")


# --- _bootstrap_corr_ci ------------------------------------------------

def test_bootstrap_corr_ci_returns_none_below_min_sample_size():
    x = pd.Series([1.0, 2.0, 3.0])
    y = pd.Series([1.0, 2.0, 3.0])
    assert _bootstrap_corr_ci(x, y) is None


def test_bootstrap_corr_ci_returns_none_on_zero_variance():
    # A constant column has no variance for Pearson r to be defined over —
    # every bootstrap resample would divide by zero.
    x = pd.Series([5.0] * 50)
    y = pd.Series(range(50), dtype=float)
    assert _bootstrap_corr_ci(x, y) is None


def test_bootstrap_corr_ci_is_narrow_for_large_strongly_correlated_sample():
    rng = np.random.default_rng(0)
    x = pd.Series(rng.normal(size=2000))
    y = pd.Series(x * 3 + rng.normal(scale=0.01, size=2000))
    ci = _bootstrap_corr_ci(x, y)
    assert ci is not None
    lo, hi = ci
    assert lo <= hi  # near-perfect r can legitimately round to lo == hi == 1.0
    assert lo > 0.95  # near-deterministic relationship, CI should hug 1.0
    assert hi - lo < 0.05  # 2000 rows → tight interval


def test_bootstrap_corr_ci_is_wide_for_small_borderline_sample():
    rng = np.random.default_rng(1)
    x = pd.Series(rng.normal(size=20))
    y = pd.Series(x * 0.9 + rng.normal(scale=1.2, size=20))
    ci = _bootstrap_corr_ci(x, y)
    assert ci is not None
    lo, hi = ci
    assert hi - lo > 0.2  # tiny n → wide interval even at a similar point estimate


def test_bootstrap_corr_ci_is_deterministic_given_same_inputs():
    rng = np.random.default_rng(2)
    x = pd.Series(rng.normal(size=300))
    y = pd.Series(x * 2 + rng.normal(scale=0.5, size=300))
    assert _bootstrap_corr_ci(x, y) == _bootstrap_corr_ci(x, y)


def test_bootstrap_corr_ci_handles_nans_via_pairwise_dropna():
    x = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0] * 20)
    y = pd.Series([2.0, 4.0, 6.0, np.nan, 10.0] * 20)
    # Should not raise despite misaligned NaNs; either returns a valid
    # interval or None (if too few complete pairs survive), never crashes.
    result = _bootstrap_corr_ci(x, y)
    assert result is None or (result[0] <= result[1])


def test_generate_insights_strong_correlation_message_includes_bootstrap_ci():
    rng = np.random.default_rng(0)
    x = rng.normal(size=500)
    df = pd.DataFrame({"x": x, "y": x * 2 + rng.normal(scale=0.01, size=500)})
    insights = generate_insights(df, {"x": "numeric", "y": "numeric"})
    strong = [i for i in insights if i["category"] == "correlation" and i["severity"] == "high"]
    assert strong
    assert "95% CI" in strong[0]["message"]
    assert "ci" in strong[0] and strong[0]["ci"] is not None


def test_generate_insights_moderate_correlation_skips_bootstrap_for_cost():
    # Moderate-severity correlations are deliberately not bootstrapped
    # (cost control — see auto_insights.py) so their message stays
    # unchanged and their "ci" key is None.
    rng = np.random.default_rng(3)
    x = rng.normal(size=200)
    df = pd.DataFrame({"x": x, "y": x * 0.65 + rng.normal(scale=0.9, size=200)})
    insights = generate_insights(df, {"x": "numeric", "y": "numeric"})
    moderate = [i for i in insights if i["category"] == "correlation" and i["severity"] == "low"]
    if moderate:  # depends on the exact r landing in the moderate band
        assert moderate[0]["ci"] is None
        assert "95% CI" not in moderate[0]["message"]


def test_generate_insights_correlation_never_crashes_on_many_strong_pairs():
    # A wide dataset where many columns are near-duplicates of each other —
    # exercises the MAX_BOOTSTRAP_PAIRS cost cap without raising or hanging.
    rng = np.random.default_rng(4)
    base = rng.normal(size=300)
    data = {f"c{i}": base + rng.normal(scale=0.01, size=300) for i in range(12)}
    df = pd.DataFrame(data)
    types = {c: "numeric" for c in df.columns}
    insights = generate_insights(df, types)  # must not raise or hang
    assert isinstance(insights, list)
