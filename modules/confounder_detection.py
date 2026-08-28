"""
Confounder / Simpson's Paradox Detection — automatically stress-tests the
strong correlations Auto-Insights already found by stratifying (categorical
confounders) or partialling out (numeric confounders) every other column in
the dataset, and flags when the relationship reverses sign or collapses
once you control for a third variable.

Why this exists: a pooled Pearson correlation can be actively misleading —
the textbook case is Simpson's Paradox, where a relationship that's
negative within every subgroup looks positive once the subgroups are
pooled together (or vice versa), because the subgroups differ on some
other variable that's driving both x and y. Auto-Insights (modules/
auto_insights.py) already surfaces "these two columns correlate" as a
finding; this module is the agentic follow-up question a careful analyst
asks next — "...but does that hold up once I control for group?" — run
automatically, not on request.

Everything here is deterministic (pandas/numpy correlation arithmetic) —
no Gemini call is required to detect a paradox. narrate_confounder_finding()
is an optional plain-English interpretation layer on top, following the
same call_gemini() plumbing (and graceful no-model fallback) as every other
narration helper in the app; callers are responsible for caching its result
per finding, same convention as modules.anomaly's narrate_* functions.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# "Worth reporting" thresholds. Kept as module constants (not buried magic
# numbers) since three different call paths reuse them and a future run
# tuning sensitivity should only need to touch one place.
_SIGN_FLIP_MIN_ADJUSTED_R = 0.2   # the adjusted relationship must itself be non-trivial to call it a "paradox"
_SIGN_FLIP_MIN_OVERALL_R = 0.05   # ...and the pooled number must be a real (non-noise) correlation too
_ATTENUATION_MIN_OVERALL_R = 0.3  # only worth flagging attenuation if the pooled correlation looked meaningful
_ATTENUATION_RATIO = 0.5          # adjusted_r shrinking below this fraction of overall_r counts as "attenuated"
_HETEROGENEITY_R_RANGE = 0.5      # per-group correlations spanning more than this counts as "attenuated" even if the weighted average looks stable


def _verdict_from_r_pair(overall_r: float, adjusted_r: float) -> str:
    """Shared paradox/attenuation/robust classification given a pooled
    correlation and its confounder-adjusted counterpart (weighted
    within-group correlation, or a partial correlation)."""
    if overall_r is None or adjusted_r is None or pd.isna(overall_r) or pd.isna(adjusted_r):
        return "robust"
    sign_flip = (overall_r > 0 > adjusted_r) or (overall_r < 0 < adjusted_r)
    if sign_flip and abs(adjusted_r) >= _SIGN_FLIP_MIN_ADJUSTED_R and abs(overall_r) >= _SIGN_FLIP_MIN_OVERALL_R:
        return "paradox"
    if abs(overall_r) >= _ATTENUATION_MIN_OVERALL_R and abs(adjusted_r) < _ATTENUATION_RATIO * abs(overall_r):
        return "attenuated"
    return "robust"


def stratified_correlation(
    df: pd.DataFrame, x: str, y: str, group_col: str, min_group_size: int = 3
) -> Optional[dict]:
    """Pearson correlation of (x, y) computed separately within each level
    of `group_col`, plus the n-weighted pooled-within-group average, and a
    verdict comparing that to the plain overall correlation.

    Returns None when there aren't at least two groups with >= min_group_size
    non-null, non-constant (x, y) pairs to compare — nothing to stratify.
    """
    sub = df[[x, y, group_col]].dropna()
    if sub.empty:
        return None

    per_group = []
    excluded = 0
    for name, gdf in sub.groupby(group_col, observed=True):
        if len(gdf) < min_group_size or gdf[x].std(ddof=0) == 0 or gdf[y].std(ddof=0) == 0:
            excluded += 1
            continue
        r = gdf[x].corr(gdf[y])
        if pd.isna(r):
            excluded += 1
            continue
        per_group.append({"group": name, "r": float(r), "n": int(len(gdf))})

    if len(per_group) < 2:
        return None

    total_n = sum(g["n"] for g in per_group)
    weighted_r = sum(g["r"] * g["n"] for g in per_group) / total_n
    overall_r = sub[x].corr(sub[y])
    if pd.isna(overall_r):
        return None

    r_range = max(g["r"] for g in per_group) - min(g["r"] for g in per_group)
    verdict = _verdict_from_r_pair(overall_r, weighted_r)
    if verdict == "robust" and r_range >= _HETEROGENEITY_R_RANGE:
        # Same sign, similar pooled magnitude, but the subgroups don't agree
        # with each other — the pooled number is an average of genuinely
        # different relationships, which is its own kind of misleading.
        verdict = "attenuated"

    return {
        "overall_r": float(overall_r),
        "weighted_within_group_r": float(weighted_r),
        "per_group": sorted(per_group, key=lambda g: -g["n"]),
        "verdict": verdict,
        "excluded_small_groups": excluded,
    }


def partial_correlation(df: pd.DataFrame, x: str, y: str, control: str) -> Optional[float]:
    """First-order partial correlation of x and y controlling for a third
    numeric column, via the standard closed-form:

        r_xy.z = (r_xy - r_xz * r_yz) / sqrt((1 - r_xz^2) * (1 - r_yz^2))

    Returns None when there's too little data, or x/control (or y/control)
    are collinear enough that the denominator is ~0 (the partial correlation
    is undefined — controlling for something that IS x, or a perfect linear
    function of it, leaves no independent variation to correlate with y).
    """
    sub = df[[x, y, control]].dropna()
    if len(sub) < 4:
        return None
    r_xy = sub[x].corr(sub[y])
    r_xz = sub[x].corr(sub[control])
    r_yz = sub[y].corr(sub[control])
    if any(pd.isna(v) for v in (r_xy, r_xz, r_yz)):
        return None
    denom = np.sqrt((1 - r_xz**2) * (1 - r_yz**2))
    if not np.isfinite(denom) or denom < 1e-6:
        return None
    partial = (r_xy - r_xz * r_yz) / denom
    return float(np.clip(partial, -1.0, 1.0))


def detect_confounders(
    df: pd.DataFrame,
    x: str,
    y: str,
    column_types: dict,
    candidates: Optional[list] = None,
    min_group_size: int = 3,
    max_categorical_groups: int = 15,
    min_numeric_rows: int = 10,
) -> list[dict]:
    """Check every other column in the dataset as a candidate confounder for
    the (x, y) relationship — stratification for categorical/text/boolean
    columns, partial correlation for numeric ones. Returns a list of finding
    dicts (possibly empty), ranked worst-first: paradox > attenuated >
    robust, and within a tier by how much the adjustment moved the number.

    Each finding: {confounder, type ("categorical"|"numeric"), overall_r,
    adjusted_r, verdict, detail}. `detail` is the per-group breakdown for
    categorical confounders, or {"n": ...} for numeric ones.
    """
    if df is None or df.empty or x not in df.columns or y not in df.columns:
        return []

    if candidates is None:
        candidates = [c for c in df.columns if c not in (x, y)]

    findings = []
    for col in candidates:
        if col not in df.columns or col not in column_types:
            continue
        ctype = column_types[col]
        if ctype in ("categorical", "text", "boolean"):
            nunique = df[col].nunique(dropna=True)
            if nunique < 2 or nunique > max_categorical_groups:
                continue
            result = stratified_correlation(df, x, y, col, min_group_size=min_group_size)
            if result is None:
                continue
            findings.append(
                {
                    "confounder": col,
                    "type": "categorical",
                    "overall_r": result["overall_r"],
                    "adjusted_r": result["weighted_within_group_r"],
                    "verdict": result["verdict"],
                    "detail": result["per_group"],
                }
            )
        elif ctype == "numeric":
            sub = df[[x, y, col]].dropna()
            if len(sub) < min_numeric_rows:
                continue
            overall_r = sub[x].corr(sub[y])
            if pd.isna(overall_r):
                continue
            partial_r = partial_correlation(sub, x, y, col)
            if partial_r is None:
                continue
            findings.append(
                {
                    "confounder": col,
                    "type": "numeric",
                    "overall_r": float(overall_r),
                    "adjusted_r": partial_r,
                    "verdict": _verdict_from_r_pair(overall_r, partial_r),
                    "detail": {"n": int(len(sub))},
                }
            )

    severity = {"paradox": 0, "attenuated": 1, "robust": 2}
    findings.sort(key=lambda f: (severity.get(f["verdict"], 3), -abs(f["overall_r"] - f["adjusted_r"])))
    return findings


def auto_scan_for_confounding(
    df: pd.DataFrame,
    column_types: dict,
    correlation_pairs: Optional[list] = None,
    top_k_pairs: int = 3,
    min_abs_r: float = 0.3,
    min_rows: int = 6,
) -> list[dict]:
    """The agentic entry point — no pair needs to be hinted. Picks the
    strongest numeric/numeric correlation pairs in the dataset (or reuses
    ones a caller already computed, e.g. Auto-Insights' correlation
    findings, via `correlation_pairs=[(a, b, r), ...]`) and runs
    detect_confounders on each, keeping only pairs where at least one
    candidate confounder came back non-"robust".

    Returns [{x, y, overall_r, findings: [...]}] — empty when nothing in
    the dataset is worth a second look, which is the common/healthy case.
    """
    if df is None or df.empty:
        return []
    numeric_cols = [c for c, t in column_types.items() if t == "numeric" and c in df.columns]
    if len(numeric_cols) < 2:
        return []

    if correlation_pairs is None:
        corr = df[numeric_cols].corr(numeric_only=True)
        pairs = []
        for i, a in enumerate(numeric_cols):
            for b in numeric_cols[i + 1 :]:
                r = corr.loc[a, b]
                if pd.isna(r) or abs(r) < min_abs_r:
                    continue
                pairs.append((a, b, float(r)))
        pairs.sort(key=lambda p: -abs(p[2]))
        correlation_pairs = pairs[:top_k_pairs]
    else:
        correlation_pairs = list(correlation_pairs)[:top_k_pairs]

    results = []
    for a, b, r in correlation_pairs:
        if a not in df.columns or b not in df.columns:
            continue
        sub = df[[a, b]].dropna()
        if len(sub) < min_rows:
            continue
        findings = [f for f in detect_confounders(df, a, b, column_types) if f["verdict"] != "robust"][:2]
        if findings:
            results.append({"x": a, "y": b, "overall_r": float(r), "findings": findings})
    return results


_VERDICT_LABELS = {
    "paradox": "a possible Simpson's Paradox",
    "attenuated": "a weakened or confounded relationship",
}


def narrate_confounder_finding(model, x: str, y: str, finding: dict) -> tuple[str, Optional[str]]:
    """Ask Gemini to explain one detect_confounders() finding in plain
    English. Returns (narration, error) — never raises. Callers should
    cache the result (e.g. keyed by (x, y, finding['confounder'])) rather
    than re-calling this on every rerun, same convention as the app's other
    narrate_* helpers.
    """
    if model is None:
        return "", "No Gemini model available for narration."

    from modules.ai_analyst import call_gemini

    verdict_label = _VERDICT_LABELS.get(finding["verdict"], "a checked relationship")
    if finding["type"] == "categorical":
        detail_lines = "\n".join(f"- {g['group']}: r = {g['r']:.2f} (n={g['n']})" for g in finding["detail"])
        detail_block = f"Within-group correlations when split by '{finding['confounder']}':\n{detail_lines}"
    else:
        detail_block = f"Partial correlation of '{x}' and '{y}' controlling for '{finding['confounder']}': {finding['adjusted_r']:.2f}"

    prompt = (
        f"A data analysis tool found {verdict_label} between '{x}' and '{y}'.\n"
        f"Overall (pooled) correlation: {finding['overall_r']:.2f}\n"
        f"{detail_block}\n\n"
        "In 2-4 plain-English sentences for a non-technical stakeholder, explain what this means "
        "and why the pooled correlation alone would be misleading here. Do not repeat raw numbers "
        "verbatim — focus on the practical interpretation and what to check next."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


# ═══════════════════════════════════════════════════════════════════════
# GROUP-DIFFERENCE CONFOUNDER CROSS-CHECK — the same paradox/attenuation
# question as stratified_correlation() above, asked of a *binary
# categorical* relationship (a significant Welch's t-test) instead of a
# numeric correlation. Simpson's Paradox isn't limited to correlations —
# "drug A beats drug B in every hospital individually, but drug B wins
# when the hospitals are pooled" is the textbook categorical version,
# caused the same way: the confounder (hospital) correlates with both
# which drug a patient got and how sick they were. Cohen's d is the
# natural effect-size analog of Pearson r here (same detect_confounders()
# thresholds turn out to transfer directly — 0.2/0.5/0.8 are literally
# Cohen's own small/medium/large conventions for d).
#
# Scope: x must have exactly two distinct groups (matching stats_lab.
# run_ttest()'s own scope — a signed effect needs exactly two groups to
# have a direction to flip). Only categorical/text/boolean columns are
# considered as candidate confounders (stratification); a numeric
# confounder would need binning to define "groups" first and isn't
# attempted here — the numeric-confounder path stays exclusive to
# detect_confounders()'s partial-correlation approach above.
# ═══════════════════════════════════════════════════════════════════════

def _cohens_d(group1: np.ndarray, group2: np.ndarray) -> Optional[float]:
    """Cohen's d for two independent samples — the exact formula
    stats_lab.run_ttest() uses (average, not pooled/weighted, of the two
    group variances), so a d computed here always matches what Hypothesis
    Sweep / Stats Lab would report for the same two groups."""
    if len(group1) < 2 or len(group2) < 2:
        return None
    pooled_std = np.sqrt((group1.std(ddof=1) ** 2 + group2.std(ddof=1) ** 2) / 2)
    if not np.isfinite(pooled_std) or pooled_std <= 0:
        return None
    return float((group1.mean() - group2.mean()) / pooled_std)


def stratified_mean_difference(
    df: pd.DataFrame, x_cat: str, y_num: str, group_col: str, min_group_size: int = 3
) -> Optional[dict]:
    """Cohen's d for y_num across x_cat's two groups, computed separately
    within each level of group_col, plus the n-weighted pooled-within-group
    average, and a verdict comparing that to the plain overall d — the
    group-difference analog of stratified_correlation().

    Only defined when x_cat has exactly 2 distinct non-null values. Returns
    None otherwise, or when there aren't at least two levels of group_col
    with >= min_group_size usable rows to compare — nothing to stratify.
    """
    sub = df[[x_cat, y_num, group_col]].dropna()
    if sub.empty:
        return None

    levels = sorted(sub[x_cat].unique(), key=str)
    if len(levels) != 2:
        return None
    label1, label2 = str(levels[0]), str(levels[1])

    def _d_and_diff(gdf: pd.DataFrame) -> Optional[tuple]:
        g1 = gdf.loc[gdf[x_cat] == levels[0], y_num]
        g2 = gdf.loc[gdf[x_cat] == levels[1], y_num]
        d = _cohens_d(g1.to_numpy(), g2.to_numpy())
        if d is None:
            return None
        return d, float(g1.mean() - g2.mean())

    overall = _d_and_diff(sub)
    if overall is None:
        return None
    overall_d, overall_diff = overall

    per_group = []
    excluded = 0
    for name, gdf in sub.groupby(group_col, observed=True):
        if len(gdf) < min_group_size:
            excluded += 1
            continue
        result = _d_and_diff(gdf)
        if result is None:
            excluded += 1
            continue
        d, diff = result
        per_group.append({"group": name, "d": d, "mean_diff": diff, "n": int(len(gdf))})

    if len(per_group) < 2:
        return None

    total_n = sum(g["n"] for g in per_group)
    weighted_d = sum(g["d"] * g["n"] for g in per_group) / total_n

    # Unlike stratified_correlation(), no extra "do the strata even agree
    # with each other" heterogeneity check on top of the sign-flip/
    # attenuation verdict: r is bounded to [-1, 1], so a fixed spread there
    # is a meaningful signal, but Cohen's d is unbounded and its per-stratum
    # sampling variance scales with 1/sqrt(n) — a fixed absolute d_range
    # threshold would flag ordinary sampling noise as "confounded" for any
    # large, genuine effect estimated from small strata. The sign-flip and
    # attenuation-ratio checks below are scale-relative and don't have this
    # problem.
    verdict = _verdict_from_r_pair(overall_d, weighted_d)

    return {
        "group_labels": (label1, label2),
        "overall_mean_diff": overall_diff,
        "overall_d": overall_d,
        "weighted_within_group_d": float(weighted_d),
        "per_group": sorted(per_group, key=lambda g: -g["n"]),
        "verdict": verdict,
        "excluded_small_groups": excluded,
    }


def detect_group_diff_confounders(
    df: pd.DataFrame,
    x_cat: str,
    y_num: str,
    column_types: dict,
    candidates: Optional[list] = None,
    min_group_size: int = 3,
    max_categorical_groups: int = 15,
) -> list[dict]:
    """Check every other categorical column as a candidate confounder for
    the (x_cat, y_num) group difference — the group-difference analog of
    detect_confounders(). Requires x_cat to have exactly 2 groups; numeric
    candidate confounders are out of scope (see module docstring above).

    Returns findings ranked worst-first (paradox > attenuated > robust),
    same family as detect_confounders() but with "metric": "cohens_d" and
    overall_d/adjusted_d in place of overall_r/adjusted_r.
    """
    if df is None or df.empty or x_cat not in df.columns or y_num not in df.columns:
        return []
    if column_types.get(x_cat) != "categorical" or column_types.get(y_num) != "numeric":
        return []
    if df[x_cat].nunique(dropna=True) != 2:
        return []

    if candidates is None:
        candidates = [c for c in df.columns if c not in (x_cat, y_num)]

    findings = []
    for col in candidates:
        if col not in df.columns or col not in column_types:
            continue
        if column_types[col] not in ("categorical", "text", "boolean"):
            continue
        nunique = df[col].nunique(dropna=True)
        if nunique < 2 or nunique > max_categorical_groups:
            continue
        result = stratified_mean_difference(df, x_cat, y_num, col, min_group_size=min_group_size)
        if result is None:
            continue
        findings.append(
            {
                "confounder": col,
                "type": "categorical",
                "metric": "cohens_d",
                "group_labels": result["group_labels"],
                "overall_d": result["overall_d"],
                "adjusted_d": result["weighted_within_group_d"],
                "verdict": result["verdict"],
                "detail": result["per_group"],
            }
        )

    severity = {"paradox": 0, "attenuated": 1, "robust": 2}
    findings.sort(key=lambda f: (severity.get(f["verdict"], 3), -abs(f["overall_d"] - f["adjusted_d"])))
    return findings


def auto_scan_for_group_diff_confounding(
    df: pd.DataFrame,
    column_types: dict,
    ttest_pairs: Optional[list] = None,
    top_k_pairs: int = 3,
    min_abs_d: float = 0.2,
    min_rows: int = 6,
) -> list[dict]:
    """The group-difference analog of auto_scan_for_confounding() — picks
    the strongest binary-categorical-vs-numeric mean differences in the
    dataset (or reuses ones a caller already computed, e.g. Hypothesis
    Sweep's significant t-test findings, via `ttest_pairs=[(cat_col,
    num_col, d), ...]` — that hinted d is passed straight through to the
    result, never recomputed) and runs detect_group_diff_confounders on
    each, keeping only pairs where at least one candidate confounder came
    back non-"robust".

    Returns [{x, y, overall_d, findings: [...]}] — empty when nothing in
    the dataset is worth a second look, the common/healthy case.
    """
    if df is None or df.empty:
        return []

    if ttest_pairs is None:
        cat_cols = [
            c for c, t in column_types.items()
            if t == "categorical" and c in df.columns and df[c].nunique(dropna=True) == 2
        ]
        numeric_cols = [c for c, t in column_types.items() if t == "numeric" and c in df.columns]
        if not cat_cols or not numeric_cols:
            return []
        pairs = []
        for cat_col in cat_cols:
            for num_col in numeric_cols:
                sub = df[[cat_col, num_col]].dropna()
                levels = sorted(sub[cat_col].unique(), key=str)
                if len(levels) != 2:
                    continue
                g1 = sub.loc[sub[cat_col] == levels[0], num_col].to_numpy()
                g2 = sub.loc[sub[cat_col] == levels[1], num_col].to_numpy()
                d = _cohens_d(g1, g2)
                if d is None or abs(d) < min_abs_d:
                    continue
                pairs.append((cat_col, num_col, float(d)))
        pairs.sort(key=lambda p: -abs(p[2]))
        ttest_pairs = pairs[:top_k_pairs]
    else:
        ttest_pairs = list(ttest_pairs)[:top_k_pairs]

    results = []
    for cat_col, num_col, d in ttest_pairs:
        if cat_col not in df.columns or num_col not in df.columns:
            continue
        sub = df[[cat_col, num_col]].dropna()
        if len(sub) < min_rows:
            continue
        findings = [
            f for f in detect_group_diff_confounders(df, cat_col, num_col, column_types)
            if f["verdict"] != "robust"
        ][:2]
        if findings:
            results.append({"x": cat_col, "y": num_col, "overall_d": float(d), "findings": findings})
    return results


def narrate_group_diff_confounder_finding(model, x_cat: str, y_num: str, finding: dict) -> tuple[str, Optional[str]]:
    """narrate_confounder_finding()'s counterpart for a group-difference
    (Cohen's d) finding instead of a correlation finding. Returns
    (narration, error) — never raises. Same caching contract: callers
    should cache the result, e.g. keyed by (x_cat, y_num, finding['confounder']).
    """
    if model is None:
        return "", "No Gemini model available for narration."

    from modules.ai_analyst import call_gemini

    verdict_label = _VERDICT_LABELS.get(finding["verdict"], "a checked relationship")
    label1, label2 = finding["group_labels"]
    detail_lines = "\n".join(
        f"- {g['group']}: {label1} minus {label2} = {g['mean_diff']:.2f} (Cohen's d = {g['d']:.2f}, n={g['n']})"
        for g in finding["detail"]
    )
    prompt = (
        f"A data analysis tool found {verdict_label} in how '{y_num}' differs between "
        f"'{x_cat}' groups ('{label1}' vs '{label2}').\n"
        f"Overall (pooled) effect size: Cohen's d = {finding['overall_d']:.2f}\n"
        f"Within-group effect sizes when split by '{finding['confounder']}':\n{detail_lines}\n\n"
        "In 2-4 plain-English sentences for a non-technical stakeholder, explain what this means "
        "and why the pooled difference alone would be misleading here. Do not repeat raw numbers "
        "verbatim — focus on the practical interpretation and what to check next."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None
