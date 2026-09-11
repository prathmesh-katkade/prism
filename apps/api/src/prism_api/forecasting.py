"""Phase 7B native Forecasting: time-series preparation, forecasting, STL decomposition,
and changepoint detection, ported from ``modules/forecasting.py`` onto the shared
``DatasetStore``.

Model/method selection stays deterministic and rule-based, exactly like Stats Lab's test
selection — ETS is tried first, SARIMAX is the fallback, seasonality is inferred from the
series' frequency, never from an LLM. The server returns structured point/interval data
only, never a server-rendered chart figure — the frontend renders it using the same
chart-data convention Visualize already established. Every result carries provenance bound
to the dataset's current revision, and every forecast response makes its uncertainty
explicit (an interval alongside every point, a caveat scaled to how far out the forecast
reaches) rather than presenting a point estimate as certainty.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, HTTPException, status
from prism_api_contracts import (
    AtlasEvidence,
    AtlasForecastAction,
    AtlasForecastRequest,
    AtlasForecastResponse,
    ChangepointFinding,
    ChangepointRequest,
    ChangepointResult,
    DecomposeRequest,
    DecompositionResult,
    ForecastInterval,
    ForecastMetrics,
    ForecastPoint,
    ForecastRequest,
    ForecastResult,
    OverviewProvenance,
)
from prism_overview_analytics import ANALYTICS_SERVICE_VERSION

# Imported at module load, not lazily inside a request handler — statsmodels' own import
# is a heavy one-time cost (same lesson as Phase 7A's scipy fix: paying it at startup
# instead of on some user's first Forecasting request is the difference between a real
# latency regression and normal process warmup).
from statsmodels.tsa.exponential_smoothing.ets import ETSModel
from statsmodels.tsa.seasonal import STL
from statsmodels.tsa.statespace.sarimax import SARIMAX

from .analytical_objects import register_forecast
from .overview import StoredDataset
from .overview import store as overview_store

router = APIRouter(prefix="/api/v1/forecasting", tags=["forecasting"])

# Mirrors modules/forecasting.py's constants exactly.
MIN_HISTORY_POINTS = 8
MIN_CYCLES_FOR_STL = 2
_SEASONAL_PERIODS_BY_FREQ = {"D": 7, "B": 5, "W": 52, "ME": 12, "MS": 12, "QE": 4, "QS": 4, "YE": 1, "YS": 1, "h": 24}
DEFAULT_MIN_SEGMENT_SIZE = 5
CHANGEPOINT_PENALTY_SCALE = 2.0

# The response caps how much raw history it echoes back (rule 46: don't send huge raw
# datasets to the frontend) — the model still fits on the full series regardless.
MAX_OBSERVED_POINTS = 2000

# A single train/test holdout (not k-fold CV — bounded, free-tier-friendly compute per
# rule 37) for MAE/RMSE/MAPE, reusing run_forecast's own fit path rather than a second
# model-fitting code path.
MAX_HOLDOUT_POINTS = 12
MIN_HOLDOUT_FRACTION = 0.2


def _canonicalize_frequency(freq: str) -> str:
    """Direct port of modules/forecasting.py::_canonicalize_frequency."""
    raw = (freq or "D").strip()
    base, separator, suffix = raw.partition("-")
    canonical_base = {"M": "ME", "Q": "QE", "A": "YE", "Y": "YE", "H": "h"}.get(base, base)
    candidate = canonical_base + (separator + suffix if separator else "")
    try:
        return str(pd.tseries.frequencies.to_offset(candidate).freqstr)
    except ValueError:
        return raw


def _infer_seasonal_periods(freq: str) -> int:
    base = _canonicalize_frequency(freq).split("-")[0]
    return _SEASONAL_PERIODS_BY_FREQ.get(base, 0)


def prepare_series(frame: pd.DataFrame, datetime_col: str, numeric_col: str) -> tuple[Optional[pd.Series], Optional[str], Optional[str]]:
    """Build a clean, regularly-spaced time series ready for forecasting.

    Direct port of modules/forecasting.py::prepare_series. Returns (series, freq, error).
    """
    clean = frame[[datetime_col, numeric_col]].dropna()
    if clean.empty:
        return None, None, "No non-null paired values in the selected columns."

    if not pd.api.types.is_datetime64_any_dtype(clean[datetime_col]):
        clean = clean.copy()
        clean[datetime_col] = pd.to_datetime(clean[datetime_col], errors="coerce", format="mixed")
        clean = clean.dropna(subset=[datetime_col])
        if clean.empty:
            return None, None, f"Could not parse any values in {datetime_col!r} as dates."

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

    freq = _canonicalize_frequency(freq)

    series = series.asfreq(freq).interpolate(limit_direction="both")
    return series, freq, None


def _require_series(stored: StoredDataset, datetime_col: str, numeric_col: str) -> tuple[pd.Series, str]:
    for column in (datetime_col, numeric_col):
        if column not in stored.frame.columns:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Column {column!r} is not in the active dataset.")
    series, freq, error = prepare_series(stored.frame, datetime_col, numeric_col)
    if series is None or freq is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=error or "This series could not be prepared for forecasting.")
    return series, freq


def run_forecast(series: pd.Series, periods: int, freq: str) -> dict[str, Any]:
    """Fit ETS (falling back to SARIMAX) and project `periods` steps ahead with a 95%
    confidence band. Direct port of modules/forecasting.py::run_forecast.
    """
    seasonal_periods = _infer_seasonal_periods(freq)
    use_seasonal = seasonal_periods >= 2 and len(series) >= 2 * seasonal_periods

    model_used = None
    forecast_df = None
    warning = None

    try:
        model = ETSModel(series, trend="add", seasonal="add", seasonal_periods=seasonal_periods, freq=freq) if use_seasonal else ETSModel(series, trend="add", freq=freq)
        fit = model.fit(disp=False)
        pred = fit.get_prediction(start=len(series), end=len(series) + periods - 1)
        summary = pred.summary_frame(alpha=0.05)
        model_used = "Exponential Smoothing (ETS)" + (" with seasonality" if use_seasonal else "")
        forecast_df = pd.DataFrame({"forecast": summary["mean"], "lower": summary["pi_lower"], "upper": summary["pi_upper"]})
    except Exception as error:
        warning = f"Exponential smoothing failed ({error}); fell back to a SARIMAX model."

    if forecast_df is None:
        try:
            seasonal_order = (1, 1, 1, seasonal_periods) if use_seasonal else (0, 0, 0, 0)
            model = SARIMAX(series, order=(1, 1, 1), seasonal_order=seasonal_order, enforce_stationarity=False, enforce_invertibility=False)
            fit = model.fit(disp=False)
            pred = fit.get_forecast(steps=periods)
            ci = pred.conf_int(alpha=0.05)
            model_used = "SARIMAX(1,1,1)" + (f"x(1,1,1,{seasonal_periods})" if use_seasonal else "")
            forecast_df = pd.DataFrame({"forecast": pred.predicted_mean, "lower": ci.iloc[:, 0], "upper": ci.iloc[:, 1]})
        except Exception as error:
            return {"error": f"Forecasting failed with both Exponential Smoothing and SARIMAX: {error}"}

    forecast_df.index.name = series.index.name or "date"
    return {"model_used": model_used, "forecast": forecast_df, "history": series, "warning": warning}


def forecast_caveat(n_history: int, periods: int, model_used: str) -> str:
    """Plain-English reliability caveat, scaled to how far out the forecast reaches.
    Direct port of modules/forecasting.py::forecast_caveat.
    """
    ratio = periods / n_history if n_history else 1.0
    confidence = "low" if ratio > 0.5 else "moderate" if ratio > 0.2 else "reasonable"
    risk_note = "Forecasting this far relative to the amount of history available carries real risk of error — treat it as directional, not precise. " if confidence != "reasonable" else ""
    return (
        f"Fit on {n_history} historical observations to project {periods} periods ahead using {model_used}. "
        f"Confidence in this forecast is **{confidence}**. {risk_note}"
        "Forecasts assume future patterns resemble the past and cannot anticipate one-off events (promotions, "
        "holidays, external shocks) — widening bands further out reflect growing uncertainty, not a return to old values."
    )


def _holdout_metrics(series: pd.Series, freq: str) -> ForecastMetrics:
    """A single train/test holdout — never presented as the forecast itself, only as a
    diagnostic of how this method performed on this series' own recent history. Reuses
    run_forecast() rather than a second model-fitting path.
    """
    n = len(series)
    holdout = min(MAX_HOLDOUT_POINTS, max(1, int(n * MIN_HOLDOUT_FRACTION)))
    if n - holdout < MIN_HISTORY_POINTS:
        return ForecastMetrics(holdout_points=0, note="Not enough history for a train/test holdout on top of the minimum needed to fit a model — metrics are unavailable for this series.")

    train, test = series.iloc[:-holdout], series.iloc[-holdout:]
    result = run_forecast(train, holdout, freq)
    if "error" in result:
        return ForecastMetrics(holdout_points=0, note="The holdout fit failed with the same error as the full-history fit would; metrics are unavailable.")

    predicted = result["forecast"]["forecast"].to_numpy()
    actual = test.to_numpy()
    errors = predicted - actual
    mae = float(np.mean(np.abs(errors)))
    rmse = float(np.sqrt(np.mean(errors**2)))
    mape = float(np.mean(np.abs(errors / actual))) * 100 if np.all(actual != 0) else None
    note = "Computed by fitting on all but the last {} point(s) and forecasting them, then comparing to what actually happened.".format(holdout)
    if mape is None:
        note += " MAPE is not shown because the holdout window includes a zero actual value (division by zero)."
    return ForecastMetrics(mae=mae, rmse=rmse, mape=mape, holdout_points=holdout, note=note)


def _provenance(stored: StoredDataset, method: str, parameters: dict[str, Any]) -> OverviewProvenance:
    return OverviewProvenance(
        source_fingerprint=stored.source_fingerprint, dataset_revision=stored.dataset.revision,
        parameters={"method": method, **parameters}, service_version=ANALYTICS_SERVICE_VERSION,
        computed_at=datetime.now(timezone.utc),
    )


def _points(series: pd.Series) -> list[ForecastPoint]:
    return [ForecastPoint(timestamp=index, value=float(value)) for index, value in series.items() if pd.notna(value)]


@router.post("/datasets/{dataset_id}/forecast", response_model=ForecastResult)
def forecast(dataset_id: str, request: ForecastRequest) -> ForecastResult:
    return execute_forecast(overview_store.get(dataset_id), request)


def execute_forecast(stored: StoredDataset, request: ForecastRequest) -> ForecastResult:
    """The route handler's actual work, extracted so Phase 8F's reproduction service can
    call it against an explicit (possibly historical) ``StoredDataset`` - the route itself
    always resolves the current one; a rerun may deliberately target an older revision."""
    series, freq = _require_series(stored, request.datetime_col, request.numeric_col)

    result = run_forecast(series, request.horizon, freq)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    forecast_df = result["forecast"]
    warnings = [result["warning"]] if result["warning"] else []
    metrics = _holdout_metrics(series, freq)
    if metrics.note and metrics.holdout_points == 0:
        warnings.append(metrics.note)

    observed = _points(series.iloc[-MAX_OBSERVED_POINTS:])
    forecast_points = [ForecastPoint(timestamp=index, value=float(row["forecast"])) for index, row in forecast_df.iterrows()]
    intervals = [ForecastInterval(timestamp=index, lower=float(row["lower"]), upper=float(row["upper"])) for index, row in forecast_df.iterrows()]

    forecast_result = ForecastResult(
        datetime_col=request.datetime_col, numeric_col=request.numeric_col, frequency=freq,
        model_used=result["model_used"], horizon=request.horizon, observed=observed,
        forecast=forecast_points, intervals=intervals, metrics=metrics,
        caveat=forecast_caveat(len(series), request.horizon, result["model_used"]), warnings=warnings,
        provenance=_provenance(stored, "forecast", {"datetime_col": request.datetime_col, "numeric_col": request.numeric_col, "horizon": request.horizon, "frequency": freq, "model_used": result["model_used"]}),
    )
    register_forecast(stored, request, forecast_result)
    return forecast_result


def can_decompose(series: pd.Series, freq: str) -> tuple[bool, Optional[str]]:
    seasonal_periods = _infer_seasonal_periods(freq)
    if seasonal_periods < 2:
        return False, f"No standard seasonal cycle is defined for frequency {freq!r} — decomposition needs a periodic pattern (daily/weekly/monthly/quarterly)."
    if len(series) < MIN_CYCLES_FOR_STL * seasonal_periods:
        needed = MIN_CYCLES_FOR_STL * seasonal_periods
        return False, f"Need at least {needed} observations ({MIN_CYCLES_FOR_STL} full seasonal cycles at period {seasonal_periods}) — only {len(series)} available."
    return True, None


def decompose_series(series: pd.Series, freq: str, robust: bool = True) -> dict[str, Any]:
    """STL decomposition. Direct port of modules/forecasting.py::decompose_series."""
    ok, reason = can_decompose(series, freq)
    if not ok:
        return {"error": reason}

    seasonal_periods = _infer_seasonal_periods(freq)
    try:
        stl_result = STL(series, period=seasonal_periods, robust=robust).fit()
    except Exception as error:
        return {"error": f"STL decomposition failed: {error}"}

    trend, seasonal, resid = stl_result.trend, stl_result.seasonal, stl_result.resid
    resid_var = float(np.var(resid))
    detrended_var = float(np.var(seasonal + resid))
    deseasonalized_var = float(np.var(trend + resid))
    trend_strength = max(0.0, min(1.0, 1 - resid_var / detrended_var)) if detrended_var > 0 else 0.0
    seasonal_strength = max(0.0, min(1.0, 1 - resid_var / deseasonalized_var)) if deseasonalized_var > 0 else 0.0
    return {"trend": trend, "seasonal": seasonal, "resid": resid, "observed": series, "seasonal_period": seasonal_periods, "trend_strength": trend_strength, "seasonal_strength": seasonal_strength}


def decomposition_verdict(decomposition: dict[str, Any]) -> str:
    trend_s, seasonal_s = decomposition["trend_strength"], decomposition["seasonal_strength"]

    def _label(score: float) -> str:
        return "strong" if score >= 0.7 else "moderate" if score >= 0.4 else "weak"

    return (
        f"Trend strength: {trend_s:.2f} ({_label(trend_s)}) — how much of the series' movement is a persistent "
        f"long-term direction. Seasonal strength: {seasonal_s:.2f} ({_label(seasonal_s)}) — how much repeats on a "
        f"{decomposition['seasonal_period']}-period cycle. Together with the residual, these three components "
        "fully reconstruct the original series (observed = trend + seasonal + residual)."
    )


@router.post("/datasets/{dataset_id}/decompose", response_model=DecompositionResult)
def decompose(dataset_id: str, request: DecomposeRequest) -> DecompositionResult:
    stored = overview_store.get(dataset_id)
    series, freq = _require_series(stored, request.datetime_col, request.numeric_col)

    decomposition = decompose_series(series, freq)
    if "error" in decomposition:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=decomposition["error"])

    return DecompositionResult(
        datetime_col=request.datetime_col, numeric_col=request.numeric_col, seasonal_period=decomposition["seasonal_period"],
        trend_strength=decomposition["trend_strength"], seasonal_strength=decomposition["seasonal_strength"],
        observed=_points(decomposition["observed"].iloc[-MAX_OBSERVED_POINTS:]), trend=_points(decomposition["trend"].iloc[-MAX_OBSERVED_POINTS:]),
        seasonal=_points(decomposition["seasonal"].iloc[-MAX_OBSERVED_POINTS:]), resid=_points(decomposition["resid"].iloc[-MAX_OBSERVED_POINTS:]),
        verdict=decomposition_verdict(decomposition),
        provenance=_provenance(stored, "decompose", {"datetime_col": request.datetime_col, "numeric_col": request.numeric_col, "frequency": freq}),
    )


def _segment_ss(values: "np.ndarray[Any, Any]") -> float:
    if len(values) == 0:
        return 0.0
    return float(np.sum((values - values.mean()) ** 2))


def _best_split(values: "np.ndarray[Any, Any]", min_segment_size: int) -> Optional[tuple[int, float]]:
    """Vectorized best single split point via prefix sums. Direct port of
    modules/forecasting.py::_best_split."""
    m = len(values)
    if m < 2 * min_segment_size:
        return None
    cs = np.concatenate(([0.0], np.cumsum(values)))
    css = np.concatenate(([0.0], np.cumsum(values**2)))
    ks = np.arange(min_segment_size, m - min_segment_size + 1)
    left_n, right_n = ks, m - ks
    left_sum, right_sum = cs[ks], cs[m] - cs[ks]
    left_ss = css[ks] - (left_sum**2) / left_n
    right_ss = (css[m] - css[ks]) - (right_sum**2) / right_n
    split_cost = left_ss + right_ss
    best_pos = int(np.argmin(split_cost))
    base_cost = css[m] - (cs[m] ** 2) / m
    improvement = float(base_cost - split_cost[best_pos])
    return int(ks[best_pos]), improvement


def detect_changepoints(series: pd.Series, max_changepoints: int = 5, min_segment_size: Optional[int] = None, penalty_scale: float = CHANGEPOINT_PENALTY_SCALE) -> dict[str, Any]:
    """Penalized binary segmentation. Direct port of modules/forecasting.py::detect_changepoints."""
    values = series.to_numpy().astype(float)
    n = len(values)
    if min_segment_size is None:
        min_segment_size = max(DEFAULT_MIN_SEGMENT_SIZE, n // 20)
    if n < 2 * min_segment_size:
        return {"error": f"Need at least {2 * min_segment_size} observations for changepoint detection (min segment size {min_segment_size}) — only {n} available."}

    global_var = float(np.var(values))
    if global_var == 0:
        return {"changepoints": [], "n_segments": 1, "penalty": 0.0}

    penalty = penalty_scale * global_var * np.log(n)
    segments = [(0, n)]
    split_positions: list[int] = []
    while len(split_positions) < max_changepoints:
        best = None
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
    boundaries = [0, *split_positions, n]
    changepoints = []
    for i, pos in enumerate(split_positions):
        before_start, before_end = boundaries[i], pos
        after_start, after_end = pos, boundaries[i + 2]
        before_mean = float(values[before_start:before_end].mean())
        after_mean = float(values[after_start:after_end].mean())
        delta = after_mean - before_mean
        pct_change = (delta / abs(before_mean)) if before_mean != 0 else None
        changepoints.append({"position": pos, "date": series.index[pos], "before_mean": before_mean, "after_mean": after_mean, "delta": delta, "pct_change": pct_change, "before_n": before_end - before_start, "after_n": after_end - after_start})

    return {"changepoints": changepoints, "n_segments": len(split_positions) + 1, "penalty": float(penalty)}


def changepoint_verdict(result: dict[str, Any]) -> str:
    changepoints = result.get("changepoints", [])
    if not changepoints:
        return "No statistically meaningful structural breaks detected — the series' level looks stable throughout (any wiggles are within what a BIC-penalized detector treats as noise)."
    lines = [f"{len(changepoints)} structural break{'s' if len(changepoints) != 1 else ''} detected:"]
    for cp in changepoints:
        direction = "up" if cp["delta"] > 0 else "down"
        pct_text = f" ({cp['pct_change']:+.1%})" if cp["pct_change"] is not None else ""
        lines.append(f"- {pd.Timestamp(cp['date']).date()} — level shifted {direction} from {cp['before_mean']:.3g} to {cp['after_mean']:.3g}{pct_text}, based on {cp['before_n']} points before vs. {cp['after_n']} after.")
    lines.append("Each break is where the series' mean permanently moved, not a single-point anomaly — treat it as 'something changed here' worth investigating, not noise.")
    return "\n".join(lines)


@router.post("/datasets/{dataset_id}/changepoints", response_model=ChangepointResult)
def changepoints(dataset_id: str, request: ChangepointRequest) -> ChangepointResult:
    stored = overview_store.get(dataset_id)
    series, freq = _require_series(stored, request.datetime_col, request.numeric_col)

    result = detect_changepoints(series, max_changepoints=request.max_changepoints)
    if "error" in result:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=result["error"])

    findings = [ChangepointFinding(position=cp["position"], timestamp=cp["date"], before_mean=cp["before_mean"], after_mean=cp["after_mean"], delta=cp["delta"], pct_change=cp["pct_change"], before_n=cp["before_n"], after_n=cp["after_n"]) for cp in result["changepoints"]]

    return ChangepointResult(
        datetime_col=request.datetime_col, numeric_col=request.numeric_col, observed=_points(series.iloc[-MAX_OBSERVED_POINTS:]),
        changepoints=findings, n_segments=result["n_segments"], verdict=changepoint_verdict(result),
        provenance=_provenance(stored, "changepoints", {"datetime_col": request.datetime_col, "numeric_col": request.numeric_col, "frequency": freq, "max_changepoints": request.max_changepoints}),
    )


@router.post("/datasets/{dataset_id}/atlas", response_model=AtlasForecastResponse)
def atlas_action(dataset_id: str, request: AtlasForecastRequest) -> AtlasForecastResponse:
    """Atlas explains the deterministic forecast/decomposition/changepoint result; it never
    computes or alters a value, and never presents a forecast as certainty."""
    stored = overview_store.get(dataset_id)
    series, freq = _require_series(stored, request.datetime_col, request.numeric_col)
    uncertainty = "This explanation describes a deterministic time-series computation; it does not establish causation, and Atlas cannot alter the underlying model or its output."

    if request.action is AtlasForecastAction.EXPLAIN_METHOD:
        seasonal_periods = _infer_seasonal_periods(freq)
        use_seasonal = seasonal_periods >= 2 and len(series) >= 2 * seasonal_periods
        summary = f"Exponential Smoothing (ETS) is tried first{' with a ' + str(seasonal_periods) + '-period seasonal component' if use_seasonal else ' without seasonality (not enough history for a full seasonal cycle)'}; SARIMAX is the fallback if ETS fails to fit."
        return AtlasForecastResponse(action=request.action, summary=summary, uncertainty=uncertainty, evidence=[AtlasEvidence(label="Frequency", value=freq), AtlasEvidence(label="History length", value=str(len(series)))])

    if request.action is AtlasForecastAction.EXPLAIN_INTERVALS:
        return AtlasForecastResponse(action=request.action, summary="The shaded band is a 95% confidence interval around the point forecast — it widens further into the future because uncertainty compounds with each additional step. A point forecast without this band is not the full picture; treat the band's width, not just its center, as the forecast.", uncertainty=uncertainty, evidence=[])

    if request.action is AtlasForecastAction.EXPLAIN_TREND:
        decomposition = decompose_series(series, freq)
        if "error" in decomposition:
            return AtlasForecastResponse(action=request.action, summary=f"Trend cannot be isolated for this series: {decomposition['error']}", uncertainty=uncertainty, evidence=[])
        return AtlasForecastResponse(action=request.action, summary=decomposition_verdict(decomposition), uncertainty=uncertainty, evidence=[AtlasEvidence(label="Trend strength", value=f"{decomposition['trend_strength']:.3f}")])

    if request.action is AtlasForecastAction.EXPLAIN_SEASONALITY:
        decomposition = decompose_series(series, freq)
        if "error" in decomposition:
            return AtlasForecastResponse(action=request.action, summary=f"Seasonality cannot be isolated for this series: {decomposition['error']}", uncertainty=uncertainty, evidence=[])
        return AtlasForecastResponse(action=request.action, summary=decomposition_verdict(decomposition), uncertainty=uncertainty, evidence=[AtlasEvidence(label="Seasonal strength", value=f"{decomposition['seasonal_strength']:.3f}"), AtlasEvidence(label="Seasonal period", value=str(decomposition["seasonal_period"]))])

    # EXPLAIN_CHANGEPOINTS
    result = detect_changepoints(series)
    if "error" in result:
        return AtlasForecastResponse(action=request.action, summary=f"Changepoint detection could not run: {result['error']}", uncertainty=uncertainty, evidence=[])
    return AtlasForecastResponse(action=request.action, summary=changepoint_verdict(result), uncertainty=uncertainty, evidence=[AtlasEvidence(label="Breaks found", value=str(len(result["changepoints"])))])
