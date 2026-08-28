"""
Regression Diagnostics Panel — deterministic evaluation suite.
Runs without an API key (pure statsmodels/scipy computation, no Gemini).

Usage:  python eval/regression_diagnostics_eval.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from modules.regression_diagnostics import (
    MIN_ROWS_REQUIRED,
    coefficient_table,
    compute_vif,
    diagnostics_verdict,
    fit_ols,
    plot_qq,
    plot_residuals_vs_fitted,
    plot_scale_location,
    plot_vif_chart,
    run_diagnostics,
    summarize_fit,
)

passed, failed = 0, 0

def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        print(f"  ❌ {name}")


print("\n📉 Regression Diagnostics Evaluation")
print("=" * 50)

# ── Test data: a clean linear relationship with known properties ──────────
np.random.seed(42)
n = 300
x1 = np.random.normal(0, 1, n)
x2 = np.random.normal(0, 1, n)
x3 = x1 * 0.9 + np.random.normal(0, 0.1, n)  # collinear with x1
noise = np.random.normal(0, 1, n)
y = 3 * x1 + 2 * x2 + 5 + noise

clean_df = pd.DataFrame({"x1": x1, "x2": x2, "y": y, "category": np.random.choice(["A", "B"], n)})
collinear_df = pd.DataFrame({"x1": x1, "x2": x2, "x3": x3, "y": y})

print("\n1. fit_ols() basic behavior")
fit1 = fit_ols(clean_df, ["x1", "x2"], "y")
check("Clean fit has no error", "error" not in fit1)
check("Fit recovers approx x1 coefficient (~3)", abs(fit1["model"].params["x1"] - 3) < 0.5)
check("Fit recovers approx x2 coefficient (~2)", abs(fit1["model"].params["x2"] - 2) < 0.5)
check("n_obs matches row count", fit1["n_obs"] == n)

print("\n2. Non-numeric column handling")
fit_mixed = fit_ols(clean_df, ["x1", "x2", "category"], "y")
check("Categorical column dropped, not crashed", "dropped_categorical" in fit_mixed)
check("dropped_categorical contains 'category'", "category" in fit_mixed.get("dropped_categorical", []))

print("\n3. Insufficient data handling")
tiny_df = clean_df.head(MIN_ROWS_REQUIRED - 1)
fit_tiny = fit_ols(tiny_df, ["x1", "x2"], "y")
check("Too few rows returns error", "error" in fit_tiny)

print("\n4. Zero-variance column handling")
const_df = clean_df.copy()
const_df["const_col"] = 5.0
fit_const = fit_ols(const_df, ["x1", "x2", "const_col"], "y")
check("Zero-variance column dropped, not crashed", "dropped_zero_variance" in fit_const)

print("\n5. No numeric features")
fit_none = fit_ols(clean_df, ["category"], "y")
check("No numeric features returns error", "error" in fit_none)

print("\n6. summarize_fit()")
summary = summarize_fit(fit1)
check("R-squared is reasonable (>0.7)", summary["r_squared"] > 0.7)
check("Adjusted R-squared <= R-squared", summary["adj_r_squared"] <= summary["r_squared"])
check("n_obs matches", summary["n_obs"] == n)
check("AIC/BIC are finite floats", np.isfinite(summary["aic"]) and np.isfinite(summary["bic"]))

print("\n7. coefficient_table()")
coef_table = coefficient_table(fit1)
check("Coefficient table has intercept + 2 features", len(coef_table) == 3)
check("Coefficient table has expected columns", set(["coefficient", "std_error", "t_stat", "p_value"]).issubset(coef_table.columns))

print("\n8. compute_vif() — multicollinearity detection")
fit_collinear = fit_ols(collinear_df, ["x1", "x2", "x3"], "y")
vif_collinear = compute_vif(fit_collinear)
check("VIF table has 3 rows", len(vif_collinear) == 3)
x1_vif = vif_collinear[vif_collinear["feature"] == "x1"]["vif"].iloc[0]
check("x1 (collinear with x3) has high VIF", x1_vif > 5)

vif_clean = compute_vif(fit1)
check("Independent features have low VIF", (vif_clean["vif"] < 5).all())

single_feature_fit = fit_ols(clean_df, ["x1"], "y")
vif_single = compute_vif(single_feature_fit)
check("Single feature returns empty VIF table (undefined for 1 var)", vif_single.empty)

print("\n9. run_diagnostics()")
diag = run_diagnostics(fit1)
check("Diagnostics has durbin_watson close to 2 (no autocorrelation, i.i.d. noise)",
      1.5 < diag["durbin_watson"] < 2.5)
check("Diagnostics has shapiro_p in [0,1]", 0 <= diag["shapiro_p"] <= 1)
check("Diagnostics has breusch_pagan_p in [0,1]", 0 <= diag["breusch_pagan_p"] <= 1)
check("residuals_normal is a bool (normal noise should pass)", diag["residuals_normal"] is True)
check("homoscedastic is a bool", isinstance(diag["homoscedastic"], bool))

print("\n10. diagnostics_verdict() produces readable output")
verdicts = diagnostics_verdict(diag, vif_clean)
check("Verdict list is non-empty", len(verdicts) >= 3)
check("Every verdict starts with an emoji marker", all(v.startswith(("✅", "⚠️")) for v in verdicts))

print("\n11. Heteroscedastic data detected")
x_hetero = np.random.uniform(1, 10, 300)
y_hetero = 2 * x_hetero + np.random.normal(0, x_hetero, 300)  # variance grows with x
hetero_df = pd.DataFrame({"x": x_hetero, "y": y_hetero})
fit_hetero = fit_ols(hetero_df, ["x"], "y")
diag_hetero = run_diagnostics(fit_hetero)
check("Heteroscedastic data flagged by Breusch-Pagan (p < 0.05)", diag_hetero["breusch_pagan_p"] < 0.05)
check("homoscedastic is False for heteroscedastic data", diag_hetero["homoscedastic"] is False)

print("\n12. Plot functions return Figure objects without crashing")
fig1 = plot_residuals_vs_fitted(diag)
fig2 = plot_qq(diag)
fig3 = plot_scale_location(diag)
fig4 = plot_vif_chart(vif_collinear)
check("plot_residuals_vs_fitted returns a Figure", fig1 is not None)
check("plot_qq returns a Figure", fig2 is not None)
check("plot_scale_location returns a Figure", fig3 is not None)
check("plot_vif_chart returns a Figure for non-empty VIF table", fig4 is not None)
check("plot_vif_chart returns None for empty VIF table", plot_vif_chart(vif_single) is None)

print("\n" + "=" * 50)
print(f"Results: {passed} passed, {failed} failed out of {passed + failed}")
if failed:
    sys.exit(1)
print("All tests passed! ✅")
