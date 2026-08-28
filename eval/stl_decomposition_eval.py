"""
Time Series Decomposition (STL) — deterministic evaluation suite.
Runs without an API key (pure statsmodels computation, no Gemini).

Usage:  python eval/stl_decomposition_eval.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from modules.forecasting import (
    build_decomposition_chart,
    can_decompose,
    decompose_series,
    decomposition_verdict,
    prepare_series,
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


print("\n📈 STL Decomposition Evaluation")
print("=" * 50)

# ── Test data: 3 years of daily data with weekly seasonality + trend ──────
np.random.seed(42)
n_days = 365 * 3
dates = pd.date_range("2023-01-01", periods=n_days, freq="D")
trend_component = np.linspace(100, 200, n_days)
seasonal_component = 20 * np.sin(2 * np.pi * np.arange(n_days) / 7)  # weekly cycle
noise = np.random.normal(0, 5, n_days)
values = trend_component + seasonal_component + noise

df = pd.DataFrame({"date": dates, "value": values})

print("\n1. prepare_series() produces a valid series")
series, freq, prep_error = prepare_series(df, "date", "value")
check("No prep error", prep_error is None)
check("Frequency inferred as daily", freq == "D")
check("Series length matches input", len(series) == n_days)

print("\n2. can_decompose() gate checks")
ok, reason = can_decompose(series, "D")
check("3 years of daily data can be decomposed", ok is True)
check("No blocking reason when ok", reason is None)

short_series = series.iloc[:10]
ok_short, reason_short = can_decompose(short_series, "D")
check("Too-short series cannot be decomposed", ok_short is False)
check("Reason given for short series", reason_short is not None)

ok_no_freq, reason_no_freq = can_decompose(series, "unknown_freq")
check("Unrecognized frequency cannot be decomposed", ok_no_freq is False)

print("\n3. decompose_series() — recovers known components")
decomp = decompose_series(series, freq)
check("No decomposition error", "error" not in decomp)
check("Trend, seasonal, resid, observed all present", all(k in decomp for k in ["trend", "seasonal", "resid", "observed"]))
check("Component lengths match input series", len(decomp["trend"]) == len(series))

# Reconstruction check: observed ≈ trend + seasonal + resid
reconstructed = decomp["trend"] + decomp["seasonal"] + decomp["resid"]
max_diff = float(np.max(np.abs(reconstructed.values - series.values)))
check("Components reconstruct the observed series (STL is additive)", max_diff < 1e-6)

# Trend should recover the underlying linear trend reasonably well
trend_corr = float(np.corrcoef(decomp["trend"].values, trend_component)[0, 1])
check("Recovered trend correlates strongly with true trend (r > 0.9)", trend_corr > 0.9)

check("seasonal_period matches weekly cycle (7)", decomp["seasonal_period"] == 7)
check("trend_strength is in [0, 1]", 0 <= decomp["trend_strength"] <= 1)
check("seasonal_strength is in [0, 1]", 0 <= decomp["seasonal_strength"] <= 1)
check("Strong trend detected (trend_strength > 0.5)", decomp["trend_strength"] > 0.5)
check("Strong seasonality detected (seasonal_strength > 0.5)", decomp["seasonal_strength"] > 0.5)

print("\n4. decompose_series() on data with no real seasonality")
np.random.seed(1)
flat_values = np.random.normal(50, 2, n_days)  # pure noise, no trend/season
flat_df = pd.DataFrame({"date": dates, "value": flat_values})
flat_series, flat_freq, _ = prepare_series(flat_df, "date", "value")
flat_decomp = decompose_series(flat_series, flat_freq)
check("No error on noise-only series", "error" not in flat_decomp)
check("Weak seasonal strength on pure noise (< 0.5)", flat_decomp["seasonal_strength"] < 0.5)

print("\n5. Error handling for insufficient data")
tiny_df = pd.DataFrame({
    "date": pd.date_range("2023-01-01", periods=10, freq="D"),
    "value": range(10),
})
tiny_series, tiny_freq, tiny_prep_error = prepare_series(tiny_df, "date", "value")
if tiny_prep_error is None:
    tiny_decomp = decompose_series(tiny_series, tiny_freq)
    check("Insufficient data returns error, not a crash", "error" in tiny_decomp)
else:
    check("prepare_series already rejects too-short data (also valid)", True)

print("\n6. decomposition_verdict() produces readable output")
verdict_text = decomposition_verdict(decomp)
check("Verdict mentions trend strength", "Trend strength" in verdict_text)
check("Verdict mentions seasonal strength", "Seasonal strength" in verdict_text)
check("Verdict mentions the seasonal period", "7" in verdict_text)

print("\n7. build_decomposition_chart() returns a Figure without crashing")
fig = build_decomposition_chart(decomp, "Test Decomposition")
check("Chart is a Figure with 4 traces", fig is not None and len(fig.data) == 4)

print("\n8. robust=False mode also works")
decomp_nonrobust = decompose_series(series, freq, robust=False)
check("Non-robust STL fit succeeds", "error" not in decomp_nonrobust)

print("\n" + "=" * 50)
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    sys.exit(1)
print("All tests passed! ✅")
