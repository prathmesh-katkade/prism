"""
Causal Effect Estimation via Propensity Score Matching — the natural next
question after modules/confounder_detection.py flags that a correlation is
confounded: "okay, but if I actually correct for the confounder, what's the
real effect?" Confounder detection only diagnoses the problem (stratified /
partial correlation); this module treats it, using the standard
observational-causal-inference recipe:

  1. Fit a propensity score P(treatment=1 | covariates) via logistic
     regression — how likely each unit was to receive treatment, given what
     we can observe about it.
  2. Greedily match each treated unit to its nearest untreated unit in
     propensity-score-logit space, within a caliper, without replacement.
  3. Check covariate balance (standardized mean difference) before and
     after matching — matching "worked" only if it made the treated and
     control groups look statistically similar on the covariates.
  4. Estimate the Average Treatment Effect on the Treated (ATT) as the mean
     outcome difference within matched pairs, with a bootstrap confidence
     interval.

This is deliberately the textbook, auditable version (logistic-regression
propensity + nearest-neighbor caliper matching), not a black-box causal ML
library — every intermediate number (propensity scores, SMDs, matched pairs)
is inspectable, which is the point for a portfolio piece: the interview
question isn't "did you call a causal inference library" but "do you
understand why naive group comparison is biased and how matching fixes it."

Detection/estimation here is 100% deterministic (numpy/pandas/sklearn) — no
Gemini call is required. narrate_causal_effect() is an optional plain-
English interpretation layer on top of an already-computed result, following
the same call_gemini() plumbing and graceful no-model fallback as every
other narrate_* helper in the app (see modules.confounder_detection,
modules.anomaly). Callers are responsible for caching its result, same
convention as those.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# Below this many units in either arm, propensity matching is too noisy to
# trust (the whole point of matching is finding "similar enough" units, and
# there just aren't enough candidates to match against with under ~5 per side).
_MIN_GROUP_SIZE = 5
# A |SMD| under this is the conventional "well balanced" threshold in the
# causal inference literature (Austin, 2011 and others use 0.1).
_BALANCE_SMD_THRESHOLD = 0.1
# Below this fraction of treated units finding a match, the ATT no longer
# represents "the treated group" — flag it rather than silently reporting a
# number that only covers a minority of who was actually treated.
_LOW_MATCH_RATE_THRESHOLD = 0.5


def standardized_mean_diff(treated: pd.Series, control: pd.Series) -> Optional[float]:
    """Standardized mean difference: (mean_treated - mean_control) / pooled_sd.
    The standard covariate-balance metric in the matching literature — unlike
    a raw mean difference it's comparable across covariates with different
    scales. Returns None if there's no variance to standardize by (both
    groups constant) or either group is empty.
    """
    treated = pd.Series(treated).dropna()
    control = pd.Series(control).dropna()
    if len(treated) == 0 or len(control) == 0:
        return None
    var_t, var_c = treated.var(ddof=1), control.var(ddof=1)
    pooled_sd = np.sqrt(((var_t if pd.notna(var_t) else 0) + (var_c if pd.notna(var_c) else 0)) / 2)
    if not np.isfinite(pooled_sd) or pooled_sd < 1e-12:
        return None
    return float((treated.mean() - control.mean()) / pooled_sd)


def fit_propensity_scores(X: np.ndarray, treated: np.ndarray) -> Optional[np.ndarray]:
    """Logistic regression P(treated=1 | X), covariates standardized first
    for solver stability. Returns None (rather than raising) if sklearn
    isn't importable or the fit fails outright (e.g. degenerate input) —
    callers treat that as "can't estimate propensity, skip."
    """
    try:
        from sklearn.linear_model import LogisticRegression
        from sklearn.preprocessing import StandardScaler
    except ImportError:
        return None

    try:
        X_scaled = StandardScaler().fit_transform(X)
        model = LogisticRegression(max_iter=1000)
        model.fit(X_scaled, treated)
        scores = model.predict_proba(X_scaled)[:, 1]
    except Exception:
        return None
    return np.clip(scores, 1e-6, 1 - 1e-6)


def nearest_neighbor_match(logit_ps: np.ndarray, treated: np.ndarray, caliper: float = 0.2) -> list[tuple[int, int]]:
    """Greedy 1:1 nearest-neighbor matching without replacement in
    logit-propensity-score space. Each treated unit (processed in order of
    how "typical" its propensity score is — closest to the control median
    first, the classic order for greedy matching since extreme-propensity
    treated units are hardest to match and benefit from a full control pool)
    is paired with its nearest still-available control within
    `caliper * std(logit_ps)`.

    Returns a list of (treated_index, control_index) positional-index pairs
    (into the arrays passed in, not the original DataFrame index).
    """
    treated_idx = np.where(treated)[0]
    control_idx = np.where(~treated)[0]
    if len(treated_idx) == 0 or len(control_idx) == 0:
        return []

    sd = np.std(logit_ps, ddof=1) if len(logit_ps) > 1 else 0.0
    max_dist = caliper * sd if sd > 0 else caliper

    control_median = np.median(logit_ps[control_idx])
    order = np.argsort(np.abs(logit_ps[treated_idx] - control_median))
    treated_idx = treated_idx[order]

    available = set(control_idx.tolist())
    pairs = []
    for t in treated_idx:
        if not available:
            break
        avail_arr = np.array(sorted(available))
        dists = np.abs(logit_ps[avail_arr] - logit_ps[t])
        best_pos = np.argmin(dists)
        if dists[best_pos] <= max_dist:
            c = int(avail_arr[best_pos])
            pairs.append((int(t), c))
            available.discard(c)
    return pairs


def _bootstrap_ci(diffs: np.ndarray, n_bootstrap: int, random_state: int) -> tuple[float, float]:
    if len(diffs) == 0:
        return float("nan"), float("nan")
    rng = np.random.default_rng(random_state)
    n = len(diffs)
    means = np.empty(n_bootstrap)
    for i in range(n_bootstrap):
        sample = diffs[rng.integers(0, n, size=n)]
        means[i] = sample.mean()
    return float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))


def estimate_causal_effect(
    df: pd.DataFrame,
    treatment_col: str,
    treated_value,
    outcome_col: str,
    covariates: Optional[list] = None,
    column_types: Optional[dict] = None,
    caliper: float = 0.2,
    n_bootstrap: int = 500,
    random_state: int = 42,
    min_group_size: int = _MIN_GROUP_SIZE,
) -> dict:
    """Estimate the Average Treatment Effect on the Treated (ATT) of
    `treatment_col == treated_value` on `outcome_col`, adjusting for
    `covariates` (numeric columns) via propensity score matching.

    Returns a dict, always with an "ok" key:
      ok=False: {"ok": False, "error": "<why>"}
      ok=True:  {"ok": True, "att", "ci_low", "ci_high", "n_treated",
                 "n_control", "n_matched", "match_rate", "treatment_col",
                 "treated_value", "control_value", "outcome_col",
                 "balance_before": [{"covariate", "smd"}, ...],
                 "balance_after": [...], "warnings": [str, ...]}

    Never raises — every failure path (non-binary treatment, non-numeric
    outcome, too few units, no usable covariates, a degenerate propensity
    fit, zero matches within the caliper) is reported as ok=False with a
    plain-English reason instead.
    """
    if df is None or df.empty:
        return {"ok": False, "error": "No data to analyze."}
    if treatment_col not in df.columns or outcome_col not in df.columns:
        return {"ok": False, "error": "Treatment or outcome column not found in the dataset."}
    if not pd.api.types.is_numeric_dtype(df[outcome_col]):
        return {"ok": False, "error": f"Outcome column '{outcome_col}' must be numeric."}

    uniques = df[treatment_col].dropna().unique().tolist()
    if len(uniques) != 2:
        return {
            "ok": False,
            "error": f"Treatment column '{treatment_col}' must have exactly 2 groups (found {len(uniques)}).",
        }
    if treated_value not in uniques:
        return {"ok": False, "error": f"'{treated_value}' is not a value of '{treatment_col}'."}
    control_value = next(v for v in uniques if v != treated_value)

    if covariates is None:
        if column_types:
            covariates = [
                c for c, t in column_types.items()
                if t == "numeric" and c in df.columns and c not in (treatment_col, outcome_col)
            ]
        else:
            covariates = [
                c for c in df.columns
                if c not in (treatment_col, outcome_col) and pd.api.types.is_numeric_dtype(df[c])
            ]
    covariates = [c for c in covariates if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    if not covariates:
        return {"ok": False, "error": "No numeric covariates available to match on."}

    sub = df[[treatment_col, outcome_col] + covariates].dropna().copy()
    sub = sub[sub[treatment_col].isin([treated_value, control_value])]
    treated_mask = (sub[treatment_col] == treated_value).to_numpy()
    n_treated, n_control = int(treated_mask.sum()), int((~treated_mask).sum())
    if n_treated < min_group_size or n_control < min_group_size:
        return {
            "ok": False,
            "error": (
                f"Not enough data after dropping missing values: {n_treated} treated, "
                f"{n_control} control (need >= {min_group_size} each)."
            ),
        }

    X = sub[covariates].to_numpy(dtype=float)
    propensity = fit_propensity_scores(X, treated_mask.astype(int))
    if propensity is None:
        return {"ok": False, "error": "Could not fit a propensity model on these covariates."}
    logit_ps = np.log(propensity / (1 - propensity))

    balance_before = [
        {"covariate": c, "smd": standardized_mean_diff(sub.loc[treated_mask, c], sub.loc[~treated_mask, c])}
        for c in covariates
    ]

    pairs = nearest_neighbor_match(logit_ps, treated_mask, caliper=caliper)
    n_matched = len(pairs)
    if n_matched == 0:
        return {
            "ok": False,
            "error": "No treated units found a control match within the caliper — try widening it or check group overlap.",
        }

    treated_pos = [p[0] for p in pairs]
    control_pos = [p[1] for p in pairs]
    outcome_arr = sub[outcome_col].to_numpy(dtype=float)
    diffs = outcome_arr[treated_pos] - outcome_arr[control_pos]
    att = float(diffs.mean())
    ci_low, ci_high = _bootstrap_ci(diffs, n_bootstrap=n_bootstrap, random_state=random_state)

    matched_treated_vals = sub[covariates].to_numpy()[treated_pos]
    matched_control_vals = sub[covariates].to_numpy()[control_pos]
    balance_after = [
        {
            "covariate": c,
            "smd": standardized_mean_diff(
                pd.Series(matched_treated_vals[:, i]), pd.Series(matched_control_vals[:, i])
            ),
        }
        for i, c in enumerate(covariates)
    ]

    match_rate = n_matched / n_treated
    warnings = []
    if match_rate < _LOW_MATCH_RATE_THRESHOLD:
        warnings.append(
            f"Only {match_rate:.0%} of treated units found a control match within the caliper — "
            "this estimate may not generalize to the full treated group."
        )
    unbalanced_after = [b["covariate"] for b in balance_after if b["smd"] is not None and abs(b["smd"]) > _BALANCE_SMD_THRESHOLD]
    if unbalanced_after:
        warnings.append(
            f"Still imbalanced after matching (|SMD| > {_BALANCE_SMD_THRESHOLD}): {', '.join(unbalanced_after)} — "
            "treat the estimate with caution."
        )
    if n_matched < 10:
        warnings.append(f"Very few matched pairs (n={n_matched}) — the confidence interval will be wide/unstable.")

    return {
        "ok": True,
        "att": att,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "n_treated": n_treated,
        "n_control": n_control,
        "n_matched": n_matched,
        "match_rate": match_rate,
        "treatment_col": treatment_col,
        "treated_value": treated_value,
        "control_value": control_value,
        "outcome_col": outcome_col,
        "covariates": covariates,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "warnings": warnings,
    }


def estimate_cate_by_subgroup(
    df: pd.DataFrame,
    treatment_col: str,
    treated_value,
    outcome_col: str,
    subgroup_col: str,
    covariates: Optional[list] = None,
    column_types: Optional[dict] = None,
    caliper: float = 0.2,
    n_bootstrap: int = 200,
    random_state: int = 42,
    min_group_size: int = _MIN_GROUP_SIZE,
) -> dict:
    """Conditional Average Treatment Effect (CATE) by subgroup — the natural
    follow-on question after estimate_causal_effect() gives one pooled ATT:
    "does the effect actually vary depending on who you look at?" A single
    pooled number can mask a treatment that helps one segment and hurts
    another (a "qualitative interaction" — the treatment-effect analogue of
    Simpson's Paradox), which is exactly the kind of finding a one-size-
    fits-all rollout decision would miss.

    Re-runs estimate_causal_effect() once on the full data (the pooled
    estimate) and once per level of `subgroup_col` (T-learner style: same
    matching procedure, just restricted to each subgroup's rows), then
    compares. Never raises — every subgroup that can't support its own
    propensity match (too few units, degenerate fit, no matches within the
    caliper) is reported as its own ok=False entry rather than aborting the
    whole comparison, so one thin subgroup doesn't hide the others' results.

    Returns a dict, always with an "ok" key:
      ok=False: {"ok": False, "error": "<why>"}  — subgroup_col invalid, or
                 the pooled estimate itself failed (same failure reasons as
                 estimate_causal_effect).
      ok=True:  {"ok": True, "pooled": <estimate_causal_effect result>,
                 "subgroup_col", "subgroups": [{"level", "ok", ...} per
                 level — either the full estimate_causal_effect fields plus
                 "level", or {"level", "ok": False, "error"}],
                 "sign_reversal": bool, "heterogeneity_detected": bool,
                 "warnings": [str, ...]}

      sign_reversal=True means at least one subgroup's ATT point estimate
      has the opposite sign from the pooled ATT — the strongest, most
      actionable form of heterogeneity. heterogeneity_detected=True means
      at least one subgroup's 95% CI doesn't overlap the pooled estimate's
      95% CI (real statistical evidence the effect differs by segment, not
      just a milder form of "the numbers aren't identical").
    """
    if df is None or df.empty:
        return {"ok": False, "error": "No data to analyze."}
    if subgroup_col not in df.columns:
        return {"ok": False, "error": f"Subgroup column '{subgroup_col}' not found in the dataset."}

    pooled = estimate_causal_effect(
        df, treatment_col, treated_value, outcome_col,
        covariates=covariates, column_types=column_types, caliper=caliper,
        n_bootstrap=n_bootstrap, random_state=random_state, min_group_size=min_group_size,
    )
    if not pooled["ok"]:
        return {"ok": False, "error": pooled["error"]}
    # Reuse whichever covariates the pooled run actually settled on (handles
    # the covariates=None / column_types auto-selection path) so every
    # subgroup is matched on the identical covariate set as the pooled run.
    covariates = pooled["covariates"]

    levels = sorted(df[subgroup_col].dropna().unique().tolist(), key=str)
    subgroups = []
    for level in levels:
        sub_df = df[df[subgroup_col] == level]
        sub_result = estimate_causal_effect(
            sub_df, treatment_col, treated_value, outcome_col,
            covariates=covariates, caliper=caliper, n_bootstrap=n_bootstrap,
            random_state=random_state, min_group_size=min_group_size,
        )
        sub_result["level"] = level
        subgroups.append(sub_result)

    usable = [s for s in subgroups if s["ok"]]
    warnings = []
    skipped = [s["level"] for s in subgroups if not s["ok"]]
    if skipped:
        warnings.append(
            f"{len(skipped)} subgroup(s) couldn't support their own estimate (too few units or no "
            f"match found): {', '.join(str(label) for label in skipped)}."
        )

    if len(usable) < 2:
        warnings.append("Not enough subgroups with a usable estimate to compare heterogeneity.")
        return {
            "ok": True,
            "pooled": pooled,
            "subgroup_col": subgroup_col,
            "subgroups": subgroups,
            "sign_reversal": False,
            "heterogeneity_detected": False,
            "warnings": warnings,
        }

    pooled_sign = np.sign(pooled["att"])
    sign_reversal = any(np.sign(s["att"]) != 0 and np.sign(s["att"]) != pooled_sign for s in usable if pooled_sign != 0)
    heterogeneity_detected = sign_reversal or any(
        s["ci_high"] < pooled["ci_low"] or s["ci_low"] > pooled["ci_high"] for s in usable
    )

    return {
        "ok": True,
        "pooled": pooled,
        "subgroup_col": subgroup_col,
        "subgroups": subgroups,
        "sign_reversal": sign_reversal,
        "heterogeneity_detected": heterogeneity_detected,
        "warnings": warnings,
    }


def narrate_cate_heterogeneity(model, result: dict) -> tuple[str, Optional[str]]:
    """Ask Gemini to explain one estimate_cate_by_subgroup() result in plain
    English. Returns (narration, error) — never raises. Same caching
    convention as narrate_causal_effect: callers should cache the result
    rather than re-calling this on every rerun.
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if not result.get("ok"):
        return "", "No result to narrate."

    from modules.ai_analyst import call_gemini

    usable = [s for s in result["subgroups"] if s["ok"]]
    lines = [f"  - {s['level']}: ATT {s['att']:.3g}, 95% CI [{s['ci_low']:.3g}, {s['ci_high']:.3g}]" for s in usable]
    pooled = result["pooled"]
    prompt = (
        f"A causal analysis estimated the pooled effect of '{pooled['treatment_col']} = {pooled['treated_value']}' "
        f"on '{pooled['outcome_col']}' as ATT {pooled['att']:.3g} (95% CI [{pooled['ci_low']:.3g}, {pooled['ci_high']:.3g}]), "
        f"then re-estimated it separately within each level of '{result['subgroup_col']}':\n" + "\n".join(lines) +
        f"\nSign reversal across subgroups: {result['sign_reversal']}. "
        f"Statistically meaningful heterogeneity (non-overlapping CIs): {result['heterogeneity_detected']}.\n\n"
        "In 2-4 plain-English sentences for a non-technical stakeholder, explain whether the effect is "
        "consistent across these subgroups or varies meaningfully, and what that implies for a rollout "
        "decision (e.g. targeting vs. a blanket rollout). Do not repeat every raw number verbatim."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


def narrate_causal_effect(model, result: dict) -> tuple[str, Optional[str]]:
    """Ask Gemini to explain one estimate_causal_effect() result in plain
    English. Returns (narration, error) — never raises. Callers should cache
    the result rather than re-calling this on every rerun, same convention
    as modules.confounder_detection.narrate_confounder_finding.
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if not result.get("ok"):
        return "", "No result to narrate."

    from modules.ai_analyst import call_gemini

    warn_block = ("\nCaveats: " + "; ".join(result["warnings"])) if result["warnings"] else ""
    prompt = (
        f"A propensity-score-matching causal analysis estimated the effect of "
        f"'{result['treatment_col']} = {result['treated_value']}' (vs. '{result['control_value']}') "
        f"on '{result['outcome_col']}'.\n"
        f"Estimated effect (ATT): {result['att']:.3g}, 95% CI [{result['ci_low']:.3g}, {result['ci_high']:.3g}]\n"
        f"Matched {result['n_matched']} of {result['n_treated']} treated units "
        f"({result['match_rate']:.0%}) to similar control units on: {', '.join(result['covariates'])}."
        f"{warn_block}\n\n"
        "In 2-4 plain-English sentences for a non-technical stakeholder, explain what this estimate means, "
        "whether the confidence interval suggests the effect is real, and any caveat that matters. "
        "Do not repeat the raw numbers verbatim — focus on practical interpretation."
    )
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None
