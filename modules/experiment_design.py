"""
Experiment Design — A/B test sample-size/power calculator, and post-hoc
power checks for a hypothesis test result already on hand.

Two audiences, one set of formulas:

1. **Before an experiment runs**: "how many users do I need per variant to
   reliably detect a lift this size?" — `sample_size_two_proportions()` for
   conversion-rate tests, `sample_size_two_means()` for continuous-metric
   tests (revenue, time-on-page, etc.).
2. **After a test already exists in the data** (e.g. a Hypothesis Sweep
   result, or historical A/B data someone hands you): "was this test even
   capable of detecting an effect this size, given how few rows it had?" —
   `power_check_ttest()`. This is the check most take-home data-analyst
   assignments skip and most interviewers ask about directly: a
   non-significant result from an underpowered test proves nothing, and a
   significant result from a tiny sample is exactly the kind of thing that
   fails to replicate.

Built on statsmodels' `NormalIndPower` (two-proportion z-test, via Cohen's h)
and `TTestIndPower` (two-sample t-test, via Cohen's d) rather than
hand-rolled formulas — these are the same primitives R's `pwr` package and
most commercial A/B calculators use, so results should match what a
stakeholder gets from Optimizely/Evan Miller's calculator to within
rounding. Every public function returns a plain dict (`{"error": "..."}`
on invalid input) rather than raising, matching `stats_lab`'s contract, so
a Streamlit caller never needs a try/except around these.

Post-hoc power also covers the two other test families `hypothesis_sweep`
runs, not just t-tests:

- **Chi-square** (`achieved_power_chi2`/`power_check_chi2`), via
  statsmodels' `GofChisquarePower`. The standardized effect size Cohen's w
  is derived directly from the test's own raw statistic and n
  (`cohens_w_from_chi2`, w = sqrt(chi2/n)) rather than back-computed from
  Cramer's V — V's relationship to w depends on the contingency table's
  row/column *shape* (min(rows, cols) - 1), and more than one table shape
  can share the same degrees of freedom, so going through V would need the
  shape threaded through separately anyway. Going through the raw
  statistic needs nothing beyond what `stats_lab.run_chi2()` already
  returns (the statistic, n, and dof), and is the same identity R's `pwr`
  package documentation uses to relate the two effect sizes.
- **ANOVA** (`achieved_power_anova`/`power_check_anova`), via statsmodels'
  `FTestAnovaPower`, using Cohen's f derived from eta-squared
  (`cohens_f_from_eta_sq`) and the actual group count/total n from the
  test's own group sizes — not approximated from eta-squared alone, per
  the same reasoning. This assumes a roughly balanced design (equal-ish
  group sizes), the standard assumption `FTestAnovaPower` itself makes; a
  wildly unbalanced ANOVA's achieved power is an approximation, same
  caveat every commercial ANOVA power calculator carries.

- **Correlation (Pearson)** (`achieved_power_correlation`/
  `power_check_correlation`), via the exact Fisher z-transform method —
  the same technique R's `pwr.r.test` and G*Power's "Correlation:
  bivariate normal model" use, and a genuinely different noncentral
  distribution family than the chi-square family the other three share
  (Fisher's z of the sample r is approximately Normal under the null,
  not noncentral chi-square). `fisher_z(r) = arctanh(r)`; achieved power
  is evaluated from the noncentrality that r's Fisher z implies at a
  given n, no effect-size back-conversion ambiguity to resolve (unlike
  chi-square/ANOVA, r *is* the standardized effect size already). Also
  gets a planning-side `sample_size_correlation()`, matching
  `sample_size_two_proportions()`/`sample_size_two_means()`'s "before an
  experiment" role for the other two.
"""

from __future__ import annotations

import math
from typing import Optional

from scipy import stats as scipy_stats
from statsmodels.stats.power import NormalIndPower, TTestIndPower
from statsmodels.stats.proportion import proportion_effectsize

DEFAULT_ALPHA = 0.05
DEFAULT_POWER = 0.8

# Above this, solve_power's root-finder for "what n reaches this power" can
# run away toward infinity (e.g. a near-zero effect size) rather than
# converging — cap the search so a bad input fails fast with a clear
# "no finite sample size" answer instead of hanging or returning nonsense.
_MAX_SOLVABLE_N = 1_000_000


def _round_up(n: float) -> int:
    # statsmodels' solve_power() sometimes returns a size-1 numpy array
    # rather than a plain float (depends on which root-finder path it took
    # internally) — .item() unwraps that to a Python scalar regardless of
    # ndim, without numpy's "implicit array-to-scalar conversion"
    # deprecation warning that a bare float(n) can trigger for ndim > 0.
    if hasattr(n, "item"):
        n = n.item()
    return int(math.ceil(float(n)))


def sample_size_two_proportions(
    baseline_rate: float,
    mde: float,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    ratio: float = 1.0,
    alternative: str = "two-sided",
) -> dict:
    """Required sample size per group for a two-proportion z-test (the
    standard "conversion rate A vs B" experiment).

    `mde` is the minimum detectable effect as an absolute rate difference
    (e.g. baseline_rate=0.20, mde=0.05 means "can we detect a move from 20%
    to 25%?"). `ratio` is group_b_n / group_a_n (1.0 = equal split).

    Returns {baseline_rate, variant_rate, mde, effect_size (Cohen's h),
    alpha, power, ratio, n_group_a, n_group_b, n_per_group, total_n} or
    {"error": "..."} on invalid input.
    """
    if not (0.0 < baseline_rate < 1.0):
        return {"error": "Baseline rate must be strictly between 0 and 1."}
    if mde == 0:
        return {"error": "Minimum detectable effect (mde) must be non-zero."}
    variant_rate = baseline_rate + mde
    if not (0.0 < variant_rate < 1.0):
        return {
            "error": (
                f"Baseline rate ({baseline_rate:.0%}) + mde ({mde:+.0%}) = "
                f"{variant_rate:.0%}, which isn't a valid probability."
            )
        }
    if ratio <= 0:
        return {"error": "ratio must be positive."}

    effect_size = proportion_effectsize(baseline_rate, variant_rate)
    try:
        n1 = NormalIndPower().solve_power(
            effect_size=abs(effect_size), alpha=alpha, power=power, ratio=ratio,
            alternative=alternative,
        )
    except Exception as exc:  # statsmodels raises on degenerate inputs
        return {"error": f"Could not solve for sample size: {exc}"}

    n_group_a = _round_up(n1)
    n_group_b = _round_up(n1 * ratio)
    return {
        "baseline_rate": baseline_rate,
        "variant_rate": variant_rate,
        "mde": mde,
        "effect_size": float(effect_size),
        "effect_size_name": "Cohen's h",
        "alpha": alpha,
        "power": power,
        "ratio": ratio,
        "n_group_a": n_group_a,
        "n_group_b": n_group_b,
        "n_per_group": n_group_a,  # convenience alias for the common ratio=1 case
        "total_n": n_group_a + n_group_b,
    }


def sample_size_two_means(
    mean_diff: float,
    std_dev: float,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
    ratio: float = 1.0,
    alternative: str = "two-sided",
) -> dict:
    """Required sample size per group for a two-sample (Welch/independent)
    t-test on a continuous metric — e.g. "can we detect a $5 lift in average
    order value, given a standard deviation of $10?".

    Returns {mean_diff, std_dev, cohens_d, alpha, power, ratio, n_group_a,
    n_group_b, n_per_group, total_n} or {"error": "..."}.
    """
    if std_dev <= 0:
        return {"error": "std_dev must be positive."}
    if mean_diff == 0:
        return {"error": "mean_diff must be non-zero."}
    if ratio <= 0:
        return {"error": "ratio must be positive."}

    cohens_d = mean_diff / std_dev
    try:
        n1 = TTestIndPower().solve_power(
            effect_size=abs(cohens_d), alpha=alpha, power=power, ratio=ratio,
            alternative=alternative,
        )
    except Exception as exc:
        return {"error": f"Could not solve for sample size: {exc}"}

    n_group_a = _round_up(n1)
    n_group_b = _round_up(n1 * ratio)
    return {
        "mean_diff": mean_diff,
        "std_dev": std_dev,
        "cohens_d": round(float(cohens_d), 6),
        "alpha": alpha,
        "power": power,
        "ratio": ratio,
        "n_group_a": n_group_a,
        "n_group_b": n_group_b,
        "n_per_group": n_group_a,
        "total_n": n_group_a + n_group_b,
    }


def achieved_power_ttest(cohens_d: float, n1: int, n2: int, alpha: float = DEFAULT_ALPHA) -> float:
    """Post-hoc (observed) power of a two-sample t-test that already ran,
    given the effect size it found and the group sizes it had. Answers
    "given the sample sizes we actually had, what were our odds of detecting
    an effect this size at all?" — distinct from p-value, which only says
    whether *this* result was significant.
    """
    if n1 < 2 or n2 < 2:
        return 0.0
    ratio = n2 / n1
    power = TTestIndPower().power(
        effect_size=abs(cohens_d), nobs1=n1, ratio=ratio, alpha=alpha, alternative="two-sided"
    )
    return float(min(max(power, 0.0), 1.0))


def power_check_ttest(
    cohens_d: float,
    n1: int,
    n2: int,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_POWER,
) -> dict:
    """Full post-hoc power verdict for a t-test result: achieved power, a
    pass/fail flag against `target_power`, and — if underpowered — the
    sample size per group that *would* reach `target_power` for this same
    effect size (so a follow-up study has a concrete number to design
    around, not just a warning).

    Returns {achieved_power, target_power, alpha, underpowered,
    recommended_n_per_group, recommended_total_n}. When the effect size is
    (near) zero, no finite sample size reaches target_power —
    `recommended_n_per_group` is `None` in that case rather than a
    misleadingly huge or infinite number.
    """
    achieved = achieved_power_ttest(cohens_d, n1, n2, alpha=alpha)
    underpowered = achieved < target_power

    recommended_n_per_group: Optional[int] = None
    if abs(cohens_d) > 1e-9:
        try:
            n_needed = TTestIndPower().solve_power(
                effect_size=abs(cohens_d), alpha=alpha, power=target_power, ratio=1.0,
                alternative="two-sided",
            )
            if n_needed and n_needed <= _MAX_SOLVABLE_N:
                recommended_n_per_group = _round_up(n_needed)
        except Exception:
            recommended_n_per_group = None

    return {
        "test": "ttest",
        "achieved_power": achieved,
        "target_power": target_power,
        "alpha": alpha,
        "n1": n1,
        "n2": n2,
        "cohens_d": cohens_d,
        "underpowered": underpowered,
        "recommended_n_per_group": recommended_n_per_group,
        "recommended_total_n": (
            recommended_n_per_group * 2 if recommended_n_per_group is not None else None
        ),
    }


def cohens_w_from_chi2(chi2_statistic: float, n: int) -> float:
    """Cohen's w computed directly from a chi-square test's own raw
    statistic and sample size (w = sqrt(chi2 / n)) — the standardized
    effect size `achieved_power_chi2`/`power_check_chi2` expect.

    Deliberately not derived from Cramer's V: V's conversion back to w
    needs the contingency table's row/column *shape* (min(rows, cols) -
    1), which isn't recoverable from V and the test's degrees of freedom
    alone — the same dof can come from more than one table shape (e.g.
    dof=4 from a 3x3 table or a 2x5 table have different min-dim). Going
    through the raw statistic sidesteps that ambiguity entirely.
    """
    if n <= 0:
        return 0.0
    return math.sqrt(max(chi2_statistic, 0.0) / n)


def achieved_power_chi2(cohens_w: float, n: int, dof: int, alpha: float = DEFAULT_ALPHA) -> float:
    """Post-hoc power of a chi-square test of independence that already
    ran, given its standardized effect size (Cohen's w — see
    `cohens_w_from_chi2`), sample size, and degrees of freedom.
    """
    if n < 2 or dof < 1:
        return 0.0
    from statsmodels.stats.power import GofChisquarePower

    try:
        power = GofChisquarePower().power(
            effect_size=abs(cohens_w), nobs=n, alpha=alpha, n_bins=dof + 1
        )
    except Exception:
        return 0.0
    return float(min(max(power, 0.0), 1.0))


def power_check_chi2(
    cohens_w: float,
    n: int,
    dof: int,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_POWER,
) -> dict:
    """Full post-hoc power verdict for a chi-square test result, same
    contract as `power_check_ttest` (achieved power, pass/fail against
    `target_power`, and a follow-up sample size when underpowered) — but
    keyed on total row count `n` rather than per-group sizes, since a
    contingency table doesn't have two independent group sizes the way a
    t-test does.
    """
    achieved = achieved_power_chi2(cohens_w, n, dof, alpha=alpha)
    underpowered = achieved < target_power

    recommended_n: Optional[int] = None
    if abs(cohens_w) > 1e-9 and dof >= 1:
        try:
            from statsmodels.stats.power import GofChisquarePower

            n_needed = GofChisquarePower().solve_power(
                effect_size=abs(cohens_w), alpha=alpha, power=target_power, n_bins=dof + 1
            )
            if n_needed and n_needed <= _MAX_SOLVABLE_N:
                recommended_n = _round_up(n_needed)
        except Exception:
            recommended_n = None

    return {
        "test": "chi2",
        "achieved_power": achieved,
        "target_power": target_power,
        "alpha": alpha,
        "n": n,
        "dof": dof,
        "cohens_w": cohens_w,
        "underpowered": underpowered,
        "recommended_n": recommended_n,
    }


def cohens_f_from_eta_sq(eta_sq: float) -> float:
    """Cohen's f (the effect size `FTestAnovaPower` expects) from
    eta-squared: f = sqrt(eta_sq / (1 - eta_sq)). Clamped just under 1.0
    so a (near-)perfect fit doesn't divide by zero and return infinity.
    """
    eta_sq = min(max(eta_sq, 0.0), 0.999999)
    return math.sqrt(eta_sq / (1 - eta_sq))


def achieved_power_anova(
    cohens_f: float, k_groups: int, nobs_total: int, alpha: float = DEFAULT_ALPHA
) -> float:
    """Post-hoc power of a one-way ANOVA that already ran, given its
    standardized effect size (Cohen's f — see `cohens_f_from_eta_sq`),
    group count, and total sample size across all groups. Assumes a
    roughly balanced design, the same assumption `FTestAnovaPower` itself
    makes.
    """
    if k_groups < 2 or nobs_total < k_groups * 2:
        return 0.0
    from statsmodels.stats.power import FTestAnovaPower

    try:
        power = FTestAnovaPower().power(
            effect_size=abs(cohens_f), nobs=nobs_total, alpha=alpha, k_groups=k_groups
        )
    except Exception:
        return 0.0
    return float(min(max(power, 0.0), 1.0))


def power_check_anova(
    eta_sq: float,
    k_groups: int,
    nobs_total: int,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_POWER,
) -> dict:
    """Full post-hoc power verdict for a one-way ANOVA result, same
    contract as `power_check_ttest`/`power_check_chi2` but keyed on group
    count and total n (a follow-up study's recommended size is reported
    both as a total and divided evenly per group).
    """
    cohens_f = cohens_f_from_eta_sq(eta_sq)
    achieved = achieved_power_anova(cohens_f, k_groups, nobs_total, alpha=alpha)
    underpowered = achieved < target_power

    recommended_n_total: Optional[int] = None
    if cohens_f > 1e-9 and k_groups >= 2:
        try:
            from statsmodels.stats.power import FTestAnovaPower

            n_needed = FTestAnovaPower().solve_power(
                effect_size=cohens_f, alpha=alpha, power=target_power, k_groups=k_groups
            )
            if n_needed and n_needed <= _MAX_SOLVABLE_N:
                recommended_n_total = _round_up(n_needed)
        except Exception:
            recommended_n_total = None

    return {
        "test": "anova",
        "achieved_power": achieved,
        "target_power": target_power,
        "alpha": alpha,
        "k_groups": k_groups,
        "nobs_total": nobs_total,
        "eta_sq": eta_sq,
        "cohens_f": cohens_f,
        "underpowered": underpowered,
        "recommended_n_total": recommended_n_total,
        "recommended_n_per_group": (
            _round_up(recommended_n_total / k_groups) if recommended_n_total is not None else None
        ),
    }


def fisher_z(r: float) -> float:
    """Fisher z-transform of a Pearson correlation: z = arctanh(r) =
    0.5*ln((1+r)/(1-r)). Clamped to r in [-0.999999, 0.999999] first so a
    (near-)perfect +-1 correlation doesn't blow up to +-infinity.
    """
    r = min(max(r, -0.999999), 0.999999)
    return math.atanh(r)


def achieved_power_correlation(r: float, n: int, alpha: float = DEFAULT_ALPHA) -> float:
    """Post-hoc power of a Pearson correlation significance test that
    already ran, given the observed r and sample size n, via the exact
    Fisher z-transform method (same technique R's `pwr.r.test` and
    G*Power's "Correlation: bivariate normal model" use, and Cohen's
    (1988) canonical correlation power tables).

    Under H0 (rho=0), Fisher's z of the sample r is approximately
    Normal(0, 1/sqrt(n-3)) — a variance that doesn't depend on the true
    correlation, unlike r itself. Achieved power is the probability that
    |z| clears the two-sided critical value, evaluated at the
    noncentrality the *observed* r implies for this n:
    power = 1 - Phi(z_crit - ncp) + Phi(-z_crit - ncp), where
    ncp = fisher_z(r) * sqrt(n - 3) and z_crit = Phi^-1(1 - alpha/2).

    Needs at least 4 paired observations (n-3 > 0 for the standard error
    to be defined) — returns 0.0 below that, same "no reliable power
    estimate from too little data" convention as achieved_power_ttest/
    chi2/anova.
    """
    if n < 4:
        return 0.0
    z_r = fisher_z(r)
    se = 1.0 / math.sqrt(n - 3)
    ncp = z_r / se
    z_crit = scipy_stats.norm.ppf(1 - alpha / 2)
    power = (
        1 - scipy_stats.norm.cdf(z_crit - ncp) + scipy_stats.norm.cdf(-z_crit - ncp)
    )
    return float(min(max(power, 0.0), 1.0))


def _n_needed_for_correlation_power(
    r: float, alpha: float, target_power: float
) -> Optional[int]:
    """Sample size needed for a Pearson correlation of magnitude r to reach
    `target_power`, starting from the standard closed-form Fisher-z
    approximation (Cohen 1988; the same formula R's `pwr.r.test` uses):
    n ~= ((z_alpha/2 + z_beta) / fisher_z(r))^2 + 3 — then nudged upward
    (never down) until plugging the rounded n back into
    `achieved_power_correlation` actually clears `target_power`, since the
    closed form drops the exact formula's small second (opposite-tail)
    term. Returns None when no finite n reaches the target (r too close to
    zero, or the closed-form estimate exceeds `_MAX_SOLVABLE_N`).
    """
    z_r = fisher_z(r)
    if abs(z_r) < 1e-9:
        return None
    z_alpha = scipy_stats.norm.ppf(1 - alpha / 2)
    z_beta = scipy_stats.norm.ppf(target_power)
    n_est = ((z_alpha + z_beta) / abs(z_r)) ** 2 + 3
    if not math.isfinite(n_est) or n_est > _MAX_SOLVABLE_N:
        return None

    n = max(4, _round_up(n_est))
    guard = 0
    while (
        achieved_power_correlation(r, n, alpha=alpha) < target_power
        and n < _MAX_SOLVABLE_N
        and guard < 50
    ):
        n += 1
        guard += 1
    return n


def power_check_correlation(
    r: float,
    n: int,
    alpha: float = DEFAULT_ALPHA,
    target_power: float = DEFAULT_POWER,
) -> dict:
    """Full post-hoc power verdict for a Pearson correlation result, same
    contract as `power_check_ttest`/`power_check_chi2`/`power_check_anova`
    (achieved power, pass/fail against `target_power`, and a follow-up
    sample size when underpowered) — keyed on total paired-observation
    count `n`, since correlation has no per-group sizes.

    Returns {test: "pearson", achieved_power, target_power, alpha, n, r,
    underpowered, recommended_n}. When r is (near) zero, no finite sample
    size reaches target_power — `recommended_n` is `None` in that case
    rather than a misleadingly huge or infinite number.
    """
    achieved = achieved_power_correlation(r, n, alpha=alpha)
    underpowered = achieved < target_power

    recommended_n: Optional[int] = None
    if abs(fisher_z(r)) > 1e-9:
        recommended_n = _n_needed_for_correlation_power(r, alpha, target_power)

    return {
        "test": "pearson",
        "achieved_power": achieved,
        "target_power": target_power,
        "alpha": alpha,
        "n": n,
        "r": r,
        "underpowered": underpowered,
        "recommended_n": recommended_n,
    }


def sample_size_correlation(
    r: float,
    alpha: float = DEFAULT_ALPHA,
    power: float = DEFAULT_POWER,
) -> dict:
    """Required sample size to reliably detect a Pearson correlation of
    magnitude `r` — the "before an experiment" counterpart to
    `power_check_correlation`, e.g. "how many paired observations do I
    need to reliably detect a correlation this strong?".

    Returns {r, alpha, power, n} or {"error": "..."} on invalid input.
    `r` must be strictly between -1 and 1 and non-zero: a zero correlation
    has no finite required sample size, and +-1 needs no sample at all
    (not a meaningful planning question).
    """
    if not (-1.0 < r < 1.0):
        return {"error": "r must be strictly between -1 and 1."}
    if r == 0:
        return {
            "error": "r must be non-zero — a zero correlation has no finite required sample size."
        }

    n = _n_needed_for_correlation_power(r, alpha, power)
    if n is None:
        return {"error": "Could not solve for a finite sample size for this r."}

    return {"r": r, "alpha": alpha, "power": power, "n": n}


def _interpret_power_check_ttest(check: dict) -> str:
    pct = f"{check['achieved_power']:.0%}"
    n1, n2 = check["n1"], check["n2"]
    n_desc = f"{n1} vs {n2}" if n1 != n2 else str(n1)

    if not check["underpowered"]:
        return (
            f"✅ Well-powered: with {n_desc} samples per group, this test had "
            f"{pct} power to detect an effect this size (target: "
            f"{check['target_power']:.0%})."
        )

    if check["recommended_n_per_group"] is None:
        return (
            f"⚠️ Underpowered: with {n_desc} samples per group, this test had only "
            f"{pct} power to detect an effect this size — the effect size is too "
            "close to zero for any finite sample size to reliably detect."
        )

    return (
        f"⚠️ Underpowered: with {n_desc} samples per group, this test had only "
        f"{pct} power to detect an effect this size — a follow-up study should use "
        f"~{check['recommended_n_per_group']:,} samples per group to reach "
        f"{check['target_power']:.0%} power."
    )


def _interpret_power_check_chi2(check: dict) -> str:
    pct = f"{check['achieved_power']:.0%}"
    n = check["n"]

    if not check["underpowered"]:
        return (
            f"✅ Well-powered: with {n:,} rows, this chi-square test had {pct} power "
            f"to detect an association this strong (target: {check['target_power']:.0%})."
        )

    if check["recommended_n"] is None:
        return (
            f"⚠️ Underpowered: with {n:,} rows, this chi-square test had only {pct} "
            "power to detect an association this strong — the association is too weak "
            "for any finite sample size to reliably detect."
        )

    return (
        f"⚠️ Underpowered: with {n:,} rows, this chi-square test had only {pct} power "
        f"to detect an association this strong — a follow-up should collect "
        f"~{check['recommended_n']:,} rows total to reach {check['target_power']:.0%} power."
    )


def _interpret_power_check_anova(check: dict) -> str:
    pct = f"{check['achieved_power']:.0%}"
    k, n = check["k_groups"], check["nobs_total"]

    if not check["underpowered"]:
        return (
            f"✅ Well-powered: with {n:,} rows across {k} groups, this ANOVA had {pct} "
            f"power to detect a difference this large (target: {check['target_power']:.0%})."
        )

    if check["recommended_n_total"] is None:
        return (
            f"⚠️ Underpowered: with {n:,} rows across {k} groups, this ANOVA had only "
            f"{pct} power to detect a difference this large — the effect is too close "
            "to zero for any finite sample size to reliably detect."
        )

    return (
        f"⚠️ Underpowered: with {n:,} rows across {k} groups, this ANOVA had only {pct} "
        f"power to detect a difference this large — a follow-up should collect "
        f"~{check['recommended_n_total']:,} rows total (~{check['recommended_n_per_group']:,} "
        f"per group) to reach {check['target_power']:.0%} power."
    )


def _interpret_power_check_pearson(check: dict) -> str:
    pct = f"{check['achieved_power']:.0%}"
    n = check["n"]

    if not check["underpowered"]:
        return (
            f"✅ Well-powered: with {n:,} paired observations, this correlation test had "
            f"{pct} power to detect a relationship this strong (target: "
            f"{check['target_power']:.0%})."
        )

    if check["recommended_n"] is None:
        return (
            f"⚠️ Underpowered: with {n:,} paired observations, this correlation test had "
            f"only {pct} power to detect a relationship this strong — the correlation is "
            "too weak for any finite sample size to reliably detect."
        )

    return (
        f"⚠️ Underpowered: with {n:,} paired observations, this correlation test had only "
        f"{pct} power to detect a relationship this strong — a follow-up should collect "
        f"~{check['recommended_n']:,} paired observations to reach "
        f"{check['target_power']:.0%} power."
    )


def interpret_power_check(check: dict) -> str:
    """Plain-English verdict for a `power_check_ttest()`/`power_check_chi2()`/
    `power_check_anova()`/`power_check_correlation()` result, dispatching
    on the check's own `"test"` key (defaults to `"ttest"` for any caller
    built before that key existed, preserving the original contract), e.g.
    "⚠️ Underpowered: with 15 samples per group, this test had only 18%
    power to detect an effect this size — a follow-up would need ~176
    samples per group for 80% power." Never raises on a missing
    recommendation (zero/near-zero effect size).
    """
    if check.get("error"):
        return check["error"]

    test = check.get("test", "ttest")
    if test == "chi2":
        return _interpret_power_check_chi2(check)
    if test == "anova":
        return _interpret_power_check_anova(check)
    if test == "pearson":
        return _interpret_power_check_pearson(check)
    return _interpret_power_check_ttest(check)


def interpret_sample_size_proportions(result: dict) -> str:
    """Plain-English readout of a `sample_size_two_proportions()` result."""
    if result.get("error"):
        return result["error"]
    return (
        f"To detect a move from {result['baseline_rate']:.1%} to "
        f"{result['variant_rate']:.1%} with {result['power']:.0%} power at "
        f"α={result['alpha']}, you need **~{result['n_per_group']:,} users per "
        f"group** (~{result['total_n']:,} total)."
    )


def interpret_sample_size_means(result: dict) -> str:
    """Plain-English readout of a `sample_size_two_means()` result."""
    if result.get("error"):
        return result["error"]
    return (
        f"To detect a mean difference of {result['mean_diff']:g} (Cohen's d = "
        f"{result['cohens_d']:.2f}) with {result['power']:.0%} power at "
        f"α={result['alpha']}, you need **~{result['n_per_group']:,} samples per "
        f"group** (~{result['total_n']:,} total)."
    )


def interpret_sample_size_correlation(result: dict) -> str:
    """Plain-English readout of a `sample_size_correlation()` result."""
    if result.get("error"):
        return result["error"]
    return (
        f"To reliably detect a correlation of r={result['r']:.2f} with "
        f"{result['power']:.0%} power at α={result['alpha']}, you need "
        f"**~{result['n']:,} paired observations**."
    )
