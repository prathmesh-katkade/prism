"""Tests for modules.anomaly — IsolationForest-based row flagging, plus the
ensemble (IsolationForest + LOF + DBSCAN) consensus detector."""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.anomaly import (
    ENSEMBLE_METHODS,
    ENSEMBLE_MIN_ROWS,
    MIN_ROWS_REQUIRED,
    anomaly_reference_numbers,
    driver_reference_numbers,
    ensemble_reference_numbers,
    find_anomalies,
    find_anomalies_ensemble,
    find_anomaly_drivers,
    fingerprint_drivers,
    fingerprint_flagged,
    narrate_anomalies,
    narrate_anomaly_drivers,
    narrate_ensemble_disagreement,
    verify_narration,
)


def _clean_df_with_one_outlier(n: int = 50) -> pd.DataFrame:
    rng = np.random.default_rng(42)
    values = rng.normal(loc=50, scale=2, size=n)
    values[0] = 5000.0  # obvious, extreme outlier
    return pd.DataFrame({"value": values, "label": ["x"] * n})


def test_find_anomalies_flags_the_planted_outlier():
    df = _clean_df_with_one_outlier()
    flagged, error = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    assert error is None
    assert flagged is not None
    assert 0 in flagged.index
    assert "anomaly_reason" in flagged.columns


def test_find_anomalies_errors_below_min_rows():
    df = pd.DataFrame({"value": range(MIN_ROWS_REQUIRED - 1)})
    flagged, error = find_anomalies(df, {"value": "numeric"})
    assert flagged is None
    assert error is not None


def test_find_anomalies_errors_with_no_numeric_columns():
    df = pd.DataFrame({"label": ["a"] * 20})
    flagged, error = find_anomalies(df, {"label": "categorical"})
    assert flagged is None
    assert error is not None


def test_find_anomalies_returns_empty_frame_when_nothing_flagged():
    # tight contamination + perfectly uniform data -> may legitimately find none
    df = pd.DataFrame({"value": [50.0] * 30})
    flagged, error = find_anomalies(df, {"value": "numeric"}, contamination=0.01)
    assert error is None
    assert flagged is not None  # empty df is a valid "no anomalies" result


# --- fingerprint_flagged -------------------------------------------------

def test_fingerprint_is_stable_for_the_same_result():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    assert fingerprint_flagged(flagged) == fingerprint_flagged(flagged)


def test_fingerprint_changes_when_flagged_rows_change():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    other = flagged.drop(index=flagged.index[0]) if len(flagged) else flagged
    if other.equals(flagged):
        # only one flagged row (common with a single planted outlier) — compare
        # against a genuinely different frame instead so the test still means something
        other = pd.DataFrame({"value": [1.0], "label": ["y"], "anomaly_reason": ["different"]})
    assert fingerprint_flagged(flagged) != fingerprint_flagged(other)


def test_fingerprint_of_empty_frame_is_stable():
    empty = pd.DataFrame({"value": [], "label": [], "anomaly_reason": []})
    assert fingerprint_flagged(empty) == fingerprint_flagged(empty.copy())


# --- narrate_anomalies ---------------------------------------------------

def test_narrate_anomalies_without_model_returns_error():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    narration, error = narrate_anomalies(None, flagged)
    assert narration == ""
    assert error is not None


def test_narrate_anomalies_with_no_flagged_rows_skips_gemini():
    empty = pd.DataFrame({"value": [], "label": [], "anomaly_reason": []})

    class _ShouldNotBeCalled:
        def generate_content(self, *_args, **_kwargs):
            raise AssertionError("Gemini should not be called when nothing was flagged")

    narration, error = narrate_anomalies(_ShouldNotBeCalled(), empty)
    assert error is None
    assert "no anomalies" in narration.lower()


def test_narrate_anomalies_calls_gemini_with_flagged_summary():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})

    class _FakeResponse:
        text = "These rows look off because of extreme values. Consider reviewing them."

    class _FakeModel:
        def generate_content(self, contents):
            assert "flagged" in contents.lower() or "anomal" in contents.lower()
            return _FakeResponse()

    narration, error = narrate_anomalies(_FakeModel(), flagged)
    assert error is None
    assert "review" in narration.lower()


# --- anomaly_reference_numbers / verify_narration -------------------------

def test_anomaly_reference_numbers_empty_is_safe():
    assert anomaly_reference_numbers(None) == set()
    empty = pd.DataFrame({"value": [], "label": [], "anomaly_reason": []})
    assert anomaly_reference_numbers(empty) == set()


def test_anomaly_reference_numbers_includes_flagged_count():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    numbers = anomaly_reference_numbers(flagged)
    assert float(len(flagged)) in numbers


def test_verify_narration_confirmed_when_flagged_count_matches():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    narration = f"{len(flagged)} row(s) look like genuine data-entry errors — worth a spot-check."
    verification = verify_narration(narration, anomaly_reference_numbers(flagged))
    assert verification["status"] == "confirmed"


def test_verify_narration_flagged_when_a_number_is_fabricated():
    df = _clean_df_with_one_outlier()
    flagged, _ = find_anomalies(df, {"value": "numeric", "label": "categorical"})
    narration = "A shocking 999999 rows were flagged — highly unusual."
    verification = verify_narration(narration, anomaly_reference_numbers(flagged))
    assert verification["status"] == "flagged"


def test_verify_narration_unverifiable_when_no_numbers_in_text():
    verification = verify_narration("These look like genuine outliers.", set())
    assert verification["status"] == "unverifiable"


def test_verify_narration_never_raises_on_malformed_input():
    verification = verify_narration("Some text with 42 in it.", None)  # type: ignore[arg-type]
    assert verification["status"] in ("flagged", "unverifiable")


# --- find_anomalies_ensemble ----------------------------------------------

def _ensemble_df(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(7)
    values = rng.normal(loc=50, scale=2, size=n)
    other = rng.normal(loc=10, scale=1, size=n)
    # a planted extreme point every method should agree is an outlier
    values[0], other[0] = 5000.0, 500.0
    return pd.DataFrame({"value": values, "other": other, "label": ["x"] * n})


def test_find_anomalies_ensemble_flags_the_planted_outlier_by_all_methods():
    df = _ensemble_df()
    consensus, summary, error = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )
    assert error is None
    assert consensus is not None and 0 in consensus.index
    assert consensus.loc[0, "consensus_count"] == len(ENSEMBLE_METHODS)
    assert set(summary.keys()) == set(ENSEMBLE_METHODS)
    for method_stats in summary.values():
        assert "flagged_count" in method_stats and "pct" in method_stats


def test_find_anomalies_ensemble_consensus_sorted_descending():
    df = _ensemble_df()
    consensus, _, error = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )
    assert error is None
    counts = consensus["consensus_count"].tolist()
    assert counts == sorted(counts, reverse=True)


def test_find_anomalies_ensemble_errors_below_min_rows():
    df = pd.DataFrame({"value": range(ENSEMBLE_MIN_ROWS - 1), "other": range(ENSEMBLE_MIN_ROWS - 1)})
    consensus, summary, error = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric"}
    )
    assert consensus is None and summary is None
    assert error is not None


def test_find_anomalies_ensemble_errors_with_no_numeric_columns():
    df = pd.DataFrame({"label": ["a"] * 30})
    consensus, summary, error = find_anomalies_ensemble(df, {"label": "categorical"})
    assert consensus is None and summary is None
    assert error is not None


def test_find_anomalies_ensemble_needs_at_least_two_numeric_columns():
    # distance-based methods (LOF/DBSCAN) are meaningless on a single axis
    # the same way IsolationForest still works on — document the stricter
    # requirement rather than silently degrading.
    rng = np.random.default_rng(1)
    df = pd.DataFrame({"value": rng.normal(size=30)})
    consensus, summary, error = find_anomalies_ensemble(df, {"value": "numeric"})
    assert consensus is None and summary is None
    assert error is not None


def test_find_anomalies_ensemble_returns_empty_when_nothing_flagged():
    df = pd.DataFrame({"value": [50.0] * 30, "other": [10.0] * 30})
    consensus, summary, error = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric"}, contamination=0.01
    )
    assert error is None
    assert consensus is not None and consensus.empty
    assert summary is not None


# --- narrate_ensemble_disagreement -----------------------------------------

def test_narrate_ensemble_disagreement_without_model_returns_error():
    df = _ensemble_df()
    consensus, summary, _ = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )
    narration, error = narrate_ensemble_disagreement(None, consensus, summary)
    assert narration == ""
    assert error is not None


def test_narrate_ensemble_disagreement_with_no_flagged_rows_skips_gemini():
    empty = pd.DataFrame({"value": [], "other": [], "anomaly_reason": [], "consensus_count": []})
    summary = {m: {"flagged_count": 0, "pct": 0.0} for m in ENSEMBLE_METHODS}

    class _ShouldNotBeCalled:
        def generate_content(self, *_args, **_kwargs):
            raise AssertionError("Gemini should not be called when nothing was flagged")

    narration, error = narrate_ensemble_disagreement(_ShouldNotBeCalled(), empty, summary)
    assert error is None
    assert "no anomal" in narration.lower()


def test_narrate_ensemble_disagreement_calls_gemini_with_method_summary():
    df = _ensemble_df()
    consensus, summary, _ = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )

    class _FakeResponse:
        text = "Isolation Forest and LOF agree on the global outlier; DBSCAN is stricter."

    class _FakeModel:
        def generate_content(self, contents):
            assert "isolation" in contents.lower() and "lof" in contents.lower()
            return _FakeResponse()

    narration, error = narrate_ensemble_disagreement(_FakeModel(), consensus, summary)
    assert error is None
    assert "agree" in narration.lower()


# --- ensemble_reference_numbers / verify_narration -------------------------

def test_ensemble_reference_numbers_empty_is_safe():
    assert ensemble_reference_numbers(None, None) == set()
    empty = pd.DataFrame({"value": [], "other": [], "anomaly_reason": [], "consensus_count": []})
    assert ensemble_reference_numbers(empty, {}) == set()


def test_ensemble_reference_numbers_includes_method_counts():
    df = _ensemble_df()
    consensus, summary, _ = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )
    numbers = ensemble_reference_numbers(consensus, summary)
    assert float(len(consensus)) in numbers
    for stats in summary.values():
        assert float(stats["flagged_count"]) in numbers


def test_verify_narration_confirmed_for_ensemble_when_numbers_match():
    df = _ensemble_df()
    consensus, summary, _ = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )
    n_full = int((consensus["consensus_count"] == len(ENSEMBLE_METHODS)).sum())
    narration = f"All 3 methods agree on {n_full} row(s) — a strong-consensus anomaly."
    verification = verify_narration(narration, ensemble_reference_numbers(consensus, summary))
    assert verification["status"] == "confirmed"


def test_verify_narration_flagged_for_ensemble_when_fabricated():
    df = _ensemble_df()
    consensus, summary, _ = find_anomalies_ensemble(
        df, {"value": "numeric", "other": "numeric", "label": "categorical"}
    )
    narration = "An implausible 424242 rows were flagged by every method."
    verification = verify_narration(narration, ensemble_reference_numbers(consensus, summary))
    assert verification["status"] == "flagged"


# --- find_anomaly_drivers ---------------------------------------------------

def _df_with_distinguishable_anomalies(n_normal: int = 60, n_anomaly: int = 8):
    """Normal rows cluster around amount=100 in North/South; anomaly rows
    are planted with a much higher amount AND a distinct region — a
    numeric driver and a categorical driver, both by construction."""
    rng = np.random.default_rng(7)
    normal = pd.DataFrame(
        {
            "amount": rng.normal(loc=100, scale=5, size=n_normal),
            "region": rng.choice(["North", "South"], size=n_normal),
        }
    )
    anomaly = pd.DataFrame(
        {
            "amount": rng.normal(loc=500, scale=5, size=n_anomaly),
            "region": ["East"] * n_anomaly,
        }
    )
    df = pd.concat([normal, anomaly], ignore_index=True)
    flagged = df.iloc[n_normal:].copy()
    return df, flagged


def test_find_anomaly_drivers_ranks_numeric_and_categorical_drivers():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    assert drivers
    columns = {d["column"] for d in drivers}
    assert "amount" in columns
    assert "region" in columns
    assert all(
        abs(drivers[i]["effect_size"]) >= abs(drivers[i + 1]["effect_size"]) for i in range(len(drivers) - 1)
    )


def test_find_anomaly_drivers_numeric_finding_has_means_and_effect_size():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    amount_finding = next(d for d in drivers if d["column"] == "amount")
    assert amount_finding["type"] == "numeric"
    assert amount_finding["anomaly_mean"] > amount_finding["normal_mean"]
    assert amount_finding["effect_size_label"] == "large"
    assert amount_finding["p_value"] < 0.05


def test_find_anomaly_drivers_empty_when_no_flagged_rows():
    df, _ = _df_with_distinguishable_anomalies()
    empty = df.iloc[0:0].copy()
    assert find_anomaly_drivers(df, empty, {"amount": "numeric", "region": "categorical"}) == []


def test_find_anomaly_drivers_empty_when_too_few_rows_on_either_side():
    df, flagged = _df_with_distinguishable_anomalies(n_normal=60, n_anomaly=1)
    assert find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"}) == []


def test_find_anomaly_drivers_empty_when_all_rows_flagged():
    df, _ = _df_with_distinguishable_anomalies()
    assert find_anomaly_drivers(df, df, {"amount": "numeric", "region": "categorical"}) == []


def test_find_anomaly_drivers_ignores_column_with_too_many_categories():
    df, _ = _df_with_distinguishable_anomalies()
    df = df.copy()
    df["high_card"] = [f"id_{i}" for i in range(len(df))]
    flagged = df.iloc[-8:].copy()
    drivers = find_anomaly_drivers(
        df,
        flagged,
        {"amount": "numeric", "region": "categorical", "high_card": "categorical"},
        max_categorical_groups=15,
    )
    assert "high_card" not in {d["column"] for d in drivers}


def test_find_anomaly_drivers_filters_non_significant_columns():
    rng = np.random.default_rng(3)
    df = pd.DataFrame(
        {
            "amount": rng.normal(loc=100, scale=5, size=60),
            "noise": rng.normal(loc=0, scale=1, size=60),
        }
    )
    flagged = df.sample(5, random_state=1)
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "noise": "numeric"})
    for d in drivers:
        assert d["p_value"] < 0.05


# --- fingerprint_drivers -----------------------------------------------------

def test_fingerprint_drivers_stable_and_sensitive():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    assert fingerprint_drivers(drivers) == fingerprint_drivers(drivers)
    assert fingerprint_drivers(drivers) != fingerprint_drivers([])
    assert fingerprint_drivers([]) == fingerprint_drivers([])


# --- narrate_anomaly_drivers ---------------------------------------------------

def test_narrate_anomaly_drivers_without_model_returns_error():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    narration, error = narrate_anomaly_drivers(None, drivers, len(flagged))
    assert narration == ""
    assert error is not None


def test_narrate_anomaly_drivers_with_no_drivers_skips_gemini():
    class _ShouldNotBeCalled:
        def generate_content(self, *_args, **_kwargs):
            raise AssertionError("Gemini should not be called when there are no drivers")

    narration, error = narrate_anomaly_drivers(_ShouldNotBeCalled(), [], 5)
    assert error is None
    assert "no statistically significant" in narration.lower()


def test_narrate_anomaly_drivers_calls_gemini_with_driver_summary():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})

    captured = {}

    class _FakeModel:
        def generate_content(self, prompt, **_kwargs):
            captured["prompt"] = prompt

            class _Resp:
                text = "The anomalies have much higher amounts and are all from the East region."

            return _Resp()

    narration, error = narrate_anomaly_drivers(_FakeModel(), drivers, len(flagged))
    assert error is None
    assert "amount" in captured["prompt"]
    assert narration


# --- driver_reference_numbers / verify_narration ------------------------------

def test_driver_reference_numbers_empty_is_safe():
    assert driver_reference_numbers(None) == set()
    assert driver_reference_numbers([]) == set()


def test_driver_reference_numbers_includes_effect_size_and_mean():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    numbers = driver_reference_numbers(drivers)
    amount_finding = next(d for d in drivers if d["column"] == "amount")
    assert round(amount_finding["effect_size"], 2) in numbers
    assert round(amount_finding["anomaly_mean"], 3) in numbers


def test_verify_narration_confirmed_for_drivers_when_numbers_match():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    amount_finding = next(d for d in drivers if d["column"] == "amount")
    narration = (
        f"The flagged rows have amount averaging {amount_finding['anomaly_mean']:.3g} vs. "
        f"{amount_finding['normal_mean']:.3g} normally (Cohen's d = {amount_finding['effect_size']:.2f})."
    )
    verification = verify_narration(narration, driver_reference_numbers(drivers))
    assert verification["status"] == "confirmed"


def test_verify_narration_flagged_for_drivers_when_fabricated():
    df, flagged = _df_with_distinguishable_anomalies()
    drivers = find_anomaly_drivers(df, flagged, {"amount": "numeric", "region": "categorical"})
    narration = "The anomalies have an implausible average amount of 999999.9."
    verification = verify_narration(narration, driver_reference_numbers(drivers))
    assert verification["status"] == "flagged"
