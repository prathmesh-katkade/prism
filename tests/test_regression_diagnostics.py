"""Baseline tests for modules.regression_diagnostics. Backfilled 2026-08-10:
the 2026-08-07 run report/changelog claimed 33 tests for this module, but
`git log -- tests/` shows none were ever committed. These cover fit_ols(),
the diagnostic battery, VIF, and verdict text on synthetic data with known
properties (clean fit, known collinearity, known heteroscedasticity).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.regression_diagnostics import (
    MIN_ROWS_REQUIRED,
    coefficient_table,
    compute_vif,
    diagnostics_verdict,
    fit_ols,
    run_diagnostics,
    summarize_fit,
)


def _clean_linear_df(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    y = 3.0 + 2.0 * x1 - 1.5 * x2 + rng.normal(scale=0.5, size=n)
    return pd.DataFrame({"x1": x1, "x2": x2, "y": y})


def test_fit_ols_recovers_known_coefficients():
    df = _clean_linear_df()
    fit = fit_ols(df, ["x1", "x2"], "y")
    assert "error" not in fit
    params = fit["model"].params
    assert abs(params["x1"] - 2.0) < 0.3
    assert abs(params["x2"] - (-1.5)) < 0.3


def test_fit_ols_errors_below_min_rows():
    df = pd.DataFrame({"x": range(MIN_ROWS_REQUIRED - 1), "y": range(MIN_ROWS_REQUIRED - 1)})
    fit = fit_ols(df, ["x"], "y")
    assert "error" in fit


def test_fit_ols_drops_categorical_features():
    df = _clean_linear_df()
    df["cat"] = ["a", "b"] * (len(df) // 2)
    fit = fit_ols(df, ["x1", "x2", "cat"], "y")
    assert "error" not in fit
    assert fit["dropped_categorical"] == ["cat"]
    assert "cat" not in fit["feature_names"]


def test_fit_ols_drops_zero_variance_columns():
    df = _clean_linear_df()
    df["const_col"] = 5.0
    fit = fit_ols(df, ["x1", "x2", "const_col"], "y")
    assert "error" not in fit
    assert "const_col" in fit.get("dropped_zero_variance", [])


def test_fit_ols_errors_when_no_numeric_features():
    df = _clean_linear_df()
    df["cat"] = "same"
    fit = fit_ols(df, ["cat"], "y")
    assert "error" in fit


def test_summarize_fit_returns_expected_keys():
    fit = fit_ols(_clean_linear_df(), ["x1", "x2"], "y")
    summary = summarize_fit(fit)
    assert set(["r_squared", "adj_r_squared", "f_statistic", "f_pvalue", "n_obs"]).issubset(summary)
    assert 0.0 <= summary["r_squared"] <= 1.0


def test_coefficient_table_has_a_row_per_feature_plus_intercept():
    fit = fit_ols(_clean_linear_df(), ["x1", "x2"], "y")
    table = coefficient_table(fit)
    assert set(["const", "x1", "x2"]).issubset(table.index)
    assert "p_value" in table.columns


def test_compute_vif_low_for_independent_features():
    fit = fit_ols(_clean_linear_df(), ["x1", "x2"], "y")
    vif_table = compute_vif(fit)
    assert (vif_table["vif"] < 5.0).all()
    assert set(vif_table["concern"]) <= {"low", "moderate"}


def test_compute_vif_high_for_collinear_features():
    rng = np.random.default_rng(1)
    x1 = rng.normal(size=200)
    df = pd.DataFrame({"x1": x1, "x2": x1 * 1.0001 + rng.normal(scale=1e-4, size=200), "y": x1 + rng.normal(size=200)})
    fit = fit_ols(df, ["x1", "x2"], "y")
    vif_table = compute_vif(fit)
    assert (vif_table["vif"] >= 5.0).any()


def test_compute_vif_empty_with_fewer_than_two_features():
    fit = fit_ols(_clean_linear_df(), ["x1"], "y")
    vif_table = compute_vif(fit)
    assert vif_table.empty


def test_run_diagnostics_returns_expected_keys():
    fit = fit_ols(_clean_linear_df(), ["x1", "x2"], "y")
    diagnostics = run_diagnostics(fit)
    for key in ("shapiro_p", "breusch_pagan_p", "durbin_watson", "residuals_normal", "homoscedastic"):
        assert key in diagnostics


def test_run_diagnostics_flags_known_heteroscedasticity():
    rng = np.random.default_rng(2)
    x = rng.uniform(1, 10, size=400)
    noise = rng.normal(scale=x)  # variance grows with x -> classic heteroscedasticity
    y = 2 * x + noise
    df = pd.DataFrame({"x": x, "y": y})
    fit = fit_ols(df, ["x"], "y")
    diagnostics = run_diagnostics(fit)
    assert diagnostics["homoscedastic"] is False


def test_diagnostics_verdict_produces_a_bullet_per_check():
    fit = fit_ols(_clean_linear_df(), ["x1", "x2"], "y")
    diagnostics = run_diagnostics(fit)
    vif_table = compute_vif(fit)
    verdicts = diagnostics_verdict(diagnostics, vif_table)
    assert len(verdicts) >= 3
    assert all(isinstance(v, str) for v in verdicts)
