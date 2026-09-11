"""Tests for modules.confounder_detection — Simpson's Paradox / confounding
variable detection. Stratifies (or partials out) candidate confounders
behind an Auto-Insights correlation finding and flags cases where the
relationship reverses sign or collapses once you control for a third
variable — the classic "correlation isn't the whole story" check.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from modules.confounder_detection import (
    auto_scan_for_confounding,
    auto_scan_for_group_diff_confounding,
    detect_confounders,
    detect_group_diff_confounders,
    narrate_confounder_finding,
    narrate_group_diff_confounder_finding,
    partial_correlation,
    stratified_correlation,
    stratified_mean_difference,
)


def _simpsons_paradox_df() -> pd.DataFrame:
    """Textbook reversal: within each group x and y are perfectly *negatively*
    correlated (r = -1), but group B sits up-and-to-the-right of group A, so
    pooling the two groups together flips the overall correlation positive
    (r ≈ +0.49). Anyone reading only the pooled number would draw the
    opposite conclusion from what's actually happening inside each group.
    """
    group_a_x = [1, 2, 3, 4, 5]
    group_a_y = [5, 4, 3, 2, 1]
    group_b_x = [7, 8, 9, 10, 11]
    group_b_y = [9, 8, 7, 6, 5]
    return pd.DataFrame(
        {
            "x": group_a_x + group_b_x,
            "y": group_a_y + group_b_y,
            "group": ["A"] * 5 + ["B"] * 5,
        }
    )


def _robust_df() -> pd.DataFrame:
    """x and y correlate strongly and a third column carries no confounding
    information at all — the relationship should survive stratification.
    """
    rng = np.random.default_rng(0)
    x = np.arange(60, dtype=float)
    y = x * 2 + rng.normal(0, 0.5, size=60)
    noise_group = np.tile(["P", "Q", "R"], 20)
    return pd.DataFrame({"x": x, "y": y, "noise_group": noise_group})


# ─────────────────────────────────────────────────────────────────────────
# stratified_correlation
# ─────────────────────────────────────────────────────────────────────────
def test_stratified_correlation_detects_sign_flip():
    df = _simpsons_paradox_df()
    result = stratified_correlation(df, "x", "y", "group")

    assert result["overall_r"] > 0.3
    assert result["weighted_within_group_r"] < -0.9
    assert result["verdict"] == "paradox"
    assert len(result["per_group"]) == 2
    for g in result["per_group"]:
        assert g["r"] < -0.9
        assert g["n"] == 5


def test_stratified_correlation_robust_relationship():
    df = _robust_df()
    result = stratified_correlation(df, "x", "y", "noise_group")

    assert result["overall_r"] > 0.9
    assert result["weighted_within_group_r"] > 0.9
    assert result["verdict"] == "robust"


def test_stratified_correlation_flags_attenuation_without_sign_flip():
    # Overall correlation driven almost entirely by one dominant group;
    # within the other, near-zero — same sign throughout, but the
    # relationship materially weakens once stratified.
    rng = np.random.default_rng(1)
    x1 = np.arange(30, dtype=float)
    y1 = x1 * 3 + rng.normal(0, 0.5, size=30)
    x2 = np.arange(30, dtype=float)
    y2 = rng.normal(0, 5, size=30)  # no real relationship in this group
    df = pd.DataFrame(
        {"x": np.concatenate([x1, x2]), "y": np.concatenate([y1, y2]), "grp": ["A"] * 30 + ["B"] * 30}
    )
    result = stratified_correlation(df, "x", "y", "grp")
    assert result["verdict"] in ("attenuated", "paradox")


def test_stratified_correlation_ignores_undersized_groups():
    df = _simpsons_paradox_df()
    df = pd.concat([df, pd.DataFrame({"x": [3], "y": [3], "group": ["C"]})], ignore_index=True)
    result = stratified_correlation(df, "x", "y", "group", min_group_size=3)
    assert len(result["per_group"]) == 2  # group C (n=1) excluded
    assert result["excluded_small_groups"] == 1


def test_stratified_correlation_returns_none_verdict_with_too_few_groups():
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [4, 3, 2, 1], "group": ["A", "A", "A", "A"]})
    result = stratified_correlation(df, "x", "y", "group")
    assert result is None


# ─────────────────────────────────────────────────────────────────────────
# partial_correlation
# ─────────────────────────────────────────────────────────────────────────
def test_partial_correlation_removes_shared_driver():
    # z drives both x and y; once z is partialled out, x and y should have
    # near-zero residual correlation.
    rng = np.random.default_rng(2)
    z = rng.normal(0, 1, 500)
    x = z * 2 + rng.normal(0, 0.1, 500)
    y = z * 3 + rng.normal(0, 0.1, 500)
    df = pd.DataFrame({"x": x, "y": y, "z": z})

    overall_r = df["x"].corr(df["y"])
    partial_r = partial_correlation(df, "x", "y", "z")

    assert overall_r > 0.9
    assert abs(partial_r) < 0.2


def test_partial_correlation_returns_none_on_perfect_collinearity():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5], "y": [2, 4, 6, 8, 10], "z": [1, 2, 3, 4, 5]})
    # z == x exactly -> denominator term (1 - r_xz^2) is ~0
    assert partial_correlation(df, "x", "y", "z") is None


# ─────────────────────────────────────────────────────────────────────────
# detect_confounders — orchestration across candidate columns
# ─────────────────────────────────────────────────────────────────────────
def test_detect_confounders_flags_the_categorical_paradox_column():
    df = _simpsons_paradox_df()
    column_types = {"x": "numeric", "y": "numeric", "group": "categorical"}
    findings = detect_confounders(df, "x", "y", column_types)

    assert len(findings) == 1
    assert findings[0]["confounder"] == "group"
    assert findings[0]["type"] == "categorical"
    assert findings[0]["verdict"] == "paradox"


def test_detect_confounders_skips_robust_confounders_when_flagged_only():
    df = _robust_df()
    column_types = {"x": "numeric", "y": "numeric", "noise_group": "categorical"}
    findings = detect_confounders(df, "x", "y", column_types)
    assert all(f["verdict"] == "robust" for f in findings)


def test_detect_confounders_handles_numeric_candidate():
    rng = np.random.default_rng(3)
    z = rng.normal(0, 1, 200)
    x = z * 2 + rng.normal(0, 0.1, 200)
    y = z * 3 + rng.normal(0, 0.1, 200)
    df = pd.DataFrame({"x": x, "y": y, "z": z})
    column_types = {"x": "numeric", "y": "numeric", "z": "numeric"}

    findings = detect_confounders(df, "x", "y", column_types)
    z_finding = next(f for f in findings if f["confounder"] == "z")
    assert z_finding["type"] == "numeric"
    assert z_finding["verdict"] in ("paradox", "attenuated")


def test_detect_confounders_empty_df():
    df = pd.DataFrame({"x": [], "y": [], "g": []})
    findings = detect_confounders(df, "x", "y", {"x": "numeric", "y": "numeric", "g": "categorical"})
    assert findings == []


# ─────────────────────────────────────────────────────────────────────────
# auto_scan_for_confounding — the agentic entry point (no pair pre-selected)
# ─────────────────────────────────────────────────────────────────────────
def test_auto_scan_finds_the_paradox_without_a_hinted_pair():
    df = _simpsons_paradox_df()
    column_types = {"x": "numeric", "y": "numeric", "group": "categorical"}
    results = auto_scan_for_confounding(df, column_types)

    assert len(results) == 1
    assert {results[0]["x"], results[0]["y"]} == {"x", "y"}
    assert results[0]["findings"][0]["confounder"] == "group"


def test_auto_scan_returns_empty_when_nothing_worth_flagging():
    df = _robust_df()
    column_types = {"x": "numeric", "y": "numeric", "noise_group": "categorical"}
    results = auto_scan_for_confounding(df, column_types)
    assert results == []


def test_auto_scan_handles_too_few_numeric_columns():
    df = pd.DataFrame({"x": [1, 2, 3], "g": ["a", "b", "c"]})
    results = auto_scan_for_confounding(df, {"x": "numeric", "g": "categorical"})
    assert results == []


# ─────────────────────────────────────────────────────────────────────────
# narrate_confounder_finding
# ─────────────────────────────────────────────────────────────────────────
def test_narrate_confounder_finding_no_model():
    df = _simpsons_paradox_df()
    findings = detect_confounders(df, "x", "y", {"x": "numeric", "y": "numeric", "group": "categorical"})
    text, error = narrate_confounder_finding(None, "x", "y", findings[0])
    assert text == ""
    assert error


def test_narrate_confounder_finding_calls_gemini():
    df = _simpsons_paradox_df()
    findings = detect_confounders(df, "x", "y", {"x": "numeric", "y": "numeric", "group": "categorical"})

    class _FakeResponse:
        text = "Within each group the relationship is actually negative — the pooled positive correlation is an artifact of group differences."

    class _FakeModel:
        def generate_content(self, contents):
            assert "group" in contents.lower()
            assert "paradox" in contents.lower() or "simpson" in contents.lower()
            return _FakeResponse()

    text, error = narrate_confounder_finding(_FakeModel(), "x", "y", findings[0])
    assert error is None
    assert "negative" in text.lower()


# ─────────────────────────────────────────────────────────────────────────
# stratified_mean_difference / detect_group_diff_confounders — the group-
# difference analog of stratified_correlation/detect_confounders, for a
# binary categorical relationship (Welch's t-test / Cohen's d) instead of
# a numeric correlation.
# ─────────────────────────────────────────────────────────────────────────

def _group_diff_paradox_df(seed: int = 7) -> pd.DataFrame:
    """Simpson's Paradox for a group difference instead of a correlation:
    treatment A beats treatment B by the same small margin within *both*
    severity strata, but A is mostly given in the low-baseline ('severe')
    stratum and B mostly in the high-baseline ('mild') stratum, so pooling
    the two strata together flips the comparison — pooled B looks far
    better than pooled A, the opposite of what's true in every stratum.
    """
    rng = np.random.default_rng(seed)
    mild_b = rng.normal(100, 1.0, 90)
    mild_a = rng.normal(102, 1.0, 10)
    severe_a = rng.normal(2, 1.0, 90)
    severe_b = rng.normal(0, 1.0, 10)
    return pd.DataFrame(
        {
            "treatment": ["B"] * 90 + ["A"] * 10 + ["A"] * 90 + ["B"] * 10,
            "outcome": np.concatenate([mild_b, mild_a, severe_a, severe_b]),
            "severity": ["mild"] * 100 + ["severe"] * 100,
        }
    )


def _group_diff_robust_df(seed: int = 11) -> pd.DataFrame:
    """A real, sizable treatment effect (A ~10, B ~5) with an unrelated
    noise column that carries no confounding information at all."""
    rng = np.random.default_rng(seed)
    treatment = rng.choice(["A", "B"], size=200)
    base = np.where(treatment == "A", 10.0, 5.0)
    return pd.DataFrame(
        {
            "treatment": treatment,
            "outcome": base + rng.normal(0, 1.0, 200),
            "noise_group": np.tile(["P", "Q", "R", "S"], 50),
        }
    )


def test_stratified_mean_difference_detects_sign_flip():
    df = _group_diff_paradox_df()
    result = stratified_mean_difference(df, "treatment", "outcome", "severity")
    assert result is not None
    assert result["verdict"] == "paradox"
    assert result["overall_d"] < 0
    assert result["weighted_within_group_d"] > 0


def test_stratified_mean_difference_robust_relationship():
    df = _group_diff_robust_df()
    result = stratified_mean_difference(df, "treatment", "outcome", "noise_group")
    assert result is not None
    assert result["verdict"] == "robust"


def test_stratified_mean_difference_requires_exactly_two_groups():
    df = pd.DataFrame(
        {
            "treatment": ["A", "B", "C"] * 10,
            "outcome": np.arange(30, dtype=float),
            "group": ["x", "y"] * 15,
        }
    )
    assert stratified_mean_difference(df, "treatment", "outcome", "group") is None


def test_stratified_mean_difference_ignores_undersized_strata():
    df = _group_diff_paradox_df()
    # Both strata (100 rows each) fall below an inflated min_group_size,
    # so nothing usable remains to compare.
    result = stratified_mean_difference(df, "treatment", "outcome", "severity", min_group_size=1000)
    assert result is None


def test_detect_group_diff_confounders_flags_the_paradox_column():
    df = _group_diff_paradox_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "severity": "categorical"}
    findings = detect_group_diff_confounders(df, "treatment", "outcome", column_types)

    assert len(findings) == 1
    assert findings[0]["confounder"] == "severity"
    assert findings[0]["metric"] == "cohens_d"
    assert findings[0]["verdict"] == "paradox"


def test_detect_group_diff_confounders_skips_robust_confounders():
    df = _group_diff_robust_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "noise_group": "categorical"}
    findings = detect_group_diff_confounders(df, "treatment", "outcome", column_types)
    assert all(f["verdict"] == "robust" for f in findings)


def test_detect_group_diff_confounders_rejects_non_binary_x():
    df = pd.DataFrame(
        {
            "treatment": ["A", "B", "C"] * 20,
            "outcome": np.arange(60, dtype=float),
            "z": ["p", "q"] * 30,
        }
    )
    column_types = {"treatment": "categorical", "outcome": "numeric", "z": "categorical"}
    assert detect_group_diff_confounders(df, "treatment", "outcome", column_types) == []


def test_detect_group_diff_confounders_ignores_numeric_candidates():
    df = _group_diff_paradox_df()
    df["numeric_noise"] = np.arange(len(df), dtype=float)
    column_types = {
        "treatment": "categorical", "outcome": "numeric",
        "severity": "categorical", "numeric_noise": "numeric",
    }
    findings = detect_group_diff_confounders(df, "treatment", "outcome", column_types)
    assert all(f["confounder"] != "numeric_noise" for f in findings)


def test_detect_group_diff_confounders_empty_df():
    df = pd.DataFrame({"treatment": [], "outcome": [], "g": []})
    types = {"treatment": "categorical", "outcome": "numeric", "g": "categorical"}
    assert detect_group_diff_confounders(df, "treatment", "outcome", types) == []


# ─────────────────────────────────────────────────────────────────────────
# auto_scan_for_group_diff_confounding — the agentic entry point (no pair
# pre-selected)
# ─────────────────────────────────────────────────────────────────────────
def test_auto_scan_group_diff_finds_the_paradox_without_a_hinted_pair():
    df = _group_diff_paradox_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "severity": "categorical"}
    results = auto_scan_for_group_diff_confounding(df, column_types)

    # severity is itself a binary categorical with a large real baseline
    # difference in outcome, so auto-scan (which has no hint about which
    # pair the caller actually cares about) legitimately surfaces both
    # (treatment, outcome) and (severity, outcome) as candidate pairs —
    # the assertion below only needs the former to carry the flagged
    # confounder, not that it's the only result.
    scan = next(r for r in results if r["x"] == "treatment" and r["y"] == "outcome")
    assert scan["findings"][0]["confounder"] == "severity"
    assert scan["findings"][0]["verdict"] == "paradox"


def test_auto_scan_group_diff_returns_empty_when_nothing_worth_flagging():
    df = _group_diff_robust_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "noise_group": "categorical"}
    assert auto_scan_for_group_diff_confounding(df, column_types) == []


def test_auto_scan_group_diff_handles_no_binary_categorical_columns():
    df = pd.DataFrame({"outcome": [1.0, 2.0, 3.0], "g": ["a", "b", "c"]})
    results = auto_scan_for_group_diff_confounding(df, {"outcome": "numeric", "g": "categorical"})
    assert results == []


def test_auto_scan_group_diff_reuses_hinted_pairs():
    df = _group_diff_paradox_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "severity": "categorical"}
    results = auto_scan_for_group_diff_confounding(
        df, column_types, ttest_pairs=[("treatment", "outcome", -1.1)]
    )
    assert len(results) == 1
    assert results[0]["overall_d"] == -1.1  # hinted value passed straight through, not recomputed


# ─────────────────────────────────────────────────────────────────────────
# narrate_group_diff_confounder_finding
# ─────────────────────────────────────────────────────────────────────────
def test_narrate_group_diff_confounder_finding_no_model():
    df = _group_diff_paradox_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "severity": "categorical"}
    findings = detect_group_diff_confounders(df, "treatment", "outcome", column_types)
    text, error = narrate_group_diff_confounder_finding(None, "treatment", "outcome", findings[0])
    assert text == ""
    assert error


def test_narrate_group_diff_confounder_finding_calls_gemini():
    df = _group_diff_paradox_df()
    column_types = {"treatment": "categorical", "outcome": "numeric", "severity": "categorical"}
    findings = detect_group_diff_confounders(df, "treatment", "outcome", column_types)

    class _FakeResponse:
        text = "Treatment A actually does better within every severity group — the pooled comparison is misleading because of how patients were assigned."

    class _FakeModel:
        def generate_content(self, contents):
            assert "severity" in contents.lower()
            assert "treatment" in contents.lower()
            return _FakeResponse()

    text, error = narrate_group_diff_confounder_finding(_FakeModel(), "treatment", "outcome", findings[0])
    assert error is None
    assert "misleading" in text.lower()
