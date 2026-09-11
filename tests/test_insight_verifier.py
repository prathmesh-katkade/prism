"""Tests for modules.insight_verifier — the statistical fact-checker that
catches Gemini making up (or mis-rounding) a number in Auto Analyst findings.
"""
from __future__ import annotations

import pandas as pd

from modules.insight_verifier import (
    compute_reference_numbers,
    extract_numbers,
    verify_finding,
    verify_findings,
)


def _sample_df() -> pd.DataFrame:
    # 100 rows, deterministic — every stat below is hand-checkable.
    return pd.DataFrame(
        {
            "age": list(range(20, 120)),
            "segment": (["A"] * 60) + (["B"] * 40),
        }
    )


def _sample_column_types() -> dict:
    return {"age": "numeric", "segment": "categorical"}


# --- extract_numbers ---------------------------------------------------

def test_extract_numbers_plain_and_percent():
    assert extract_numbers("Revenue grew by 42.5% to 1,234 units.") == [42.5, 1234.0]


def test_extract_numbers_none_present():
    assert extract_numbers("The dataset looks generally healthy.") == []


def test_extract_numbers_negative():
    assert extract_numbers("Profit fell by -12.3 last quarter.") == [-12.3]


# --- compute_reference_numbers ------------------------------------------

def test_reference_numbers_include_row_count():
    df = _sample_df()
    refs = compute_reference_numbers(df, _sample_column_types())
    assert 100.0 in refs


def test_reference_numbers_include_column_mean():
    df = _sample_df()
    refs = compute_reference_numbers(df, _sample_column_types())
    mean_age = round(df["age"].mean(), 2)
    assert mean_age in refs


def test_reference_numbers_include_category_share():
    df = _sample_df()
    refs = compute_reference_numbers(df, _sample_column_types())
    # segment "A" is 60/100 = 60% of rows
    assert 60.0 in refs


# --- verify_finding -------------------------------------------------------

def test_verify_finding_confirmed_for_real_row_count():
    df = _sample_df()
    refs = compute_reference_numbers(df, _sample_column_types())
    result = verify_finding("The dataset has 100 rows in total.", refs)
    assert result["status"] == "confirmed"
    assert result["checked"] == 1


def test_verify_finding_flagged_for_fabricated_number():
    df = _sample_df()
    refs = compute_reference_numbers(df, _sample_column_types())
    result = verify_finding("The dataset has 9999 rows in total.", refs)
    assert result["status"] == "flagged"


def test_verify_finding_unverifiable_when_no_numbers():
    df = _sample_df()
    refs = compute_reference_numbers(df, _sample_column_types())
    result = verify_finding("Segment A dominates the dataset overall.", refs)
    assert result["status"] == "unverifiable"
    assert result["checked"] == 0


# --- verify_findings (batch) ---------------------------------------------

def test_verify_findings_preserves_order_and_length():
    df = _sample_df()
    findings = [
        "There are 100 rows.",
        "There are 9999 rows.",
        "No notable outliers.",
    ]
    results = verify_findings(df, _sample_column_types(), findings)
    assert len(results) == 3
    assert results[0]["status"] == "confirmed"
    assert results[1]["status"] == "flagged"
    assert results[2]["status"] == "unverifiable"


def test_verify_findings_never_raises_on_bad_input():
    # empty dataframe shouldn't blow up the whole findings panel
    df = pd.DataFrame()
    results = verify_findings(df, {}, ["Some finding with 42 in it."])
    assert len(results) == 1
    assert results[0]["status"] in ("unverifiable", "flagged", "confirmed")
