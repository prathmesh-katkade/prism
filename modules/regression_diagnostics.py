"""
Regression Diagnostics Panel — the checks a hiring panel actually asks
about: residual behavior, normality, multicollinearity, heteroscedasticity,
and autocorrelation for a fitted OLS regression.

Fits its own statsmodels OLS (not reusing ML Lab's sklearn LinearRegression)
because statsmodels' RegressionResults carries the inferential statistics
(standard errors, p-values, VIF-ready design matrix) that sklearn's
estimator deliberately doesn't compute — sklearn optimizes for prediction,
statsmodels for inference, and diagnostics need inference.

Every function here takes plain pandas/numpy inputs and returns a dict or
a plotly Figure — no Streamlit imports, so this module is testable without
spinning up the app.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import statsmodels.api as sm
from scipy import stats
from statsmodels.stats.diagnostic import het_breuschpagan
from statsmodels.stats.outliers_influence import variance_inflation_factor
from statsmodels.stats.stattools import durbin_watson

MIN_ROWS_REQUIRED = 15  # below this, standard errors are too unstable to trust
MAX_FEATURES_FOR_VIF = 30  # VIF is O(features^2) in practice; guard against pathological inputs

VIF_MODERATE_THRESHOLD = 5.0
VIF_HIGH_THRESHOLD = 10.0


def fit_ols(df: pd.DataFrame, feature_cols: list[str], target_col: str) -> dict:
    """Fit an OLS model on numeric features only (categoricals must be
    one-hot encoded by the caller before this — kept explicit rather than
    silently encoding here, since encoding choices belong to the feature
    engineering step, not the diagnostics step).

    Returns a dict with "model" (the fitted RegressionResults), "X", "y",
    "feature_names", or "error" if the fit couldn't run.
    """
    numeric_features = [c for c in feature_cols if pd.api.types.is_numeric_dtype(df[c])]
    dropped = [c for c in feature_cols if c not in numeric_features]

    data = df[numeric_features + [target_col]].dropna()
    if len(data) < MIN_ROWS_REQUIRED:
        return {"error": f"Need at least {MIN_ROWS_REQUIRED} complete rows to fit a reliable regression (found {len(data)})."}
    if not numeric_features:
        return {"error": "No numeric feature columns available — encode categorical columns first (see Feature Engineering)."}

    # Drop zero-variance columns — statsmodels' OLS silently produces
    # singular-matrix warnings and unusable coefficients otherwise.
    variances = data[numeric_features].var()
    zero_var = [c for c in numeric_features if variances.get(c, 0) == 0]
    numeric_features = [c for c in numeric_features if c not in zero_var]
    if not numeric_features:
        return {"error": "All candidate feature columns are constant (zero variance) — nothing to regress on."}

    X = data[numeric_features]
    y = data[target_col]
    X_with_const = sm.add_constant(X)

    try:
        model = sm.OLS(y, X_with_const).fit()
    except Exception as e:
        return {"error": f"OLS fit failed: {e}"}

    result = {
        "model": model,
        "X": X,
        "y": y,
        "feature_names": numeric_features,
        "n_obs": len(data),
    }
    if dropped:
        result["dropped_categorical"] = dropped
    if zero_var:
        result["dropped_zero_variance"] = zero_var
    return result


def summarize_fit(fit_result: dict) -> dict:
    """Headline fit-quality numbers: R², adjusted R², F-statistic + p-value."""
    model = fit_result["model"]
    return {
        "r_squared": float(model.rsquared),
        "adj_r_squared": float(model.rsquared_adj),
        "f_statistic": float(model.fvalue),
        "f_pvalue": float(model.f_pvalue),
        "n_obs": int(model.nobs),
        "aic": float(model.aic),
        "bic": float(model.bic),
    }


def coefficient_table(fit_result: dict) -> pd.DataFrame:
    """Coefficient, std error, t-stat, p-value, and 95% CI per feature (incl. intercept)."""
    model = fit_result["model"]
    ci = model.conf_int(alpha=0.05)
    return pd.DataFrame({
        "coefficient": model.params,
        "std_error": model.bse,
        "t_stat": model.tvalues,
        "p_value": model.pvalues,
        "ci_lower": ci[0],
        "ci_upper": ci[1],
    }).round(4)


def compute_vif(fit_result: dict) -> pd.DataFrame:
    """Variance Inflation Factor per feature — the standard multicollinearity
    diagnostic. VIF > 10 is conventionally "problematic", 5-10 "moderate
    concern". The intercept column is excluded since VIF is meaningless for it.
    """
    feature_names = fit_result["feature_names"]
    if len(feature_names) > MAX_FEATURES_FOR_VIF:
        feature_names = feature_names[:MAX_FEATURES_FOR_VIF]
    if len(feature_names) < 2:
        return pd.DataFrame(columns=["feature", "vif", "concern"])

    X = fit_result["X"][feature_names]
    X_with_const = sm.add_constant(X)
    # Column 0 is the constant — VIF is computed per feature, skipping it.
    rows = []
    for i, name in enumerate(feature_names, start=1):
        try:
            vif = variance_inflation_factor(X_with_const.values, i)
        except (ZeroDivisionError, np.linalg.LinAlgError):
            vif = float("inf")
        concern = "high" if vif >= VIF_HIGH_THRESHOLD else "moderate" if vif >= VIF_MODERATE_THRESHOLD else "low"
        rows.append({"feature": name, "vif": round(vif, 2) if np.isfinite(vif) else vif, "concern": concern})
    return pd.DataFrame(rows).sort_values("vif", ascending=False, key=lambda s: s.map(lambda v: float("inf") if not np.isfinite(v) else v))


def run_diagnostics(fit_result: dict) -> dict:
    """Run the full diagnostic battery: normality (Shapiro-Wilk on
    residuals), heteroscedasticity (Breusch-Pagan), and autocorrelation
    (Durbin-Watson). Returns a dict of test results plus plain-English verdicts.
    """
    model = fit_result["model"]
    residuals = model.resid
    fitted = model.fittedvalues

    # Normality of residuals (Shapiro-Wilk; subsample if huge, same
    # threshold convention as Stats Lab's own normality check)
    n = len(residuals)
    sample = residuals if n <= 5000 else residuals.sample(5000, random_state=0)
    try:
        shapiro_stat, shapiro_p = stats.shapiro(sample)
    except Exception:
        shapiro_stat, shapiro_p = None, None

    # Heteroscedasticity — Breusch-Pagan test
    try:
        bp_stat, bp_pvalue, bp_fvalue, bp_fpvalue = het_breuschpagan(residuals, model.model.exog)
    except Exception:
        bp_stat, bp_pvalue = None, None

    # Autocorrelation — Durbin-Watson (2.0 = no autocorrelation; <1.5 or >2.5 flags concern)
    dw_stat = float(durbin_watson(residuals))

    return {
        "residuals": residuals,
        "fitted": fitted,
        "shapiro_stat": float(shapiro_stat) if shapiro_stat is not None else None,
        "shapiro_p": float(shapiro_p) if shapiro_p is not None else None,
        "residuals_normal": bool(shapiro_p >= 0.05) if shapiro_p is not None else None,
        "breusch_pagan_stat": float(bp_stat) if bp_stat is not None else None,
        "breusch_pagan_p": float(bp_pvalue) if bp_pvalue is not None else None,
        "homoscedastic": bool(bp_pvalue >= 0.05) if bp_pvalue is not None else None,
        "durbin_watson": dw_stat,
        "autocorrelation_concern": bool(dw_stat < 1.5 or dw_stat > 2.5),
    }


def diagnostics_verdict(diagnostics: dict, vif_table: pd.DataFrame) -> list[str]:
    """Plain-English bullet list summarizing what the diagnostics mean —
    the kind of read-out a candidate should be able to give verbally.
    """
    verdicts = []

    if diagnostics["residuals_normal"] is True:
        verdicts.append(f"✅ Residuals look normally distributed (Shapiro-Wilk p={diagnostics['shapiro_p']:.4f}) — the model's confidence intervals and p-values are trustworthy.")
    elif diagnostics["residuals_normal"] is False:
        verdicts.append(f"⚠️ Residuals deviate from normality (Shapiro-Wilk p={diagnostics['shapiro_p']:.4f}) — p-values and confidence intervals may be unreliable; consider a transform on the target or a robust regression.")

    if diagnostics["homoscedastic"] is True:
        verdicts.append(f"✅ No significant heteroscedasticity detected (Breusch-Pagan p={diagnostics['breusch_pagan_p']:.4f}) — residual variance looks constant across fitted values.")
    elif diagnostics["homoscedastic"] is False:
        verdicts.append(f"⚠️ Heteroscedasticity detected (Breusch-Pagan p={diagnostics['breusch_pagan_p']:.4f}) — residual variance changes with fitted values; standard errors may be biased. Consider weighted least squares or robust standard errors.")

    dw = diagnostics["durbin_watson"]
    if diagnostics["autocorrelation_concern"]:
        direction = "positive" if dw < 1.5 else "negative"
        verdicts.append(f"⚠️ Durbin-Watson={dw:.2f} suggests {direction} autocorrelation in residuals — if this is time-series data, consecutive errors are not independent, violating an OLS assumption.")
    else:
        verdicts.append(f"✅ Durbin-Watson={dw:.2f} is close to 2.0 — no strong evidence of autocorrelation in residuals.")

    if not vif_table.empty:
        high_vif = vif_table[vif_table["concern"] == "high"]
        if not high_vif.empty:
            names = ", ".join(high_vif["feature"].tolist())
            verdicts.append(f"⚠️ High multicollinearity (VIF ≥ {VIF_HIGH_THRESHOLD:.0f}): {names}. Coefficient estimates for these features are unstable — consider dropping one or using regularization (Ridge/Lasso).")
        else:
            verdicts.append(f"✅ No feature has VIF ≥ {VIF_HIGH_THRESHOLD:.0f} — multicollinearity is not a major concern.")

    return verdicts


# ── Plots ────────────────────────────────────────────────────────────────

def plot_residuals_vs_fitted(diagnostics: dict) -> go.Figure:
    """Residuals vs. fitted values — the single most-used diagnostic plot.
    A random scatter around 0 supports linearity + homoscedasticity; a
    funnel or curve shape flags a violated assumption.
    """
    fig = px.scatter(
        x=diagnostics["fitted"], y=diagnostics["residuals"],
        labels={"x": "Fitted values", "y": "Residuals"},
        title="Residuals vs. Fitted",
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


def plot_qq(diagnostics: dict) -> go.Figure:
    """Normal Q-Q plot of residuals — points on the diagonal support normality."""
    residuals = diagnostics["residuals"]
    (osm, osr), (slope, intercept, r) = stats.probplot(residuals, dist="norm")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=osm, y=osr, mode="markers", name="Residuals"))
    line_x = np.array([osm.min(), osm.max()])
    fig.add_trace(go.Scatter(x=line_x, y=slope * line_x + intercept, mode="lines", name="Reference line", line=dict(dash="dash", color="gray")))
    fig.update_layout(title="Normal Q-Q Plot", xaxis_title="Theoretical Quantiles", yaxis_title="Sample Quantiles", margin=dict(t=50, b=10, l=10, r=10))
    return fig


def plot_scale_location(diagnostics: dict) -> go.Figure:
    """Scale-Location plot — sqrt of standardized residuals vs. fitted, a
    complementary heteroscedasticity view to the raw residuals-vs-fitted plot."""
    residuals = diagnostics["residuals"]
    std_resid = (residuals - residuals.mean()) / residuals.std()
    sqrt_abs_std_resid = np.sqrt(np.abs(std_resid))
    fig = px.scatter(
        x=diagnostics["fitted"], y=sqrt_abs_std_resid,
        labels={"x": "Fitted values", "y": "√|Standardized residuals|"},
        title="Scale-Location",
    )
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig


def plot_vif_chart(vif_table: pd.DataFrame) -> Optional[go.Figure]:
    """Horizontal bar chart of VIF per feature, with threshold reference lines."""
    if vif_table.empty:
        return None
    finite = vif_table[np.isfinite(vif_table["vif"])].sort_values("vif")
    if finite.empty:
        return None
    fig = px.bar(
        finite, x="vif", y="feature", orientation="h",
        color="concern", color_discrete_map={"low": "#2ecc71", "moderate": "#f39c12", "high": "#e74c3c"},
        title="Variance Inflation Factor (VIF) by Feature",
        labels={"vif": "VIF", "feature": "Feature"},
    )
    fig.add_vline(x=VIF_MODERATE_THRESHOLD, line_dash="dot", line_color="orange")
    fig.add_vline(x=VIF_HIGH_THRESHOLD, line_dash="dot", line_color="red")
    fig.update_layout(margin=dict(t=50, b=10, l=10, r=10))
    return fig
