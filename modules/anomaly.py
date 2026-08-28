"""
Anomaly Detection — flags unusual rows via scikit-learn's IsolationForest
over the dataset's numeric columns, with a plain-English reason per flagged row.
"""

from __future__ import annotations

import hashlib
from typing import Optional

import numpy as np
import pandas as pd

try:
    from sklearn.cluster import DBSCAN
    from sklearn.ensemble import IsolationForest
    from sklearn.neighbors import LocalOutlierFactor
    from sklearn.preprocessing import StandardScaler
except ImportError:  # the app should still load even if the package isn't installed yet
    IsolationForest = None
    DBSCAN = None
    LocalOutlierFactor = None
    StandardScaler = None

MIN_ROWS_REQUIRED = 10

# Multi-method ensemble — three detectors with genuinely different
# assumptions, so a row every method agrees on is a much stronger signal
# than any single model's opinion:
#   isolation_forest — global isolation via random recursive splits (same
#                       model as find_anomalies() above)
#   lof               — local density: flags points whose neighborhood is
#                       much sparser than their neighbors' neighborhoods,
#                       catching local outliers a global method can miss
#   dbscan            — density-based clustering: anything that doesn't
#                       fall in any dense cluster (label -1) is an outlier
# Needs more rows than the single-method detector above (LOF/DBSCAN need
# enough neighbors to estimate local density meaningfully) and needs at
# least two numeric columns (a distance/density notion on a single axis
# degenerates to "how far from the median", which IsolationForest already
# covers on its own).
ENSEMBLE_METHODS = ("isolation_forest", "lof", "dbscan")
ENSEMBLE_MIN_ROWS = 20


def is_available() -> bool:
    """Whether scikit-learn is installed."""
    return IsolationForest is not None


def _reason_for_row(row: pd.Series, numeric_cols: list[str], medians: pd.Series) -> str:
    """Pick the numeric column with the largest relative deviation from its
    median as the human-readable reason a row was flagged.
    """
    best_col, best_ratio = None, 0.0
    for col in numeric_cols:
        median = medians[col]
        value = row[col]
        if pd.isna(value) or pd.isna(median) or median == 0:
            continue
        ratio = abs(value / median)
        if ratio > best_ratio:
            best_ratio, best_col = ratio, col

    if best_col is None:
        return "Unusual combination of values across numeric columns."
    direction = "above" if row[best_col] > medians[best_col] else "below"
    return f"{best_col} is {best_ratio:.1f}x {direction} the column median."


def find_anomalies(
    df: pd.DataFrame, column_types: dict[str, str], contamination: float = 0.05
) -> tuple[Optional[pd.DataFrame], Optional[str]]:
    """Run IsolationForest over numeric columns and return flagged rows with reasons.

    Returns (flagged_df, error). flagged_df carries an added 'anomaly_reason'
    column and may be empty (0 rows) if nothing was flagged — that's a valid
    "no anomalies found" result, not an error. error is set only when
    detection couldn't run at all (no numeric columns, missing dependency,
    or too few rows).
    """
    if IsolationForest is None:
        return None, "scikit-learn isn't installed. Run `pip install -r requirements.txt` and restart the app."

    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    if not numeric_cols:
        return None, "No numeric columns available for anomaly detection."

    if len(df) < MIN_ROWS_REQUIRED:
        return None, f"Not enough rows to reliably detect anomalies (need at least {MIN_ROWS_REQUIRED})."

    numeric_df = df[numeric_cols].copy()
    # IsolationForest can't handle NaNs — fill with the column median for
    # detection purposes only; the returned rows still carry their original values.
    numeric_df = numeric_df.fillna(numeric_df.median(numeric_only=True))
    numeric_df = numeric_df.dropna(axis=1, how="all")
    if numeric_df.shape[1] == 0:
        return None, "All numeric columns are entirely empty — nothing to analyze."

    model = IsolationForest(contamination=contamination, random_state=42)
    predictions = model.fit_predict(numeric_df)  # -1 = anomaly, 1 = normal

    flagged_idx = df.index[predictions == -1]
    if len(flagged_idx) == 0:
        return df.iloc[0:0].copy(), None  # empty frame — a valid "no anomalies" result

    medians = numeric_df.median()
    flagged = df.loc[flagged_idx].copy()
    flagged["anomaly_reason"] = [
        _reason_for_row(numeric_df.loc[idx], list(numeric_df.columns), medians) for idx in flagged_idx
    ]
    return flagged, None


def fingerprint_flagged(flagged: Optional[pd.DataFrame]) -> str:
    """A short, stable hash of a `find_anomalies()` result — used to cache
    the AI narration below so re-viewing the same flagged set (e.g. after
    switching tabs and back, with no re-detection) doesn't re-spend a
    Gemini call. Changes whenever the row count or the specific rows/reasons
    flagged change; index order doesn't matter (sorted first).
    """
    if flagged is None or flagged.empty:
        return "empty"
    reasons = flagged["anomaly_reason"] if "anomaly_reason" in flagged.columns else pd.Series(dtype=str)
    parts = sorted(f"{idx}:{reasons.get(idx, '')}" for idx in flagged.index)
    key = f"{len(flagged)}|" + "|".join(parts)
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


_NARRATION_PROMPT = (
    "You are a senior data analyst explaining an anomaly-detection result (from an "
    "IsolationForest model) to a stakeholder who isn't technical. {n} row(s) out of the "
    "dataset were flagged as unusual. Here are the most common reasons they were flagged, "
    "with counts:\n\n{reasons_text}\n\n"
    "In 3-4 sentences: explain in plain English what pattern of anomalies this suggests "
    "(e.g. data-entry errors vs. genuine rare events), and suggest one concrete next action "
    "(e.g. spot-check a few rows, exclude them, or investigate a specific column further). "
    "Do not simply restate the numbers back."
)


def narrate_anomalies(model, flagged: Optional[pd.DataFrame]) -> tuple[str, Optional[str]]:
    """Ask Gemini to turn a `find_anomalies()` result into a short plain-
    English explanation + suggested next action.

    Returns (narration, error). Callers should cache the result keyed by
    `fingerprint_flagged(flagged)` to avoid re-calling Gemini for a result
    the user has already seen narrated (this function itself makes no
    caching decision — it always calls Gemini when given a model and a
    non-empty flagged set, same as the rest of the app's narration
    helpers).
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if flagged is None or flagged.empty:
        return "No anomalies were flagged — nothing to narrate.", None
    if "anomaly_reason" not in flagged.columns:
        return "", "This result has no anomaly_reason column to narrate."

    from modules.ai_analyst import call_gemini

    reason_counts = flagged["anomaly_reason"].value_counts().head(8)
    reasons_text = "\n".join(f"- {reason} ({count} row(s))" for reason, count in reason_counts.items())
    prompt = _NARRATION_PROMPT.format(n=len(flagged), reasons_text=reasons_text)
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


# ═══════════════════════════════════════════════════════════════════════
# NARRATION FACT-CHECK — same "plausible but wrong number" safety net
# insight_verifier applies to Auto Analyst's findings (see that module's
# docstring) and hypothesis_sweep applies to its own narration, extended
# here to both anomaly narration helpers. Ground truth comes straight from
# the flagged DataFrame / methods_summary dict each narration was built
# from — no DataFrame recomputation needed, same reasoning as
# hypothesis_sweep.sweep_reference_numbers().
# ═══════════════════════════════════════════════════════════════════════
def anomaly_reference_numbers(flagged: Optional[pd.DataFrame]) -> set[float]:
    """Ground-truth numbers for narrate_anomalies()'s prose: the flagged
    row count and the per-reason counts narrate_anomalies() itself fed to
    Gemini. Never raises — a malformed frame just yields a smaller
    reference set, which verify_narration() degrades to "unverifiable"/
    "flagged" for, same non-blocking contract as insight_verifier.
    """
    numbers: set[float] = set()
    if flagged is None or flagged.empty:
        return numbers
    try:
        numbers.add(float(len(flagged)))
        if "anomaly_reason" in flagged.columns:
            for count in flagged["anomaly_reason"].value_counts().head(8):
                numbers.add(float(count))
    except (TypeError, ValueError, AttributeError):
        pass
    return numbers


def ensemble_reference_numbers(consensus: Optional[pd.DataFrame], methods_summary: Optional[dict]) -> set[float]:
    """Ground-truth numbers for narrate_ensemble_disagreement()'s prose:
    the consensus row count, each method's flagged_count/pct, and the
    full-agreement count — the exact numbers that function's prompt cites.
    Never raises.
    """
    numbers: set[float] = set()
    if consensus is None or consensus.empty or not methods_summary:
        return numbers
    try:
        numbers.add(float(len(consensus)))
        for stats in methods_summary.values():
            numbers.add(float(stats.get("flagged_count", 0)))
            numbers.add(float(stats.get("pct", 0)))
        if "consensus_count" in consensus.columns:
            numbers.add(float((consensus["consensus_count"] == len(ENSEMBLE_METHODS)).sum()))
    except (TypeError, ValueError, AttributeError):
        pass
    return numbers


def verify_narration(narration: str, reference_numbers: set[float]) -> dict:
    """Fact-check either anomaly narration helper's prose against its own
    pre-computed reference numbers. Reuses insight_verifier.verify_finding()
    — same {"status": "confirmed" | "flagged" | "unverifiable", ...}
    contract as every other verified surface in the app. Never raises.
    """
    from modules import insight_verifier

    try:
        return insight_verifier.verify_finding(narration or "", reference_numbers)
    except Exception:
        return {"status": "unverifiable", "checked": 0, "matched": 0}


# ═══════════════════════════════════════════════════════════════════════
# ANOMALY DRIVERS — IsolationForest (and the ensemble) say *which* rows are
# unusual but never *why*. This answers that: split the dataset into
# flagged vs. not-flagged and test every other column for a real
# difference between the two groups — Welch's t-test (Cohen's d) for
# numeric columns, chi-square test of independence (Cramer's V) for
# categorical/boolean ones. Reuses stats_lab.run_ttest()/run_chi2()
# directly rather than reimplementing the formulas, so a driver's effect
# size and "small/medium/large" label always match what Stats Lab would
# report for the same two columns — same reasoning as confounder_detection
# reusing stats_lab's Cohen's d convention.
# ═══════════════════════════════════════════════════════════════════════
MIN_ROWS_PER_SIDE = 2  # each of anomaly/normal needs >=2 rows for a test to be defined
SIGNIFICANCE_THRESHOLD = 0.05


def find_anomaly_drivers(
    df: pd.DataFrame,
    flagged: Optional[pd.DataFrame],
    column_types: dict[str, str],
    max_categorical_groups: int = 15,
    top_n: int = 8,
) -> list[dict]:
    """Rank every column (other than the flagged set itself) by how
    strongly it distinguishes anomalous rows from normal ones.

    Returns a list of finding dicts, ranked by |effect size| descending
    (ties broken by p-value), keeping only statistically significant
    drivers (p < 0.05) — same bar the rest of the app's hypothesis-testing
    surfaces use. Returns [] when there's nothing to compare (no anomalies,
    all rows flagged, too few rows on either side, or no columns test
    cleanly) rather than raising; this is exploratory ranking, not a
    required result.
    """
    if df is None or df.empty or flagged is None or flagged.empty:
        return []

    tagged = df.copy()
    tagged["_is_anomaly"] = tagged.index.isin(flagged.index)
    if tagged["_is_anomaly"].sum() < MIN_ROWS_PER_SIDE or (~tagged["_is_anomaly"]).sum() < MIN_ROWS_PER_SIDE:
        return []  # need at least 2 rows on each side for a test to mean anything

    from modules import stats_lab

    findings = []
    for col, ctype in column_types.items():
        if col not in tagged.columns or col == "anomaly_reason":
            continue
        try:
            if ctype == "numeric":
                result = stats_lab.run_ttest(tagged, col, "_is_anomaly")
                if "error" in result:
                    continue
                findings.append(
                    {
                        "column": col,
                        "type": "numeric",
                        "test": "ttest",
                        "effect_size": result["effect_size"],
                        "effect_size_name": "Cohen's d",
                        "effect_size_label": result["effect_size_label"],
                        "p_value": result["p_value"],
                        "anomaly_mean": result["means"].get("True"),
                        "normal_mean": result["means"].get("False"),
                    }
                )
            elif ctype in ("categorical", "boolean", "text"):
                nunique = tagged[col].nunique(dropna=True)
                if nunique < 2 or nunique > max_categorical_groups:
                    continue
                result = stats_lab.run_chi2(tagged, col, "_is_anomaly")
                if "error" in result:
                    continue
                findings.append(
                    {
                        "column": col,
                        "type": "categorical",
                        "test": "chi2",
                        "effect_size": result["effect_size"],
                        "effect_size_name": "Cramer's V",
                        "effect_size_label": result["effect_size_label"],
                        "p_value": result["p_value"],
                    }
                )
        except (ValueError, TypeError, KeyError, ZeroDivisionError):
            continue  # a single misbehaving column shouldn't sink the whole scan

    findings = [f for f in findings if f["p_value"] < SIGNIFICANCE_THRESHOLD]
    findings.sort(key=lambda f: (-abs(f["effect_size"]), f["p_value"]))
    return findings[:top_n]


def fingerprint_drivers(drivers: list[dict]) -> str:
    """Stable hash of a find_anomaly_drivers() result, for the same
    narration-caching purpose as fingerprint_flagged()."""
    if not drivers:
        return "empty"
    parts = [f"{d['column']}:{d['effect_size']:.4f}:{d['p_value']:.6f}" for d in drivers]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


_DRIVER_NARRATION_PROMPT = (
    "You are a senior data analyst explaining *why* certain rows were flagged as anomalies "
    "(not just that they were). Below are the columns that differ most between the {n_flagged} "
    "flagged row(s) and the rest of the dataset, ranked by effect size, each with a "
    "statistical test result:\n\n{drivers_text}\n\n"
    "In 3-4 sentences: explain in plain English what characterizes the anomalous rows (e.g. "
    "'these are mostly high-value transactions in region X'), and suggest one concrete next "
    "step. Do not simply restate the numbers back."
)


def narrate_anomaly_drivers(model, drivers: list[dict], n_flagged: int) -> tuple[str, Optional[str]]:
    """Ask Gemini to turn a find_anomaly_drivers() result into a short
    plain-English explanation of what characterizes the anomalies.

    Returns (narration, error), same contract as narrate_anomalies().
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if not drivers:
        return "No statistically significant drivers found — the flagged rows don't differ from the rest on any single column.", None

    lines = []
    for d in drivers:
        if d["type"] == "numeric":
            lines.append(
                f"- {d['column']} (numeric): anomaly mean {d['anomaly_mean']:.3g} vs. normal mean "
                f"{d['normal_mean']:.3g}, Cohen's d = {d['effect_size']:.2f} ({d['effect_size_label']}), "
                f"p = {d['p_value']:.4f}"
            )
        else:
            lines.append(
                f"- {d['column']} (categorical): Cramer's V = {d['effect_size']:.2f} "
                f"({d['effect_size_label']}), p = {d['p_value']:.4f}"
            )
    drivers_text = "\n".join(lines)
    prompt = _DRIVER_NARRATION_PROMPT.format(n_flagged=n_flagged, drivers_text=drivers_text)

    from modules.ai_analyst import call_gemini

    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


def driver_reference_numbers(drivers: list[dict]) -> set[float]:
    """Ground-truth numbers for narrate_anomaly_drivers()'s prose: each
    driver's effect size and p-value (rounded the same way the prompt
    renders them, so verify_narration's substring-ish matching lines up).
    Never raises.
    """
    numbers: set[float] = set()
    try:
        for d in drivers or []:
            numbers.add(round(float(d["effect_size"]), 2))
            numbers.add(round(float(d["p_value"]), 4))
            if d["type"] == "numeric":
                if d.get("anomaly_mean") is not None:
                    numbers.add(round(float(d["anomaly_mean"]), 3))
                if d.get("normal_mean") is not None:
                    numbers.add(round(float(d["normal_mean"]), 3))
    except (TypeError, ValueError, KeyError):
        pass
    return numbers


def _dbscan_eps(scaled: "np.ndarray", min_samples: int) -> float:
    """Heuristic eps for DBSCAN: the 90th percentile of each point's
    distance to its min_samples-th nearest neighbor (a simplified k-distance
    "elbow" — the full elbow-plot method needs a human eyeballing a curve,
    which has no place in an unattended pipeline call).
    """
    from sklearn.neighbors import NearestNeighbors

    n_neighbors = min(min_samples + 1, len(scaled))  # +1: a point is its own nearest neighbor
    nn = NearestNeighbors(n_neighbors=n_neighbors).fit(scaled)
    distances, _ = nn.kneighbors(scaled)
    kth_distances = distances[:, -1]
    eps = float(np.percentile(kth_distances, 90))
    return eps if eps > 0 else 0.5


def find_anomalies_ensemble(
    df: pd.DataFrame, column_types: dict[str, str], contamination: float = 0.05
) -> tuple[Optional[pd.DataFrame], Optional[dict], Optional[str]]:
    """Run three anomaly detectors with different assumptions (see
    ENSEMBLE_METHODS above) over the same numeric columns and return their
    consensus — the self-verifying-agent pattern applied to anomaly
    detection: instead of trusting one model's opinion, cross-check it
    against others built on different assumptions and surface how much
    they agree.

    Returns (consensus_df, methods_summary, error):
      consensus_df — union of every row flagged by at least one method,
        with 'consensus_count' (how many of the 3 methods flagged it,
        1-3) and 'anomaly_reason' (which methods + the largest numeric
        deviation, reusing _reason_for_row's logic), sorted by
        consensus_count descending. May be empty (valid "nothing flagged
        by any method" result).
      methods_summary — {method: {"flagged_count": int, "pct": float}}
        per-method counts, for the UI to show e.g. "LOF flagged 8 (13%),
        DBSCAN flagged 3 (5%)".
      error — set only when detection couldn't run at all.
    """
    if IsolationForest is None or DBSCAN is None or LocalOutlierFactor is None:
        return None, None, "scikit-learn isn't installed. Run `pip install -r requirements.txt` and restart the app."

    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    if len(numeric_cols) < 2:
        return None, None, "Ensemble mode needs at least 2 numeric columns (LOF/DBSCAN rely on distance between them)."

    if len(df) < ENSEMBLE_MIN_ROWS:
        return None, None, f"Not enough rows for the ensemble detector (need at least {ENSEMBLE_MIN_ROWS})."

    numeric_df = df[numeric_cols].copy()
    numeric_df = numeric_df.fillna(numeric_df.median(numeric_only=True))
    numeric_df = numeric_df.dropna(axis=1, how="all")
    if numeric_df.shape[1] < 2:
        return None, None, "Fewer than 2 usable numeric columns after dropping fully-empty ones."

    scaled = StandardScaler().fit_transform(numeric_df.values)
    n = len(numeric_df)
    min_samples = max(5, round(0.02 * n))

    flags: dict[str, "np.ndarray"] = {}

    iso = IsolationForest(contamination=contamination, random_state=42)
    flags["isolation_forest"] = iso.fit_predict(numeric_df) == -1

    lof = LocalOutlierFactor(n_neighbors=min(min_samples, n - 1), contamination=contamination)
    flags["lof"] = lof.fit_predict(scaled) == -1

    eps = _dbscan_eps(scaled, min_samples)
    dbscan_labels = DBSCAN(eps=eps, min_samples=min_samples).fit_predict(scaled)
    flags["dbscan"] = dbscan_labels == -1

    methods_summary = {
        method: {"flagged_count": int(mask.sum()), "pct": round(100 * mask.sum() / n, 2)}
        for method, mask in flags.items()
    }

    consensus_count = np.zeros(n, dtype=int)
    for mask in flags.values():
        consensus_count += mask.astype(int)

    flagged_positions = np.where(consensus_count > 0)[0]
    if len(flagged_positions) == 0:
        return df.iloc[0:0].copy(), methods_summary, None

    medians = numeric_df.median()
    flagged_idx = numeric_df.index[flagged_positions]
    consensus = df.loc[flagged_idx].copy()
    consensus["consensus_count"] = consensus_count[flagged_positions]

    reasons = []
    for pos, idx in zip(flagged_positions, flagged_idx):
        flagged_by = [m for m, mask in flags.items() if mask[pos]]
        base_reason = _reason_for_row(numeric_df.loc[idx], list(numeric_df.columns), medians)
        method_label = ", ".join(m.replace("_", " ") for m in flagged_by)
        reasons.append(f"Flagged by {len(flagged_by)}/{len(ENSEMBLE_METHODS)} methods ({method_label}). {base_reason}")
    consensus["anomaly_reason"] = reasons

    consensus = consensus.sort_values("consensus_count", ascending=False)
    return consensus, methods_summary, None


_ENSEMBLE_NARRATION_PROMPT = (
    "You are a senior data analyst explaining a multi-method anomaly-detection result to a "
    "stakeholder who isn't technical. Three different anomaly detectors were run over the same "
    "data, each with different assumptions: Isolation Forest (global isolation via random "
    "splits), LOF/Local Outlier Factor (local density — flags points in sparser neighborhoods "
    "than their neighbors), and DBSCAN (density-based clustering — anything outside a dense "
    "cluster). Here's how many rows each method flagged, out of {n_rows} total rows:\n\n"
    "{summary_text}\n\n"
    "{agreement_text}\n\n"
    "In 3-4 sentences: explain in plain English what the level of agreement or disagreement "
    "between the methods suggests about the kind of anomalies present (e.g. a few extreme "
    "global outliers vs. local pockets of unusual density), and suggest one concrete next "
    "action. Do not simply restate the numbers back."
)


def narrate_ensemble_disagreement(model, consensus: Optional[pd.DataFrame], methods_summary: Optional[dict]) -> tuple[str, Optional[str]]:
    """Ask Gemini to explain what the ensemble's agreement/disagreement
    pattern suggests — the interpretive step of the self-verifying-agent
    pattern: the detection itself stays deterministic and auditable
    (three independent sklearn models), Gemini's only job is turning
    "IsoForest flagged 12, LOF flagged 8, only 3 rows overlap" into an
    explanation a stakeholder can act on.

    Returns (narration, error). Callers should cache by
    fingerprint_flagged(consensus) same as narrate_anomalies().
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if consensus is None or consensus.empty or not methods_summary:
        return "No anomalies were flagged by any method — nothing to narrate.", None

    n_rows = len(consensus)
    summary_text = "\n".join(
        f"- {method.replace('_', ' ').title()}: {stats['flagged_count']} row(s) ({stats['pct']}%)"
        for method, stats in methods_summary.items()
    )
    full_agreement = int((consensus["consensus_count"] == len(ENSEMBLE_METHODS)).sum()) if "consensus_count" in consensus.columns else 0
    agreement_text = (
        f"{full_agreement} row(s) were flagged by all {len(ENSEMBLE_METHODS)} methods "
        f"(strong consensus); the rest were flagged by only 1-2 methods."
    )
    prompt = _ENSEMBLE_NARRATION_PROMPT.format(n_rows=n_rows, summary_text=summary_text, agreement_text=agreement_text)

    from modules.ai_analyst import call_gemini

    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None
