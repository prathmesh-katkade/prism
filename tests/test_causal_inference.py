"""Tests for modules.causal_inference — propensity score matching for
Average Treatment Effect on the Treated (ATT) estimation. The confounder
detector (modules.confounder_detection) diagnoses "this correlation is
confounded"; this module answers the natural follow-up, "so what's the
actual effect once I correct for it?"
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from modules.causal_inference import (
    estimate_cate_by_subgroup,
    estimate_causal_effect,
    narrate_cate_heterogeneity,
    narrate_causal_effect,
    nearest_neighbor_match,
    standardized_mean_diff,
)


def _confounded_df(n=500, true_effect=5.0, seed=0):
    """z (e.g. "customer tenure") drives both treatment assignment and the
    outcome, so a naive group-mean comparison is biased upward beyond the
    true effect. Propensity score matching on z should recover an estimate
    much closer to `true_effect` than the naive diff-in-means does.
    """
    rng = np.random.default_rng(seed)
    z = rng.normal(50, 10, n)
    propensity = 1 / (1 + np.exp(-(z - 50) / 8))
    treated = rng.random(n) < propensity
    outcome = 2 * z + true_effect * treated + rng.normal(0, 3, n)
    return pd.DataFrame(
        {
            "treatment": np.where(treated, "yes", "no"),
            "outcome": outcome,
            "z": z,
        }
    ), true_effect


# ─────────────────────────────────────────────────────────────────────────
# standardized_mean_diff
# ─────────────────────────────────────────────────────────────────────────
def test_smd_zero_when_groups_identical():
    s = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert standardized_mean_diff(s, s) == pytest.approx(0.0, abs=1e-9)


def test_smd_positive_when_treated_higher():
    treated = pd.Series([10.0, 11.0, 12.0, 13.0])
    control = pd.Series([1.0, 2.0, 3.0, 4.0])
    assert standardized_mean_diff(treated, control) > 0


def test_smd_none_on_empty_input():
    assert standardized_mean_diff(pd.Series([], dtype=float), pd.Series([1.0])) is None


def test_smd_none_on_zero_variance_both_groups():
    assert standardized_mean_diff(pd.Series([5.0, 5.0]), pd.Series([5.0, 5.0])) is None


# ─────────────────────────────────────────────────────────────────────────
# nearest_neighbor_match
# ─────────────────────────────────────────────────────────────────────────
def test_nearest_neighbor_match_pairs_close_points():
    logit_ps = np.array([0.0, 0.05, 5.0, 5.05])
    treated = np.array([True, False, True, False])
    pairs = nearest_neighbor_match(logit_ps, treated, caliper=1.0)
    assert (0, 1) in pairs
    assert (2, 3) in pairs
    assert len(pairs) == 2


def test_nearest_neighbor_match_respects_caliper():
    logit_ps = np.array([0.0, 100.0])
    treated = np.array([True, False])
    pairs = nearest_neighbor_match(logit_ps, treated, caliper=0.01)
    assert pairs == []


def test_nearest_neighbor_match_no_replacement():
    logit_ps = np.array([0.0, 0.1, 0.2])
    treated = np.array([True, True, False])
    pairs = nearest_neighbor_match(logit_ps, treated, caliper=5.0)
    control_used = [c for _, c in pairs]
    assert len(control_used) == len(set(control_used))  # each control matched at most once


def test_nearest_neighbor_match_empty_when_no_treated_or_control():
    assert nearest_neighbor_match(np.array([0.0, 0.1]), np.array([True, True]), caliper=1.0) == []
    assert nearest_neighbor_match(np.array([0.0, 0.1]), np.array([False, False]), caliper=1.0) == []


# ─────────────────────────────────────────────────────────────────────────
# estimate_causal_effect — validation / failure paths
# ─────────────────────────────────────────────────────────────────────────
def test_estimate_causal_effect_empty_df():
    result = estimate_causal_effect(pd.DataFrame(), "t", "yes", "y")
    assert result["ok"] is False
    assert "error" in result


def test_estimate_causal_effect_missing_columns():
    df = pd.DataFrame({"a": [1, 2, 3]})
    result = estimate_causal_effect(df, "t", "yes", "y")
    assert result["ok"] is False


def test_estimate_causal_effect_non_numeric_outcome():
    df = pd.DataFrame({"t": ["yes", "no"] * 10, "y": ["a", "b"] * 10, "z": range(20)})
    result = estimate_causal_effect(df, "t", "yes", "y", covariates=["z"])
    assert result["ok"] is False
    assert "numeric" in result["error"].lower()


def test_estimate_causal_effect_non_binary_treatment():
    df = pd.DataFrame({"t": ["a", "b", "c"] * 10, "y": range(30), "z": range(30)})
    result = estimate_causal_effect(df, "t", "a", "y", covariates=["z"])
    assert result["ok"] is False
    assert "2 groups" in result["error"]


def test_estimate_causal_effect_too_few_units():
    df = pd.DataFrame({"t": ["yes", "no", "yes"], "y": [1.0, 2.0, 3.0], "z": [1.0, 2.0, 3.0]})
    result = estimate_causal_effect(df, "t", "yes", "y", covariates=["z"], min_group_size=5)
    assert result["ok"] is False
    assert "enough data" in result["error"]


def test_estimate_causal_effect_no_covariates_available():
    df = pd.DataFrame({"t": ["yes", "no"] * 10, "y": range(20)})
    result = estimate_causal_effect(df, "t", "yes", "y", covariates=[])
    assert result["ok"] is False
    assert "covariates" in result["error"].lower()


def test_estimate_causal_effect_unknown_treated_value():
    df, _ = _confounded_df()
    result = estimate_causal_effect(df, "treatment", "maybe", "outcome", covariates=["z"])
    assert result["ok"] is False


# ─────────────────────────────────────────────────────────────────────────
# estimate_causal_effect — the actual statistical claim: matching reduces
# confounding bias relative to a naive group-mean comparison.
# ─────────────────────────────────────────────────────────────────────────
def test_matching_reduces_confounding_bias_vs_naive_diff():
    df, true_effect = _confounded_df()
    naive_diff = df.loc[df["treatment"] == "yes", "outcome"].mean() - df.loc[df["treatment"] == "no", "outcome"].mean()

    result = estimate_causal_effect(df, "treatment", "yes", "outcome", covariates=["z"], random_state=1)

    assert result["ok"] is True
    assert abs(naive_diff - true_effect) > abs(result["att"] - true_effect), (
        "PSM estimate should be closer to the true effect than the naive (unadjusted) difference"
    )
    assert result["ci_low"] < result["att"] < result["ci_high"]


def test_matching_improves_covariate_balance():
    df, _ = _confounded_df()
    result = estimate_causal_effect(df, "treatment", "yes", "outcome", covariates=["z"], random_state=1)
    assert result["ok"] is True
    before = abs(next(b["smd"] for b in result["balance_before"] if b["covariate"] == "z"))
    after = abs(next(b["smd"] for b in result["balance_after"] if b["covariate"] == "z"))
    assert after < before


def test_result_reports_n_treated_and_control():
    df, _ = _confounded_df()
    result = estimate_causal_effect(df, "treatment", "yes", "outcome", covariates=["z"], random_state=1)
    assert result["n_treated"] + result["n_control"] == len(df)
    assert result["control_value"] == "no"


def test_auto_selects_numeric_covariates_via_column_types():
    df, _ = _confounded_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "z": "numeric"}
    result = estimate_causal_effect(df, "treatment", "yes", "outcome", column_types=column_types, random_state=1)
    assert result["ok"] is True
    assert result["covariates"] == ["z"]


def test_low_match_rate_produces_a_warning():
    # Force a near-zero caliper so almost nothing matches, without failing outright.
    df, _ = _confounded_df(n=200, seed=2)
    result = estimate_causal_effect(
        df, "treatment", "yes", "outcome", covariates=["z"], caliper=0.001, random_state=1
    )
    if result["ok"]:
        assert result["match_rate"] < 1.0
    else:
        assert "caliper" in result["error"].lower()


# ─────────────────────────────────────────────────────────────────────────
# narrate_causal_effect
# ─────────────────────────────────────────────────────────────────────────
def test_narrate_causal_effect_no_model():
    df, _ = _confounded_df()
    result = estimate_causal_effect(df, "treatment", "yes", "outcome", covariates=["z"], random_state=1)
    text, error = narrate_causal_effect(None, result)
    assert text == ""
    assert error


def test_narrate_causal_effect_not_ok_result():
    text, error = narrate_causal_effect(object(), {"ok": False, "error": "nope"})
    assert text == ""
    assert error


def test_narrate_causal_effect_calls_gemini():
    df, _ = _confounded_df()
    result = estimate_causal_effect(df, "treatment", "yes", "outcome", covariates=["z"], random_state=1)

    class _FakeResponse:
        text = "Treated customers saw a real, statistically meaningful lift over similar untreated customers."

    class _FakeModel:
        def generate_content(self, contents):
            assert "treatment" in contents.lower()
            assert "outcome" in contents.lower()
            return _FakeResponse()

    text, error = narrate_causal_effect(_FakeModel(), result)
    assert error is None
    assert "lift" in text.lower()


# ─────────────────────────────────────────────────────────────────────────
# estimate_cate_by_subgroup — Conditional Average Treatment Effect: does the
# effect vary by subgroup? (heterogeneous treatment effects / "qualitative
# interaction" detection, the natural agentic follow-on to the pooled ATT).
# ─────────────────────────────────────────────────────────────────────────
def _subgroup_df(n_per_group=250, seed=0):
    """Two segments with genuinely different, opposite-signed treatment
    effects (a real "qualitative interaction" — not just different
    magnitudes): segment "A" benefits (+6), segment "B" is actively hurt
    (-6). The pooled ATT should land near the middle-ish, but per-segment
    CATE should recover both signs distinctly.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for segment, effect in [("A", 6.0), ("B", -6.0)]:
        z = rng.normal(50, 10, n_per_group)
        propensity = 1 / (1 + np.exp(-(z - 50) / 8))
        treated = rng.random(n_per_group) < propensity
        outcome = 2 * z + effect * treated + rng.normal(0, 3, n_per_group)
        rows.append(pd.DataFrame({
            "treatment": np.where(treated, "yes", "no"),
            "outcome": outcome,
            "z": z,
            "segment": segment,
        }))
    return pd.concat(rows, ignore_index=True)


def _homogeneous_df(n_per_group=250, seed=0):
    """Same +5 effect in every segment — CATE should find no heterogeneity."""
    rng = np.random.default_rng(seed)
    rows = []
    for segment in ["A", "B"]:
        z = rng.normal(50, 10, n_per_group)
        propensity = 1 / (1 + np.exp(-(z - 50) / 8))
        treated = rng.random(n_per_group) < propensity
        outcome = 2 * z + 5.0 * treated + rng.normal(0, 3, n_per_group)
        rows.append(pd.DataFrame({
            "treatment": np.where(treated, "yes", "no"),
            "outcome": outcome,
            "z": z,
            "segment": segment,
        }))
    return pd.concat(rows, ignore_index=True)


def test_cate_detects_sign_reversal_across_subgroups():
    df = _subgroup_df()
    result = estimate_cate_by_subgroup(
        df, "treatment", "yes", "outcome", "segment", covariates=["z"], random_state=1
    )
    assert result["ok"] is True
    assert result["sign_reversal"] is True
    levels = {s["level"]: s for s in result["subgroups"] if s.get("ok")}
    assert levels["A"]["att"] > 0
    assert levels["B"]["att"] < 0


def test_cate_no_heterogeneity_when_effect_is_uniform():
    df = _homogeneous_df()
    result = estimate_cate_by_subgroup(
        df, "treatment", "yes", "outcome", "segment", covariates=["z"], random_state=1
    )
    assert result["ok"] is True
    assert result["sign_reversal"] is False
    assert result["heterogeneity_detected"] is False


def test_cate_missing_subgroup_column():
    df, _ = _confounded_df()
    result = estimate_cate_by_subgroup(df, "treatment", "yes", "outcome", "nonexistent_col", covariates=["z"])
    assert result["ok"] is False
    assert "nonexistent_col" in result["error"]


def test_cate_propagates_pooled_failure():
    df = pd.DataFrame({"t": ["a", "b", "c"] * 10, "y": range(30), "z": range(30), "seg": ["x", "y"] * 15})
    result = estimate_cate_by_subgroup(df, "t", "a", "y", "seg", covariates=["z"])
    assert result["ok"] is False


def test_cate_skips_undersized_subgroup_without_crashing():
    df = _subgroup_df(n_per_group=250)
    # Add a third, tiny segment that can't support matching (min_group_size=5).
    tiny = pd.DataFrame({
        "treatment": ["yes", "no"],
        "outcome": [1.0, 2.0],
        "z": [50.0, 51.0],
        "segment": ["C", "C"],
    })
    df = pd.concat([df, tiny], ignore_index=True)
    result = estimate_cate_by_subgroup(
        df, "treatment", "yes", "outcome", "segment", covariates=["z"], random_state=1
    )
    assert result["ok"] is True
    skipped = [s for s in result["subgroups"] if s["level"] == "C"]
    assert skipped and skipped[0]["ok"] is False
    # The two well-populated segments still produced usable estimates.
    assert sum(1 for s in result["subgroups"] if s.get("ok")) == 2


def test_cate_requires_at_least_two_usable_subgroups_for_heterogeneity_flags():
    df = _subgroup_df(n_per_group=250)
    df = df[df["segment"] == "A"].copy()  # only one segment present
    result = estimate_cate_by_subgroup(
        df, "treatment", "yes", "outcome", "segment", covariates=["z"], random_state=1
    )
    assert result["ok"] is True
    assert result["heterogeneity_detected"] is False
    assert result["sign_reversal"] is False
    assert any("not enough" in w.lower() for w in result["warnings"])


def test_narrate_cate_heterogeneity_no_model():
    df = _subgroup_df()
    result = estimate_cate_by_subgroup(df, "treatment", "yes", "outcome", "segment", covariates=["z"], random_state=1)
    text, error = narrate_cate_heterogeneity(None, result)
    assert text == ""
    assert error


def test_narrate_cate_heterogeneity_calls_gemini():
    df = _subgroup_df()
    result = estimate_cate_by_subgroup(df, "treatment", "yes", "outcome", "segment", covariates=["z"], random_state=1)

    class _FakeResponse:
        text = "The treatment helps segment A but actively hurts segment B — a one-size-fits-all rollout would be a mistake."

    class _FakeModel:
        def generate_content(self, contents):
            return _FakeResponse()

    text, error = narrate_cate_heterogeneity(_FakeModel(), result)
    assert error is None
    assert "segment" in text.lower()
