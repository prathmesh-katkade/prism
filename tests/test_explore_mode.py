"""Tests for modules.visualization.suggest_encodings() — the "PyGWalker
explore mode" auto-suggested-encodings feature: a deterministic, zero-Gemini
ranking of candidate charts (Scatter/Bar/Line/Histogram) by how much signal
they're likely to reveal, closing the oldest standing backlog item (first
logged Run 13, reused unbuilt through Run 19).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.visualization import (
    EXPLORE_CARDINALITY_MAX,
    EXPLORE_CARDINALITY_MIN,
    suggest_encodings,
    suggestion_to_builder_state,
)


def test_strong_numeric_correlation_ranks_as_scatter():
    n = 50
    x = np.arange(n, dtype=float)
    df = pd.DataFrame({"spend": x, "revenue": x * 2 + 1, "noise": np.zeros(n)})
    column_types = {"spend": "numeric", "revenue": "numeric", "noise": "numeric"}

    ranked = suggest_encodings(df, column_types)

    assert ranked, "expected at least one suggestion for a perfectly correlated pair"
    top = ranked[0]
    assert top["chart_type"] == "Scatter"
    assert {top["col_x"], top["col_y"]} == {"spend", "revenue"}
    assert top["score"] == pytest.approx(1.0, abs=1e-6)
    assert "correlation" in top["reason"]


def test_categorical_with_strong_group_difference_suggests_bar():
    df = pd.DataFrame(
        {
            "segment": ["A"] * 20 + ["B"] * 20,
            "revenue": [10.0] * 20 + [1000.0] * 20,
        }
    )
    column_types = {"segment": "categorical", "revenue": "numeric"}

    ranked = suggest_encodings(df, column_types)

    bar = next((c for c in ranked if c["chart_type"] == "Bar"), None)
    assert bar is not None
    assert bar["col_x"] == "segment"
    assert bar["col_y"] == "revenue"
    assert bar["score"] > 0.9  # near-total variance explained by the group split
    assert "segment" in bar["reason"]


def test_datetime_numeric_trend_suggests_line():
    dates = pd.date_range("2024-01-01", periods=30, freq="D")
    df = pd.DataFrame({"date": dates, "users": np.arange(30, dtype=float)})
    column_types = {"date": "datetime", "users": "numeric"}

    ranked = suggest_encodings(df, column_types)

    line = next((c for c in ranked if c["chart_type"] == "Line"), None)
    assert line is not None
    assert line["col_x"] == "date"
    assert line["col_y"] == "users"
    assert line["score"] > 0.9


def test_skewed_numeric_suggests_histogram():
    rng = np.random.default_rng(42)
    skewed = rng.exponential(scale=2.0, size=300)
    df = pd.DataFrame({"amount": skewed})
    column_types = {"amount": "numeric"}

    ranked = suggest_encodings(df, column_types)

    hist = next((c for c in ranked if c["chart_type"] == "Histogram"), None)
    assert hist is not None
    assert hist["col_x"] == "amount"
    assert "skew" in hist["reason"]


def test_cardinality_out_of_range_excludes_categorical_bar_suggestion():
    # A single constant category and a 20-way high-cardinality ID-like column
    # should both be skipped for the categorical-effect-size candidate.
    df = pd.DataFrame(
        {
            "constant_flag": ["yes"] * 40,
            "near_unique_id": [f"id_{i}" for i in range(40)],
            "value": np.arange(40, dtype=float),
        }
    )
    column_types = {"constant_flag": "categorical", "near_unique_id": "categorical", "value": "numeric"}

    ranked = suggest_encodings(df, column_types)

    assert all(c["col_x"] not in ("constant_flag", "near_unique_id") for c in ranked if c["chart_type"] == "Bar")
    # sanity: the cardinality bounds themselves are outside this test's fixture range
    assert df["constant_flag"].nunique() < EXPLORE_CARDINALITY_MIN
    assert df["near_unique_id"].nunique() > EXPLORE_CARDINALITY_MAX


def test_empty_or_insufficient_data_returns_no_suggestions():
    df = pd.DataFrame({"only_col": [1, 2, 3]})
    column_types = {"only_col": "numeric"}

    assert suggest_encodings(df, column_types) == []
    assert suggest_encodings(pd.DataFrame(), {}) == []


def test_ranked_descending_by_score_and_capped_at_max_suggestions():
    n = 60
    rng = np.random.default_rng(7)
    df = pd.DataFrame({f"num{i}": rng.normal(size=n) for i in range(6)})
    # Force a few strongly correlated pairs so there are more than
    # EXPLORE_MAX_SUGGESTIONS candidates to rank and cap.
    df["num1"] = df["num0"] * 3 + 0.01
    df["num2"] = df["num0"] * -2 + 0.02
    column_types = {c: "numeric" for c in df.columns}

    ranked = suggest_encodings(df, column_types, max_suggestions=3)

    assert len(ranked) <= 3
    scores = [c["score"] for c in ranked]
    assert scores == sorted(scores, reverse=True)


def test_no_duplicate_chart_x_y_triples():
    n = 40
    x = np.arange(n, dtype=float)
    df = pd.DataFrame({"a": x, "b": x * 2})
    column_types = {"a": "numeric", "b": "numeric"}

    ranked = suggest_encodings(df, column_types)

    seen = set()
    for c in ranked:
        key = (c["chart_type"], c["col_x"], c["col_y"])
        assert key not in seen
        seen.add(key)


def test_every_suggestion_is_buildable_by_build_manual_chart():
    from modules.visualization import build_manual_chart

    n = 40
    df = pd.DataFrame(
        {
            "spend": np.arange(n, dtype=float),
            "revenue": np.arange(n, dtype=float) * 1.5,
            "segment": (["A"] * 20 + ["B"] * 20),
            "date": pd.date_range("2024-01-01", periods=n, freq="D"),
        }
    )
    df.loc[df["segment"] == "B", "revenue"] += 500  # give the categorical split real signal
    column_types = {"spend": "numeric", "revenue": "numeric", "segment": "categorical", "date": "datetime"}

    ranked = suggest_encodings(df, column_types)
    assert ranked
    for c in ranked:
        fig = build_manual_chart(df, c["chart_type"], c["col_x"], c["col_y"], color=c["color"])
        assert fig is not None


# --- suggestion_to_builder_state(): "Load into Manual Builder" click-through ---
# Turns a suggest_encodings() suggestion into the exact Manual Chart Builder
# widget session_state keys/values needed to preload it — the click-through
# that makes Explore Mode actionable instead of just informational (open
# backlog item since Run 20, built Run 23).

def test_scatter_suggestion_maps_x_y_and_chart_type():
    suggestion = {
        "chart_type": "Scatter", "col_x": "spend", "col_y": "revenue",
        "color": None, "reason": "strong correlation", "score": 0.95,
    }

    state = suggestion_to_builder_state(suggestion)

    assert state["manual_x"] == "spend"
    assert state["manual_y"] == "revenue"
    assert state["manual_chart_type"] == "Scatter"


def test_histogram_suggestion_has_no_col_y_maps_to_none_sentinel():
    suggestion = {
        "chart_type": "Histogram", "col_x": "amount", "col_y": None,
        "color": None, "reason": "right-skewed", "score": 0.8,
    }

    state = suggestion_to_builder_state(suggestion)

    assert state["manual_x"] == "amount"
    assert state["manual_y"] == "(none)"  # the Manual Builder's "no Y-axis" sentinel
    assert state["manual_chart_type"] == "Histogram"


def test_bar_suggestion_maps_categorical_x_and_numeric_y():
    suggestion = {
        "chart_type": "Bar", "col_x": "segment", "col_y": "revenue",
        "color": None, "reason": "varies strongly across segment groups", "score": 0.92,
    }

    state = suggestion_to_builder_state(suggestion)

    assert state["manual_x"] == "segment"
    assert state["manual_y"] == "revenue"
    assert state["manual_chart_type"] == "Bar"


def test_no_color_maps_to_none_sentinel():
    suggestion = {"chart_type": "Scatter", "col_x": "a", "col_y": "b", "color": None, "reason": "r", "score": 0.5}

    state = suggestion_to_builder_state(suggestion)

    assert state["manual_color"] == "(none)"


def test_color_present_is_passed_through():
    # suggest_encodings doesn't emit a color today, but the mapping should
    # honor it if a future suggestion source does — keeps this function
    # correct rather than coincidentally correct for today's only caller.
    suggestion = {"chart_type": "Scatter", "col_x": "a", "col_y": "b", "color": "segment", "reason": "r", "score": 0.5}

    state = suggestion_to_builder_state(suggestion)

    assert state["manual_color"] == "segment"


def test_facet_and_aggregation_channels_reset_to_defaults():
    # A stale facet/facet-row pick from a previous manual build can collide
    # with the newly-loaded x/y/color (the Manual Builder's facet options
    # dynamically exclude the current x/y/color) — resetting avoids a
    # Streamlit "value not in options" error on the next rerun.
    suggestion = {"chart_type": "Bar", "col_x": "segment", "col_y": "revenue", "color": None, "reason": "r", "score": 0.5}

    state = suggestion_to_builder_state(suggestion)

    assert state["manual_facet"] == "(none)"
    assert state["manual_facet_row"] == "(none)"
    assert state["manual_agg"] == "Mean"


def test_returns_exactly_the_manual_builder_widget_keys():
    suggestion = {"chart_type": "Line", "col_x": "date", "col_y": "users", "color": None, "reason": "r", "score": 0.5}

    state = suggestion_to_builder_state(suggestion)

    assert set(state.keys()) == {
        "manual_x", "manual_y", "manual_chart_type", "manual_color", "manual_facet", "manual_facet_row", "manual_agg",
    }
