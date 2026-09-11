"""Tests for modules.experiment_design — A/B test sample-size/power
calculator and post-hoc power checks for existing test results.
"""
from __future__ import annotations

from modules.experiment_design import (
    achieved_power_anova,
    achieved_power_chi2,
    achieved_power_correlation,
    achieved_power_ttest,
    cohens_f_from_eta_sq,
    cohens_w_from_chi2,
    fisher_z,
    interpret_power_check,
    interpret_sample_size_correlation,
    interpret_sample_size_means,
    interpret_sample_size_proportions,
    power_check_anova,
    power_check_chi2,
    power_check_correlation,
    power_check_ttest,
    sample_size_correlation,
    sample_size_two_means,
    sample_size_two_proportions,
)

# --- sample_size_two_proportions -------------------------------------------

def test_sample_size_two_proportions_basic_is_sane():
    result = sample_size_two_proportions(baseline_rate=0.20, mde=0.05)
    assert result.get("error") is None
    # 20% -> 25% lift, alpha=.05, power=.8, two-sided (statsmodels'
    # NormalIndPower/Cohen's h reference value, cross-checked against
    # standard online A/B calculators using the same arcsine formula).
    assert 1000 <= result["n_per_group"] <= 1200
    assert result["total_n"] == result["n_per_group"] * 2


def test_sample_size_two_proportions_smaller_effect_needs_more_n():
    small_effect = sample_size_two_proportions(baseline_rate=0.20, mde=0.02)
    large_effect = sample_size_two_proportions(baseline_rate=0.20, mde=0.10)
    assert small_effect["n_per_group"] > large_effect["n_per_group"]


def test_sample_size_two_proportions_higher_power_needs_more_n():
    low_power = sample_size_two_proportions(baseline_rate=0.20, mde=0.05, power=0.8)
    high_power = sample_size_two_proportions(baseline_rate=0.20, mde=0.05, power=0.95)
    assert high_power["n_per_group"] > low_power["n_per_group"]


def test_sample_size_two_proportions_rejects_invalid_rate():
    for bad_rate in (0.0, 1.0, -0.1, 1.2):
        result = sample_size_two_proportions(baseline_rate=bad_rate, mde=0.05)
        assert result.get("error")


def test_sample_size_two_proportions_rejects_out_of_range_variant():
    # baseline 0.98 + mde 0.05 -> variant rate 1.03, impossible
    result = sample_size_two_proportions(baseline_rate=0.98, mde=0.05)
    assert result.get("error")


def test_sample_size_two_proportions_rejects_zero_mde():
    result = sample_size_two_proportions(baseline_rate=0.2, mde=0.0)
    assert result.get("error")


def test_sample_size_two_proportions_unequal_ratio():
    result = sample_size_two_proportions(baseline_rate=0.2, mde=0.05, ratio=2.0)
    assert result.get("error") is None
    assert result["n_group_b"] == round(result["n_group_a"] * 2.0)


# --- sample_size_two_means --------------------------------------------------

def test_sample_size_two_means_matches_known_medium_effect():
    # Cohen's d=0.5 (medium), alpha=.05, power=.8, two-sided is a textbook
    # reference value: ~64 per group.
    result = sample_size_two_means(mean_diff=5.0, std_dev=10.0)  # d = 0.5
    assert result.get("error") is None
    assert result["cohens_d"] == 0.5
    assert 60 <= result["n_per_group"] <= 68


def test_sample_size_two_means_larger_diff_needs_less_n():
    small = sample_size_two_means(mean_diff=1.0, std_dev=10.0)
    large = sample_size_two_means(mean_diff=8.0, std_dev=10.0)
    assert small["n_per_group"] > large["n_per_group"]


def test_sample_size_two_means_rejects_zero_std_dev():
    result = sample_size_two_means(mean_diff=5.0, std_dev=0.0)
    assert result.get("error")


def test_sample_size_two_means_rejects_zero_mean_diff():
    result = sample_size_two_means(mean_diff=0.0, std_dev=10.0)
    assert result.get("error")


# --- achieved_power_ttest ----------------------------------------------------

def test_achieved_power_ttest_matches_known_reference():
    # d=0.5, n=64 per group, alpha=.05 two-sided -> power ~0.8
    power = achieved_power_ttest(cohens_d=0.5, n1=64, n2=64)
    assert 0.75 <= power <= 0.85


def test_achieved_power_ttest_increases_with_sample_size():
    small_n = achieved_power_ttest(cohens_d=0.3, n1=20, n2=20)
    large_n = achieved_power_ttest(cohens_d=0.3, n1=500, n2=500)
    assert large_n > small_n


def test_achieved_power_ttest_zero_effect_equals_alpha():
    # With no true effect, power to (falsely) reject is just the alpha level.
    power = achieved_power_ttest(cohens_d=0.0, n1=100, n2=100, alpha=0.05)
    assert 0.03 <= power <= 0.07


# --- power_check_ttest -------------------------------------------------------

def test_power_check_flags_underpowered_result():
    check = power_check_ttest(cohens_d=0.3, n1=15, n2=15)
    assert check["underpowered"] is True
    assert check["achieved_power"] < 0.8
    assert check["recommended_n_per_group"] > 15


def test_power_check_flags_well_powered_result():
    check = power_check_ttest(cohens_d=0.5, n1=500, n2=500)
    assert check["underpowered"] is False
    assert check["achieved_power"] > 0.95


def test_power_check_handles_zero_effect_size_without_raising():
    check = power_check_ttest(cohens_d=0.0, n1=50, n2=50)
    assert check.get("error") is None
    assert check["underpowered"] is True
    # No true effect -> no finite sample size reaches 80% power; the
    # calculator should say so rather than return a bogus number.
    assert check["recommended_n_per_group"] is None


def test_power_check_respects_custom_target_power():
    check = power_check_ttest(cohens_d=0.5, n1=30, n2=30, target_power=0.5)
    loose = check["underpowered"]
    stricter = power_check_ttest(cohens_d=0.5, n1=30, n2=30, target_power=0.99)["underpowered"]
    # A stricter target is at least as likely to flag underpowered as a loose one.
    assert stricter or not loose or stricter == loose


# --- interpret_power_check ---------------------------------------------------

def test_interpret_power_check_text_underpowered():
    check = power_check_ttest(cohens_d=0.3, n1=15, n2=15)
    text = interpret_power_check(check)
    assert "underpowered" in text.lower()
    assert "%" in text


def test_interpret_power_check_text_well_powered():
    check = power_check_ttest(cohens_d=0.5, n1=500, n2=500)
    text = interpret_power_check(check)
    assert "well-powered" in text.lower()


def test_interpret_power_check_handles_none_recommendation():
    check = power_check_ttest(cohens_d=0.0, n1=50, n2=50)
    text = interpret_power_check(check)
    assert text  # doesn't raise, returns something sensible


# --- interpret_sample_size_* --------------------------------------------------

def test_interpret_sample_size_proportions_text():
    result = sample_size_two_proportions(baseline_rate=0.20, mde=0.05)
    text = interpret_sample_size_proportions(result)
    assert "per group" in text
    assert str(result["n_per_group"]) in text.replace(",", "")


def test_interpret_sample_size_proportions_error_passthrough():
    result = sample_size_two_proportions(baseline_rate=1.5, mde=0.05)
    assert interpret_sample_size_proportions(result) == result["error"]


def test_interpret_sample_size_means_text():
    result = sample_size_two_means(mean_diff=5.0, std_dev=10.0)
    text = interpret_sample_size_means(result)
    assert "per group" in text
    assert str(result["n_per_group"]) in text.replace(",", "")


def test_interpret_sample_size_means_error_passthrough():
    result = sample_size_two_means(mean_diff=5.0, std_dev=0.0)
    assert interpret_sample_size_means(result) == result["error"]


# --- cohens_w_from_chi2 / achieved_power_chi2 / power_check_chi2 -----------
# Reference values are Cohen's (1988) canonical chi-square power tables,
# reproduced by G*Power and R's pwr.chisq.test: w=0.3 (medium effect),
# df=1, alpha=.05 needs n~87 for 80% power.

def test_cohens_w_from_chi2_matches_definition():
    # w = sqrt(chi2 / n) by definition; chi2=7.83, n=87 -> w ~ 0.3
    w = cohens_w_from_chi2(chi2_statistic=7.83, n=87)
    assert 0.29 <= w <= 0.31


def test_cohens_w_from_chi2_handles_zero_n():
    assert cohens_w_from_chi2(chi2_statistic=10.0, n=0) == 0.0


def test_achieved_power_chi2_matches_known_reference():
    power = achieved_power_chi2(cohens_w=0.3, n=87, dof=1)
    assert 0.75 <= power <= 0.85


def test_achieved_power_chi2_increases_with_sample_size():
    small_n = achieved_power_chi2(cohens_w=0.2, n=30, dof=1)
    large_n = achieved_power_chi2(cohens_w=0.2, n=500, dof=1)
    assert large_n > small_n


def test_achieved_power_chi2_handles_degenerate_inputs_without_raising():
    assert achieved_power_chi2(cohens_w=0.3, n=1, dof=1) == 0.0
    assert achieved_power_chi2(cohens_w=0.3, n=100, dof=0) == 0.0


def test_power_check_chi2_flags_underpowered_result():
    check = power_check_chi2(cohens_w=0.2, n=30, dof=1)
    assert check["underpowered"] is True
    assert check["achieved_power"] < 0.8
    assert check["recommended_n"] > 30
    assert check["test"] == "chi2"


def test_power_check_chi2_flags_well_powered_result():
    check = power_check_chi2(cohens_w=0.3, n=500, dof=1)
    assert check["underpowered"] is False
    assert check["achieved_power"] > 0.95


def test_power_check_chi2_handles_zero_effect_size_without_raising():
    check = power_check_chi2(cohens_w=0.0, n=50, dof=2)
    assert check.get("error") is None
    assert check["underpowered"] is True
    assert check["recommended_n"] is None


def test_interpret_power_check_dispatches_to_chi2_text():
    check = power_check_chi2(cohens_w=0.2, n=30, dof=1)
    text = interpret_power_check(check)
    assert "underpowered" in text.lower()
    assert "%" in text
    assert "chi-square" in text.lower()


# --- cohens_f_from_eta_sq / achieved_power_anova / power_check_anova -------
# Reference values are Cohen's (1988) canonical ANOVA power tables: f=0.25
# (medium effect), k=3 groups, alpha=.05 needs total n~159 (~53/group) for
# 80% power.

def test_cohens_f_from_eta_sq_matches_definition():
    # f = sqrt(eta_sq / (1 - eta_sq)); eta_sq=0.0588 -> f ~ 0.25 (medium)
    f = cohens_f_from_eta_sq(0.0588)
    assert 0.24 <= f <= 0.26


def test_cohens_f_from_eta_sq_guards_perfect_fit():
    # eta_sq -> 1 would divide by zero; must return a large-but-finite f.
    f = cohens_f_from_eta_sq(1.0)
    assert f > 0 and f < float("inf")


def test_achieved_power_anova_matches_known_reference():
    power = achieved_power_anova(cohens_f=0.25, k_groups=3, nobs_total=159)
    assert 0.75 <= power <= 0.85


def test_achieved_power_anova_increases_with_sample_size():
    small_n = achieved_power_anova(cohens_f=0.2, k_groups=3, nobs_total=60)
    large_n = achieved_power_anova(cohens_f=0.2, k_groups=3, nobs_total=600)
    assert large_n > small_n


def test_achieved_power_anova_handles_degenerate_inputs_without_raising():
    assert achieved_power_anova(cohens_f=0.25, k_groups=1, nobs_total=100) == 0.0
    assert achieved_power_anova(cohens_f=0.25, k_groups=3, nobs_total=2) == 0.0


def test_power_check_anova_flags_underpowered_result():
    check = power_check_anova(eta_sq=0.02, k_groups=3, nobs_total=60)
    assert check["underpowered"] is True
    assert check["achieved_power"] < 0.8
    assert check["recommended_n_total"] > 60
    assert check["recommended_n_per_group"] == -(-check["recommended_n_total"] // 3)
    assert check["test"] == "anova"


def test_power_check_anova_flags_well_powered_result():
    check = power_check_anova(eta_sq=0.15, k_groups=3, nobs_total=300)
    assert check["underpowered"] is False
    assert check["achieved_power"] > 0.95


def test_power_check_anova_handles_zero_effect_size_without_raising():
    check = power_check_anova(eta_sq=0.0, k_groups=3, nobs_total=60)
    assert check.get("error") is None
    assert check["underpowered"] is True
    assert check["recommended_n_total"] is None
    assert check["recommended_n_per_group"] is None


def test_interpret_power_check_dispatches_to_anova_text():
    check = power_check_anova(eta_sq=0.02, k_groups=3, nobs_total=60)
    text = interpret_power_check(check)
    assert "underpowered" in text.lower()
    assert "%" in text
    assert "anova" in text.lower()


def test_interpret_power_check_still_handles_ttest_dict_without_test_key():
    # Older/other callers may build a ttest-shaped dict without an explicit
    # "test" key (power_check_ttest's original contract) — must still be
    # interpreted as a t-test, not raise a KeyError.
    check = power_check_ttest(cohens_d=0.3, n1=15, n2=15)
    check.pop("test", None)
    text = interpret_power_check(check)
    assert "underpowered" in text.lower()


# --- fisher_z / achieved_power_correlation / power_check_correlation -------
# Reference values are Cohen's (1988) canonical correlation power tables,
# reproduced by G*Power's "Correlation: bivariate normal model" and R's
# pwr.r.test: r=0.3 (medium effect), alpha=.05, power=.8 needs n~84-85 —
# n=((z_alpha/2 + z_beta)/atanh(0.3))^2 + 3 ~= 84.92, textbook tables round
# this up to 85.

def test_fisher_z_matches_definition():
    # z = arctanh(r) = 0.5*ln((1+r)/(1-r))
    assert abs(fisher_z(0.3) - 0.30952) < 1e-4
    assert fisher_z(0.0) == 0.0


def test_fisher_z_handles_perfect_correlation_without_raising():
    # r=+-1 would blow up arctanh to +-infinity; must clamp to a large-but-
    # finite value instead.
    z = fisher_z(1.0)
    assert z > 0 and z < float("inf")
    z_neg = fisher_z(-1.0)
    assert z_neg < 0 and z_neg > float("-inf")


def test_achieved_power_correlation_matches_known_reference():
    power = achieved_power_correlation(r=0.3, n=85)
    assert 0.75 <= power <= 0.85


def test_achieved_power_correlation_increases_with_sample_size():
    small_n = achieved_power_correlation(r=0.2, n=30)
    large_n = achieved_power_correlation(r=0.2, n=500)
    assert large_n > small_n


def test_achieved_power_correlation_zero_effect_equals_alpha():
    # No true correlation -> power to (falsely) reject is just alpha.
    power = achieved_power_correlation(r=0.0, n=100, alpha=0.05)
    assert 0.03 <= power <= 0.07


def test_achieved_power_correlation_is_symmetric_in_sign():
    assert achieved_power_correlation(r=0.4, n=50) == achieved_power_correlation(r=-0.4, n=50)


def test_achieved_power_correlation_handles_degenerate_inputs_without_raising():
    assert achieved_power_correlation(r=0.3, n=0) == 0.0
    assert achieved_power_correlation(r=0.3, n=3) == 0.0  # n-3 must be > 0
    assert achieved_power_correlation(r=1.0, n=100) == 1.0


def test_power_check_correlation_flags_underpowered_result():
    check = power_check_correlation(r=0.2, n=30)
    assert check["underpowered"] is True
    assert check["achieved_power"] < 0.8
    assert check["recommended_n"] > 30
    assert check["test"] == "pearson"


def test_power_check_correlation_flags_well_powered_result():
    check = power_check_correlation(r=0.5, n=200)
    assert check["underpowered"] is False
    assert check["achieved_power"] > 0.95


def test_power_check_correlation_handles_zero_effect_size_without_raising():
    check = power_check_correlation(r=0.0, n=50)
    assert check.get("error") is None
    assert check["underpowered"] is True
    assert check["recommended_n"] is None


def test_power_check_correlation_recommended_n_actually_reaches_target():
    # The recommended n, plugged back in, should really clear target_power
    # (not just the closed-form approximation before rounding).
    check = power_check_correlation(r=0.15, n=40, target_power=0.8)
    assert check["recommended_n"] is not None
    achieved_at_recommended = achieved_power_correlation(r=0.15, n=check["recommended_n"])
    assert achieved_at_recommended >= 0.8


def test_interpret_power_check_dispatches_to_pearson_text():
    check = power_check_correlation(r=0.15, n=30)
    text = interpret_power_check(check)
    assert "underpowered" in text.lower()
    assert "%" in text
    assert "correlation" in text.lower()


def test_interpret_power_check_dispatches_to_pearson_well_powered_text():
    check = power_check_correlation(r=0.5, n=200)
    text = interpret_power_check(check)
    assert "well-powered" in text.lower()


# --- sample_size_correlation / interpret_sample_size_correlation -----------

def test_sample_size_correlation_matches_known_medium_effect():
    result = sample_size_correlation(r=0.3)
    assert result.get("error") is None
    assert 80 <= result["n"] <= 90


def test_sample_size_correlation_smaller_effect_needs_more_n():
    small_effect = sample_size_correlation(r=0.1)
    large_effect = sample_size_correlation(r=0.5)
    assert small_effect["n"] > large_effect["n"]


def test_sample_size_correlation_higher_power_needs_more_n():
    low_power = sample_size_correlation(r=0.3, power=0.8)
    high_power = sample_size_correlation(r=0.3, power=0.95)
    assert high_power["n"] > low_power["n"]


def test_sample_size_correlation_sign_does_not_matter():
    assert sample_size_correlation(r=0.3)["n"] == sample_size_correlation(r=-0.3)["n"]


def test_sample_size_correlation_rejects_zero_r():
    result = sample_size_correlation(r=0.0)
    assert result.get("error")


def test_sample_size_correlation_rejects_out_of_range_r():
    for bad_r in (1.0, -1.0, 1.5, -2.0):
        result = sample_size_correlation(r=bad_r)
        assert result.get("error")


def test_interpret_sample_size_correlation_text():
    result = sample_size_correlation(r=0.3)
    text = interpret_sample_size_correlation(result)
    assert "paired observations" in text
    assert str(result["n"]) in text.replace(",", "")


def test_interpret_sample_size_correlation_error_passthrough():
    result = sample_size_correlation(r=0.0)
    assert interpret_sample_size_correlation(result) == result["error"]
