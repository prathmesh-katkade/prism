from __future__ import annotations

import io

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from prism_api.main import create_app

from modules import forecasting as legacy_forecasting


def _daily_csv(start: str, values: list[float], col: str = "revenue") -> bytes:
    dates = pd.date_range(start, periods=len(values), freq="D")
    frame = pd.DataFrame({"date": dates.strftime("%Y-%m-%d"), col: values})
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False)
    return buffer.getvalue().encode()


# 10 points, non-seasonal (below 2*7=14), simple linear trend — fast, stable ETS fit.
FORECAST_VALUES = [10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0, 24.0, 26.0, 28.0]
FORECAST_CSV = _daily_csv("2026-01-01", FORECAST_VALUES)

# 28 points (4 weeks), a clean linear trend plus a repeating weekly offset — enough for STL
# (needs >= 2*7=14).
_WEEKDAY_OFFSET = [0.0, 8.0, -4.0, 3.0, -6.0, 9.0, -10.0]
DECOMPOSE_VALUES = [100.0 + 2.0 * i + _WEEKDAY_OFFSET[i % 7] for i in range(28)]
DECOMPOSE_CSV = _daily_csv("2026-01-01", DECOMPOSE_VALUES)

# 40 points: a stable level for 20 days, then a clear permanent level shift.
CHANGEPOINT_VALUES = [50.0 + (i % 3) for i in range(20)] + [80.0 + (i % 3) for i in range(20)]
CHANGEPOINT_CSV = _daily_csv("2026-01-01", CHANGEPOINT_VALUES)

# A perfectly flat series — no meaningful break anywhere.
STABLE_VALUES = [42.0] * 30
STABLE_CSV = _daily_csv("2026-01-01", STABLE_VALUES)


def _dataset(client: TestClient, csv: bytes, name: str = "series.csv") -> str:
    response = client.post("/api/v1/overview/datasets", files={"file": (name, csv, "text/csv")})
    assert response.status_code == 201
    return response.json()["dataset_id"]


def _legacy_series(csv: bytes, col: str = "revenue") -> tuple[pd.Series, str]:
    frame = pd.read_csv(io.BytesIO(csv))
    series, freq, error = legacy_forecasting.prepare_series(frame, "date", col)
    assert error is None, error
    return series, freq


# --- time-series validation --------------------------------------------------------


def test_forecast_rejects_a_column_not_in_the_active_dataset() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "does_not_exist", "horizon": 3})
    assert response.status_code == 422


def test_forecast_rejects_a_series_with_too_few_distinct_timestamps() -> None:
    csv = _daily_csv("2026-01-01", [1.0, 2.0, 3.0])  # below MIN_HISTORY_POINTS (8)
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 3})
    assert response.status_code == 422
    assert "at least" in response.json()["detail"]


def test_forecast_rejects_an_unparseable_datetime_column() -> None:
    csv = b"date,revenue\n" + b"".join(f"not-a-date-{i},{i}\n".encode() for i in range(10))
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 3})
    assert response.status_code == 422
    assert "parse" in response.json()["detail"]


# --- forecast: point + interval + caveat + holdout metrics, parity-tested -----------


def test_forecast_returns_a_point_forecast_with_an_interval_for_every_point() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 3})
    assert response.status_code == 200
    body = response.json()

    assert len(body["forecast"]) == 3
    assert len(body["intervals"]) == 3
    for point, interval in zip(body["forecast"], body["intervals"], strict=True):
        assert point["timestamp"] == interval["timestamp"]
        assert interval["lower"] <= interval["upper"]
    assert body["frequency"] == "D"
    assert "caveat" in body and body["caveat"]


def test_forecast_matches_legacy_model_choice_and_point_values_on_the_same_fixture() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 3})
    native = response.json()

    series, freq = _legacy_series(FORECAST_CSV)
    legacy = legacy_forecasting.run_forecast(series, 3, freq)
    assert "error" not in legacy

    assert native["model_used"] == legacy["model_used"]
    native_values = [point["value"] for point in native["forecast"]]
    legacy_values = legacy["forecast"]["forecast"].to_numpy().tolist()
    assert native_values == pytest.approx(legacy_values, abs=1e-6)


def test_forecast_caveat_matches_legacy_wording_exactly() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 3})
    native = response.json()

    series, freq = _legacy_series(FORECAST_CSV)
    legacy = legacy_forecasting.run_forecast(series, 3, freq)
    expected_caveat = legacy_forecasting.forecast_caveat(len(series), 3, legacy["model_used"])
    assert native["caveat"] == expected_caveat


def test_forecast_includes_holdout_metrics_when_enough_history_remains() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 3})
    metrics = response.json()["metrics"]
    assert metrics["holdout_points"] > 0
    assert metrics["mae"] is not None
    assert metrics["rmse"] is not None


def test_forecast_omits_metrics_gracefully_when_history_is_too_short_for_a_holdout() -> None:
    # Exactly MIN_HISTORY_POINTS: a holdout would leave fewer than the minimum to fit on.
    csv = _daily_csv("2026-01-01", [float(i) for i in range(8)])
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 2})
    assert response.status_code == 200
    metrics = response.json()["metrics"]
    assert metrics["holdout_points"] == 0
    assert metrics["mae"] is None
    assert metrics["note"]


# --- decomposition: parity-tested trend/seasonal strength ---------------------------


def test_decompose_rejects_a_series_with_no_seasonal_cycle() -> None:
    # Below 2 full seasonal cycles at period 7 (needs >= 14).
    csv = _daily_csv("2026-01-01", [float(i) for i in range(10)])
    client = TestClient(create_app())
    dataset_id = _dataset(client, csv)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/decompose", json={"datetime_col": "date", "numeric_col": "revenue"})
    assert response.status_code == 422


def test_decompose_matches_legacy_trend_and_seasonal_strength_on_the_same_fixture() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, DECOMPOSE_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/decompose", json={"datetime_col": "date", "numeric_col": "revenue"})
    assert response.status_code == 200
    native = response.json()

    series, freq = _legacy_series(DECOMPOSE_CSV)
    from modules.forecasting import decompose_series as legacy_decompose

    legacy = legacy_decompose(series, freq)
    assert "error" not in legacy

    assert native["trend_strength"] == pytest.approx(legacy["trend_strength"], abs=1e-6)
    assert native["seasonal_strength"] == pytest.approx(legacy["seasonal_strength"], abs=1e-6)
    assert native["seasonal_period"] == legacy["seasonal_period"]
    # A clean planted trend + weekly pattern should show up as a clearly non-trivial signal.
    assert native["trend_strength"] > 0.5


def test_decompose_reconstructs_the_observed_series_from_its_components() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, DECOMPOSE_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/decompose", json={"datetime_col": "date", "numeric_col": "revenue"})
    body = response.json()
    for observed, trend, seasonal, resid in zip(body["observed"], body["trend"], body["seasonal"], body["resid"], strict=True):
        assert observed["value"] == pytest.approx(trend["value"] + seasonal["value"] + resid["value"], abs=1e-6)


# --- changepoints: parity-tested, matches a planted level shift ---------------------


def test_changepoints_detects_a_planted_level_shift_matching_legacy_position() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CHANGEPOINT_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/changepoints", json={"datetime_col": "date", "numeric_col": "revenue", "max_changepoints": 5})
    assert response.status_code == 200
    native = response.json()

    series, _ = _legacy_series(CHANGEPOINT_CSV)
    legacy = legacy_forecasting.detect_changepoints(series, max_changepoints=5)

    assert len(native["changepoints"]) == len(legacy["changepoints"])
    for native_cp, legacy_cp in zip(native["changepoints"], legacy["changepoints"], strict=True):
        assert native_cp["position"] == legacy_cp["position"]
        assert native_cp["delta"] == pytest.approx(legacy_cp["delta"], abs=1e-6)
    # The planted shift is at index 20 (day 20 of 40); the detector should land close to it.
    assert native["changepoints"][0]["position"] == pytest.approx(20, abs=2)


def test_changepoints_reports_none_for_a_perfectly_stable_series() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, STABLE_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/changepoints", json={"datetime_col": "date", "numeric_col": "revenue"})
    assert response.status_code == 200
    body = response.json()
    assert body["changepoints"] == []
    assert "No statistically meaningful" in body["verdict"]


# --- provenance ----------------------------------------------------------------


def test_forecast_result_binds_provenance_to_the_current_revision() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    dataset = client.get(f"/api/v1/overview/datasets/{dataset_id}/profile").json()["dataset"]

    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/forecast", json={"datetime_col": "date", "numeric_col": "revenue", "horizon": 2})
    provenance = response.json()["provenance"]

    assert provenance["source_fingerprint"] == dataset["source_fingerprint"]
    assert provenance["dataset_revision"] == dataset["revision"]


# --- Atlas: explains the deterministic result, never invents a value ----------------


def test_atlas_explain_method_reports_frequency_and_history_length() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/atlas", json={"action": "explain_method", "datetime_col": "date", "numeric_col": "revenue"})
    assert response.status_code == 200
    body = response.json()
    assert any(item["label"] == "Frequency" and item["value"] == "D" for item in body["evidence"])
    assert any(item["label"] == "History length" and item["value"] == "10" for item in body["evidence"])


def test_atlas_explain_intervals_never_presents_the_forecast_as_certain() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, FORECAST_CSV)
    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/atlas", json={"action": "explain_intervals", "datetime_col": "date", "numeric_col": "revenue"})
    body = response.json()
    assert "95%" in body["summary"]
    assert "not the full picture" in body["summary"] or "band" in body["summary"]


def test_atlas_explain_changepoints_matches_the_deterministic_detector() -> None:
    client = TestClient(create_app())
    dataset_id = _dataset(client, CHANGEPOINT_CSV)
    detected = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/changepoints", json={"datetime_col": "date", "numeric_col": "revenue"}).json()

    response = client.post(f"/api/v1/forecasting/datasets/{dataset_id}/atlas", json={"action": "explain_changepoints", "datetime_col": "date", "numeric_col": "revenue"})
    body = response.json()
    evidence_value = next(item["value"] for item in body["evidence"] if item["label"] == "Breaks found")
    assert int(evidence_value) == len(detected["changepoints"])
