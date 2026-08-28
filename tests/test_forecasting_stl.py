"""Baseline tests for modules.forecasting's STL decomposition path
(prepare_series, can_decompose, decompose_series, decomposition_verdict).
Backfilled 2026-08-10: the 2026-08-07 run report/changelog claimed 26 tests
for this feature, but `git log -- tests/` shows none were ever committed.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.forecasting import (
    MIN_HISTORY_POINTS,
    can_decompose,
    decompose_series,
    decomposition_verdict,
    prepare_series,
)


def _synthetic_daily_series(n_days: int = 60, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n_days, freq="D")
    trend = np.linspace(0, 20, n_days)  # clear upward trend
    seasonal = 5 * np.sin(2 * np.pi * np.arange(n_days) / 7)  # weekly cycle
    noise = rng.normal(scale=0.5, size=n_days)
    return pd.Series(trend + seasonal + noise + 100, index=idx)


# --- prepare_series --------------------------------------------------------

def test_prepare_series_builds_a_regular_index():
    df = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=30, freq="D"), "value": range(30)})
    series, freq, error = prepare_series(df, "date", "value")
    assert error is None
    assert freq == "D"
    assert len(series) == 30


def test_prepare_series_errors_below_min_history():
    df = pd.DataFrame(
        {"date": pd.date_range("2026-01-01", periods=MIN_HISTORY_POINTS - 1, freq="D"), "value": range(MIN_HISTORY_POINTS - 1)}
    )
    series, freq, error = prepare_series(df, "date", "value")
    assert series is None
    assert error is not None


def test_prepare_series_errors_on_all_null_pair():
    df = pd.DataFrame({"date": pd.date_range("2026-01-01", periods=10, freq="D"), "value": [np.nan] * 10})
    series, freq, error = prepare_series(df, "date", "value")
    assert series is None
    assert error is not None


def test_prepare_series_averages_duplicate_timestamps():
    dates = pd.to_datetime(["2026-01-01"] * 3 + list(pd.date_range("2026-01-02", periods=10, freq="D")))
    values = [10, 20, 30] + list(range(10))
    df = pd.DataFrame({"date": dates, "value": values})
    series, freq, error = prepare_series(df, "date", "value")
    assert error is None
    assert series.loc["2026-01-01"] == 20.0  # mean of 10, 20, 30


def test_prepare_series_coerces_string_dtype_datetime_column():
    """Regression test: a freshly uploaded CSV's date column is `object`
    dtype (data_engine.detect_column_types labels it "datetime" without
    ever converting the DataFrame itself). Before this fix, Series.asfreq()
    silently turned every value to NaN when the index wasn't already a real
    DatetimeIndex — no error, just a dead Forecasting/Decomposition tab.
    """
    dates_as_strings = [d.strftime("%Y-%m-%d") for d in pd.date_range("2026-01-01", periods=30, freq="D")]
    df = pd.DataFrame({"date": dates_as_strings, "value": range(30)})
    assert df["date"].dtype == object

    series, freq, error = prepare_series(df, "date", "value")
    assert error is None
    assert freq == "D"
    assert series.isna().sum() == 0
    assert list(series.values) == list(range(30))


def test_prepare_series_errors_when_string_column_has_no_parseable_dates():
    df = pd.DataFrame({"date": ["not", "a", "date"] * 4, "value": range(12)})
    series, freq, error = prepare_series(df, "date", "value")
    assert series is None
    assert error is not None


# --- can_decompose ----------------------------------------------------------

def test_can_decompose_true_with_enough_weekly_cycles():
    series = _synthetic_daily_series(n_days=30)
    ok, reason = can_decompose(series, "D")
    assert ok is True
    assert reason is None


def test_can_decompose_false_with_too_little_history():
    series = _synthetic_daily_series(n_days=10)
    ok, reason = can_decompose(series, "D")
    assert ok is False
    assert reason is not None


def test_can_decompose_false_for_frequency_with_no_seasonal_cycle():
    series = _synthetic_daily_series(n_days=30)
    ok, reason = can_decompose(series, "A")  # yearly has no defined sub-cycle here
    assert ok is False
    assert reason is not None


# --- decompose_series ---------------------------------------------------

def test_decompose_series_returns_all_expected_components():
    series = _synthetic_daily_series(n_days=60)
    result = decompose_series(series, "D")
    assert "error" not in result
    for key in ("trend", "seasonal", "resid", "observed", "trend_strength", "seasonal_strength"):
        assert key in result


def test_decompose_series_additive_reconstruction_identity():
    """observed == trend + seasonal + resid, the core STL invariant."""
    series = _synthetic_daily_series(n_days=60)
    result = decompose_series(series, "D")
    reconstructed = result["trend"] + result["seasonal"] + result["resid"]
    assert np.allclose(reconstructed.values, series.values, atol=1e-6)


def test_decompose_series_recovers_strong_trend_and_seasonality():
    series = _synthetic_daily_series(n_days=60)
    result = decompose_series(series, "D")
    # trend is a strong linear ramp, seasonality a clean weekly sine — both
    # should score meaningfully above zero on the strength heuristic
    assert result["trend_strength"] > 0.5
    assert result["seasonal_strength"] > 0.3


def test_decompose_series_strength_scores_are_bounded():
    series = _synthetic_daily_series(n_days=60)
    result = decompose_series(series, "D")
    assert 0.0 <= result["trend_strength"] <= 1.0
    assert 0.0 <= result["seasonal_strength"] <= 1.0


def test_decompose_series_error_when_insufficient_history():
    series = _synthetic_daily_series(n_days=5)
    result = decompose_series(series, "D")
    assert "error" in result


def test_decompose_series_on_flat_series_does_not_crash():
    idx = pd.date_range("2026-01-01", periods=30, freq="D")
    series = pd.Series([50.0] * 30, index=idx)
    result = decompose_series(series, "D")
    assert "error" not in result
    assert result["trend_strength"] == 0.0 or result["trend_strength"] >= 0.0


# --- decomposition_verdict -----------------------------------------------

def test_decomposition_verdict_mentions_both_strengths():
    series = _synthetic_daily_series(n_days=60)
    result = decompose_series(series, "D")
    verdict = decomposition_verdict(result)
    assert "Trend strength" in verdict
    assert "Seasonal strength" in verdict
