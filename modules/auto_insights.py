"""
Auto-Insight Engine — proactive statistical insights surfaced on upload.

Scans the dataset for noteworthy patterns without any user prompting:
distribution anomalies (high skewness/kurtosis), strong correlations,
outlier prevalence, missing-value patterns, high-cardinality warnings,
potential date columns, constant/near-constant columns, and class
imbalance in likely target columns.

Each insight carries a severity (high/medium/low), a plain-English
explanation, and a category tag. An optional Gemini narration pass turns
the raw findings into a paragraph-style executive brief.

Designed to run in <2 seconds on a 50K-row dataset with 30 columns — all
computation is vectorized pandas/numpy, no ML models, no iterative fits.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

# ── Thresholds (tuned for real-world Kaggle datasets) ──────────────────────

SKEW_THRESHOLD = 2.0          # |skewness| above this → "highly skewed"
KURTOSIS_THRESHOLD = 7.0      # excess kurtosis above this → "heavy-tailed"
CORR_STRONG_THRESHOLD = 0.85  # |r| above this → "strongly correlated pair"
CORR_MODERATE_THRESHOLD = 0.6 # |r| above this → "moderately correlated"
MISSING_HIGH_PCT = 40.0       # >40% missing → high-severity warning
MISSING_MODERATE_PCT = 10.0   # >10% missing → medium-severity
OUTLIER_IQR_MULTIPLIER = 1.5  # standard IQR fence
OUTLIER_HIGH_PCT = 10.0       # >10% outliers → high-severity
NEAR_CONSTANT_PCT = 99.0      # one value ≥99% of rows → near-constant
IMBALANCE_MINORITY_PCT = 10.0 # minority class <10% → imbalanced
HIGH_CARDINALITY_RATIO = 0.9  # nunique/nrows > 0.9 → likely ID column
MAX_INSIGHTS = 12             # cap total insights to avoid wall-of-text

# Bootstrap CI for strong-correlation insights (see _bootstrap_corr_ci below).
# Only "high"-severity (strong, |r| >= CORR_STRONG_THRESHOLD) pairs get a
# bootstrap CI — moderate correlations are common enough in wide datasets
# that bootstrapping every one of them would be needless cost for a
# secondary-severity finding. MAX_BOOTSTRAP_PAIRS additionally bounds the
# worst case (a dataset with many near-duplicate columns can have dozens of
# pairs above the strong threshold) so generate_insights() never becomes the
# slow path on upload.
BOOTSTRAP_ITER = 500           # resamples per pair
BOOTSTRAP_MAX_N = 5000          # subsample cap so one pair's CI stays O(1)-ish
BOOTSTRAP_MIN_N = 10             # below this, a CI isn't meaningful
BOOTSTRAP_CI_LEVEL = 0.95
MAX_BOOTSTRAP_PAIRS = 20        # hard cap on CI computations per generate_insights() call
WIDE_CI_SPAN = 0.3              # CI wider than this despite a "strong" r → flag as uncertain


def _iqr_outlier_pct(series: pd.Series) -> float:
    """Percentage of values outside the 1.5×IQR fence."""
    clean = series.dropna()
    if len(clean) < 4:
        return 0.0
    q1, q3 = clean.quantile(0.25), clean.quantile(0.75)
    iqr = q3 - q1
    if iqr == 0:
        return 0.0
    lower = q1 - OUTLIER_IQR_MULTIPLIER * iqr
    upper = q3 + OUTLIER_IQR_MULTIPLIER * iqr
    outliers = ((clean < lower) | (clean > upper)).sum()
    return float(outliers / len(clean) * 100)


def _bootstrap_corr_ci(
    series_a: pd.Series,
    series_b: pd.Series,
    n_boot: int = BOOTSTRAP_ITER,
    ci: float = BOOTSTRAP_CI_LEVEL,
    random_state: int = 42,
) -> Optional[tuple[float, float]]:
    """Percentile bootstrap confidence interval for a Pearson correlation.

    A point-estimate r alone doesn't say how much sampling noise could move
    it — the same r=0.87 is a very different claim on 20 rows vs. 20,000.
    This resamples row *pairs* with replacement (so x and y stay linked,
    unlike resampling each series independently) n_boot times, recomputes r
    on each resample, and returns the (ci*100)% percentile interval.

    Deterministic given the same inputs (fixed random_state) so tests and
    repeated runs on an unchanged dataset are reproducible.

    Returns None (never raises) when there isn't enough data for a
    meaningful interval: fewer than BOOTSTRAP_MIN_N complete pairs, or a
    series with zero variance (undefined r — every resample would divide by
    zero). For very large datasets, resampling is done on a fixed random
    subsample capped at BOOTSTRAP_MAX_N rows rather than the full column —
    keeps cost bounded on a 250K-row upload while the interval stays a
    faithful (if very slightly wider) estimate of the true sampling
    uncertainty.
    """
    paired = pd.DataFrame({"a": series_a, "b": series_b}).dropna()
    n = len(paired)
    if n < BOOTSTRAP_MIN_N:
        return None

    rng = np.random.default_rng(random_state)
    if n > BOOTSTRAP_MAX_N:
        sample_idx = rng.choice(n, size=BOOTSTRAP_MAX_N, replace=False)
        paired = paired.iloc[sample_idx]
        n = BOOTSTRAP_MAX_N

    x = paired["a"].to_numpy(dtype=float)
    y = paired["b"].to_numpy(dtype=float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None

    boot_r = np.empty(n_boot)
    for i in range(n_boot):
        idx = rng.integers(0, n, size=n)
        xs, ys = x[idx], y[idx]
        xd, yd = xs - xs.mean(), ys - ys.mean()
        denom = np.sqrt((xd**2).sum() * (yd**2).sum())
        boot_r[i] = (xd * yd).sum() / denom if denom > 0 else np.nan

    boot_r = boot_r[~np.isnan(boot_r)]
    if len(boot_r) < n_boot * 0.5:
        return None

    alpha = (1 - ci) / 2
    lo, hi = np.percentile(boot_r, [alpha * 100, (1 - alpha) * 100])
    lo, hi = float(np.clip(lo, -1.0, 1.0)), float(np.clip(hi, -1.0, 1.0))
    return round(min(lo, hi), 3), round(max(lo, hi), 3)


def _detect_distribution_insights(df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Flag highly skewed or heavy-tailed numeric distributions."""
    insights = []
    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    for col in numeric_cols:
        series = df[col].dropna()
        if len(series) < 10:
            continue
        skew = float(series.skew())
        kurt = float(series.kurtosis())  # excess kurtosis (Fisher)
        if abs(skew) >= SKEW_THRESHOLD:
            direction = "right" if skew > 0 else "left"
            insights.append({
                "category": "distribution",
                "severity": "medium",
                "column": col,
                "metric": f"skewness={skew:.2f}",
                "message": (
                    f"'{col}' is highly {direction}-skewed (skewness={skew:.2f}). "
                    f"Consider a log or Box-Cox transform before modeling."
                ),
            })
        if kurt >= KURTOSIS_THRESHOLD:
            insights.append({
                "category": "distribution",
                "severity": "low",
                "column": col,
                "metric": f"kurtosis={kurt:.2f}",
                "message": (
                    f"'{col}' has heavy tails (excess kurtosis={kurt:.2f}). "
                    f"Outlier-sensitive methods (mean, linear regression) may be affected."
                ),
            })
    return insights


def _detect_correlation_insights(df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Find strongly correlated numeric pairs (potential multicollinearity)."""
    insights = []
    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    if len(numeric_cols) < 2:
        return insights
    corr = df[numeric_cols].corr()
    seen = set()
    n_bootstrapped = 0
    for i, col_a in enumerate(numeric_cols):
        for col_b in numeric_cols[i + 1:]:
            r = corr.loc[col_a, col_b]
            if pd.isna(r):
                continue
            key = tuple(sorted([col_a, col_b]))
            if key in seen:
                continue
            seen.add(key)
            if abs(r) >= CORR_STRONG_THRESHOLD:
                ci = None
                if n_bootstrapped < MAX_BOOTSTRAP_PAIRS:
                    ci = _bootstrap_corr_ci(df[col_a], df[col_b])
                    n_bootstrapped += 1
                message = (
                    f"'{col_a}' and '{col_b}' are strongly correlated (r={r:.3f}). "
                    f"If both are used as features, multicollinearity may inflate variance "
                    f"in linear models — consider dropping one or using PCA."
                )
                if ci is not None:
                    lo, hi = ci
                    message += f" (95% CI: {lo:.3f} to {hi:.3f}"
                    if (hi - lo) >= WIDE_CI_SPAN:
                        message += " — wide interval, treat with caution on this sample size"
                    message += ".)"
                insights.append({
                    "category": "correlation",
                    "severity": "high",
                    "column": f"{col_a} ↔ {col_b}",
                    "metric": f"r={r:.3f}",
                    "message": message,
                    "ci": ci,
                })
            elif abs(r) >= CORR_MODERATE_THRESHOLD:
                insights.append({
                    "category": "correlation",
                    "severity": "low",
                    "column": f"{col_a} ↔ {col_b}",
                    "metric": f"r={r:.3f}",
                    "message": (
                        f"'{col_a}' and '{col_b}' are moderately correlated (r={r:.3f}). "
                        f"Worth investigating whether one drives the other."
                    ),
                    "ci": None,
                })
    return insights


def _detect_missing_insights(df: pd.DataFrame) -> list[dict]:
    """Flag columns with significant missing data."""
    insights = []
    total = len(df)
    if total == 0:
        return insights
    for col in df.columns:
        missing = df[col].isna().sum()
        pct = missing / total * 100
        if pct >= MISSING_HIGH_PCT:
            insights.append({
                "category": "missing_data",
                "severity": "high",
                "column": col,
                "metric": f"{pct:.1f}% missing",
                "message": (
                    f"'{col}' is {pct:.1f}% missing ({missing:,} of {total:,} rows). "
                    f"This column may be unreliable for analysis — consider dropping it "
                    f"or investigating why the data is absent."
                ),
            })
        elif pct >= MISSING_MODERATE_PCT:
            insights.append({
                "category": "missing_data",
                "severity": "medium",
                "column": col,
                "metric": f"{pct:.1f}% missing",
                "message": (
                    f"'{col}' has {pct:.1f}% missing values ({missing:,} rows). "
                    f"Imputation or careful handling is recommended before modeling."
                ),
            })
    return insights


def _detect_outlier_insights(df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Flag numeric columns with high outlier prevalence."""
    insights = []
    numeric_cols = [c for c, t in column_types.items() if t == "numeric"]
    for col in numeric_cols:
        pct = _iqr_outlier_pct(df[col])
        if pct >= OUTLIER_HIGH_PCT:
            insights.append({
                "category": "outliers",
                "severity": "high",
                "column": col,
                "metric": f"{pct:.1f}% outliers",
                "message": (
                    f"'{col}' has {pct:.1f}% values outside the IQR fence — "
                    f"a high outlier rate. Verify these are real data points, not errors. "
                    f"Robust methods (median, IQR-based scaling) are safer here."
                ),
            })
        elif pct >= 5.0:
            insights.append({
                "category": "outliers",
                "severity": "medium",
                "column": col,
                "metric": f"{pct:.1f}% outliers",
                "message": (
                    f"'{col}' has {pct:.1f}% values outside the IQR fence. "
                    f"Consider winsorizing or using robust statistics."
                ),
            })
    return insights


def _detect_structural_insights(df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Flag near-constant columns, high-cardinality suspects, and class imbalance."""
    insights = []
    total = len(df)
    if total == 0:
        return insights

    for col in df.columns:
        ctype = column_types.get(col)
        series = df[col].dropna()
        if len(series) == 0:
            continue

        # Near-constant
        top_freq = series.value_counts(normalize=True).iloc[0] * 100 if len(series) > 0 else 0
        if top_freq >= NEAR_CONSTANT_PCT:
            insights.append({
                "category": "structure",
                "severity": "medium",
                "column": col,
                "metric": f"{top_freq:.1f}% single value",
                "message": (
                    f"'{col}' is near-constant — {top_freq:.1f}% of values are the same. "
                    f"It carries almost no information and can usually be dropped."
                ),
            })
            continue

        # High cardinality (likely ID column)
        if ctype == "categorical":
            nunique = series.nunique()
            ratio = nunique / len(series)
            if ratio >= HIGH_CARDINALITY_RATIO and nunique > 50:
                insights.append({
                    "category": "structure",
                    "severity": "medium",
                    "column": col,
                    "metric": f"{nunique:,} unique / {len(series):,} rows",
                    "message": (
                        f"'{col}' has {nunique:,} unique values in {len(series):,} rows — "
                        f"likely an ID or free-text column. Exclude it from modeling."
                    ),
                })

        # Class imbalance (for low-cardinality categoricals that look like targets)
        if ctype == "categorical":
            nunique = series.nunique()
            if 2 <= nunique <= 10:
                counts = series.value_counts(normalize=True) * 100
                minority_pct = counts.min()
                if minority_pct < IMBALANCE_MINORITY_PCT:
                    minority_label = counts.idxmin()
                    insights.append({
                        "category": "imbalance",
                        "severity": "medium",
                        "column": col,
                        "metric": f"minority={minority_pct:.1f}%",
                        "message": (
                            f"'{col}' shows class imbalance — the minority class "
                            f"'{minority_label}' is only {minority_pct:.1f}% of the data. "
                            f"If this is a target variable, consider SMOTE or stratified sampling."
                        ),
                    })

    return insights


def _detect_duplicate_rows(df: pd.DataFrame) -> list[dict]:
    """Flag if the dataset has a notable percentage of duplicate rows."""
    insights = []
    n_dupes = df.duplicated().sum()
    if n_dupes > 0:
        pct = n_dupes / len(df) * 100
        severity = "high" if pct > 10 else "medium" if pct > 1 else "low"
        insights.append({
            "category": "duplicates",
            "severity": severity,
            "column": "(all columns)",
            "metric": f"{n_dupes:,} duplicates ({pct:.1f}%)",
            "message": (
                f"Found {n_dupes:,} exact duplicate rows ({pct:.1f}% of the dataset). "
                f"Unless duplicates are expected (e.g., transaction logs), consider deduplication."
            ),
        })
    return insights


def generate_insights(df: pd.DataFrame, column_types: dict[str, str]) -> list[dict]:
    """Run all insight detectors and return a prioritized list.

    Each insight is a dict with keys: category, severity, column, metric, message.
    Results are sorted by severity (high → medium → low), then truncated to
    MAX_INSIGHTS to avoid overwhelming the user.
    """
    all_insights = []
    all_insights.extend(_detect_missing_insights(df))
    all_insights.extend(_detect_duplicate_rows(df))
    all_insights.extend(_detect_outlier_insights(df, column_types))
    all_insights.extend(_detect_distribution_insights(df, column_types))
    all_insights.extend(_detect_correlation_insights(df, column_types))
    all_insights.extend(_detect_structural_insights(df, column_types))

    severity_order = {"high": 0, "medium": 1, "low": 2}
    all_insights.sort(key=lambda x: severity_order.get(x["severity"], 3))

    return all_insights[:MAX_INSIGHTS]


def format_insights_text(insights: list[dict]) -> str:
    """Render insights as a compact text block for Gemini narration input."""
    if not insights:
        return "No notable insights detected."
    lines = []
    for i, ins in enumerate(insights, 1):
        lines.append(f"{i}. [{ins['severity'].upper()}] {ins['message']}")
    return "\n".join(lines)


_NARRATION_PROMPT = (
    "You are a senior data analyst writing a brief executive summary of a dataset's "
    "initial health check. Below are the automated findings from the scan. Synthesize "
    "them into a 3–5 sentence paragraph that a non-technical stakeholder could read. "
    "Focus on the most actionable items first. Do NOT list every finding — highlight "
    "the top 3 and mention how many others exist. Write in second person ('your data').\n\n"
    "Findings:\n{findings_text}"
)


def narrate_insights(model, insights: list[dict]) -> tuple[str, Optional[str]]:
    """Ask Gemini to turn raw insights into a stakeholder-friendly paragraph.

    Returns (narration, error). Falls back gracefully if Gemini is unavailable.
    """
    if model is None:
        return "", "No Gemini model available for narration."
    if not insights:
        return "Your dataset looks clean — no significant issues detected.", None

    from modules.ai_analyst import call_gemini

    findings_text = format_insights_text(insights)
    prompt = _NARRATION_PROMPT.format(findings_text=findings_text)
    text, error = call_gemini(model, prompt)
    if error:
        return "", error
    return text.strip(), None


# ═══════════════════════════════════════════════════════════════════════
# NARRATION FACT-CHECK — same "plausible but wrong number" safety net
# insight_verifier applies to Auto Analyst's findings, extended here to
# narrate_insights()'s executive-summary prose. Each insight's "message"
# is already deterministic, non-LLM text (built straight from the
# detector's own computed stats — see _detect_*_insights above), so the
# reference set is simply every number that appears in any message
# narrate_insights() was given to synthesize. No DataFrame recomputation
# needed, same reasoning as hypothesis_sweep.sweep_reference_numbers().
# ═══════════════════════════════════════════════════════════════════════
def insights_reference_numbers(insights: list[dict]) -> set[float]:
    """Ground-truth numbers for narrate_insights()'s prose: every number
    quoted in the source insight messages themselves. Never raises.
    """
    from modules import insight_verifier

    numbers: set[float] = set()
    try:
        for ins in insights or []:
            numbers.update(insight_verifier.extract_numbers(ins.get("message", "")))
    except (TypeError, AttributeError):
        pass
    return numbers


def verify_narration(narration: str, insights: list[dict]) -> dict:
    """Fact-check narrate_insights()'s prose against the source insights'
    own numbers. Reuses insight_verifier.verify_finding() — same
    {"status": "confirmed" | "flagged" | "unverifiable", ...} contract as
    every other verified surface in the app. Never raises.
    """
    from modules import insight_verifier

    try:
        reference_numbers = insights_reference_numbers(insights)
    except Exception:
        reference_numbers = set()
    return insight_verifier.verify_finding(narration or "", reference_numbers)


def severity_icon(severity: str) -> str:
    """Emoji icon for UI display."""
    return {"high": "🔴", "medium": "🟡", "low": "🔵"}.get(severity, "⚪")


def category_label(category: str) -> str:
    """Human-readable category name."""
    return {
        "distribution": "Distribution",
        "correlation": "Correlation",
        "missing_data": "Missing Data",
        "outliers": "Outliers",
        "structure": "Structure",
        "imbalance": "Class Imbalance",
        "duplicates": "Duplicates",
    }.get(category, category.title())
