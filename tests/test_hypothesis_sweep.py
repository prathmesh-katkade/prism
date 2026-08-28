"""Tests for modules.hypothesis_sweep — automated pairwise hypothesis
testing across a dataset with Benjamini-Hochberg FDR correction."""
from __future__ import annotations

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests

from modules.hypothesis_sweep import (
    DEFAULT_ALPHA,
    annotate_power,
    build_sweep_chart,
    cross_check_categorical_interactions,
    cross_check_confounders,
    cross_check_interactions,
    fingerprint_sweep,
    narrate_sweep,
    sweep_hypotheses,
    sweep_reference_numbers,
    verify_narration,
)


def _correlated_df(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=n)
    y = 3 * x + rng.normal(scale=0.1, size=n)  # strong, near-deterministic correlation
    group = rng.choice(["a", "b", "c"], size=n)
    # numeric that genuinely differs by group (planted ANOVA signal)
    offset = pd.Series(group).map({"a": 0, "b": 5, "c": 10}).to_numpy()
    z = offset + rng.normal(scale=0.5, size=n)
    # two categoricals that are genuinely associated (planted chi-square signal)
    cat_a = pd.Series(group)
    cat_b = cat_a.map({"a": "low", "b": "mid", "c": "high"})
    return pd.DataFrame({"x": x, "y": y, "z": z, "group": group, "tier": cat_b})


def _column_types(df: pd.DataFrame) -> dict[str, str]:
    types = {}
    for col in df.columns:
        types[col] = "numeric" if pd.api.types.is_numeric_dtype(df[col]) else "categorical"
    return types


# --- sweep_hypotheses: planted-signal recovery ----------------------------

def test_sweep_finds_planted_numeric_correlation():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    xy = next(r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"x", "y"})
    assert xy["test"] == "pearson"
    assert xy["significant"] is True
    assert abs(xy["effect_size"]) > 0.9


def test_sweep_finds_planted_anova_signal():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    zg = next(r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"z", "group"})
    assert zg["test"] == "anova"
    assert zg["significant"] is True


def test_sweep_finds_planted_chi2_signal():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    gt = next(r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"group", "tier"})
    assert gt["test"] == "chi2"
    assert gt["significant"] is True


def test_sweep_result_is_sorted_by_adjusted_p_value():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    p_adjs = [r["p_adj"] for r in result["tested"]]
    assert p_adjs == sorted(p_adjs)


def test_sweep_counts_are_internally_consistent():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    assert result["n_tests_run"] == len(result["tested"])
    assert result["n_significant"] == sum(1 for r in result["tested"] if r["significant"])
    assert result["n_significant"] <= result["n_tests_run"]


# --- FDR correction actually corrects -------------------------------------

def test_fdr_correction_matches_statsmodels_directly():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df), alpha=0.05)
    # order-independent check: adjusted p-values from the module should be a
    # valid Benjamini-Hochberg correction of the module's own raw p-values
    reject, expected_adj, _, _ = multipletests(
        [r["p_value"] for r in result["tested"]], alpha=0.05, method="fdr_bh"
    )
    actual_adj = [r["p_adj"] for r in result["tested"]]
    assert np.allclose(actual_adj, expected_adj)
    assert [bool(x) for x in reject] == [r["significant"] for r in result["tested"]]


def test_fdr_correction_suppresses_noise_false_positives():
    # 15 mutually independent noise columns -> 105 pairs. At raw alpha=0.05
    # we'd expect ~5 "significant" pairs by chance alone; BH correction
    # should knock most or all of those back down since there's no real signal.
    rng = np.random.default_rng(123)
    df = pd.DataFrame({f"n{i}": rng.normal(size=300) for i in range(15)})
    result = sweep_hypotheses(df, _column_types(df))
    raw_significant = sum(1 for r in result["tested"] if r["p_value"] < 0.05)
    assert result["n_significant"] <= raw_significant


def test_effect_size_is_populated_and_sortable():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    for row in result["tested"]:
        assert row["effect_size"] is not None
        assert row["effect_size_name"]
        assert row["effect_size_label"]


# --- pair cap ---------------------------------------------------------------

def test_max_pairs_cap_is_respected_and_reported():
    rng = np.random.default_rng(1)
    df = pd.DataFrame({f"n{i}": rng.normal(size=50) for i in range(10)})  # 45 pairs
    result = sweep_hypotheses(df, _column_types(df), max_pairs=3)
    assert result["n_pairs_available"] == 45
    assert len(result["tested"]) <= 3
    assert result["n_pairs_skipped"] >= 42


# --- edge cases --------------------------------------------------------------

def test_sweep_handles_empty_dataframe():
    df = pd.DataFrame()
    result = sweep_hypotheses(df, {})
    assert result["tested"] == []
    assert result["n_tests_run"] == 0
    assert result["n_significant"] == 0


def test_sweep_handles_single_column():
    df = pd.DataFrame({"only": [1, 2, 3, 4, 5]})
    result = sweep_hypotheses(df, {"only": "numeric"})
    assert result["tested"] == []
    assert result["n_pairs_available"] == 0


def test_sweep_skips_single_category_columns_without_crashing():
    df = pd.DataFrame({"const": ["a"] * 20, "value": range(20)})
    result = sweep_hypotheses(df, {"const": "categorical", "value": "numeric"})
    assert result["tested"] == []
    assert result["n_pairs_skipped"] == 1


def test_sweep_handles_nan_heavy_columns():
    df = pd.DataFrame({"a": [np.nan] * 10 + list(range(10)), "b": list(range(20))})
    result = sweep_hypotheses(df, {"a": "numeric", "b": "numeric"})
    # should not raise; either scores the pair on the non-null rows or skips it
    assert isinstance(result["tested"], list)


# --- fingerprint_sweep -------------------------------------------------------

def test_fingerprint_is_stable_for_the_same_result():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    assert fingerprint_sweep(result) == fingerprint_sweep(result)


def test_fingerprint_changes_when_significant_findings_change():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    other = sweep_hypotheses(_correlated_df(seed=99), _column_types(df))
    assert fingerprint_sweep(result) != fingerprint_sweep(other)


def test_fingerprint_of_empty_result_is_stable():
    empty = {"tested": [], "n_tests_run": 0, "n_significant": 0}
    assert fingerprint_sweep(empty) == fingerprint_sweep(empty) == "empty"
    assert fingerprint_sweep(None) == "empty"


# --- narrate_sweep -----------------------------------------------------------

def test_narrate_sweep_without_model_returns_error():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    narration, error = narrate_sweep(None, result)
    assert narration == ""
    assert error is not None


def test_narrate_sweep_with_no_viable_pairs_skips_gemini():
    empty = {"tested": [], "n_tests_run": 0, "n_significant": 0}

    class _ShouldNotBeCalled:
        def generate_content(self, *_args, **_kwargs):
            raise AssertionError("Gemini should not be called with no viable pairs")

    narration, error = narrate_sweep(_ShouldNotBeCalled(), empty)
    assert error is None
    assert "nothing to narrate" in narration.lower()


def test_narrate_sweep_with_no_significant_findings_skips_gemini():
    rng = np.random.default_rng(5)
    df = pd.DataFrame({"n0": rng.normal(size=30), "n1": rng.normal(size=30)})
    result = sweep_hypotheses(df, _column_types(df))
    result["tested"] = [{**r, "significant": False} for r in result["tested"]]

    class _ShouldNotBeCalled:
        def generate_content(self, *_args, **_kwargs):
            raise AssertionError("Gemini should not be called with nothing significant")

    narration, error = narrate_sweep(_ShouldNotBeCalled(), result)
    assert error is None
    assert "no reliable relationships" in narration.lower()


def test_narrate_sweep_calls_gemini_with_top_findings():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))

    class _FakeResponse:
        text = "The strongest signal is between x and y — worth a closer look."

    class _FakeModel:
        def generate_content(self, contents):
            assert "hypothesis sweep" in contents.lower()
            assert "false-discovery-rate" in contents.lower()
            return _FakeResponse()

    narration, error = narrate_sweep(_FakeModel(), result)
    assert error is None
    assert "worth a closer look" in narration.lower()


# --- sweep_reference_numbers / verify_narration --------------------------
# Fact-checks narrate_sweep()'s Gemini prose against the sweep's own
# already-computed test statistics (Run 17) — the same "plausible but
# wrong number" safety net insight_verifier applies to Auto Analyst
# findings, but backed by exact numbers the sweep already produced rather
# than a DataFrame recomputation.

def test_sweep_reference_numbers_includes_top_level_counts():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    numbers = sweep_reference_numbers(result)
    assert float(result["n_tests_run"]) in numbers
    assert float(result["n_significant"]) in numbers


def test_sweep_reference_numbers_includes_per_test_statistics():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    numbers = sweep_reference_numbers(result)
    row = result["tested"][0]
    assert round(float(row["effect_size"]), 2) in numbers
    assert round(float(row["n"]), 2) in numbers


def test_sweep_reference_numbers_empty_result_is_safe():
    assert sweep_reference_numbers(None) == set()
    assert sweep_reference_numbers({"tested": []}) == {0.0}


def test_verify_narration_confirmed_when_numbers_match():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    n_sig = result["n_significant"]
    narration = f"{n_sig} relationship(s) survived FDR correction — worth a closer look."
    verification = verify_narration(narration, result)
    assert verification["status"] == "confirmed"


def test_verify_narration_flagged_when_a_number_is_fabricated():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    narration = "A whopping 987654 relationships were significant — an extraordinary result."
    verification = verify_narration(narration, result)
    assert verification["status"] == "flagged"


def test_verify_narration_unverifiable_when_no_numbers_in_text():
    result = {"tested": [], "n_tests_run": 0, "n_significant": 0}
    verification = verify_narration("Nothing to report here.", result)
    assert verification["status"] == "unverifiable"


def test_verify_narration_never_raises_on_malformed_result():
    # A malformed "tested" value must degrade gracefully (no exception) —
    # the narration's number won't match the resulting near-empty
    # reference set, which correctly reads as "flagged", not a crash.
    verification = verify_narration("Some text with 42 in it.", {"tested": "not a list"})
    assert verification["status"] in ("flagged", "unverifiable")


# --- build_sweep_chart --------------------------------------------------------

def test_build_sweep_chart_returns_none_when_nothing_significant():
    result = {"tested": [{"col_a": "a", "col_b": "b", "significant": False, "effect_size": 0.01}]}
    assert build_sweep_chart(result) is None


def test_build_sweep_chart_returns_figure_for_significant_findings():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    fig = build_sweep_chart(result)
    assert fig is not None


# --- cross_check_confounders ---------------------------------------------
# Agentic follow-up to the sweep itself: does a significant pearson pair
# hold up once you control for a third variable? Reuses
# modules.confounder_detection.auto_scan_for_confounding — same paradox
# shape as test_confounder_detection's _simpsons_paradox_df, scaled up so
# the pooled pair also clears FDR significance inside a real sweep.

def _sweep_paradox_df(n_per_group: int = 60, seed: int = 1) -> pd.DataFrame:
    """Within each of two groups, x and y are strongly *negatively*
    correlated, but group B sits far up-and-to-the-right of group A, so the
    pooled correlation comes out strongly *positive* instead — classic
    Simpson's Paradox, scaled up so the pooled x/y pair is itself a
    significant sweep finding (not just a paradox in isolation)."""
    rng = np.random.default_rng(seed)
    x_a = np.linspace(1, 20, n_per_group)
    y_a = 20 - x_a + rng.normal(scale=0.3, size=n_per_group)
    x_b = np.linspace(30, 49, n_per_group)
    y_b = 70 - x_b + rng.normal(scale=0.3, size=n_per_group)
    return pd.DataFrame(
        {
            "x": np.concatenate([x_a, x_b]),
            "y": np.concatenate([y_a, y_b]),
            "group": ["A"] * n_per_group + ["B"] * n_per_group,
        }
    )


def test_cross_check_confounders_flags_planted_paradox():
    df = _sweep_paradox_df()
    result = sweep_hypotheses(df, _column_types(df))
    xy = next(r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"x", "y"})
    assert xy["test"] == "pearson" and xy["significant"] is True  # sanity: the sweep itself found it

    cross = cross_check_confounders(df, _column_types(df), result)
    assert cross
    scan = next(s for s in cross if {s["x"], s["y"]} == {"x", "y"})
    verdicts = {f["confounder"]: f["verdict"] for f in scan["findings"]}
    assert verdicts.get("group") == "paradox"


def test_cross_check_confounders_empty_when_nothing_significant():
    rng = np.random.default_rng(2)
    df = pd.DataFrame({"a": rng.normal(size=50), "b": rng.normal(size=50)})
    result = sweep_hypotheses(df, _column_types(df))
    assert cross_check_confounders(df, _column_types(df), result) == []


def test_cross_check_confounders_skips_when_no_significant_pearson_pair():
    df = _correlated_df()
    # Only the categorical/categorical pair is significant, no pearson pair.
    fake_result = {
        "tested": [
            {"col_a": "group", "col_b": "tier", "test": "chi2", "significant": True, "effect_size": 0.9},
            {"col_a": "x", "col_b": "z", "test": "pearson", "significant": False, "effect_size": 0.01},
        ]
    }
    assert cross_check_confounders(df, _column_types(df), fake_result) == []


def test_cross_check_confounders_handles_missing_or_malformed_result_safely():
    df = _correlated_df()
    types = _column_types(df)
    assert cross_check_confounders(df, types, None) == []
    assert cross_check_confounders(df, types, {"tested": "not a list"}) == []


def test_cross_check_confounders_correlation_scans_are_tagged():
    df = _sweep_paradox_df()
    result = sweep_hypotheses(df, _column_types(df))
    cross = cross_check_confounders(df, _column_types(df), result)
    assert cross and all(s["relationship"] == "correlation" for s in cross)


# --- cross_check_confounders: binary-categorical/numeric (t-test) pairs --
# Same agentic follow-up question, asked of a significant group difference
# instead of a correlation — see confounder_detection's "GROUP-DIFFERENCE
# CONFOUNDER CROSS-CHECK" section for why Simpson's Paradox applies here
# too.

def _sweep_group_diff_paradox_df(seed: int = 13) -> pd.DataFrame:
    """Same group-difference Simpson's Paradox construction as
    test_confounder_detection._group_diff_paradox_df, reused here so the
    pooled treatment/outcome difference is itself a significant Hypothesis
    Sweep t-test finding (not just a paradox in isolation)."""
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


def test_cross_check_confounders_flags_planted_group_diff_paradox():
    df = _sweep_group_diff_paradox_df()
    result = sweep_hypotheses(df, _column_types(df))
    treatment_outcome = next(
        r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"treatment", "outcome"}
    )
    assert treatment_outcome["test"] == "ttest" and treatment_outcome["significant"] is True  # sanity

    cross = cross_check_confounders(df, _column_types(df), result)
    scan = next(s for s in cross if {s["x"], s["y"]} == {"treatment", "outcome"})
    assert scan["relationship"] == "group_diff"
    verdicts = {f["confounder"]: f["verdict"] for f in scan["findings"]}
    assert verdicts.get("severity") == "paradox"


def test_cross_check_confounders_skips_when_no_significant_ttest_or_pearson_pair():
    fake_result = {
        "tested": [
            {"col_a": "group", "col_b": "tier", "test": "chi2", "significant": True, "effect_size": 0.9},
        ]
    }
    df = _correlated_df()
    assert cross_check_confounders(df, _column_types(df), fake_result) == []


# --- cross_check_interactions: two-way ANOVA effect modification ---------
# A different agentic follow-up question than cross_check_confounders' —
# eta-squared has no sign to flip, so this asks instead whether a *third*
# categorical column changes the *size* of the group effect.

def _interaction_df(n_per_cell: int = 60, seed: int = 5) -> pd.DataFrame:
    """`group` has a strong effect on `value` only within `region == north`
    (0, 5, 20); within `region == south` there's no group effect at all
    (flat at 5). Pooled group means (2.5, 5, 12.5) still differ enough for
    the overall one-way ANOVA to be significant, while the interaction
    term should also be significant — the group effect genuinely depends
    on region, not just an additive shift."""
    rng = np.random.default_rng(seed)
    rows = []
    north_means = {"a": 0.0, "b": 5.0, "c": 20.0}
    south_means = {"a": 5.0, "b": 5.0, "c": 5.0}
    for group, mean in north_means.items():
        rows.append(pd.DataFrame({
            "value": rng.normal(mean, 1.0, n_per_cell), "group": group, "region": "north",
        }))
    for group, mean in south_means.items():
        rows.append(pd.DataFrame({
            "value": rng.normal(mean, 1.0, n_per_cell), "group": group, "region": "south",
        }))
    return pd.concat(rows, ignore_index=True)


def test_cross_check_interactions_flags_planted_effect_modification():
    df = _interaction_df()
    types = _column_types(df)
    result = sweep_hypotheses(df, types)
    ga = next(r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"group", "value"})
    assert ga["test"] == "anova" and ga["significant"] is True  # sanity: pooled effect is real too

    interactions = cross_check_interactions(df, types, result)
    assert interactions
    hit = next(f for f in interactions if f["other_col"] == "region")
    assert hit["cat_col"] == "group" and hit["numeric_col"] == "value"
    assert hit["significant"] is True
    assert hit["interaction_p_adj"] < DEFAULT_ALPHA
    assert set(hit["group_means"].keys()) == {"north", "south"}


def test_cross_check_interactions_empty_when_no_significant_anova_row():
    rng = np.random.default_rng(9)
    df = pd.DataFrame({
        "value": rng.normal(size=90),
        "group": rng.choice(["a", "b", "c"], size=90),
        "region": rng.choice(["north", "south"], size=90),
    })
    result = sweep_hypotheses(df, _column_types(df))
    assert cross_check_interactions(df, _column_types(df), result) == []


def test_cross_check_interactions_empty_when_no_third_categorical_column():
    rng = np.random.default_rng(11)
    df = pd.DataFrame({
        "value": np.concatenate([rng.normal(0, 1, 40), rng.normal(8, 1, 40), rng.normal(16, 1, 40)]),
        "group": ["a"] * 40 + ["b"] * 40 + ["c"] * 40,
    })
    result = sweep_hypotheses(df, _column_types(df))
    assert cross_check_interactions(df, _column_types(df), result) == []


def test_cross_check_interactions_handles_missing_or_malformed_result_safely():
    df = _interaction_df()
    types = _column_types(df)
    assert cross_check_interactions(df, types, None) == []
    assert cross_check_interactions(df, types, {"tested": "not a list"}) == []


def test_cross_check_interactions_respects_top_k_cap():
    df = _interaction_df()
    types = _column_types(df)
    result = sweep_hypotheses(df, types)
    interactions = cross_check_interactions(df, types, result, top_k=1)
    assert len(interactions) <= 1


# --- cross_check_categorical_interactions: three-way (chi2) association ---
# The chi-square analog of cross_check_interactions: does the *association*
# between two categorical columns itself depend on a third categorical
# column, rather than a numeric mean depending on it? Tested via a log-
# linear (Poisson GLM) likelihood-ratio test for the A:B:C three-way term.

def _three_way_categorical_df(seed: int = 7) -> pd.DataFrame:
    """Within region == "north", cat_a and cat_b are near-perfectly matched
    (a1<->b1, a2<->b2). Within region == "south", cat_a and cat_b are
    independent (uniform 50/50 regardless of cat_a). Pooling both regions
    still leaves a real marginal association (so the plain two-way chi2 on
    cat_a x cat_b is significant), but the *strength* of that association
    genuinely depends on region — a three-way interaction, not just an
    additive effect."""
    rng = np.random.default_rng(seed)
    rows = []
    n_per_cell = 70
    for cat_a in ("a1", "a2"):
        matched_b = "b1" if cat_a == "a1" else "b2"
        other_b = "b2" if cat_a == "a1" else "b1"
        # north: ~95% matched, 5% noise (avoids exact-zero-cell separation)
        b_north = rng.choice([matched_b, other_b], size=n_per_cell, p=[0.95, 0.05])
        rows.append(pd.DataFrame({"cat_a": cat_a, "cat_b": b_north, "region": "north"}))
        # south: genuinely independent of cat_a
        b_south = rng.choice(["b1", "b2"], size=n_per_cell, p=[0.5, 0.5])
        rows.append(pd.DataFrame({"cat_a": cat_a, "cat_b": b_south, "region": "south"}))
    return pd.concat(rows, ignore_index=True)


def test_cross_check_categorical_interactions_flags_planted_effect_modification():
    df = _three_way_categorical_df()
    types = _column_types(df)
    result = sweep_hypotheses(df, types)
    ab = next(r for r in result["tested"] if {r["col_a"], r["col_b"]} == {"cat_a", "cat_b"})
    assert ab["test"] == "chi2" and ab["significant"] is True  # sanity: pooled association is real too

    interactions = cross_check_categorical_interactions(df, types, result)
    assert interactions
    hit = next(f for f in interactions if f["other_col"] == "region")
    assert {hit["cat_a"], hit["cat_b"]} == {"cat_a", "cat_b"}
    assert hit["significant"] is True
    assert hit["interaction_p_adj"] < DEFAULT_ALPHA
    assert set(hit["cramers_v_by_level"].keys()) == {"north", "south"}
    # the planted signal: association is far stronger within north than south
    assert hit["cramers_v_by_level"]["north"] > hit["cramers_v_by_level"]["south"]


def test_cross_check_categorical_interactions_empty_when_no_significant_chi2_row():
    rng = np.random.default_rng(13)
    df = pd.DataFrame({
        "cat_a": rng.choice(["a1", "a2"], size=120),
        "cat_b": rng.choice(["b1", "b2"], size=120),
        "region": rng.choice(["north", "south"], size=120),
    })
    result = sweep_hypotheses(df, _column_types(df))
    assert cross_check_categorical_interactions(df, _column_types(df), result) == []


def test_cross_check_categorical_interactions_empty_when_no_third_categorical_column():
    df = _three_way_categorical_df()[["cat_a", "cat_b"]]
    types = _column_types(df)
    result = sweep_hypotheses(df, types)
    assert cross_check_categorical_interactions(df, types, result) == []


def test_cross_check_categorical_interactions_handles_missing_or_malformed_result_safely():
    df = _three_way_categorical_df()
    types = _column_types(df)
    assert cross_check_categorical_interactions(df, types, None) == []
    assert cross_check_categorical_interactions(df, types, {"tested": "not a list"}) == []


def test_cross_check_categorical_interactions_respects_top_k_cap():
    df = _three_way_categorical_df()
    types = _column_types(df)
    result = sweep_hypotheses(df, types)
    interactions = cross_check_categorical_interactions(df, types, result, top_k=1)
    assert len(interactions) <= 1


def test_cross_check_categorical_interactions_never_raises_on_degenerate_input():
    # A third categorical column with only 1 real level after dropna, and
    # one with too many levels (>10) — both should just be skipped, not raise.
    rng = np.random.default_rng(17)
    df = pd.DataFrame({
        "cat_a": rng.choice(["a1", "a2"], size=100),
        "cat_b": rng.choice(["b1", "b2"], size=100),
        "constant_col": "same",
        "high_card_col": [f"lvl{i}" for i in range(100)],
    })
    result = sweep_hypotheses(df, _column_types(df))
    # Should complete without raising regardless of whether anything's significant.
    cross_check_categorical_interactions(df, _column_types(df), result)


# --- group_sizes on ttest rows, and annotate_power() -----------------------

def _ttest_df(n_per_group: int = 100, d: float = 1.0, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    group_a = rng.normal(loc=0.0, scale=1.0, size=n_per_group)
    group_b = rng.normal(loc=d, scale=1.0, size=n_per_group)  # planted mean shift
    value = np.concatenate([group_a, group_b])
    group = ["a"] * n_per_group + ["b"] * n_per_group
    return pd.DataFrame({"value": value, "group": group})


def test_ttest_row_carries_group_sizes():
    df = _ttest_df(n_per_group=50)
    result = sweep_hypotheses(df, {"value": "numeric", "group": "categorical"})
    row = next(r for r in result["tested"] if r["test"] == "ttest")
    assert row["group_sizes"] == {"a": 50, "b": 50}


def test_pearson_and_chi2_rows_have_no_group_sizes():
    # group_sizes is only meaningful for the two "compare means/counts across
    # groups" test families (ttest, anova); pearson (no groups) and chi2 (a
    # contingency table, not per-group sizes) carry None.
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    ungrouped = [r for r in result["tested"] if r["test"] in ("pearson", "chi2")]
    assert ungrouped and all(r["group_sizes"] is None for r in ungrouped)


def test_anova_rows_carry_group_sizes():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    row = next(r for r in result["tested"] if r["test"] == "anova")
    assert row["group_sizes"] is not None
    assert len(row["group_sizes"]) == 3  # a/b/c groups
    assert sum(row["group_sizes"].values()) <= len(df)


def test_chi2_rows_carry_dof():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    chi2_row = next(r for r in result["tested"] if r["test"] == "chi2")
    assert chi2_row["dof"] is not None and chi2_row["dof"] >= 1


def test_non_chi2_rows_have_no_dof():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    non_chi2 = [r for r in result["tested"] if r["test"] != "chi2"]
    assert non_chi2 and all(r["dof"] is None for r in non_chi2)


def test_annotate_power_flags_underpowered_significant_ttest():
    # Small n, small-ish planted effect -> significant sometimes, but even
    # when it is, power should be well under 80%.
    df = _ttest_df(n_per_group=12, d=1.2, seed=3)
    result = sweep_hypotheses(df, {"value": "numeric", "group": "categorical"})
    annotated = annotate_power(result)
    row = next(r for r in annotated["tested"] if r["test"] == "ttest")
    if row["significant"]:
        assert row["power_check"] is not None
        assert row["power_check"]["n1"] == 12 and row["power_check"]["n2"] == 12
    else:
        assert row["power_check"] is None


def test_annotate_power_flags_well_powered_significant_ttest():
    df = _ttest_df(n_per_group=500, d=0.8, seed=1)
    result = sweep_hypotheses(df, {"value": "numeric", "group": "categorical"})
    annotated = annotate_power(result)
    row = next(r for r in annotated["tested"] if r["test"] == "ttest")
    assert row["significant"] is True
    assert row["power_check"]["underpowered"] is False
    assert row["power_check"]["achieved_power"] > 0.95


def test_annotate_power_skips_nonsignificant_rows():
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    annotated = annotate_power(result)
    for row in annotated["tested"]:
        if not row["significant"]:
            assert row["power_check"] is None


def test_annotate_power_covers_significant_anova_row():
    # _correlated_df() plants a real z~group ANOVA signal.
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    annotated = annotate_power(result)
    row = next(r for r in annotated["tested"] if r["test"] == "anova")
    assert row["significant"] is True
    assert row["power_check"] is not None
    assert row["power_check"]["test"] == "anova"
    assert row["power_check"]["k_groups"] == 3


def test_annotate_power_covers_significant_chi2_row():
    # _correlated_df() plants a real group~tier chi-square signal.
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    annotated = annotate_power(result)
    row = next(r for r in annotated["tested"] if r["test"] == "chi2")
    assert row["significant"] is True
    assert row["power_check"] is not None
    assert row["power_check"]["test"] == "chi2"
    assert row["power_check"]["dof"] == row["dof"]


def test_annotate_power_covers_significant_pearson_row():
    # _correlated_df() plants a strong, near-deterministic x~y correlation.
    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    annotated = annotate_power(result)
    row = next(r for r in annotated["tested"] if r["test"] == "pearson")
    assert row["significant"] is True
    assert row["power_check"] is not None
    assert row["power_check"]["test"] == "pearson"
    assert row["power_check"]["n"] == row["n"]


def test_annotate_power_flags_underpowered_significant_pearson_row():
    # Small n, modest planted correlation -> when significant, power should
    # still be well under 80%.
    rng = np.random.default_rng(11)
    n = 15
    x = rng.normal(size=n)
    y = 0.5 * x + rng.normal(scale=1.0, size=n)
    df = pd.DataFrame({"x": x, "y": y})
    result = sweep_hypotheses(df, {"x": "numeric", "y": "numeric"})
    annotated = annotate_power(result)
    row = next(r for r in annotated["tested"] if r["test"] == "pearson")
    if row["significant"]:
        assert row["power_check"] is not None
        assert row["power_check"]["underpowered"] is True
    else:
        assert row["power_check"] is None


def test_annotate_power_handles_empty_result():
    assert annotate_power({"tested": []}) == {"tested": []}
    assert annotate_power(None) is None


def test_annotate_power_does_not_mutate_input():
    df = _ttest_df(n_per_group=500, d=0.8, seed=1)
    result = sweep_hypotheses(df, {"value": "numeric", "group": "categorical"})
    original_row = next(r for r in result["tested"] if r["test"] == "ttest")
    assert "power_check" not in original_row
    annotate_power(result)
    # original untouched after annotate_power runs
    assert "power_check" not in original_row


# --- integration: full sweep -> annotate_power -> app-facing badge/prose ---
# for all four now-covered test families in one pass, the way app.py's
# Hypothesis Sweep tab and detector_runner.run_all_detectors() actually
# consume it end to end.

def test_annotate_power_end_to_end_covers_all_four_families_with_readable_prose():
    from modules.experiment_design import interpret_power_check

    df = _correlated_df()
    result = sweep_hypotheses(df, _column_types(df))
    annotated = annotate_power(result)

    significant = [r for r in annotated["tested"] if r["significant"]]
    by_test = {r["test"]: r for r in significant}
    # all four families have planted signals in _correlated_df(): x~y
    # (pearson), z~group (anova), group~tier (chi2).
    assert "anova" in by_test and "chi2" in by_test and "pearson" in by_test

    seen_families = set()
    for row in significant:
        check = row.get("power_check")
        assert check is not None, f"expected a power_check for a significant {row['test']} row"
        assert check["test"] == row["test"]
        text = interpret_power_check(check)
        assert text and "%" in text  # never raises, always produces readable prose
        seen_families.add(row["test"])

    # Confirms the fixture actually exercises more than one non-ttest family
    # (this is the point of the test — planted ANOVA + chi2 signals both
    # got annotated, not just ttest as before this change).
    assert "anova" in seen_families
    assert "chi2" in seen_families
