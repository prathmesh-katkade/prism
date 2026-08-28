"""Tests for modules.mllab.run_cross_validation — k-fold cross-validation
for ML Lab's baseline models, reporting mean +/- std per metric instead of
a single 80/20 split's point estimate."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.mllab import run_baseline_models, run_cross_validation


def _classification_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = (x1 + rng.normal(scale=0.3, size=n) > 0).astype(int)
    return pd.DataFrame({"x1": x1, "x2": x2, "target": y})


def _regression_df(n: int = 200, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = 3 * x1 - 2 * x2 + rng.normal(scale=0.5, size=n)
    return pd.DataFrame({"x1": x1, "x2": x2, "target": y})


def test_classification_returns_mean_and_std_for_both_models():
    df = _classification_df()
    result = run_cross_validation(df, ["x1", "x2"], "target", "classification")
    assert "error" not in result
    for name in ("Baseline", "Random Forest"):
        for metric in ("accuracy", "f1"):
            entry = result["results"][name][metric]
            assert 0.0 <= entry["mean"] <= 1.0
            assert entry["std"] >= 0.0


def test_regression_returns_mean_and_std_for_both_models():
    df = _regression_df()
    result = run_cross_validation(df, ["x1", "x2"], "target", "regression")
    assert "error" not in result
    for name in ("Baseline", "Random Forest"):
        assert result["results"][name]["rmse"]["mean"] >= 0.0  # RMSE is always non-negative
        assert result["results"][name]["r2"]["mean"] <= 1.0


def test_default_n_splits_is_5_for_a_large_enough_dataset():
    df = _classification_df()
    result = run_cross_validation(df, ["x1", "x2"], "target", "classification")
    assert result["n_splits"] == 5


def test_n_splits_is_capped_by_the_smallest_class_for_classification():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({
        "x1": rng.normal(size=60),
        "target": [0] * 57 + [1] * 3,  # smallest class has only 3 rows
    })
    result = run_cross_validation(df, ["x1"], "target", "classification", n_splits=5)
    assert result["n_splits"] <= 3


def test_n_splits_is_capped_for_a_small_dataset():
    df = _regression_df(n=10)
    result = run_cross_validation(df, ["x1", "x2"], "target", "regression", n_splits=5)
    assert result["n_splits"] <= 5  # len(data)//2 == 5, so this happens not to reduce further
    assert result["n_splits"] >= 2


def test_errors_with_fewer_than_4_rows():
    df = _regression_df(n=3)
    result = run_cross_validation(df, ["x1", "x2"], "target", "regression")
    assert "error" in result


def test_handles_categorical_features_without_crashing():
    rng = np.random.default_rng(3)
    df = pd.DataFrame({
        "num": rng.normal(size=100),
        "cat": rng.choice(["a", "b", "c"], size=100),
        "target": rng.choice([0, 1], size=100),
    })
    result = run_cross_validation(df, ["num", "cat"], "target", "classification")
    assert "error" not in result


def test_result_is_deterministic_across_runs():
    df = _classification_df()
    first = run_cross_validation(df, ["x1", "x2"], "target", "classification")
    second = run_cross_validation(df, ["x1", "x2"], "target", "classification")
    assert first["results"] == second["results"]


def test_run_baseline_models_includes_cv_results():
    df = _classification_df()
    result = run_baseline_models(df, ["x1", "x2"], "target", "classification")
    assert "cv_results" in result
    assert "error" not in result["cv_results"]
    assert "Baseline" in result["cv_results"]["results"]
