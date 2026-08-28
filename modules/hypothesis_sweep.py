"""
Hypothesis Sweep — the agentic version of Stats Lab. Where Stats Lab tests
one manually-picked pair of columns at a time, this generates and runs
*every* statistically viable pairwise hypothesis test across the dataset
automatically, then applies Benjamini-Hochberg false-discovery-rate (FDR)
correction across the whole sweep before ranking what's left by effect size.

Reuses `stats_lab.suggest_test` / `stats_lab.run_test` for the actual test
dispatch, so a given pair type always resolves to exactly the same test
Stats Lab's manual flow would pick (Pearson for numeric/numeric, Welch's
t-test or one-way ANOVA for numeric/categorical depending on group count,
chi-square for categorical/categorical) — this module's only job is the
"run many, then correct for running many" part.

Why the correction matters: running N independent tests at a raw alpha of
0.05 produces roughly 0.05*N false positives by chance alone, even when
nothing in the data is really related. A dataset with 10 numeric columns
already has 45 possible pairs — reporting every p<0.05 pair from that
sweep without correction is implicit p-hacking. Benjamini-Hochberg controls
the expected proportion of false discoveries among the flagged pairs
instead, which is what makes an automated multi-test sweep a defensible
exploratory-analysis technique.
"""

from __future__ import annotations

import hashlib
from itertools import combinations
from typing import Optional

import pandas as pd

from modules import experiment_design, stats_lab

# Hard cap on pairs tested in one sweep so a very wide dataset (hundreds of
# columns) can't blow up runtime — C(200, 2) is already ~20k combinations,
# so this caps *columns considered*, not raw pair count, keeping the sweep
# proportional to what a human could plausibly review anyway.
DEFAULT_MAX_PAIRS = 200
DEFAULT_ALPHA = 0.05


def _viable_pairs(column_types: dict[str, str]) -> list[tuple[str, str]]:
    cols = [c for c, t in column_types.items() if t in ("numeric", "categorical")]
    return list(combinations(cols, 2))


def sweep_hypotheses(
    df: pd.DataFrame,
    column_types: dict[str, str],
    alpha: float = DEFAULT_ALPHA,
    max_pairs: int = DEFAULT_MAX_PAIRS,
) -> dict:
    """Run every viable pairwise hypothesis test and FDR-correct the results.

    Returns {
      "tested": [ {col_a, col_b, test, test_label, statistic, p_value,
                   p_adj, significant, effect_size, effect_size_name,
                   effect_size_label, n}, ... ] sorted by p_adj ascending,
                 ties broken by |effect_size| descending,
      "n_pairs_available": int,  # viable pairs before the max_pairs cap
      "n_pairs_skipped": int,    # dropped by the cap or unusable (e.g. a
                                  # categorical column with only 1 category)
      "n_tests_run": int,        # tests actually executed and scored
      "n_significant": int,      # significant *after* FDR correction
      "alpha": alpha,
    }

    An empty or all-unusable dataset returns a result with "tested": []
    and zeroed counts rather than raising — a sweep that finds nothing
    viable to test is a valid outcome, not a failure.
    """
    all_pairs = _viable_pairs(column_types)
    n_pairs_available = len(all_pairs)
    pairs = all_pairs[:max_pairs]
    n_skipped = n_pairs_available - len(pairs)

    rows = []
    for col_a, col_b in pairs:
        suggestion = stats_lab.suggest_test(df, column_types, col_a, col_b)
        if suggestion.get("error"):
            n_skipped += 1
            continue
        result = stats_lab.run_test(df, suggestion)
        if result.get("error") or result.get("p_value") is None:
            n_skipped += 1
            continue
        n = len(df[[col_a, col_b]].dropna())
        rows.append(
            {
                "col_a": col_a,
                "col_b": col_b,
                "test": result["test"],
                "test_label": stats_lab.TEST_LABELS[result["test"]],
                "statistic": result["statistic"],
                "p_value": result["p_value"],
                "effect_size": result["effect_size"],
                "effect_size_name": result["effect_size_name"],
                "effect_size_label": result["effect_size_label"],
                "n": n,
                # Per-group n for ttest/anova rows (needed for a post-hoc power
                # check — see annotate_power() below); None for pearson (no
                # groups) and chi2 (a contingency table, not per-group counts).
                "group_sizes": (
                    dict(result["groups"]) if result["test"] in ("ttest", "anova") else None
                ),
                # Degrees of freedom, chi2 rows only (also for annotate_power()
                # below — chi-square power needs dof, not just Cramer's V).
                "dof": result.get("dof"),
            }
        )

    if not rows:
        return {
            "tested": [],
            "n_pairs_available": n_pairs_available,
            "n_pairs_skipped": n_skipped,
            "n_tests_run": 0,
            "n_significant": 0,
            "alpha": alpha,
        }

    from statsmodels.stats.multitest import multipletests

    p_values = [r["p_value"] for r in rows]
    reject, p_adj, _, _ = multipletests(p_values, alpha=alpha, method="fdr_bh")
    for row, adj, sig in zip(rows, p_adj, reject):
        row["p_adj"] = float(adj)
        row["significant"] = bool(sig)

    rows.sort(key=lambda r: (r["p_adj"], -abs(r["effect_size"])))

    return {
        "tested": rows,
        "n_pairs_available": n_pairs_available,
        "n_pairs_skipped": n_skipped,
        "n_tests_run": len(rows),
        "n_significant": int(sum(reject)),
        "alpha": alpha,
    }


def annotate_power(result: dict, target_power: float = experiment_design.DEFAULT_POWER) -> dict:
    """Attach a post-hoc power check to every significant row in a sweep
    result, across all four test families `sweep_hypotheses()` runs:
    t-test (`experiment_design.power_check_ttest`), chi-square
    (`power_check_chi2`), one-way ANOVA (`power_check_anova`), and Pearson
    correlation (`power_check_correlation`, via a Fisher z-transform —
    see `experiment_design`'s module docstring for why that's a genuinely
    different distribution family than the other three).

    A significant result only tells you *this* sample showed an effect —
    it says nothing about whether the test had enough power to reliably
    find one in the first place. A "significant" result from 8 rows per
    group is far less trustworthy than the same p-value from 800, and this
    surfaces that distinction automatically rather than making the user
    reason about sample size themselves.

    Non-mutating: returns a new dict with a new `tested` list; the input
    `result` (and its row dicts) are left untouched.
    """
    if not result or not result.get("tested"):
        return result

    alpha = result.get("alpha", DEFAULT_ALPHA)
    annotated_rows = []
    for row in result["tested"]:
        row = dict(row)
        test = row.get("test")
        group_sizes = row.get("group_sizes")
        dof = row.get("dof")

        if (
            test == "ttest"
            and row.get("significant")
            and group_sizes
            and len(group_sizes) == 2
            and all(n >= 2 for n in group_sizes.values())
        ):
            n1, n2 = list(group_sizes.values())
            row["power_check"] = experiment_design.power_check_ttest(
                row["effect_size"], n1, n2, alpha=alpha, target_power=target_power
            )
        elif (
            test == "anova"
            and row.get("significant")
            and group_sizes
            and len(group_sizes) >= 2
            and all(n >= 2 for n in group_sizes.values())
        ):
            k_groups = len(group_sizes)
            nobs_total = sum(group_sizes.values())
            row["power_check"] = experiment_design.power_check_anova(
                row["effect_size"], k_groups, nobs_total, alpha=alpha, target_power=target_power
            )
        elif (
            test == "chi2"
            and row.get("significant")
            and dof
            and dof >= 1
            and row.get("n", 0) >= 2
        ):
            cohens_w = experiment_design.cohens_w_from_chi2(row["statistic"], row["n"])
            row["power_check"] = experiment_design.power_check_chi2(
                cohens_w, row["n"], dof, alpha=alpha, target_power=target_power
            )
        elif (
            test == "pearson"
            and row.get("significant")
            and row.get("n", 0) >= 4
        ):
            row["power_check"] = experiment_design.power_check_correlation(
                row["effect_size"], row["n"], alpha=alpha, target_power=target_power
            )
        else:
            row["power_check"] = None
        annotated_rows.append(row)

    annotated = dict(result)
    annotated["tested"] = annotated_rows
    return annotated


def fingerprint_sweep(result: Optional[dict]) -> str:
    """A short, stable hash of a `sweep_hypotheses()` result's significant
    findings — used to cache a Gemini narration call keyed to output that's
    actually different, same pattern as `anomaly.fingerprint_flagged`.
    """
    if not result or not result.get("tested"):
        return "empty"
    significant = [r for r in result["tested"] if r["significant"]]
    key = "|".join(
        f"{r['col_a']}:{r['col_b']}:{r['test']}:{r['p_adj']:.6f}" for r in significant
    )
    return hashlib.sha256(key.encode()).hexdigest()[:16]


_SWEEP_NARRATION_PROMPT = (
    "You are a senior data analyst explaining the results of an automated statistical "
    "hypothesis sweep to a stakeholder who isn't technical. {n_tests} pairwise statistical "
    "tests were run automatically across the dataset's columns (correlation tests for "
    "numeric/numeric pairs, t-test/ANOVA for numeric/categorical pairs, chi-square for "
    "categorical/categorical pairs), then corrected for the multiple-comparisons problem "
    "with Benjamini-Hochberg false-discovery-rate correction so random noise doesn't get "
    "reported as a real finding. {n_significant} pair(s) stayed significant after correction. "
    "Here are the top findings, ranked by effect size:\n\n{findings_text}\n\n"
    "In 3-4 sentences: explain in plain English what these relationships suggest about the "
    "data, and recommend one concrete next step (e.g. investigate a specific relationship "
    "further in Stats Lab, or treat it as a candidate feature in ML Lab). Do not simply "
    "restate the numbers back."
)


def narrate_sweep(model, result: Optional[dict]) -> tuple[str, Optional[str]]:
    """Ask Gemini to interpret a hypothesis sweep's significant findings.

    Returns (narration, error). Callers should cache the result keyed by
    `fingerprint_sweep(result)` to avoid re-calling Gemini for a sweep the
    user has already seen narrated — same caching contract as every other
    narration helper in the app (see `anomaly.narrate_anomalies`).
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if not result or not result.get("tested"):
        return "No column pairs were viable to test in this sweep — nothing to narrate.", None

    significant = [r for r in result["tested"] if r["significant"]]
    if not significant:
        return (
            f"None of the {result['n_tests_run']} test(s) run stayed significant after "
            "false-discovery-rate correction — no reliable relationships were found in this sweep.",
            None,
        )

    from modules.ai_analyst import call_gemini

    top = significant[:8]
    findings_text = "\n".join(
        f"- '{r['col_a']}' vs '{r['col_b']}' ({r['test_label']}): {r['effect_size_label']} effect "
        f"({r['effect_size_name']}={r['effect_size']:.2f}, p_adj={r['p_adj']:.4f})"
        for r in top
    )
    prompt = _SWEEP_NARRATION_PROMPT.format(
        n_tests=result["n_tests_run"], n_significant=result["n_significant"], findings_text=findings_text
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


# ═══════════════════════════════════════════════════════════════════════
# NARRATION FACT-CHECK — the same "plausible but wrong number" safety net
# insight_verifier applies to Auto Analyst's Gemini findings (see that
# module's docstring), extended here to narrate_sweep()'s prose. The
# reference numbers don't need recomputing from the DataFrame the way
# insight_verifier.compute_reference_numbers() does — sweep_hypotheses()
# already produced every statistic narrate_sweep() could plausibly cite
# (p-values, adjusted p-values, effect sizes, sample sizes, test counts),
# so the ground truth here is exact, not a reference-set approximation.
# ═══════════════════════════════════════════════════════════════════════
def sweep_reference_numbers(result: Optional[dict]) -> set[float]:
    """Ground-truth numbers straight from a sweep result's own already-
    computed statistics. Never raises — a malformed result just yields an
    empty (or partial) reference set, which verify_narration() degrades to
    "unverifiable" for, same non-blocking contract as insight_verifier.
    """
    if not result:
        return set()
    numbers: set[float] = set()
    try:
        numbers.add(float(result.get("n_tests_run", 0)))
        numbers.add(float(result.get("n_significant", 0)))
        for row in result.get("tested") or []:
            for key in ("p_value", "p_adj", "effect_size", "n"):
                value = row.get(key)
                if value is None:
                    continue
                numbers.add(round(float(value), 4))
                numbers.add(round(float(value), 2))
                numbers.add(round(float(value) * 100, 2))  # p/effect sizes often quoted as %
    except (TypeError, ValueError, AttributeError):
        pass
    return numbers


def verify_narration(narration: str, result: Optional[dict]) -> dict:
    """Fact-check narrate_sweep()'s prose against the sweep's own numbers.
    Reuses insight_verifier.verify_finding() — same {"status": "confirmed"
    | "flagged" | "unverifiable", ...} contract as every other verified
    surface in the app, just backed by exact sweep statistics instead of a
    DataFrame recomputation. Never raises.
    """
    from modules import insight_verifier

    try:
        reference_numbers = sweep_reference_numbers(result)
    except Exception:
        reference_numbers = set()
    return insight_verifier.verify_finding(narration or "", reference_numbers)


# ═══════════════════════════════════════════════════════════════════════
# CONFOUNDER CROSS-CHECK — the sweep's own agentic follow-up question.
# Auto-Insights' strong correlations already get stress-tested by
# modules.confounder_detection ("...but does it hold up once you control
# for a third variable?" — see that module's docstring for why this
# matters, Simpson's Paradox in particular). A sweep finding that survives
# FDR correction across dozens of tests is a *stronger* claim than a single
# eyeballed correlation, which makes it more likely to get taken at face
# value — exactly the kind of finding worth auto-questioning, not less.
# ═══════════════════════════════════════════════════════════════════════
def cross_check_confounders(
    df: pd.DataFrame, column_types: dict[str, str], result: Optional[dict], top_k: int = 3
) -> list[dict]:
    """For the sweep's strongest significant findings, auto-run the same
    paradox/attenuation check Auto-Insights' correlations get:

    - numeric/numeric (Pearson) pairs, via `confounder_detection.
      auto_scan_for_confounding`'s `correlation_pairs=` hook — the pair's
      already-computed r is reused directly, nothing recomputed.
    - binary-categorical/numeric (Welch's t-test) pairs, via
      `confounder_detection.auto_scan_for_group_diff_confounding`'s
      `ttest_pairs=` hook — same reuse, but for Cohen's d instead of r
      (see that module's "GROUP-DIFFERENCE CONFOUNDER CROSS-CHECK" section
      for why a categorical relationship is just as susceptible to
      Simpson's Paradox as a correlation is).

    One-way ANOVA (>2 groups) and chi-square pairs are still out of scope —
    neither has a single signed effect size for a confounder to flip.
    Deterministic, no Gemini call. Returns a list of scans tagged with
    `"relationship"` ("correlation" or "group_diff") so callers can render
    each appropriately — each scan is otherwise its source function's own
    shape ({x, y, overall_r, findings: [...]} or {x, y, overall_d,
    findings: [...]}). Empty when nothing significant survived FDR
    correction or every candidate confounder came back "robust". Never
    raises: a malformed `result` just yields an empty list, same
    non-blocking contract as `sweep_reference_numbers`.
    """
    try:
        tested = result.get("tested") if result else None
        if not tested:
            return []
        significant_pearson = [
            r for r in tested
            if r.get("significant") and r.get("test") == "pearson" and r.get("effect_size") is not None
        ]
        significant_ttest = [
            r for r in tested
            if r.get("significant") and r.get("test") == "ttest" and r.get("effect_size") is not None
        ]
    except (TypeError, AttributeError, KeyError):
        return []

    if not significant_pearson and not significant_ttest:
        return []

    from modules import confounder_detection

    scans = []
    if significant_pearson:
        pairs = [(r["col_a"], r["col_b"], float(r["effect_size"])) for r in significant_pearson[:top_k]]
        for scan in confounder_detection.auto_scan_for_confounding(
            df, column_types, correlation_pairs=pairs, top_k_pairs=top_k
        ):
            scan["relationship"] = "correlation"
            scans.append(scan)

    if significant_ttest:
        ttest_pairs = []
        for r in significant_ttest[:top_k]:
            col_a, col_b = r["col_a"], r["col_b"]
            if column_types.get(col_a) == "categorical":
                cat_col, num_col = col_a, col_b
            else:
                cat_col, num_col = col_b, col_a
            ttest_pairs.append((cat_col, num_col, float(r["effect_size"])))
        for scan in confounder_detection.auto_scan_for_group_diff_confounding(
            df, column_types, ttest_pairs=ttest_pairs, top_k_pairs=top_k
        ):
            scan["relationship"] = "group_diff"
            scans.append(scan)

    return scans


def cross_check_interactions(
    df: pd.DataFrame, column_types: dict[str, str], result: Optional[dict], top_k: int = 3
) -> list[dict]:
    """For the sweep's strongest significant one-way ANOVA findings (a
    categorical column splitting a numeric column's mean across 3+ groups),
    check whether a *third* categorical column moderates that difference —
    does the size of the group effect actually depend on another factor?

    This answers a different question than `cross_check_confounders()`:
    a confounder check asks whether a *signed* effect (correlation r,
    Cohen's d) flips or attenuates once a covariate is controlled for —
    one-way ANOVA's eta-squared has no sign to flip, which is exactly why
    `cross_check_confounders()`'s own docstring puts ANOVA pairs out of
    scope. Effect modification is the analogous question for a multi-group
    effect, answered with a genuine two-way ANOVA
    (`numeric ~ C(cat) + C(other) + C(cat):C(other)`, Type II sum of
    squares) — the interaction term's own p-value is what's tested, not a
    derived correlation.

    Candidate "other" columns are every remaining categorical column with
    2-10 distinct levels (same cardinality cap `stats_lab.suggest_test`
    uses for the cat_col itself), skipping any candidate whose cross-tab
    with cat_col doesn't have at least 4 populated (cat, other) cells with
    2+ rows each — too sparse a design matrix to fit a stable interaction
    term. p-values across every candidate actually tested are FDR-corrected
    together (same multiple-comparisons rationale `sweep_hypotheses()`
    itself uses), and only interactions that survive correction are
    returned. Deterministic, no Gemini call. Never raises: a malformed
    `result`, an unfittable candidate, or a patsy/statsmodels fit failure
    just skips that candidate rather than aborting the whole check.

    Returns a list of {cat_col, numeric_col, other_col, interaction_p,
    interaction_p_adj, group_means: {other_level: {cat_level: mean}}}
    sorted by interaction_p_adj ascending, capped to `top_k` entries. Empty
    when there's no significant ANOVA row, no viable third column, or
    nothing survives correction.
    """
    try:
        tested = result.get("tested") if result else None
        if not tested:
            return []
        significant_anova = [
            r for r in tested if r.get("significant") and r.get("test") == "anova"
        ]
    except (TypeError, AttributeError, KeyError):
        return []

    if not significant_anova:
        return []

    import statsmodels.formula.api as smf
    from statsmodels.stats.anova import anova_lm
    from statsmodels.stats.multitest import multipletests

    candidates = []  # each: (cat_col, numeric_col, other_col, clean_df)
    for row in significant_anova[:top_k]:
        col_a, col_b = row["col_a"], row["col_b"]
        if column_types.get(col_a) == "categorical":
            cat_col, numeric_col = col_a, col_b
        else:
            cat_col, numeric_col = col_b, col_a

        other_cols = [
            c for c, t in column_types.items()
            if t == "categorical" and c != cat_col
        ]
        for other_col in other_cols:
            try:
                clean = df[[numeric_col, cat_col, other_col]].dropna()
                other_levels = clean[other_col].nunique()
                if not (2 <= other_levels <= 10):
                    continue
                cell_counts = clean.groupby([cat_col, other_col]).size()
                populated_cells = cell_counts[cell_counts >= 2]
                if len(populated_cells) < 4:
                    continue
            except (TypeError, ValueError, KeyError):
                continue
            candidates.append((cat_col, numeric_col, other_col, clean))

    if not candidates:
        return []

    fits = []
    for cat_col, numeric_col, other_col, clean in candidates:
        try:
            formula = (
                f"Q('{numeric_col}') ~ C(Q('{cat_col}')) + C(Q('{other_col}')) "
                f"+ C(Q('{cat_col}')):C(Q('{other_col}'))"
            )
            model = smf.ols(formula, data=clean).fit()
            aov = anova_lm(model, typ=2)
            interaction_terms = [ix for ix in aov.index if ":" in ix]
            if not interaction_terms:
                continue
            p_value = float(aov.loc[interaction_terms[0], "PR(>F)"])
            if pd.isna(p_value):
                continue
        except Exception:
            continue

        group_means = {}
        for other_level, sub in clean.groupby(other_col):
            group_means[str(other_level)] = {
                str(cat_level): float(vals.mean())
                for cat_level, vals in sub.groupby(cat_col)[numeric_col]
            }

        fits.append(
            {
                "cat_col": cat_col,
                "numeric_col": numeric_col,
                "other_col": other_col,
                "interaction_p": p_value,
                "group_means": group_means,
            }
        )

    if not fits:
        return []

    p_values = [f["interaction_p"] for f in fits]
    reject, p_adj, _, _ = multipletests(p_values, alpha=result.get("alpha", DEFAULT_ALPHA), method="fdr_bh")
    for f, adj, sig in zip(fits, p_adj, reject):
        f["interaction_p_adj"] = float(adj)
        f["significant"] = bool(sig)

    significant_fits = [f for f in fits if f["significant"]]
    significant_fits.sort(key=lambda f: f["interaction_p_adj"])
    return significant_fits[:top_k]


def cross_check_categorical_interactions(
    df: pd.DataFrame, column_types: dict[str, str], result: Optional[dict], top_k: int = 3
) -> list[dict]:
    """The chi-square analog of `cross_check_interactions()`: for the
    sweep's strongest significant categorical/categorical (chi-square)
    findings, check whether a *third* categorical column moderates the
    strength of that association — is `cat_a` and `cat_b` more (or less)
    associated within some levels of `other_col` than others?

    `cross_check_interactions()` answers this for a numeric outcome via a
    two-way ANOVA interaction term. There's no numeric outcome here, so the
    equivalent tool is a log-linear (Poisson GLM) model over the full
    `cat_a x cat_b x other_col` contingency table: fit the saturated model
    (every two-way interaction plus the three-way `cat_a:cat_b:other_col`
    term) against the model without that three-way term, and run a
    likelihood-ratio test on the deviance difference. A significant result
    means the two-way association's *shape* genuinely differs across levels
    of `other_col`, not just an additive shift in cell counts.

    Candidate "other" columns are every remaining categorical column with
    2-10 distinct levels (same cardinality cap `cross_check_interactions()`
    uses), skipping any candidate whose full `cat_a x cat_b x other_col`
    grid averages fewer than 2 observations per cell — too sparse for a
    stable log-linear fit. p-values across every candidate actually fit are
    FDR-corrected together (same multiple-comparisons rationale used
    throughout this module). Deterministic, no Gemini call. Never raises: a
    malformed `result`, an unfittable candidate, or a statsmodels
    convergence failure just skips that candidate.

    Returns a list of {cat_a, cat_b, other_col, interaction_p,
    interaction_p_adj, cramers_v_by_level: {other_level: float}} sorted by
    interaction_p_adj ascending, capped to `top_k`. Empty when there's no
    significant chi2 row, no viable third column, or nothing survives
    correction.
    """
    try:
        tested = result.get("tested") if result else None
        if not tested:
            return []
        significant_chi2 = [
            r for r in tested if r.get("significant") and r.get("test") == "chi2"
        ]
    except (TypeError, AttributeError, KeyError):
        return []

    if not significant_chi2:
        return []

    import numpy as np
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    from statsmodels.stats.multitest import multipletests

    candidates = []  # each: (cat_a, cat_b, other_col, counts_df)
    for row in significant_chi2[:top_k]:
        cat_a, cat_b = row["col_a"], row["col_b"]
        other_cols = [
            c for c, t in column_types.items()
            if t == "categorical" and c not in (cat_a, cat_b)
        ]
        for other_col in other_cols:
            try:
                clean = df[[cat_a, cat_b, other_col]].dropna()
                a_levels = clean[cat_a].unique()
                b_levels = clean[cat_b].unique()
                other_levels = clean[other_col].unique()
                if not (2 <= len(a_levels) <= 10 and 2 <= len(b_levels) <= 10):
                    continue
                if not (2 <= len(other_levels) <= 10):
                    continue
                grid_size = len(a_levels) * len(b_levels) * len(other_levels)
                if grid_size < 4 or len(clean) / grid_size < 2:
                    continue
                full_index = pd.MultiIndex.from_product(
                    [a_levels, b_levels, other_levels], names=[cat_a, cat_b, other_col]
                )
                counts = (
                    clean.groupby([cat_a, cat_b, other_col])
                    .size()
                    .reindex(full_index, fill_value=0)
                    .reset_index(name="count")
                )
            except (TypeError, ValueError, KeyError):
                continue
            candidates.append((cat_a, cat_b, other_col, clean, counts))

    if not candidates:
        return []

    fits = []
    for cat_a, cat_b, other_col, clean, counts in candidates:
        try:
            qa, qb, qo = f"Q('{cat_a}')", f"Q('{cat_b}')", f"Q('{other_col}')"
            full_formula = f"count ~ C({qa}) * C({qb}) * C({qo})"
            reduced_formula = (
                f"count ~ C({qa})*C({qb}) + C({qa})*C({qo}) + C({qb})*C({qo})"
            )
            full_model = smf.glm(full_formula, data=counts, family=sm.families.Poisson()).fit()
            reduced_model = smf.glm(
                reduced_formula, data=counts, family=sm.families.Poisson()
            ).fit()
            lr_stat = 2 * (full_model.llf - reduced_model.llf)
            df_diff = full_model.df_model - reduced_model.df_model
            if lr_stat < 0 or df_diff <= 0:
                continue
            p_value = float(stats_lab.stats.chi2.sf(lr_stat, df_diff))
            if np.isnan(p_value):
                continue
        except Exception:
            continue

        cramers_v_by_level = {}
        for level, sub in clean.groupby(other_col):
            table = pd.crosstab(sub[cat_a], sub[cat_b])
            if table.shape[0] < 2 or table.shape[1] < 2 or table.to_numpy().sum() == 0:
                cramers_v_by_level[str(level)] = 0.0
                continue
            stat, _, _, _ = stats_lab.stats.chi2_contingency(table)
            n = table.to_numpy().sum()
            min_dim = min(table.shape) - 1
            cramers_v_by_level[str(level)] = (
                float(np.sqrt((stat / n) / min_dim)) if n > 0 and min_dim > 0 else 0.0
            )

        fits.append(
            {
                "cat_a": cat_a,
                "cat_b": cat_b,
                "other_col": other_col,
                "interaction_p": p_value,
                "cramers_v_by_level": cramers_v_by_level,
            }
        )

    if not fits:
        return []

    p_values = [f["interaction_p"] for f in fits]
    reject, p_adj, _, _ = multipletests(p_values, alpha=result.get("alpha", DEFAULT_ALPHA), method="fdr_bh")
    for f, adj, sig in zip(fits, p_adj, reject):
        f["interaction_p_adj"] = float(adj)
        f["significant"] = bool(sig)

    significant_fits = [f for f in fits if f["significant"]]
    significant_fits.sort(key=lambda f: f["interaction_p_adj"])
    return significant_fits[:top_k]


def build_sweep_chart(result: dict, top_n: int = 15):
    """Horizontal bar chart of the top significant findings by |effect size|."""
    import plotly.express as px

    significant = [r for r in result.get("tested", []) if r["significant"]][:top_n]
    if not significant:
        return None

    significant = sorted(significant, key=lambda r: abs(r["effect_size"]))
    labels = [f"{r['col_a']} vs {r['col_b']}" for r in significant]
    values = [abs(r["effect_size"]) for r in significant]
    fig = px.bar(
        x=values, y=labels, orientation="h",
        labels={"x": "|Effect size|", "y": "Column pair"},
        title="Hypothesis Sweep — significant findings by effect size",
    )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig
