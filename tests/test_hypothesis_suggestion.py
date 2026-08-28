"""Tests for auto_analyst.suggest_followup_hypothesis — picks the single
most promising column pair straight from the data (not LLM prose) to hand
off to Stats Lab for a real significance test.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.auto_analyst import suggest_followup_hypothesis


def test_suggests_strongest_numeric_correlation_pair():
    rng = np.random.default_rng(0)
    x = rng.normal(size=200)
    df = pd.DataFrame(
        {
            "x": x,
            "y_strong": x * 2 + rng.normal(scale=0.1, size=200),  # near-perfect correlation
            "z_noise": rng.normal(size=200),  # unrelated
        }
    )
    column_types = {"x": "numeric", "y_strong": "numeric", "z_noise": "numeric"}
    suggestion = suggest_followup_hypothesis(df, column_types)
    assert suggestion is not None
    assert {suggestion["col_a"], suggestion["col_b"]} == {"x", "y_strong"}


def test_suggests_numeric_categorical_pair_when_groups_differ():
    df = pd.DataFrame(
        {
            "value": [10, 11, 9, 10, 100, 101, 99, 102],
            "group": ["low"] * 4 + ["high"] * 4,
        }
    )
    column_types = {"value": "numeric", "group": "categorical"}
    suggestion = suggest_followup_hypothesis(df, column_types)
    assert suggestion is not None
    assert suggestion["col_a"] == "value"
    assert suggestion["col_b"] == "group"


def test_returns_none_when_nothing_promising():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"a": rng.normal(size=100), "b": rng.normal(size=100)})
    column_types = {"a": "numeric", "b": "numeric"}
    suggestion = suggest_followup_hypothesis(df, column_types)
    assert suggestion is None


def test_returns_none_with_insufficient_columns():
    df = pd.DataFrame({"a": range(20)})
    suggestion = suggest_followup_hypothesis(df, {"a": "numeric"})
    assert suggestion is None


def test_never_raises_on_high_cardinality_categorical():
    df = pd.DataFrame({"value": range(50), "id": [f"row_{i}" for i in range(50)]})
    column_types = {"value": "numeric", "id": "categorical"}
    # every "id" is unique -> 50 groups, over MAX_GROUPS_FOR_TEST -> should be skipped, not raise
    suggestion = suggest_followup_hypothesis(df, column_types)
    assert suggestion is None
