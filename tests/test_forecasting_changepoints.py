"""Tests for modules.forecasting's structural-break / changepoint detector
(detect_changepoints, changepoint_verdict, build_changepoint_chart).

detect_changepoints() is a dependency-free binary segmentation implementation
(classic Scott & Knott 1974 change-in-mean splitting, the same idea behind
the `ruptures`/`changepoint` packages' Binseg method) with a BIC-style
penalty as the stopping rule — no new pip dependency needed for a technique
already covered by numpy.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.forecasting import (
    DEFAULT_MIN_SEGMENT_SIZE,
    build_changepoint_chart,
    changepoint_verdict,
    detect_changepoints,
)


def _series_with_one_level_shift(n: int = 60, shift_at: int = 30, shift_size: float = 20.0, noise: float = 0.5, seed: int = 0) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    values = np.zeros(n)
    values[shift_at:] += shift_size
    values += rng.normal(scale=noise, size=n)
    return pd.Series(values, index=idx)


def _flat_noisy_series(n: int = 60, noise: float = 1.0, seed: int = 1) -> pd.Series:
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-01-01", periods=n, freq="D")
    return pd.Series(rng.normal(scale=noise, size=n), index=idx)


# --- detect_changepoints: errors / edge cases -------------------------------

def test_detect_changepoints_errors_below_min_length():
    series = _series_with_one_level_shift(n=2 * DEFAULT_MIN_SEGMENT_SIZE - 1)
    result = detect_changepoints(series)
    assert "error" in result


def test_detect_changepoints_handles_constant_series_without_crashing():
    idx = pd.date_range("2026-01-01", periods=30, freq="D")
    series = pd.Series([42.0] * 30, index=idx)
    result = detect_changepoints(series)
    assert "error" not in result
    assert result["changepoints"] == []
    assert result["n_segments"] == 1


def test_detect_changepoints_no_false_positive_on_pure_noise():
    series = _flat_noisy_series(n=80, noise=1.0)
    result = detect_changepoints(series)
    assert "error" not in result
    # A BIC-penalized detector shouldn't manufacture breaks out of flat noise.
    assert result["changepoints"] == []


# --- detect_changepoints: recovers a planted break --------------------------

def test_detect_changepoints_recovers_planted_level_shift():
    series = _series_with_one_level_shift(n=60, shift_at=30, shift_size=20.0, noise=0.5)
    result = detect_changepoints(series)
    assert "error" not in result
    assert len(result["changepoints"]) == 1
    cp = result["changepoints"][0]
    # Detected split should land within a few points of the true break at 30.
    assert abs(cp["position"] - 30) <= 3
    assert cp["delta"] > 15  # recovers most of the planted +20 shift
    assert cp["after_mean"] > cp["before_mean"]


def test_detect_changepoints_reports_correct_segment_sizes():
    series = _series_with_one_level_shift(n=60, shift_at=30, shift_size=20.0, noise=0.5)
    result = detect_changepoints(series)
    cp = result["changepoints"][0]
    assert cp["before_n"] + cp["after_n"] == 60
    assert cp["before_n"] == cp["position"]


def test_detect_changepoints_pct_change_is_signed_and_finite():
    series = _series_with_one_level_shift(n=60, shift_at=30, shift_size=20.0, noise=0.5)
    # Shift the whole series positive so before_mean != 0 and pct_change is well-defined.
    series = series + 100
    result = detect_changepoints(series)
    cp = result["changepoints"][0]
    assert cp["pct_change"] is not None
    assert np.isfinite(cp["pct_change"])
    assert cp["pct_change"] > 0


# --- detect_changepoints: respects caps and honors weaker-signal skip -------

def test_detect_changepoints_respects_max_changepoints_cap():
    # Three planted shifts, but cap the detector to 1.
    idx = pd.date_range("2026-01-01", periods=90, freq="D")
    values = np.zeros(90)
    values[30:60] += 20.0
    values[60:] += 40.0
    rng = np.random.default_rng(2)
    values += rng.normal(scale=0.5, size=90)
    series = pd.Series(values, index=idx)

    result = detect_changepoints(series, max_changepoints=1)
    assert len(result["changepoints"]) <= 1


def test_detect_changepoints_finds_multiple_planted_shifts():
    idx = pd.date_range("2026-01-01", periods=90, freq="D")
    values = np.zeros(90)
    values[30:60] += 20.0
    values[60:] += 40.0
    rng = np.random.default_rng(2)
    values += rng.normal(scale=0.3, size=90)
    series = pd.Series(values, index=idx)

    result = detect_changepoints(series, max_changepoints=5)
    assert len(result["changepoints"]) == 2
    positions = sorted(cp["position"] for cp in result["changepoints"])
    assert abs(positions[0] - 30) <= 3
    assert abs(positions[1] - 60) <= 3


def test_detect_changepoints_deterministic_across_repeated_calls():
    series = _series_with_one_level_shift(n=60, shift_at=30, shift_size=20.0, noise=0.5)
    r1 = detect_changepoints(series)
    r2 = detect_changepoints(series)
    assert r1["changepoints"] == r2["changepoints"]


def test_detect_changepoints_min_segment_size_prevents_tiny_splits():
    # True break sits at position 10, well inside the region a
    # min_segment_size of 40 forbids on a 100-point series — any split the
    # detector reports must still respect the constraint on both sides,
    # even though that pushes it away from the true break.
    series = _series_with_one_level_shift(n=100, shift_at=10, shift_size=20.0, noise=0.5)
    result = detect_changepoints(series, min_segment_size=40)
    assert "error" not in result
    for cp in result["changepoints"]:
        assert cp["position"] >= 40
        assert 100 - cp["position"] >= 40
        assert cp["position"] != 10


# --- changepoint_verdict -----------------------------------------------------

def test_changepoint_verdict_mentions_no_breaks_when_none_found():
    idx = pd.date_range("2026-01-01", periods=30, freq="D")
    series = pd.Series([10.0] * 30, index=idx)
    result = detect_changepoints(series)
    verdict = changepoint_verdict(result)
    assert "no" in verdict.lower()


def test_changepoint_verdict_mentions_each_break_date():
    series = _series_with_one_level_shift(n=60, shift_at=30, shift_size=20.0, noise=0.5)
    result = detect_changepoints(series)
    verdict = changepoint_verdict(result)
    cp_date = result["changepoints"][0]["date"]
    assert str(pd.Timestamp(cp_date).date()) in verdict


# --- build_changepoint_chart --------------------------------------------------

def test_build_changepoint_chart_does_not_crash_with_no_breaks():
    idx = pd.date_range("2026-01-01", periods=30, freq="D")
    series = pd.Series([10.0] * 30, index=idx)
    result = detect_changepoints(series)
    fig = build_changepoint_chart(series, result, "test")
    assert fig is not None


def test_build_changepoint_chart_adds_a_vline_per_changepoint():
    series = _series_with_one_level_shift(n=60, shift_at=30, shift_size=20.0, noise=0.5)
    result = detect_changepoints(series)
    fig = build_changepoint_chart(series, result, "test")
    # Plotly vlines land in fig.layout.shapes
    assert len(fig.layout.shapes) == len(result["changepoints"])
