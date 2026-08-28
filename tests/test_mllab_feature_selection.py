"""Tests for modules.mllab.run_feature_selection — the Mutual Info + L1 +
RFE consensus feature-selection engine."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.mllab import build_feature_selection_chart, run_feature_selection


def _classification_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    informative = rng.normal(size=n)
    noise1 = rng.normal(size=n)
    noise2 = rng.normal(size=n)
    # target depends strongly and only on `informative`
    target = (informative + rng.normal(scale=0.1, size=n) > 0).astype(int)
    return pd.DataFrame(
        {"informative": informative, "noise1": noise1, "noise2": noise2, "target": target}
    )


def _regression_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    informative = rng.normal(size=n)
    noise1 = rng.normal(size=n)
    noise2 = rng.normal(size=n)
    target = 5 * informative + rng.normal(scale=0.2, size=n)
    return pd.DataFrame(
        {"informative": informative, "noise1": noise1, "noise2": noise2, "target": target}
    )


# --- classification: informative feature should outrank noise -------------

def test_classification_ranks_informative_feature_above_noise():
    df = _classification_df()
    result = run_feature_selection(
        df, ["informative", "noise1", "noise2"], "target", "classification", top_k=1
    )
    assert "error" not in result
    ranking = result["ranking"]
    assert ranking.index[0] == "informative"
    assert ranking.loc["informative", "consensus_votes"] >= ranking.loc["noise1", "consensus_votes"]
    assert result["recommended_features"] == ["informative"]


def test_regression_ranks_informative_feature_above_noise():
    df = _regression_df()
    result = run_feature_selection(
        df, ["informative", "noise1", "noise2"], "target", "regression", top_k=1
    )
    assert "error" not in result
    ranking = result["ranking"]
    assert ranking.index[0] == "informative"
    assert result["recommended_features"] == ["informative"]


# --- shape / contract ------------------------------------------------------

def test_ranking_has_expected_columns():
    df = _regression_df()
    result = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    expected_cols = {
        "mutual_info", "mutual_info_rank", "l1_coef_abs", "l1_rank",
        "rfe_selected", "rfe_rank", "consensus_votes", "consensus_rank",
    }
    assert expected_cols.issubset(set(result["ranking"].columns))


def test_consensus_votes_are_between_0_and_3():
    df = _regression_df()
    result = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    votes = result["ranking"]["consensus_votes"]
    assert votes.between(0, 3).all()


def test_default_top_k_is_half_of_features_rounded_down():
    df = _regression_df()
    # 3 numeric features -> default top_k = max(1, 3 // 2) = 1
    result = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    assert result["top_k"] == 1
    assert len(result["recommended_features"]) == 1


def test_explicit_top_k_is_respected_and_capped_by_feature_count():
    df = _regression_df()
    result = run_feature_selection(
        df, ["informative", "noise1", "noise2"], "target", "regression", top_k=2
    )
    assert result["top_k"] == 2
    assert len(result["recommended_features"]) == 2

    capped = run_feature_selection(
        df, ["informative", "noise1", "noise2"], "target", "regression", top_k=99
    )
    assert capped["top_k"] == 3  # capped at n_features


# --- categorical features get one-hot expanded, like feature_importances --

def test_handles_categorical_features_without_crashing():
    rng = np.random.default_rng(3)
    n = 150
    category = rng.choice(["a", "b", "c"], size=n)
    numeric = rng.normal(size=n)
    target = (pd.Series(category).map({"a": 0, "b": 1, "c": 1}).to_numpy())
    df = pd.DataFrame({"category": category, "numeric": numeric, "target": target})
    result = run_feature_selection(df, ["category", "numeric"], "target", "classification")
    assert "error" not in result
    # one-hot expansion means more ranked features than raw input columns
    assert result["n_features"] >= 2
    assert any(name.startswith("category_") for name in result["ranking"].index)


# --- determinism -------------------------------------------------------------

def test_result_is_deterministic_across_runs():
    df = _regression_df()
    r1 = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    r2 = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    assert r1["recommended_features"] == r2["recommended_features"]
    pd.testing.assert_series_equal(r1["ranking"]["consensus_votes"], r2["ranking"]["consensus_votes"])


# --- error handling ------------------------------------------------------------

def test_errors_with_fewer_than_2_features():
    df = _regression_df()
    result = run_feature_selection(df, ["informative"], "target", "regression")
    assert "error" in result


def test_handles_missing_values_in_features():
    df = _regression_df()
    df.loc[0:10, "informative"] = np.nan
    result = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    assert "error" not in result


# --- build_feature_selection_chart --------------------------------------------

def test_build_feature_selection_chart_returns_figure():
    df = _regression_df()
    result = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    fig = build_feature_selection_chart(result["ranking"])
    assert fig is not None
    assert len(fig.data) > 0


def test_build_feature_selection_chart_respects_top_n():
    df = _regression_df()
    result = run_feature_selection(df, ["informative", "noise1", "noise2"], "target", "regression")
    fig = build_feature_selection_chart(result["ranking"], top_n=2)
    assert len(fig.data[0].y) <= 2
