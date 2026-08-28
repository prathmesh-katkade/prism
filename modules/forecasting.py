"""
Forecasting — pick a datetime + numeric column, get a statsmodels forecast
with confidence bands. Tries ETS (statsmodels' ExponentialSmoothing/Holt-
Winters implementation) first since it natively supports trend + seasonality;
falls back to SARIMAX if ETS can't fit the series (e.g. too little data for
the seasonal component it picked).
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.statespace.sarimax import SARIMAX

MIN_HISTORY_POINTS = 8

# STL needs at least 2 full seasonal cycles to estimate a seasonal component
# at all — below that the decomposition is numerically unstable or outright
# fails inside statsmodels.
MIN_CYCLES_FOR_STL = 2

# Roughly-standard seasonal cycle length per inferred pandas frequency code.
_SEASONAL_PERIODS_BY_FREQ = {
    "D": 7, "B": 5, "W": 52, "M": 12, "MS": 12, "Q": 4, "QS": 4, "A": 1, "Y": 1, "H": 24,
}


def _infer_seasonal_periods(freq: str) -> int:
    base = (freq or "D").split("-")[0]
    return _SEASONAL_PERIODS_BY_FREQ.get(base, 0)


def prepare_series(df: pd.DataFrame, datetime_col: str, numeric_col: str) -> tuple[Optional[pd.Series], Optional[str], Optional[str]]:
    """Build a clean, regularly-spaced time series ready for forecasting.

    Returns (series, freq, error). Duplicate timestamps are averaged; gaps
    introduced by resampling to a regular frequency are linearly interpolated
    (statsmodels' forecasting models require an evenly-spaced index).
    """
    clean = df[[datetime_col, numeric_col]].dropna()
    if clean.empty:
        return None, None, "No non-null paired values in the selected columns."

    # `column_types`'s "datetime" label is a content heuristic (data_engine.
    # detect_column_types) — it never mutates the DataFrame itself, so a
    # freshly uploaded CSV's date column is still plain `object`/string
    # dtype unless the user separately ran "Fix Column Types." Coerce here
    # rather than trust the caller: Series.asfreq() below silently discards
    # every value (turns the whole series to NaN, no error raised) when the
    # index isn't already a real DatetimeIndex, since it can't align
    # string labels against the new datetime index it builds.
    if not pd.api.types.is_datetime64_any_dtype(clean[datetime_col]):
        clean = clean.copy()
        clean[datetime_col] = pd.to_datetime(clean[datetime_col], errors="coerce", format="mixed")
        clean = clean.dropna(subset=[datetime_col])
        if clean.empty:
            return None, None, f"Could not parse any values in '{datetime_col}' as dates."

    series = clean.groupby(datetime_col)[numeric_col].mean().sort_index()
    if len(series) < MIN_HISTORY_POINTS:
        return None, None, f"Only {len(series)} distinct timestamps found — need at least {MIN_HISTORY_POINTS} to forecast."

    freq = pd.infer_freq(series.index)
    if freq is None:
        median_gap = series.index.to_series().diff().dropna().median()
        if median_gap <= pd.Timedelta(days=1):
            freq = "D"
        elif median_gap <= pd.Timedelta(days=8):
            freq = "W"
        elif median_gap <= pd.Timedelta(days=32):
            freq = "MS"
        else:
            freq = "QS"

    series = series.asfreq(freq).interpolate(limit_direction="both")
    return series, freq, None


def run_forecast(series: pd.Series, periods: int, freq: str) -> dict:
    """Fit a forecast model and project `periods` steps ahead with a 95%
    confidence band. Returns a dict with "model_used", "forecast" (a
    DataFrame indexed by future dates with forecast/lower/upper columns),
    "history" (the input series), and "warning" (set if ETS failed over to
    SARIMAX) — or "error" if both models failed.
    """
    seasonal_periods = _infer_seasonal_periods(freq)
    use_seasonal = seasonal_periods >= 2 and len(series) >= 2 * seasonal_periods

    model_used = None
    forecast_df = None
    warning = None

    try:
        if use_seasonal:
            model = ETSModel(series, trend="add", seasonal="add", seasonal_periods=seasonal_periods, freq=freq)
        else:
            model = ETSModel(series, trend="add", freq=freq)
        fit = model.fit(disp=False)
        pred = fit.get_prediction(start=len(series), end=len(series) + periods - 1)
        summary = pred.summary_frame(alpha=0.05)
        model_used = "Exponential Smoothing (ETS)" + (" with seasonality" if use_seasonal else "")
        forecast_df = pd.DataFrame(
            {"forecast": summary["mean"], "lower": summary["pi_lower"], "upper": summary["pi_upper"]}
        )
    except Exception as e:
        warning = f"Exponential smoothing failed ({e}); fell back to a SARIMAX model."

    if forecast_df is None:
        try:
            seasonal_order = (1, 1, 1, seasonal_periods) if use_seasonal else (0, 0, 0, 0)
            model = SARIMAX(
                series, order=(1, 1, 1), seasonal_order=seasonal_order,
                enforce_stationarity=False, enforce_invertibility=False,
            )
            fit = model.fit(disp=False)
            pred = fit.get_forecast(steps=periods)
            ci = pred.conf_int(alpha=0.05)
            model_used = "SARIMAX(1,1,1)" + (f"x(1,1,1,{seasonal_periods})" if use_seasonal else "")
            forecast_df = pd.DataFrame(
                {"forecast": pred.predicted_mean, "lower": ci.iloc[:, 0], "upper": ci.iloc[:, 1]}
            )
        except Exception as e:
            return {"error": f"Forecasting failed with both Exponential Smoothing and SARIMAX: {e}"}

    forecast_df.index.name = series.index.name or "date"
    return {"model_used": model_used, "forecast": forecast_df, "history": series, "warning": warning}


def forecast_caveat(n_history: int, periods: int, model_used: str) -> str:
    """Plain-English reliability caveat, scaled to how far out the forecast reaches."""
    ratio = periods / n_history if n_history else 1.0
    if ratio > 0.5:
        confidence = "low"
    elif ratio > 0.2:
        confidence = "moderate"
    else:
        confidence = "reasonable"

    risk_note = (
        "Forecasting this far relative to the amount of history available carries real risk of error — "
        "treat it as directional, not precise. "
        if confidence != "reasonable"
        else ""
    )
    return (
        f"Fit on {n_history} historical observations to project {periods} periods ahead using {model_used}. "
        f"Confidence in this forecast is **{confidence}**. {risk_note}"
        "Forecasts assume future patterns resemble the past and cannot anticipate one-off events (promotions, "
        "holidays, external shocks) — widening bands further out reflect growing uncertainty, not a return to old values."
    )


def build_forecast_chart(history: pd.Series, forecast_df: pd.DataFrame, title: str) -> go.Figure:
    """History as a solid line, forecast as a dashed line, with a shaded 95% confidence band."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=history.index, y=history.values, mode="lines", name="History"))
    fig.add_trace(
        go.Scatter(x=forecast_df.index, y=forecast_df["forecast"], mode="lines", name="Forecast", line=dict(dash="dash"))
    )
    fig.add_trace(
        go.Scatter(
            x=list(forecast_df.index) + list(forecast_df.index[::-1]),
            y=list(forecast_df["upper"]) + list(forecast_df["lower"][::-1]),
            fill="toself", fillcolor="rgba(0, 200, 200, 0.15)", line=dict(width=0),
            name="95% confidence", hoverinfo="skip",
        )
    )
    fig.update_layout(title=title, margin=dict(t=50, b=10, l=10, r=10))
    return fig


# ==========================================================================
# STL Decomposition — trend / seasonal / residual breakdown
# ==========================================================================


def can_decompose(series: pd.Series, freq: str) -> tuple[bool, Optional[str]]:
    """Whether `series` has enough history to decompose at the seasonal
    period implied by `freq`. Returns (ok, reason_if_not).
    """
    seasonal_periods = _infer_seasonal_periods(freq)
    if seasonal_periods < 2:
        return False, f"No standard seasonal cycle is defined for frequency '{freq}' — decomposition needs a periodic pattern (daily/weekly/monthly/quarterly)."
    if len(series) < MIN_CYCLES_FOR_STL * seasonal_periods:
        needed = MIN_CYCLES_FOR_STL * seasonal_periods
        return False, f"Need at least {needed} observations ({MIN_CYCLES_FOR_STL} full seasonal cycles at period {seasonal_periods}) — only {len(series)} available."
    return True, None


def decompose_series(series: pd.Series, freq: str, robust: bool = True) -> dict:
    """STL (Seasonal-Trend decomposition using LOESS) — splits a time series
    into trend + seasonal + residual components. Unlike classical additive/
    multiplicative decomposition, STL allows the seasonal component to
    change over time and is robust to outliers when robust=True.

    Returns a dict with "trend", "seasonal", "resid" (all pd.Series aligned
    to `series`'s index), "seasonal_period", and "strength" (a 0-1 score for
    how much of the variance each component explains) — or "error".
    """
    ok, reason = can_decompose(series, freq)
    if not ok:
        return {"error": reason}

    seasonal_periods = _infer_seasonal_periods(freq)
    try:
        stl_result = STL(series, period=seasonal_periods, robust=robust).fit()
    except Exception as e:
        return {"error": f"STL decomposition failed: {e}"}

    trend, seasonal, resid = stl_result.trend, stl_result.seasonal, stl_result.resid

    # Strength-of-component heuristic (Hyndman & Athanasopoulos): how much
    # variance the trend/seasonal component removes relative to the noise
    # floor set by the residual. Clipped to [0, 1] since the ratio can
    # slightly exceed 1 on noisy series due to how detrend+deseasonalize interact.
    resid_var = float(np.var(resid))
    detrended_var = float(np.var(seasonal + resid))
    deseasonalized_var = float(np.var(trend + resid))
    trend_strength = max(0.0, min(1.0, 1 - resid_var / detrended_var)) if detrended_var > 0 else 0.0
    seasonal_strength = max(0.0, min(1.0, 1 - resid_var / deseasonalized_var)) if deseasonalized_var > 0 else 0.0

    return {
        "trend": trend,
        "seasonal": seasonal,
        "resid": resid,
        "observed": series,
        "seasonal_period": seasonal_periods,
        "trend_strength": trend_strength,
        "seasonal_strength": seasonal_strength,
    }


def decomposition_verdict(decomposition: dict) -> str:
    """Plain-English read of trend/seasonal strength."""
    trend_s = decomposition["trend_strength"]
    seasonal_s = decomposition["seasonal_strength"]

    def _label(score: float) -> str:
        if score >= 0.7:
            return "strong"
        if score >= 0.4:
            return "moderate"
        return "weak"

    return (
        f"**Trend strength: {trend_s:.2f}** ({_label(trend_s)}) — how much of the series' movement is a "
        f"persistent long-term direction. **Seasonal strength: {seasonal_s:.2f}** ({_label(seasonal_s)}) — "
        f"how much repeats on a {decomposition['seasonal_period']}-period cycle. Together with the residual, "
        f"these three components fully reconstruct the original series (observed = trend + seasonal + residual)."
    )


def build_decomposition_chart(decomposition: dict, title: str) -> go.Figure:
    """Four stacked subplots: observed, trend, seasonal, residual — the
    standard STL decomposition view."""
    fig = make_subplots(
        rows=4, cols=1, shared_xaxes=True,
        subplot_titles=("Observed", "Trend", "Seasonal", "Residual"),
        vertical_spacing=0.06,
    )
    observed = decomposition["observed"]
    fig.add_trace(go.Scatter(x=observed.index, y=observed.values, mode="lines", name="Observed", line=dict(color="#4c9be8")), row=1, col=1)
    trend = decomposition["trend"]
    fig.add_trace(go.Scatter(x=trend.index, y=trend.values, mode="lines", name="Trend", line=dict(color="#e8974c")), row=2, col=1)
    seasonal = decomposition["seasonal"]
    fig.add_trace(go.Scatter(x=seasonal.index, y=seasonal.values, mode="lines", name="Seasonal", line=dict(color="#4ce89b")), row=3, col=1)
    resid = decomposition["resid"]
    fig.add_trace(go.Scatter(x=resid.index, y=resid.values, mode="markers", name="Residual", marker=dict(color="#b04ce8", size=4)), row=4, col=1)
    fig.add_hline(y=0, line_dash="dot", line_color="gray", row=4, col=1)

    fig.update_layout(title=title, showlegend=False, height=700, margin=dict(t=60, b=10, l=10, r=10))
    return fig


# ==========================================================================
# Changepoint / structural-break detection — binary segmentation with a
# BIC-style penalty. Answers a different question than STL decomposition:
# not "what's the repeating pattern?" but "did this metric's *level*
# permanently shift, and when?" — the kind of question a demo audience asks
# about a revenue/traffic series ("what happened in March?").
#
# Deliberately dependency-free (no `ruptures`/`changepoint` package): this is
# a from-scratch implementation of classic binary segmentation (Scott &
# Knott, 1974) — the same greedy split-on-largest-residual-reduction idea
# those libraries use for their `Binseg` estimator — with a BIC-style
# penalty (`penalty_scale * sigma^2 * ln(n)`) as the stopping rule so the
# detector doesn't manufacture breaks out of pure noise. Everything here
# reuses numpy, already a hard dependency.
# ==========================================================================

DEFAULT_MIN_SEGMENT_SIZE = 5
MAX_CHANGEPOINTS_DEFAULT = 5
CHANGEPOINT_PENALTY_SCALE = 2.0


def _segment_ss(values: np.ndarray) -> float:
    """Sum of squared deviations from the segment's own mean."""
    if len(values) == 0:
        return 0.0
    return float(np.sum((values - values.mean()) ** 2))


def _best_split(values: np.ndarray, min_segment_size: int) -> Optional[tuple[int, float]]:
    """Best single split point for `values`, vectorized via prefix sums so
    every candidate split is scored in O(m) total rather than O(m) work
    per candidate. Returns (split_index, cost_improvement) — the index is
    relative to the start of `values` — or None if no split respects
    `min_segment_size` on both sides.
    """
    m = len(values)
    if m < 2 * min_segment_size:
        return None

    cs = np.concatenate(([0.0], np.cumsum(values)))
    css = np.concatenate(([0.0], np.cumsum(values ** 2)))

    ks = np.arange(min_segment_size, m - min_segment_size + 1)
    left_n, right_n = ks, m - ks
    left_sum, right_sum = cs[ks], cs[m] - cs[ks]
    left_ss = css[ks] - (left_sum ** 2) / left_n
    right_ss = (css[m] - css[ks]) - (right_sum ** 2) / right_n
    split_cost = left_ss + right_ss

    best_pos = int(np.argmin(split_cost))
    base_cost = css[m] - (cs[m] ** 2) / m
    improvement = float(base_cost - split_cost[best_pos])
    return int(ks[best_pos]), improvement


def detect_changepoints(
    series: pd.Series,
    max_changepoints: int = MAX_CHANGEPOINTS_DEFAULT,
    min_segment_size: Optional[int] = None,
    penalty_scale: float = CHANGEPOINT_PENALTY_SCALE,
) -> dict:
    """Detect structural breaks (permanent mean shifts) in `series` via
    penalized binary segmentation. At each step, every current segment is
    scanned for its single best internal split (the one minimizing combined
    within-segment sum of squares); the globally strongest candidate across
    all segments is accepted only if its cost improvement clears a
    BIC-style penalty, then the process repeats on the resulting segments
    until no candidate clears the penalty or `max_changepoints` is reached.

    Returns a dict with "changepoints" (a list of dicts, one per detected
    break, ordered by position: "position", "date", "before_mean",
    "after_mean", "delta", "pct_change", "before_n", "after_n") and
    "n_segments" — or "error" if the series is too short.
    """
    values = series.values.astype(float)
    n = len(values)

    if min_segment_size is None:
        min_segment_size = max(DEFAULT_MIN_SEGMENT_SIZE, n // 20)

    if n < 2 * min_segment_size:
        return {
            "error": f"Need at least {2 * min_segment_size} observations for changepoint detection "
                     f"(min segment size {min_segment_size}) — only {n} available."
        }

    global_var = float(np.var(values))
    if global_var == 0:
        return {"changepoints": [], "n_segments": 1, "penalty": 0.0}

    penalty = penalty_scale * global_var * np.log(n)

    segments = [(0, n)]
    split_positions: list[int] = []
    while len(split_positions) < max_changepoints:
        best = None  # (improvement, absolute_split_pos, segment_list_index)
        for i, (start, end) in enumerate(segments):
            result = _best_split(values[start:end], min_segment_size)
            if result is None:
                continue
            local_k, improvement = result
            if improvement <= penalty:
                continue
            if best is None or improvement > best[0]:
                best = (improvement, start + local_k, i)
        if best is None:
            break
        _, split_pos, seg_idx = best
        start, end = segments.pop(seg_idx)
        segments.insert(seg_idx, (split_pos, end))
        segments.insert(seg_idx, (start, split_pos))
        split_positions.append(split_pos)

    split_positions.sort()
    boundaries = [0] + split_positions + [n]
    changepoints = []
    for i, pos in enumerate(split_positions):
        before_start, before_end = boundaries[i], pos
        after_start, after_end = pos, boundaries[i + 2]
        before_mean = float(values[before_start:before_end].mean())
        after_mean = float(values[after_start:after_end].mean())
        delta = after_mean - before_mean
        pct_change = (delta / abs(before_mean)) if before_mean != 0 else None
        changepoints.append({
            "position": pos,
            "date": series.index[pos],
            "before_mean": before_mean,
            "after_mean": after_mean,
            "delta": delta,
            "pct_change": pct_change,
            "before_n": before_end - before_start,
            "after_n": after_end - after_start,
        })

    return {"changepoints": changepoints, "n_segments": len(split_positions) + 1, "penalty": float(penalty)}


def changepoint_verdict(result: dict) -> str:
    """Plain-English read of the detected breaks (or their absence)."""
    changepoints = result.get("changepoints", [])
    if not changepoints:
        return (
            "No statistically meaningful structural breaks detected — the series' level looks stable "
            "throughout (any wiggles are within what a BIC-penalized detector treats as noise)."
        )

    lines = [f"**{len(changepoints)} structural break{'s' if len(changepoints) != 1 else ''} detected:**"]
    for cp in changepoints:
        direction = "up" if cp["delta"] > 0 else "down"
        pct_text = f" ({cp['pct_change']:+.1%})" if cp["pct_change"] is not None else ""
        lines.append(
            f"- **{pd.Timestamp(cp['date']).date()}** — level shifted {direction} from "
            f"{cp['before_mean']:.3g} to {cp['after_mean']:.3g}{pct_text}, "
            f"based on {cp['before_n']} points before vs. {cp['after_n']} after."
        )
    lines.append(
        "Each break is where the series' *mean* permanently moved, not a single-point anomaly — treat it as "
        "'something changed here' (a policy, a system change, an external event) worth investigating, not noise."
    )
    return "\n".join(lines)


def build_changepoint_chart(series: pd.Series, result: dict, title: str) -> go.Figure:
    """The raw series with a vertical dashed line at each detected break."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=series.index, y=series.values, mode="lines", name="Observed", line=dict(color="#4c9be8")))
    for cp in result.get("changepoints", []):
        fig.add_vline(
            x=cp["date"], line_dash="dash", line_color="#e8974c",
            annotation_text=f"{cp['delta']:+.3g}", annotation_position="top",
        )
    fig.update_layout(title=title, showlegend=False, margin=dict(t=50, b=10, l=10, r=10))
    return fig
